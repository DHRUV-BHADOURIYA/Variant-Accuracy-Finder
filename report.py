from __future__ import annotations

import math
from pathlib import Path
from statistics import median, pstdev

from analyzer import MoveAnalysis, TEAM
from png import Game


PLAYERS = ("Red", "Blue", "Yellow", "Green")
TEAMS = ("RY", "BG")
CLASSIFICATIONS = ("BEST", "EXCELLENT", "GOOD", "INACCURACY", "MISTAKE", "BLUNDER")
DIFFICULTIES = ("NEAR_EQUIVALENT", "CLOSE", "DIFFERENT", "VERY_DIFFERENT")


def win_percent(cp: float) -> float:
    cp = max(-1000.0, min(1000.0, cp))
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def lichess_accuracy(before_cp: float, after_cp: float) -> float:
    before = win_percent(before_cp)
    after = win_percent(after_cp)
    if after >= before:
        return 100.0
    win_diff = before - after
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * win_diff) - 3.166924740191411
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


def _multipv_available(analyses: list[MoveAnalysis]) -> bool:
    return any(item.engine_candidate_count >= 2 for item in analyses)


def _game_accuracy(analyses: list[MoveAnalysis], keys: set[str]) -> float | None:
    if not analyses:
        return None
    cps: list[int | None] = [15] + [item.after_ry_cp for item in analyses]
    win_percents: list[float | None] = [win_percent(15)] + [win_percent(cp) if cp is not None else None for cp in cps[1:]]
    move_count = len(analyses)
    window_size = max(2, min(8, move_count // 10))
    window_size = min(window_size, len(win_percents))

    windows: list[list[float | None]] = []
    windows.extend([win_percents[:window_size]] * max(0, window_size - 2))
    windows.extend(win_percents[i : i + window_size] for i in range(len(win_percents) - window_size + 1))

    weights: list[float | None] = []
    for window in windows:
        if any(value is None for value in window):
            weights.append(None)
            continue
        values = [value for value in window if value is not None]
        weights.append(max(0.5, min(12.0, pstdev(values))))

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
    weighted_mean = sum(value * weight for value, weight in weighted_values) / sum(weight for _, weight in weighted_values)
    harmonic_mean = 0.0 if any(value <= 0.0 for value in raw_values) else len(raw_values) / sum(1.0 / value for value in raw_values)
    return (weighted_mean + harmonic_mean) / 2.0


def _team_items(analyses: list[MoveAnalysis], team: str) -> list[MoveAnalysis]:
    return [item for item in analyses if TEAM[item.move.player] == team and item.accuracy is not None]


def _rank_label(item: MoveAnalysis) -> int | str | None:
    if item.played_move_rank in (1, 2, 3):
        return item.played_move_rank
    if item.played_move_rank is not None:
        return "OUTSIDE"
    return None


def _rank_stats(items: list[MoveAnalysis]) -> tuple[int, int, int, int]:
    ranked = [_rank_label(item) for item in items]
    ranked = [rank for rank in ranked if rank is not None]
    return (
        sum(rank == 1 for rank in ranked),
        sum(rank == 2 for rank in ranked),
        sum(rank == 3 for rank in ranked),
        sum(rank == "OUTSIDE" for rank in ranked),
    )


def _longest_rank1_streak(items: list[MoveAnalysis]) -> int:
    best = current = 0
    for item in items:
        if item.played_move_rank == 1:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _hard_rank1(items: list[MoveAnalysis]) -> tuple[int, int]:
    eligible = [item for item in items if item.decision_difficulty in {"DIFFERENT", "VERY_DIFFERENT"}]
    rank1 = sum(item.played_move_rank == 1 for item in eligible)
    return rank1, len(eligible)


def _difficulty_table(analyses: list[MoveAnalysis]) -> list[str]:
    lines = [
        "ENGINE DECISION SEPARATION — RY vs BG",
        "-" * 128,
        "Difficulty        RY Moves   RY #1   RY #1 %      BG Moves   BG #1   BG #1 %",
    ]
    for difficulty in DIFFICULTIES:
        values = []
        for team in TEAMS:
            items = [item for item in _team_items(analyses, team) if item.decision_difficulty == difficulty]
            rank1 = sum(item.played_move_rank == 1 for item in items)
            pct = 100.0 * rank1 / len(items) if items else 0.0
            values.append((len(items), rank1, pct))
        lines.append(
            f"{difficulty:<17} {values[0][0]:>7} {values[0][1]:>7} {values[0][2]:>8.2f}%   "
            f"{values[1][0]:>8} {values[1][1]:>7} {values[1][2]:>8.2f}%"
        )
    return lines


def _fair_play_table(analyses: list[MoveAnalysis]) -> list[str]:
    if not _multipv_available(analyses):
        return [
            "FAIR-PLAY SIGNALS — RY vs BG",
            "-" * 128,
            "MultiPV is not available from the selected engine; candidate-based engine-agreement signals are not assessed.",
        ]

    lines = [
        "FAIR-PLAY SIGNALS — RY vs BG",
        "-" * 128,
    ]

    rows: list[tuple[str, str, str]] = []
    for team in TEAMS:
        items = _team_items(analyses, team)
        rank1, _, _, _ = _rank_stats(items)
        hard1, hard_total = _hard_rank1(items)
        losses = [item.best_vs_played_cp for item in items if item.best_vs_played_cp is not None]
        gaps = [item.best_vs_second_cp for item in items if item.best_vs_second_cp is not None]
        very_high = [item for item in items if item.decision_difficulty == "VERY_DIFFERENT"]
        hard_pct = 100 * hard1 / hard_total if hard_total else 0.0
        rank_pct = 100 * rank1 / len(items) if items else 0.0
        rows.append((
            team,
            f"#1 {rank1}/{len(items)} ({rank_pct:.2f}%), hard #1 {hard1}/{hard_total} ({hard_pct:.2f}%), max streak {_longest_rank1_streak(items)}",
            f"median loss {_fmt_float(median(losses) if losses else None)} CP, mean loss {_fmt_float(sum(losses)/len(losses) if losses else None)} CP, median B-S {_fmt_float(median(gaps) if gaps else None)} CP, very-different {len(very_high)}/{len(items)}"
        ))
    lines.append(f"{'Team':<29} {'Engine agreement':<52} {'Error / separation':<55}")
    for team, agreement, errors in rows:
        lines.append(f"{team:<29} {agreement:<52} {errors:<55}")
    return lines


def _feature_summary(analyses: list[MoveAnalysis]) -> list[str]:
    assessed = [item for item in analyses if item.accuracy is not None]
    if not assessed:
        return ["No assessed moves."]

    counts = {name: 0 for name in CLASSIFICATIONS}
    for item in assessed:
        if item.classification in counts:
            counts[item.classification] += 1

    lines = [
        f"Moves assessed: {len(assessed)}",
        "Classification counts: " + ", ".join(f"{key}={counts[key]}" for key in counts),
    ]

    if not _multipv_available(assessed):
        lines.extend([
            "Engine agreement: Not assessed (selected engine does not provide usable MultiPV candidates).",
            "Best-vs-second separation: Not assessed.",
        ])
        return lines

    ranked = [item.played_move_rank for item in assessed if item.played_move_rank is not None]
    critical = [item.best_vs_second_cp for item in assessed if item.best_vs_second_cp is not None]

    lines.extend([
        f"Engine rank #1: {sum(rank == 1 for rank in ranked)}/{len(ranked) if ranked else 0}",
        f"Average best-vs-second gap: {_fmt_float(sum(critical) / len(critical) if critical else None)} CP",
    ])

    lines.append("")
    lines.append("ENGINE RANK — RY vs BG")
    lines.append("-" * 128)
    lines.append("Team   Assessed   Rank #1       Rank #1 %    Rank #2    Rank #3    Outside")
    for team in TEAMS:
        items = _team_items(analyses, team)
        rank1, rank2, rank3, outside = _rank_stats(items)
        total = len(items)
        lines.append(
            f"{team:<6} {total:>8}   {rank1:>4}/{total:<5} {100*rank1/total if total else 0:>8.2f}%   "
            f"{rank2:>4}      {rank3:>4}      {outside:>7}"
        )

    lines.extend(["", *_difficulty_table(analyses), "", *_fair_play_table(analyses)])

    lines.append("")
    lines.append("RANK-#1 STREAKS — RY vs BG")
    lines.append("-" * 128)
    for team in TEAMS:
        items = _team_items(analyses, team)
        hard1, hard_total = _hard_rank1(items)
        lines.append(f"{team:<6} Longest #1 streak: {_longest_rank1_streak(items)}   Hard-position #1: {hard1}/{hard_total} ({100*hard1/hard_total if hard_total else 0:.2f}%)")

    return lines


def _classification_counts(analyses: list[MoveAnalysis], team: str) -> dict[str, int]:
    counts = {classification: 0 for classification in CLASSIFICATIONS}
    for item in analyses:
        if TEAM[item.move.player] != team:
            continue
        classification = item.classification
        if classification in counts:
            counts[classification] += 1
    return counts


def _classification_table(analyses: list[MoveAnalysis]) -> list[str]:
    ry = _classification_counts(analyses, "RY")
    bg = _classification_counts(analyses, "BG")
    ry_total = sum(ry.values())
    bg_total = sum(bg.values())
    lines = [
        "MOVE CLASSIFICATION — RY vs BG",
        "-" * 128,
        "Category       RY Count   RY %       BG Count   BG %",
    ]
    for classification in CLASSIFICATIONS:
        ry_count = ry[classification]
        bg_count = bg[classification]
        ry_pct = 100.0 * ry_count / ry_total if ry_total else 0.0
        bg_pct = 100.0 * bg_count / bg_total if bg_total else 0.0
        lines.append(f"{classification:<14} {ry_count:>7} {ry_pct:>7.2f}%   {bg_count:>8} {bg_pct:>7.2f}%")
    lines.append(f"{'TOTAL':<14} {ry_total:>7} {'100.00%' if ry_total else 'N/A':>8}   {bg_total:>8} {'100.00%' if bg_total else 'N/A':>7}")
    return lines


def _game_flow_graph(analyses: list[MoveAnalysis], width: int = 64, height: int = 11) -> list[str]:
    """Create a compact ASCII graph of RY's estimated win probability over the game."""
    values = [
        (index, win_percent(item.after_ry_cp))
        for index, item in enumerate(analyses, start=1)
        if item.after_ry_cp is not None
    ]
    if not values:
        return ["GAME FLOW — RY vs BG", "No RY/BG win-probability data available."]

    values.insert(0, (0, 50.0))
    max_ply = values[-1][0]
    if max_ply <= 0:
        max_ply = 1

    points: list[tuple[int, int]] = []
    for ply, probability in values:
        x = round((ply / max_ply) * (width - 1))
        y = round(((100.0 - probability) / 100.0) * (height - 1))
        points.append((x, y))

    by_x: dict[int, int] = {}
    for x, y in points:
        by_x[x] = y
    points = sorted(by_x.items())

    plot_offset = 5
    plot_width = max(1, width - plot_offset)
    canvas = [[" " for _ in range(width)] for _ in range(height)]
    for row in range(height):
        probability = 100 - (row * 100 // (height - 1))
        label = f"{probability:>3} |"
        for x in range(min(len(label), width)):
            canvas[row][x] = label[x]

    plot_points = [(min(plot_width - 1, x), y) for x, y in points]

    for (x1, y1), (x2, y2) in zip(plot_points, plot_points[1:]):
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for step in range(steps + 1):
            x = round(x1 + (x2 - x1) * step / steps)
            y = round(y1 + (y2 - y1) * step / steps)
            if 0 <= x < plot_width and 0 <= y < height:
                canvas[y][plot_offset + x] = "*"

    lines = [
        "GAME FLOW — RY vs BG",
        "-" * (plot_offset + plot_width),
    ]
    lines.extend("".join(row) for row in canvas)
    lines.append("     +" + "-" * plot_width)

    opening_pad = max(1, plot_width // 2 - 9)
    middle_pad = max(1, plot_width // 2 - 7)
    lines.append(f"      Ply 1{' ' * max(1, plot_width - 14)}Ply {max_ply}")
    lines.append(f"      Opening{' ' * opening_pad}Middlegame{' ' * middle_pad}End")
    lines.append("RY = estimated RY winning probability; BG = 100% - RY.")
    return lines


def generate_report(game: Game, analyses: list[MoveAnalysis]) -> str:
    headers = game.headers
    names = _player_names(headers)
    multipv_available = _multipv_available(analyses)
    lines: list[str] = []
    lines.append("4PC VARIANT ACCURACY FINDER — V2.2")
    lines.append("=" * 128)
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
    lines.append("Evaluation: unrestricted position analysis at the configured depth; no searchmoves restriction.")
    lines.append(f"MultiPV-dependent features: {'available' if multipv_available else 'not available from the selected engine'}.")
    lines.append("Engine agreement: candidate ranking and decision separation are reported only when usable MultiPV data is available.")
    lines.append("Fair-play signals: conditional engine agreement, decision separation, error distribution, and #1 streaks when MultiPV is available.")
    lines.append("Important: these signals measure statistical unusualness; they are not a standalone cheating verdict.")
    lines.append("")

    player_keys = {color: {color} for color in PLAYERS}
    team_keys = {team: {team} for team in TEAMS}
    lines.append("SUMMARY")
    lines.append("-" * 128)
    for color in PLAYERS:
        accuracy = _game_accuracy(analyses, player_keys[color])
        lines.append(f"{color:<7} {names[color]:<24} Accuracy: {_fmt_float(accuracy)}")
    lines.append("")
    for team in TEAMS:
        accuracy = _game_accuracy(analyses, team_keys[team])
        lines.append(f"Team {team:<3} {'':<24} Accuracy: {_fmt_float(accuracy)}")

    lines.append("")
    lines.append("FEATURE SUMMARY")
    lines.append("-" * 128)
    lines.extend(_feature_summary(analyses))

    lines.append("")
    lines.extend(_classification_table(analyses))

    lines.append("")
    lines.extend(_game_flow_graph(analyses))

    lines.append("")
    lines.append("MOVE-BY-MOVE")
    lines.append("-" * 128)
    lines.append("Ply Rd Player       Played       Before   After    MoverBefore MoverAfter  Acc   Class       BestMove  Rank Gap  B-S Gap Difficulty Critical")
    for item in analyses:
        best_move = item.engine_best_move or "N/A"
        rank = str(item.played_move_rank) if item.played_move_rank is not None else "N/A"
        gap = _fmt_score(item.best_vs_played_cp, None)
        second_gap = _fmt_score(item.best_vs_second_cp, None)
        lines.append(
            f"{item.move.ply + 1:>3} {item.move.round_number:>2} {item.move.player:<11} {item.move.notation:<12} "
            f"{_fmt_score(item.before_cp, item.before_mate):>7} {_fmt_score(item.after_cp, item.after_mate):>7} "
            f"{_fmt_score(item.before_mover_cp, None):>11} {_fmt_score(item.after_mover_cp, None):>10} {_fmt_float(item.accuracy):>6} "
            f"{item.classification:<11} {best_move:<9} {rank:>4} {gap:>5} {second_gap:>7} {item.decision_difficulty:<16} {item.criticality}"
        )

    lines.append("")
    lines.append("Notes")
    lines.append("- Before/After are raw engine scores from the side-to-move perspective, capped at +/-1000 for Win% conversion.")
    lines.append("- MoverBefore/MoverAfter are converted to the moving player's team perspective.")
    lines.append("- Rank is the played move's position among returned MultiPV candidates. Outside means it was not in the returned candidates; it is not automatically a bad move.")
    lines.append("- When MultiPV is unavailable, rank, best-vs-played, best-vs-second, criticality, and decision-difficulty fields are N/A/UNASSESSED rather than inferred from a single PV.")
    lines.append("- Decision separation is based on best-vs-second CP. NEAR_EQUIVALENT <30 CP, CLOSE 30-74 CP, DIFFERENT 75-149 CP, VERY_DIFFERENT >=150 CP.")
    lines.append("- DIFFERENT and VERY_DIFFERENT are called hard-position candidates in the report only as an engine-separation filter; they do not claim human difficulty.")
    lines.append("- Hard-position #1 rate measures how often the player selected engine #1 when the engine strongly separated its first two choices.")
    lines.append("- Error statistics use best-vs-played CP from the mover's team perspective and are complementary to Accuracy.")
    lines.append("- The game-flow graph is a rough ASCII visualization of RY's estimated winning probability across the mainline; BG is the inverse.")
    lines.append("- The game-flow probability is an engine-score conversion, not a calibrated literal probability of the final result.")
    return "\n".join(lines)


def save_report(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")
