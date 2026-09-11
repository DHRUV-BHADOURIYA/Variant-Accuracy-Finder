from __future__ import annotations

import math
from dataclasses import dataclass

from board import PositionState
from config import ANALYSIS_DEPTH, START_FEN
from png import Game, ParsedMove
from uci_engine import EngineLine, UCIEngine


TEAM = {
    "Red": "RY",
    "Yellow": "RY",
    "Blue": "BG",
    "Green": "BG",
}

PLAYERS = ("Red", "Blue", "Yellow", "Green")


@dataclass
class MoveAnalysis:
    move: ParsedMove
    before_cp: int | None
    before_mate: int | None
    after_cp: int | None
    after_mate: int | None
    before_mover_cp: int | None
    after_mover_cp: int | None
    before_win_percent: float | None
    after_win_percent: float | None
    accuracy: float | None
    classification: str
    depth: int
    after_ry_cp: int | None
    engine_best_move: str | None
    played_move_rank: int | None
    best_vs_played_cp: int | None
    engine_candidate_count: int
    best_vs_second_cp: int | None
    criticality: str
    decision_difficulty: str


def _score(line: EngineLine | None) -> tuple[int | None, int | None]:
    if line is None or not line.is_exact:
        return None, None
    return line.score_cp, line.mate


def _score_as_cp(cp: int | None, mate: int | None) -> int | None:
    if mate is not None:
        return 1000 if mate > 0 else -1000
    if cp is None:
        return None
    return max(-1000, min(1000, cp))


def _team_relative_cp(stm_cp: int | None, stm_player: str, pov_team: str) -> int | None:
    if stm_cp is None:
        return None
    return stm_cp if TEAM[stm_player] == pov_team else -stm_cp


def _win_percent(cp: int) -> float:
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def _move_accuracy(before_win: float, after_win: float) -> float:
    if after_win >= before_win:
        return 100.0
    win_diff = before_win - after_win
    raw = (
        103.1668100711649 * math.exp(-0.04354415386753951 * win_diff)
        - 3.166924740191411
    )
    return max(0.0, min(100.0, raw + 1.0))


def _classify_accuracy(accuracy: float | None) -> str:
    if accuracy is None:
        return "UNASSESSED"
    if accuracy >= 99.0:
        return "BEST"
    if accuracy >= 95.0:
        return "EXCELLENT"
    if accuracy >= 90.0:
        return "GOOD"
    if accuracy >= 80.0:
        return "INACCURACY"
    if accuracy >= 60.0:
        return "MISTAKE"
    return "BLUNDER"


def _candidate_data(lines: dict[int, EngineLine], mover: str) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    mover_team = TEAM[mover]
    for multipv in sorted(lines):
        line = lines[multipv]
        if not line.pv:
            continue
        cp = _score_as_cp(line.score_cp, line.mate)
        if cp is None:
            continue
        relative_cp = _team_relative_cp(cp, mover, mover_team)
        if relative_cp is not None:
            candidates.append((line.pv[0], relative_cp))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def _agreement(
    before_result_lines: dict[int, EngineLine],
    move: ParsedMove,
    multipv_supported: bool,
) -> tuple[str | None, int | None, int | None, int | None, int]:
    if not multipv_supported:
        return None, None, None, None, 0
    candidates = _candidate_data(before_result_lines, move.player)
    if len(candidates) < 2:
        return None, None, None, None, 0
    best_move, best_cp = candidates[0]
    second_cp = candidates[1][1]
    played_rank = next(
        (index + 1 for index, (candidate_move, _) in enumerate(candidates) if candidate_move == move.uci),
        None,
    )
    return best_move, played_rank, best_cp, second_cp, len(candidates)


def _criticality(best_vs_second_cp: int | None) -> str:
    if best_vs_second_cp is None:
        return "UNASSESSED"
    if best_vs_second_cp >= 150:
        return "VERY_HIGH"
    if best_vs_second_cp >= 75:
        return "HIGH"
    if best_vs_second_cp >= 30:
        return "MEDIUM"
    return "LOW"


