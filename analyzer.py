from __future__ import annotations

from dataclasses import dataclass

from board import PositionState
from config import ANALYSIS_DEPTH, START_FEN
from png import Game, ParsedMove
from uci_engine import EngineLine, UCIEngine


@dataclass
class MoveAnalysis:
    move: ParsedMove
    best_cp: int | None
    best_mate: int | None
    played_cp: int | None
    played_mate: int | None
    cp_loss: float | None
    accuracy: float | None
    best_move: str | None
    rank: int | None
    depth: int


def _score(line: EngineLine | None) -> tuple[int | None, int | None]:
    if line is None:
        return None, None
    return line.score_cp, line.mate


def _mover_perspective_after(line: EngineLine | None) -> int | None:
    # The engine reports score from the current side-to-move perspective.
    # After a played move, the opponent is STM, so negate the CP score.
    if line is None or line.score_cp is None or line.mate is not None:
        return None
    return -line.score_cp


def analyze_game(game: Game, engine: UCIEngine) -> list[MoveAnalysis]:
    state = PositionState(fen=START_FEN)
    results: list[MoveAnalysis] = []

    for index, move in enumerate(game.moves):
        print(f"Analyzing ply {index + 1}/{len(game.moves)}: {move.notation}")

        before = engine.analyze(state.fen, state.uci_moves(), ANALYSIS_DEPTH)
        best_line = before.get(1)
        best_cp, best_mate = _score(best_line)
        best_move = best_line.pv[0] if best_line and best_line.pv else None

        after_state = state.copy_with_move(move)
        after = engine.analyze(after_state.fen, after_state.uci_moves(), ANALYSIS_DEPTH)
        played_line = after.get(1)
        played_cp, played_mate = _score(played_line)

        mover_after_cp = _mover_perspective_after(played_line)
        cp_loss: float | None = None
        accuracy: float | None = None
        if best_cp is not None and mover_after_cp is not None:
            cp_loss = max(0.0, float(best_cp - mover_after_cp))
            from report import lichess_accuracy
            accuracy = lichess_accuracy(best_cp, mover_after_cp)

        rank = None
        for multipv, line in before.items():
            if line.pv and line.pv[0].lower() == move.uci.lower():
                rank = multipv
                break

        results.append(
            MoveAnalysis(
                move=move,
                best_cp=best_cp,
                best_mate=best_mate,
                played_cp=played_cp,
                played_mate=played_mate,
                cp_loss=cp_loss,
                accuracy=accuracy,
                best_move=best_move,
                rank=rank,
                depth=best_line.depth if best_line else 0,
            )
        )
        state.play(move)

    return results
