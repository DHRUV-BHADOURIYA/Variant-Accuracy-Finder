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
    engine_bestmove: str | None
    depth: int
    score_anomaly: bool = False


def _score(line: EngineLine | None) -> tuple[int | None, int | None]:
    if line is None or not line.is_exact:
        return None, None
    return line.score_cp, line.mate


def analyze_game(game: Game, engine: UCIEngine) -> list[MoveAnalysis]:
    state = PositionState(fen=START_FEN)
    results: list[MoveAnalysis] = []

    for index, move in enumerate(game.moves):
        print(f"Analyzing ply {index + 1}/{len(game.moves)}: {move.notation}")

        # Search the best move from the current root.
        before_result = engine.analyze(
            state.fen,
            state.uci_moves(),
            ANALYSIS_DEPTH,
        )
        best_line = before_result.lines.get(1)
        best_cp, best_mate = _score(best_line)
        engine_bestmove = before_result.bestmove
        best_move = engine_bestmove
        if best_move is None and best_line and best_line.pv:
            best_move = best_line.pv[0]

        # Clear the hash before the second measurement. The played-move score
        # must not inherit TT entries produced by the unrestricted search.
        engine.clear_hash()

        # Evaluate the actual played move from the exact same root position
        # with an independent transposition-table state.
        played_result = engine.analyze(
            state.fen,
            state.uci_moves(),
            ANALYSIS_DEPTH,
            searchmoves=[move.uci],
        )
        played_line = played_result.lines.get(1)
        played_cp, played_mate = _score(played_line)

        cp_loss: float | None = None
        accuracy: float | None = None
        if best_cp is not None and played_cp is not None:
            cp_loss = max(0.0, float(best_cp - played_cp))
            from report import lichess_accuracy
            accuracy = lichess_accuracy(best_cp, played_cp)

        score_anomaly = (
            best_cp is not None
            and played_cp is not None
            and played_cp > best_cp
        )

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
                engine_bestmove=engine_bestmove,
                depth=best_line.depth if best_line else 0,
                score_anomaly=score_anomaly,
            )
        )
        state.play(move)

    return results
