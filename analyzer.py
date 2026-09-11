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

    # Engine agreement: candidates are ranked from the moving player's team POV.
    engine_best_move: str | None
    played_move_rank: int | None
    best_vs_played_cp: int | None
    engine_candidate_count: int

    # Initial criticality measure: separation between engine #1 and #2.
    best_vs_second_cp: int | None
    criticality: str


def _score(line: EngineLine | None) -> tuple[int | None, int | None]:
    if line is None or not line.is_exact:
        return None, None
    return line.score_cp, line.mate


def _score_as_cp(cp: int | None, mate: int | None) -> int | None:
    """Lichess-style CP representation, capped at +/-1000."""
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
    """Current Lichess AccuracyPercent.fromWinPercents implementation."""
    if after_win >= before_win:
        return 100.0
    win_diff = before_win - after_win
    raw = (
        103.1668100711649 * math.exp(-0.04354415386753951 * win_diff)
        - 3.166924740191411
    )
    return max(0.0, min(100.0, raw + 1.0))


def _classify_accuracy(accuracy: float | None) -> str:
    """Provisional move-quality bands; thresholds are intentionally configurable later."""
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


def _candidate_data(
    lines: dict[int, EngineLine],
    mover: str,
) -> list[tuple[str, int]]:
    """Return exact engine candidates ordered best-to-worst for the mover's team."""
    candidates: list[tuple[str, int]] = []
    mover_team = TEAM[mover]
    stm_player = mover

    for multipv in sorted(lines):
        line = lines[multipv]
        if not line.pv:
            continue
        cp = _score_as_cp(line.score_cp, line.mate)
        if cp is None:
            continue
        relative_cp = _team_relative_cp(cp, stm_player, mover_team)
        if relative_cp is None:
            continue
        candidates.append((line.pv[0], relative_cp))

    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def _agreement(
    before_result_lines: dict[int, EngineLine],
    move: ParsedMove,
) -> tuple[str | None, int | None, int | None, int | None, int | None]:
    """Calculate engine rank and gaps from the mover's team perspective."""
    candidates = _candidate_data(before_result_lines, move.player)
    if not candidates:
        return None, None, None, None, None

    best_move, best_cp = candidates[0]
    second_cp = candidates[1][1] if len(candidates) >= 2 else None
    played_rank = next(
        (index + 1 for index, (candidate_move, _) in enumerate(candidates) if candidate_move == move.uci),
        None,
    )

    # The played move's actual child evaluation is more authoritative than a
    # candidate PV score, so this is filled by the caller after evaluating the child.
    return best_move, played_rank, best_cp, second_cp, len(candidates)


def _criticality(best_vs_second_cp: int | None) -> str:
    """Initial engine-separation criticality; deliberately not a cheating score."""
    if best_vs_second_cp is None:
        return "UNASSESSED"
    if best_vs_second_cp >= 150:
        return "VERY_HIGH"
    if best_vs_second_cp >= 75:
        return "HIGH"
    if best_vs_second_cp >= 30:
        return "MEDIUM"
    return "LOW"


def analyze_game(game: Game, engine: UCIEngine) -> list[MoveAnalysis]:
    state = PositionState(fen=START_FEN)
    results: list[MoveAnalysis] = []

    # Each mainline position is evaluated once. MultiPV=3 gives us the engine's
    # leading alternatives at the position before the played move.
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
        ) = _agreement(current_result.lines, move)

        state.play(move)
        next_player = PLAYERS[(index + 1) % 4]

        after_result = engine.analyze(state.fen, state.uci_moves(), ANALYSIS_DEPTH)
        after_line = after_result.lines.get(1)
        after_cp_raw, after_mate = _score(after_line)
        after_cp = _score_as_cp(after_cp_raw, after_mate)
        after_mover_cp = _team_relative_cp(after_cp, next_player, TEAM[move.player])
        after_win = _win_percent(after_mover_cp) if after_mover_cp is not None else None

        accuracy = None
        if before_win is not None and after_win is not None:
            accuracy = _move_accuracy(before_win, after_win)

        # Use the actual resulting position to measure how well the played move
        # scored from the mover's team perspective.
        best_vs_played_cp = None
        if best_cp is not None and after_mover_cp is not None:
            best_vs_played_cp = max(0, best_cp - after_mover_cp)

        best_vs_second_cp = None
        if best_cp is not None and second_cp is not None:
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
            )
        )

        current_result = after_result
        current_line = after_line

    return results
