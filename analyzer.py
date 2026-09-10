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
    depth: int
    after_ry_cp: int | None


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


def analyze_game(game: Game, engine: UCIEngine) -> list[MoveAnalysis]:
    state = PositionState(fen=START_FEN)
    results: list[MoveAnalysis] = []

    # Lichess evaluates each mainline position once and compares adjacent
    # positions. There is deliberately no root searchmoves measurement here.
    current_result = engine.analyze(state.fen, state.uci_moves(), ANALYSIS_DEPTH)
    current_line = current_result.lines.get(1)

    for index, move in enumerate(game.moves):
        print(f"Analyzing ply {index + 1}/{len(game.moves)}: {move.notation}")

        before_cp_raw, before_mate = _score(current_line)
        before_cp = _score_as_cp(before_cp_raw, before_mate)
        before_mover_cp = _team_relative_cp(before_cp, move.player, TEAM[move.player])
        before_win = _win_percent(before_mover_cp) if before_mover_cp is not None else None

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

        # Fixed RY POV is used by the Lichess-style game aggregation below.
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
                depth=current_line.depth if current_line else 0,
                after_ry_cp=after_ry_cp,
            )
        )

        current_line = after_line

    return results
