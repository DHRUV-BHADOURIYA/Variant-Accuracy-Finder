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
    after_cp: int | None
    after_mate: int | None
    mover_after_cp: int | None
    cp_loss: float | None
    accuracy: float | None
    best_move: str | None
    engine_bestmove: str | None
    depth: int
    score_anomaly: bool = False


def _score(line: EngineLine | None) -> tuple[int | None, int | None]:
    if line is None:
        return None, None
    return line.score_cp, line.mate


def _mover_perspective_after(line: EngineLine | None) -> int | None:
    """Convert resulting-position CP from next STM to the mover perspective."""
    if line is None or line.score_cp is None or line.mate is not None:
        return None
    return -line.score_cp


def analyze_game(game: Game, engine: UCIEngine) -> list[MoveAnalysis]:
    state = PositionState(fen=START_FEN)
    results: list[MoveAnalysis] = []

    for index, move in enumerate(game.moves):
        print(f"Analyzing ply {index + 1}/{len(game.moves)}: {move.notation}")

        # Search the position before the played move. MultiPV is intentionally
        # not used: the single-PV root result is authoritative for accuracy.
        before_result = engine.analyze(state.fen, state.uci_moves(), ANALYSIS_DEPTH)
        best_line = before_result.lines.get(1)
        best_cp, best_mate = _score(best_line)
        engine_bestmove = before_result.bestmove
        best_move = engine_bestmove
        if best_move is None and best_line and best_line.pv:
            best_move = best_line.pv[0]

        # Search the actual resulting position with the same single-PV setup.
        after_state = state.copy_with_move(move)
        after_result = engine.analyze(after_state.fen, after_state.uci_moves(), ANALYSIS_DEPTH)
        played_line = after_result.lines.get(1)
        after_cp, after_mate = _score(played_line)

        mover_after_cp = _mover_perspective_after(played_line)
        cp_loss: float | None = None
        accuracy: float | None = None
        if best_cp is not None and mover_after_cp is not None:
            cp_loss = max(0.0, float(best_cp - mover_after_cp))
            from report import lichess_accuracy
            accuracy = lichess_accuracy(best_cp, mover_after_cp)

        # This should normally be impossible for a consistent search result.
        # Keep the warning rather than manufacturing a negative loss.
        score_anomaly = (
            best_cp is not None
            and mover_after_cp is not None
            and mover_after_cp > best_cp
        )

        results.append(
            MoveAnalysis(
                move=move,
                best_cp=best_cp,
                best_mate=best_mate,
                after_cp=after_cp,
                after_mate=after_mate,
                mover_after_cp=mover_after_cp,
                cp_loss=cp_loss,
                accuracy=accuracy,
                best_move=best_move,
                engine_bestmove=engine_bestmove,
                depth=best_line.depth if best_line else 0,
                score_anomaly=score_anomaly,
            )
        )
        state.play(move)

    return results
