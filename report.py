from __future__ import annotations

import math
from pathlib import Path
from statistics import mean

from analyzer import MoveAnalysis
from png import Game


TEAM = {
    "Red": "RY",
    "Yellow": "RY",
    "Blue": "BG",
    "Green": "BG",
}


def win_percent(cp: float) -> float:
    """Lichess win-percent mapping from centipawns."""
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def lichess_accuracy(before_cp: float, after_cp: float) -> float:
    """Lichess move accuracy formula, clamped to [0, 100]."""
    before = win_percent(before_cp)
    after = win_percent(after_cp)
    value = 103.1668 * math.exp(-0.04354 * (before - after)) - 3.1669
    return max(0.0, min(100.0, value))


def _fmt_score(cp: int | None, mate: int | None) -> str:
    if mate is not None:
        return f"M{mate:+d}"
    if cp is None:
        return "N/A"
    return f"{cp:+d}"


def _fmt_float(value: float | None, digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def _player_names(headers: dict[str, str]) -> dict[str, str]:
    return {color: headers.get(color, color) for color in TEAM}


def generate_report(game: Game, analyses: list[MoveAnalysis]) -> str:
    headers = game.headers
    names = _player_names(headers)

    lines: list[str] = []
    lines.append("4PC VARIANT ACCURACY FINDER — V1.1")
    lines.append("=" * 72)
    lines.append(f"Game:       {headers.get('GameNr', 'Unknown')}")
    lines.append(f"Variant:    {headers.get('Variant', 'Unknown')}")
    lines.append(f"Result:     {headers.get('Result', 'Unknown')}")
    lines.append(f"Termination:{headers.get('Termination', 'Unknown')}")
    lines.append("")
    lines.append("Players:")
    for color in ("Red", "Blue", "Yellow", "Green"):
        lines.append(f"  {color:<7} {names[color]}")
    lines.append("")
    lines.append("Teams: RY = Red + Yellow | BG = Blue + Green")
    lines.append("Accuracy: Lichess move-accuracy formula applied to STM-relative CP.")
    lines.append("Score convention: every raw engine score is from the current STM perspective.")
    lines.append("After a move, MoverAfterCP is the negated score of the resulting position.")
    lines.append("Mate transitions are reported but excluded from CP-loss/accuracy averages in V1.1.")
    lines.append("")

    by_player: dict[str, list[float]] = {p: [] for p in TEAM}
    by_team: dict[str, list[float]] = {"RY": [], "BG": []}
    for item in analyses:
        if item.accuracy is not None:
            by_player[item.move.player].append(item.accuracy)
            by_team[TEAM[item.move.player]].append(item.accuracy)

    lines.append("SUMMARY")
    lines.append("-" * 72)
    for color in ("Red", "Blue", "Yellow", "Green"):
        scores = by_player[color]
        avg = mean(scores) if scores else None
        lines.append(f"{color:<7} {names[color]:<24} Accuracy: {_fmt_float(avg)}")
    lines.append("")
    for team in ("RY", "BG"):
        avg = mean(by_team[team]) if by_team[team] else None
        lines.append(f"Team {team:<3} {'':<24} Accuracy: {_fmt_float(avg)}")

    lines.append("")
    lines.append("MOVE-BY-MOVE")
    lines.append("-" * 72)
    lines.append(
        "Ply Rd Player       Played       Best         BestCP AfterCP MoverCP Loss   Acc    Rank"
    )

    for item in analyses:
        marker = " !" if item.score_anomaly else ""
        lines.append(
            f"{item.move.ply + 1:>3} "
            f"{item.move.round_number:>2} "
            f"{item.move.player:<11} "
            f"{item.move.notation:<12} "
            f"{(item.best_move or 'N/A'):<12} "
            f"{_fmt_score(item.best_cp, item.best_mate):>6} "
            f"{_fmt_score(item.after_cp, item.after_mate):>7} "
            f"{_fmt_score(item.mover_after_cp, None):>7} "
            f"{_fmt_float(item.cp_loss, 1):>5} "
            f"{_fmt_float(item.accuracy):>6} "
            f"{item.rank if item.rank is not None else 'N/A':>4}{marker}"
        )

    anomalies = [item for item in analyses if item.score_anomaly]
    if anomalies:
        lines.append("")
        lines.append("SEARCH INVARIANT WARNINGS")
        lines.append("-" * 72)
        for item in anomalies:
            lines.append(
                f"Ply {item.move.ply + 1}: played move {item.move.uci} has "
                f"MoverAfterCP {item.mover_after_cp:+d}, above root BestCP {item.best_cp:+d}."
            )
            lines.append(
                "  This is not silently treated as negative loss; inspect the engine/search pipeline."
            )

    lines.append("")
    lines.append("Notes")
    lines.append("- BestCP is the root score before the move, from the mover's STM perspective.")
    lines.append("- AfterCP is the raw score after the played move, from the next player's STM perspective.")
    lines.append("- MoverAfterCP = -AfterCP for normal CP scores.")
    lines.append("- CP loss = max(0, BestCP - MoverAfterCP).")
    lines.append("- Rank is based on the MultiPV lines; V1.1 uses MultiPV=3.")
    lines.append("- If the played move is outside MultiPV=3, rank is N/A rather than guessed.")
    lines.append("- Best uses the engine's UCI bestmove when available; PV[0] is the fallback.")
    lines.append("- Player/team averages are arithmetic means of eligible move accuracies.")

    return "\n".join(lines)


def save_report(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")
