from __future__ import annotations

import math
from dataclasses import dataclass

from board import PositionState
from config import ANALYSIS_DEPTH, START_FEN
from png import Game, ParsedMove
from uci_engine import EngineLine, SearchResult, UCIEngine

TEAM = {"Red": "RY", "Yellow": "RY", "Blue": "BG", "Green": "BG"}
PLAYERS = ("Red", "Blue", "Yellow", "Green")


@dataclass
class MoveAnalysis:
    move: ParsedMove
    # Raw engine scores. These are never clamped and never converted from mate.
    before_raw_cp: int | None
    before_cp: int | None
    before_mate: int | None
    after_raw_cp: int | None
    after_cp: int | None
    after_mate: int | None
    # Normalized CP used only by the Win%/accuracy model.
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
    # Preserve the deepest engine data used for the before/after decision.
    before_engine_lines: dict[int, EngineLine]
    before_engine_bestmove: str | None
    after_engine_lines: dict[int, EngineLine]
    after_engine_bestmove: str | None


def _score(line: EngineLine | None) -> tuple[int | None, int | None]:
    if line is None or not line.is_exact:
        return None, None
    return line.score_cp, line.mate


def _score_for_win_percent(cp: int | None, mate: int | None) -> int | None:
    """Normalize an engine score only for the Win% model."""
    if mate is not None:
        return 1000 if mate > 0 else -1000
    if cp is None:
        return None
    return max(-1000, min(1000, cp))


def _team_relative_cp(stm_cp: int | None, stm_player: str, pov_team: str) -> int | None:
    if stm_cp is None:
        return None
    return stm_cp if TEAM[stm_player] == pov_team else -stm_cp


def _team_relative_score_for_win_percent(cp: int | None, mate: int | None, stm_player: str, pov_team: str) -> int | None:
    normalized = _score_for_win_percent(cp, mate)
    return _team_relative_cp(normalized, stm_player, pov_team)


def _win_percent(cp: int) -> float:
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def _move_accuracy(before_win: float, after_win: float) -> float:
    if after_win >= before_win:
        return 100.0
    win_diff = before_win - after_win
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * win_diff) - 3.166924740191411
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
    candidates = []
    mover_team = TEAM[mover]
    for multipv in sorted(lines):
        line = lines[multipv]
        if not line.pv:
            continue
        if not line.is_exact or line.mate is not None or line.score_cp is None:
            continue
        # Keep raw CP for engine-agreement/separation statistics.
        relative_cp = _team_relative_cp(line.score_cp, mover, mover_team)
        if relative_cp is not None:
            candidates.append((line.pv[0], relative_cp))
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def _agreement(before_result_lines: dict[int, EngineLine], move: ParsedMove, multipv_supported: bool):
    if not multipv_supported:
        return None, None, None, None, None, 0
    candidates = _candidate_data(before_result_lines, move.player)
    if not candidates:
        return None, None, None, None, None, 0
    best_move, best_cp = candidates[0]
    second_cp = candidates[1][1] if len(candidates) >= 2 else None
    played_entry = next((cp for candidate_move, cp in candidates if candidate_move == move.uci), None)
    played_rank = next((i + 1 for i, (candidate_move, _) in enumerate(candidates) if candidate_move == move.uci), None)
    return best_move, played_rank, best_cp, played_entry, second_cp, len(candidates)


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


def _is_checkmate_move(game: Game, index: int, move: ParsedMove) -> bool:
    if index != len(game.moves) - 1:
        return False
    termination = game.headers.get("Termination", "").strip().lower()
    return "checkmate" in termination or "#" in move.notation


def _copy_lines(result: SearchResult | None) -> dict[int, EngineLine]:
    if result is None:
        return {}
    return dict(result.lines)


def analyze_game(game: Game, engine: UCIEngine) -> list[MoveAnalysis]:
    state = PositionState(fen=START_FEN)
    results: list[MoveAnalysis] = []
    current_result = engine.analyze(state.fen, state.uci_moves(), ANALYSIS_DEPTH)
    current_line = current_result.lines.get(1)

    for index, move in enumerate(game.moves):
        print(f"Analyzing ply {index + 1}/{len(game.moves)}: {move.notation}")
        before_raw_cp, before_mate = _score(current_line)
        before_cp = _score_for_win_percent(before_raw_cp, before_mate)
        before_mover_cp = _team_relative_score_for_win_percent(
            before_raw_cp, before_mate, move.player, TEAM[move.player]
        )
        before_win = _win_percent(before_mover_cp) if before_mover_cp is not None else None

        (
            engine_best_move,
            played_move_rank,
            best_cp,
            played_root_cp,
            second_cp,
            engine_candidate_count,
        ) = _agreement(current_result.lines, move, engine.multipv_supported)

        before_engine_lines = _copy_lines(current_result)
        before_engine_bestmove = current_result.bestmove

        state.play(move)
        next_player = PLAYERS[(index + 1) % 4]
        after_result: SearchResult | None = None

        # Always try the engine first. For engines that correctly report a
        # terminal score, this gives us genuine mate information. The PGN
        # terminal marker is only a fallback when no exact score is returned.
        try:
            after_result = engine.analyze(state.fen, state.uci_moves(), ANALYSIS_DEPTH)
        except Exception:
            after_result = None

        after_line = after_result.lines.get(1) if after_result is not None else None
        after_raw_cp, after_mate = _score(after_line)

        if after_raw_cp is None and after_mate is None and _is_checkmate_move(game, index, move):
            # Do not invent a mate distance. Represent the terminal result
            # separately through the Win% normalization only.
            terminal_mate = 1 if TEAM[next_player] == TEAM[move.player] else -1
            after_mate = terminal_mate
            after_raw_cp = None

        after_cp = _score_for_win_percent(after_raw_cp, after_mate)
        after_mover_cp = _team_relative_score_for_win_percent(
            after_raw_cp, after_mate, next_player, TEAM[move.player]
        )
        after_win = _win_percent(after_mover_cp) if after_mover_cp is not None else None

        accuracy = _move_accuracy(before_win, after_win) if before_win is not None and after_win is not None else None

        # True root-level best-vs-played: both values come from the same
        # BEFORE search and are expressed from the mover's team POV. If the
        # played move is outside the returned MultiPV candidates, leave this
        # statistic unassessed rather than mixing in the after-position score.
        best_vs_played_cp = (
            max(0, best_cp - played_root_cp)
            if best_cp is not None and played_root_cp is not None
            else None
        )
        best_vs_second_cp = (
            max(0, best_cp - second_cp)
            if best_cp is not None and second_cp is not None
            else None
        )
        after_ry_cp = _team_relative_cp(after_cp, next_player, "RY")

        results.append(
            MoveAnalysis(
                move,
                before_raw_cp,
                before_cp,
                before_mate,
                after_raw_cp,
                after_cp,
                after_mate,
                before_mover_cp,
                after_mover_cp,
                before_win,
                after_win,
                accuracy,
                _classify_accuracy(accuracy),
                current_line.depth if current_line else 0,
                after_ry_cp,
                engine_best_move,
                played_move_rank,
                best_vs_played_cp,
                engine_candidate_count,
                best_vs_second_cp,
                _criticality(best_vs_second_cp),
                _decision_difficulty(best_vs_second_cp),
                before_engine_lines,
                before_engine_bestmove,
                _copy_lines(after_result),
                after_result.bestmove if after_result is not None else None,
            )
        )

        if after_line is None:
            break
        current_result = after_result
        current_line = after_line
    return results
