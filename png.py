from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


PLAYERS = ("Red", "Blue", "Yellow", "Green")


@dataclass(frozen=True)
class ParsedMove:
    ply: int
    round_number: int
    player: str
    notation: str
    uci: str


@dataclass
class Game:
    headers: dict[str, str]
    moves: list[ParsedMove]


_MOVE_TOKEN_RE = re.compile(r"(?:[KQRBN][a-n]?\d+)?[a-n]\d+(?:[-x][KQRBN]?[a-n]\d+)?(?:=[QRBN])?[+#]?")
_COORD_RE = re.compile(r"([a-n]\d+)")


def _strip_noise(text: str) -> str:
    # Remove brace comments and semicolon comments.
    text = re.sub(r"\{[^}]*\}", " ", text, flags=re.S)
    text = re.sub(r";[^\n]*", " ", text)
    # Remove recursive annotation variations. PGNs from Chess.com normally do
    # not contain these, but handling them here keeps the parser conservative.
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\([^()]*\)", " ", text)
    return text


def _normalize_move(token: str) -> str | None:
    token = token.strip()
    if not token or token in {"...", "#", "++"}:
        return None

    token = re.sub(r"[+#]+$", "", token)

    # Chess.com 4PC uses forms such as Bi1xc7, Qh14-d10, and h2-h3.
    # The destination can have a piece prefix for captures (xQc5).
    coords = _COORD_RE.findall(token)
    if len(coords) < 2:
        return None

    source, destination = coords[-2], coords[-1]
    promotion = ""
    promo = re.search(r"=([QRBN])", token, re.I)
    if promo:
        promotion = promo.group(1).lower()

    return f"{source}{destination}{promotion}"


def parse_pgn_text(text: str) -> Game:
    headers: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r'^\s*\[([^\s]+)\s+"(.*)"\]\s*$', line)
        if match:
            headers[match.group(1)] = match.group(2)

    body_lines = [line for line in text.splitlines() if not re.match(r'^\s*\[[^\]]+\]\s*$', line)]
    body = _strip_noise("\n".join(body_lines))

    # Strip move numbers (1., 2., ... and 1... forms) and result markers.
    body = re.sub(r"\b\d+\.(?:\.\.)?", " ", body)
    body = re.sub(r"\b(?:1-0|0-1|1/2-1/2|\*)\b", " ", body)

    raw_tokens = body.split()
    moves: list[ParsedMove] = []
    ply = 0

    for token in raw_tokens:
        # A lone '#' is the termination marker, not a move.
        if token in {"#", "++", "..."}:
            continue
        uci = _normalize_move(token)
        if uci is None:
            continue

        player = PLAYERS[ply % 4]
        moves.append(
            ParsedMove(
                ply=ply,
                round_number=(ply // 4) + 1,
                player=player,
                notation=token,
                uci=uci,
            )
        )
        ply += 1

    return Game(headers=headers, moves=moves)


def parse_pgn(path: str | Path) -> Game:
    path = Path(path)
    return parse_pgn_text(path.read_text(encoding="utf-8"))
