# Variant Accuracy Finder

V1 of a 4-player chess accuracy analyzer for Chess.com 4PC games.

## V1 scope

- Input: one Chess.com 4PC PGN file.
- Move order: Red -> Blue -> Yellow -> Green.
- Teams: Red + Yellow (RY) vs Blue + Green (BG).
- Engine: any compatible 4PC UCI engine.
- Search depth: 20.
- MultiPV: 3.
- Default engine threads: 1 for reproducibility.
- Output: a `.txt` report in `reports/`.
- Accuracy: Lichess move-accuracy formula applied to STM-relative centipawn scores.

The analyzer deliberately does not assign a fixed `engine_team`. Scores are interpreted from the engine's current side-to-move perspective, which is required for the negamax-style team search used by the 4PC engine.

## Usage

```bash
python main.py game.pgn --engine path/to/your/4pc-engine
```

Optional thread count:

```bash
python main.py game.pgn --engine path/to/your/4pc-engine --threads 1
```

The report is written to:

```text
reports/<GameNr>_report.txt
```

## Accuracy calculation

For a normal centipawn position:

```text
winPercent(cp) = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)

accuracy = 103.1668 * exp(-0.04354 * (winBefore - winAfter)) - 3.1669
```

The result is clamped to 0..100.

For a played move, the engine evaluates the resulting position with the next player to move. Therefore the resulting CP is negated before comparing it with the pre-move evaluation:

```text
mover_after_cp = -played_position_cp
cp_loss = max(0, best_cp - mover_after_cp)
```

Mate transitions are reported but excluded from CP-loss/accuracy averages in V1.

## V1 limitations

This is intentionally a correctness-first first version. It does not yet reproduce Chess.com's proprietary CAPS2 accuracy calculation, does not model game-level accuracy, and does not invent a rank when a played move falls outside MultiPV=3.

The analyzer performs a depth-20 search before and after every move. This is expensive but makes the first implementation straightforward to validate before optimization.
