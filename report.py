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


def _volatility_weights(win_percents: list[float | None], move_count: int) -> list[float | None]:
    """Calculate one local volatility weight for every analyzed move.

    win_percents[0] is the initial position and win_percents[i + 1] is the
    position after move i. The window used for move i therefore contains its
    resulting position and preceding positions, with a maximum size of eight.
    """
    if move_count <= 0:
        return []

    window_size = max(2, min(8, move_count // 10))
    window_size = min(window_size, len(win_percents))
    weights: list[float | None] = []

    for move_index in range(move_count):
        after_index = move_index + 1
        end = after_index + 1
        start = max(0, end - window_size)
        window = win_percents[start:end]
        if len(window) < 2 or any(value is None for value in window):
            weights.append(None)
            continue
        values = [value for value in window if value is not None]
        weights.append(max(0.5, min(12.0, pstdev(values))))

    return weights


def _game_accuracy(analyses: list[MoveAnalysis], keys: set[str]) -> float | None:
    if not analyses:
        return None

    # Use the common RY-relative trajectory only for game-level volatility.
    # Individual move accuracy remains calculated from the mover's team POV.
    cps: list[int | None] = [15] + [item.after_ry_cp for item in analyses]
    win_percents: list[float | None] = [
        win_percent(15.0)
    ] + [
        win_percent(float(cp)) if cp is not None else None
        for cp in cps[1:]
    ]
    weights = _volatility_weights(win_percents, len(analyses))

    weighted_values: list[tuple[float, float]] = []
    raw_values: list[float] = []
    for index, item in enumerate(analyses):
        if item.accuracy is None:
            continue
        if item.move.player not in keys and TEAM[item.move.player] not in keys:
            continue
        weight = weights[index]
        if weight is None:
            continue
        weighted_values.append((item.accuracy, weight))
        raw_values.append(item.accuracy)

    if not weighted_values:
        return None

    weighted_mean = sum(value * weight for value, weight in weighted_values) / sum(
        weight for _, weight in weighted_values
    )
    harmonic_mean = (
        0.0
        if any(value <= 0.0 for value in raw_values)
        else len(raw_values) / sum(1.0 / value for value in raw_values)
    )
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
    lines.append(f"      Ply 1{' ' * opening_pad}Opening{' ' * middle_pad}Middlegame{' ' * middle_pad}End")
    lines.append(f"      0{' ' * max(1, plot_width - 8)}{max_ply}")
    lines.append("      RY probability estimated from engine evaluations; BG = 100% − RY.")
    return lines


def generate_report(game: Game, analyses: list[MoveAnalysis]) -> str:
    names = _player_names(game.headers)
    lines: list[str] = []
    lines.append("4PC VARIANT ACCURACY FINDER — V2.2")
    lines.append("=" * 128)
    lines.append(f"Game: {game.headers.get('GameNr', 'Unknown')}")
    lines.append(f"Result: {game.headers.get('Result', 'Unknown')}")
    lines.append(f"Termination: {game.headers.get('Termination', 'Unknown')}")
    lines.append("")
    for player in PLAYERS:
        lines.append(f"{player}: {names[player]} ({TEAM[player]})")

    lines.extend(["", *_game_flow_graph(analyses)])
    lines.extend(["", *_classification_table(analyses)])
    lines.extend(["", *_feature_summary(analyses)])

    lines.append("")
    lines.append("MOVE-BY-MOVE ANALYSIS")
    lines.append("-" * 128)
    header = (
        "Ply  Player  Move            Before  After   MoverBefore  MoverAfter  Accuracy  Class       "
        "BestMove        Rank  B-P CP  B-S CP  Criticality      Difficulty"
    )
    lines.append(header)
    lines.append("-" * 128)
    for index, item in enumerate(analyses, start=1):
        lines.append(
            f"{index:>3}  {item.move.player:<6} {item.move.notation:<15} "
            f"{_fmt_score(item.before_cp, item.before_mate):>7} "
            f"{_fmt_score(item.after_cp, item.after_mate):>7} "
            f"{_fmt_score(item.before_mover_cp, None):>11} "
            f"{_fmt_score(item.after_mover_cp, None):>10} "
            f"{_fmt_float(item.accuracy):>8}  {item.classification:<11} "
            f"{item.engine_best_move or '-':<14} "
            f"{str(item.played_move_rank) if item.played_move_rank is not None else '-':>4} "
            f"{_fmt_float(item.best_vs_played_cp):>7} "
            f"{_fmt_float(item.best_vs_second_cp):>7} "
            f"{item.criticality:<16} {item.decision_difficulty}"
        )

    lines.append("")
    lines.append("PLAYER SUMMARY")
    lines.append("-" * 128)
    for player in PLAYERS:
        items = [item for item in analyses if item.move.player == player and item.accuracy is not None]
        accuracy = sum(item.accuracy for item in items) / len(items) if items else None
        lines.append(f"{player:<6} {names[player]:<24} Team={TEAM[player]}  Moves={len(items):>3}  Mean move accuracy={_fmt_float(accuracy)}")

    lines.append("")
    lines.append("TEAM / GAME SUMMARY")
    lines.append("-" * 128)
    for team in TEAMS:
        items = _team_items(analyses, team)
        accuracy = _game_accuracy(analyses, {team})
        move_mean = sum(item.accuracy for item in items) / len(items) if items else None
        lines.append(f"{team:<6} Moves={len(items):>3}  Mean move accuracy={_fmt_float(move_mean)}  Game accuracy={_fmt_float(accuracy)}")

    return "\n".join(lines) + "\n"


def save_report(report: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
