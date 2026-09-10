from __future__ import annotations

import math
from pathlib import Path
from statistics import mean, pstdev

from analyzer import MoveAnalysis, TEAM
from png import Game


PLAYERS = ("Red", "Blue", "Yellow", "Green")
TEAMS = ("RY", "BG")


def win_percent(cp: float) -> float:
    """Lichess WinPercent.fromCentiPawns mapping."""
    cp = max(-1000.0, min(1000.0, cp))
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def lichess_accuracy(before_cp: float, after_cp: float) -> float:
    """Current Lichess AccuracyPercent.fromWinPercents."""
    before = win_percent(before_cp)
    after = win_percent(after_cp)
    if after >= before:
        return 100.0
    win_diff = before - after
    raw = (
        103.1668100711649 * math.exp(-0.04354415386753951 * win_diff)
        - 3.166924740191411
    )
    return max(0.0, min(100.0, raw + 1.0))


def _fmt_score(cp: int | None, mate: int | None) -> str:
    if mate is not None:
        return f"M{mate:+d}"
    if cp is None:
        return "N/A"
    return f"{cp:+d}"


def _fmt_float(value: float | None, digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def _player_names(headers: dict[str, str]) -> dict[str, str]:
    return {color: headers.get(color, color) for color in PLAYERS}


def _accuracy_with_uncertainty(accuracy: float, weight: float) -> tuple[float, float]:
    return accuracy, weight


def _game_accuracy(analyses: list[MoveAnalysis], keys: set[str]) -> float | None:
    """Port of Lichess AccuracyPercent.gameAccuracy for one group.

    The position WinPercents are kept in fixed RY POV. Each move's accuracy is
    computed in the mover's POV, then the Lichess volatility-weighted mean and
    harmonic mean are combined 50/50.
    """
    if not analyses:
        return None

    # Lichess uses Eval.Cp.initial = 15 for the initial position.
    cps: list[int | None] = [15] + [item.after_ry_cp for item in analyses]
    win_percents: list[float | None] = [win_percent(15)] + [
        win_percent(cp) if cp is not None else None for cp in cps[1:]
    ]

    move_count = len(analyses)
    window_size = max(2, min(8, move_count // 10))
    window_size = min(window_size, len(win_percents))

    windows: list[list[float | None]] = []
    windows.extend([win_percents[:window_size]] * max(0, window_size - 2))
    windows.extend(
        win_percents[i : i + window_size]
        for i in range(len(win_percents) - window_size + 1)
    )

    weights: list[float | None] = []
    for window in windows:
        if any(value is None for value in window):
            weights.append(None)
            continue
        values = [value for value in window if value is not None]
        weight = max(0.5, min(12.0, pstdev(values)))
        weights.append(weight)

    weighted_values: list[tuple[float, float]] = []
    raw_values: list[float] = []

    for index, item in enumerate(analyses):
        if item.accuracy is None:
            continue
        if item.move.player not in keys and TEAM[item.move.player] not in keys:
            continue
        if index >= len(weights) or weights[index] is None:
            continue
        weighted_values.append((item.accuracy, weights[index]))
        raw_values.append(item.accuracy)

    if not weighted_values or not raw_values:
        return None

    weighted_mean = sum(value * weight for value, weight in weighted_values) / sum(
        weight for _, weight in weighted_values
    )

    if any(value <= 0.0 for value in raw_values):
        harmonic_mean = 0.0
    else:
        harmonic_mean = len(raw_values) / sum(1.0 / value for value in raw_values)

    return (weighted_mean + harmonic_mean) / 2.0


def generate_report(game: Game, analyses: list[MoveAnalysis]) -> str:
    headers = game.headers
    names = _player_names(headers)

    lines: list[str] = []
    lines.append("4PC VARIANT ACCURACY FINDER — V2.0")
    lines.append("=" * 86)
    lines.append(f"Game:       {headers.get('GameNr', 'Unknown')}")
    lines.append(f"Variant:    {headers.get('Variant', 'Unknown')}")
    lines.append(f"Result:     {headers.get('Result', 'Unknown')}")
    lines.append(f"Termination:{headers.get('Termination', 'Unknown')}")
    lines.append("")
    lines.append("Players:")
    for color in PLAYERS:
        lines.append(f"  {color:<7} {names[color]}")
    lines.append("")
    lines.append("Teams: RY = Red + Yellow | BG = Blue + Green")
    lines.append("Accuracy model: Lichess AccuracyPercent methodology adapted to 4PC teams.")
    lines.append("Evaluation: one unrestricted engine evaluation per mainline position at the configured depth.")
    lines.append("Move scoring: compare the position before and after the actual move; no searchmoves restriction.")
    lines.append("Perspective: evaluations are converted from STM to the moving player's team perspective.")
    lines.append("Win%: Lichess sigmoid with CP capped at +/-1000.")
    lines.append("Move accuracy: current Lichess AccuracyPercent formula, including the +1 uncertainty bonus.")
    lines.append("Game accuracy: 50% volatility-weighted mean + 50% harmonic mean, matching Lichess.")
    lines.append("")

    player_keys = {color: {color} for color in PLAYERS}
    team_keys = {team: {team} for team in TEAMS}

    lines.append("SUMMARY")
    lines.append("-" * 86)
    for color in PLAYERS:
        accuracy = _game_accuracy(analyses, player_keys[color])
        lines.append(f"{color:<7} {names[color]:<24} Accuracy: {_fmt_float(accuracy)}")
    lines.append("")
    for team in TEAMS:
        accuracy = _game_accuracy(analyses, team_keys[team])
        lines.append(f"Team {team:<3} {'':<24} Accuracy: {_fmt_float(accuracy)}")

    lines.append("")
    lines.append("MOVE-BY-MOVE")
    lines.append("-" * 86)
    lines.append(
        "Ply Rd Player       Played       Before   After    MoverBefore MoverAfter  Acc"
    )

    for item in analyses:
        lines.append(
            f"{item.move.ply + 1:>3} "
            f"{item.move.round_number:>2} "
            f"{item.move.player:<11} "
            f"{item.move.notation:<12} "
            f"{_fmt_score(item.before_cp, item.before_mate):>7} "
            f"{_fmt_score(item.after_cp, item.after_mate):>7} "
            f"{_fmt_score(item.before_mover_cp, None):>11} "
            f"{_fmt_score(item.after_mover_cp, None):>10} "
            f"{_fmt_float(item.accuracy):>6}"
        )

    lines.append("")
    lines.append("Notes")
    lines.append("- Before/After are raw engine scores from the side-to-move perspective, capped at +/-1000 for Lichess Win% conversion.")
    lines.append("- MoverBefore/MoverAfter are converted to the moving player's team perspective.")
    lines.append("- A teammate's next-turn evaluation keeps the sign; an opponent's next-turn evaluation is inverted.")
    lines.append("- Mate scores are converted to +/-1000 before Win% conversion; mate transitions remain part of the Lichess-style calculation.")
    lines.append("- The initial position uses Lichess's initial CP value of +15 in the fixed RY perspective for game aggregation.")
    lines.append("- Player and team summaries use the same volatility-weighted + harmonic aggregation, not an arithmetic mean.")
    lines.append("- The four-player team mapping is RY versus BG; Lichess's White/Black POV is replaced by fixed team POV.")

    return "\n".join(lines)


def save_report(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")