def _decision_difficulty(best_vs_second_cp: int | None) -> str:
    if best_vs_second_cp is None:
        return "UNASSESSED"
    if best_vs_second_cp >= 150:
        return "VERY_DIFFERENT"
    if best_vs_second_cp >= 75:
        return "DIFFERENT"
    if best_vs_second_cp >= 30:
        return "CLOSE"
    return "NEAR_EQUIVALENT"


def _is_checkmate_move(move: ParsedMove) -> bool:
    """The supplied 4PC notation marks a game-ending checkmate with '#'."""
    return "#" in move.notation


def analyze_game(game: Game, engine: UCIEngine) -> list[MoveAnalysis]:
    state = PositionState(fen=START_FEN)
    results: list[MoveAnalysis] = []

    current_result = engine.analyze(state.fen, state.uci_moves(), ANALYSIS_DEPTH)
    current_line = current_result.lines.get(1)

    for index, move in enumerate(game.moves):
        print(f"Analyzing ply {index + 1}/{len(game.moves)}: {move.notation}")

        before_cp_raw, before_mate = _score(current_line)
        before_cp = _score_as_cp(before_cp_raw, before_mate)
        before_mover_cp = _team_relative_cp(before_cp, move.player, TEAM[move.player])
        before_win = _win_percent(before_mover_cp) if before_mover_cp is not None else None

        (
            engine_best_move,
            played_move_rank,
            best_cp,
            second_cp,
            engine_candidate_count,
        ) = _agreement(current_result.lines, move, engine.multipv_supported)

        state.play(move)
        next_player = PLAYERS[(index + 1) % 4]

        # Do not send another `go depth` after a checkmating move. A terminal
        # position has no legal move and this engine does not emit bestmove for
        # such a search, which would otherwise make the analyzer wait forever.
        # From the mover's team POV, a checkmate is a forced +1000 terminal score.
        if _is_checkmate_move(move):
            after_mover_cp = 1000
            after_win = _win_percent(after_mover_cp)
            after_cp = -1000 if TEAM[next_player] != TEAM[move.player] else 1000
            after_mate = -1 if after_cp < 0 else 1
            after_line = None
        else:
            after_result = engine.analyze(state.fen, state.uci_moves(), ANALYSIS_DEPTH)
            after_line = after_result.lines.get(1)
            after_cp_raw, after_mate = _score(after_line)
            after_cp = _score_as_cp(after_cp_raw, after_mate)
            after_mover_cp = _team_relative_cp(after_cp, next_player, TEAM[move.player])
            after_win = _win_percent(after_mover_cp) if after_mover_cp is not None else None

        accuracy = None
        if before_win is not None and after_win is not None:
            accuracy = _move_accuracy(before_win, after_win)

        best_vs_played_cp = None
        if engine.multipv_supported and best_cp is not None and after_mover_cp is not None:
            best_vs_played_cp = max(0, best_cp - after_mover_cp)

        best_vs_second_cp = None
        if engine.multipv_supported and best_cp is not None and second_cp is not None:
            best_vs_second_cp = max(0, best_cp - second_cp)

        after_ry_cp = _team_relative_cp(after_cp, next_player, "RY")

        results.append(
            MoveAnalysis(
                move=move,
                before_cp=before_cp,
                before_mate=before_mate,
                after_cp=after_cp,
                after_mate=after_mate,
                before_mover_cp=before_mover_cp,
                after_mover_cp=after_mover_cp,
                before_win_percent=before_win,
                after_win_percent=after_win,
                accuracy=accuracy,
                classification=_classify_accuracy(accuracy),
                depth=current_line.depth if current_line else 0,
                after_ry_cp=after_ry_cp,
                engine_best_move=engine_best_move,
                played_move_rank=played_move_rank,
                best_vs_played_cp=best_vs_played_cp,
                engine_candidate_count=engine_candidate_count,
                best_vs_second_cp=best_vs_second_cp,
                criticality=_criticality(best_vs_second_cp),
                decision_difficulty=_decision_difficulty(best_vs_second_cp),
            )
        )

        if after_line is None:
            break
        current_result = after_result
        current_line = after_line

    return results
