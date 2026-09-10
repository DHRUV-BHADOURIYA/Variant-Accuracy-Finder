from __future__ import annotations

from dataclasses import dataclass, field

from config import START_FEN
from png import ParsedMove


@dataclass
class PositionState:
    fen: str = START_FEN
    moves: list[str] = field(default_factory=list)

    def uci_moves(self) -> list[str]:
        return list(self.moves)

    def play(self, move: ParsedMove) -> None:
        self.moves.append(move.uci)

    def copy_with_move(self, move: ParsedMove) -> "PositionState":
        result = PositionState(self.fen, list(self.moves))
        result.play(move)
        return result
