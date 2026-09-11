# Variant Accuracy Finder

A transparent, engine-based accuracy analyzer for four-player team chess.

The project reconstructs a four-player game, evaluates each consecutive position with a compatible UCI engine, converts evaluations to the perspective of the team that played the move, and produces move-level, player-level, and team-level accuracy statistics.

Maintainer / developer: Dhruv

## 1. Project overview

Variant Accuracy Finder is designed specifically for four-player team chess. It is not a conventional two-player chess accuracy calculator with the board size or notation changed. The analyzer explicitly models the four-player turn cycle, team relationships, and side-to-move-relative engine scores.

The current V2 architecture focuses on one question:

> How much did the position change, from the perspective of the team that actually played the move?

The analyzer therefore evaluates the position before a move and the resulting position after that move. It does not compare an unrestricted root search against a separate `searchmoves` search for the played move.

This separation is important because the accuracy calculation should describe the effect of the move that was actually played, while avoiding artifacts caused by comparing two searches with different root constraints or contaminated transposition-table state.

## 2. Four-player game model

The fixed turn order is:

```text
Red -> Blue -> Yellow -> Green -> Red -> ...
```

The teams are:

```text
RY = Red + Yellow
BG = Blue + Green
```

Therefore the strategic opposition is:

```text
RY vs BG
```

The analyzer always tracks the actual side to move. The four-player sequence must never be reduced to an ordinary White/Black alternation.

### Side-to-move score convention

Engine centipawn scores are interpreted from the current side-to-move perspective:

```text
+100 CP = current side to move is better by 100 CP
-100 CP = current side to move is worse by 100 CP
```

This convention applies regardless of which team the current player belongs to.

After a move, the side to move changes. Consequently, the engine's score for the resulting position is initially from the next player's perspective. To compare the resulting position with the position before the move, it must be converted back to the mover's perspective.

For example:

```text
Before: +120 CP
After:   -80 CP   # from the next player's perspective

Mover-relative after score = +80 CP
CP loss = 120 - 80 = 40 CP
```

The raw values `+120` and `-80` must not be subtracted directly. Doing so would produce a false 200 CP loss.

## 3. Accuracy model

V2 uses a transparent win-percentage-based accuracy model.

First, a centipawn score is converted into an expected win percentage using a sigmoid function:

```text
winPercent(cp) =
    50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)
```

The score is capped at ±1000 CP for the numerical accuracy calculation.

For a move, the analyzer compares the win percentage of the mover-relative position before the move with the mover-relative position after the move.

If the resulting position is at least as good as the previous position for the mover's team, the move receives 100 accuracy.

Otherwise, the win-percentage loss is passed through an exponential accuracy curve:

```text
winDiff = beforeWinPercent - afterWinPercent

rawAccuracy =
    103.1668100711649 * exp(-0.04354415386753951 * winDiff)
    - 3.166924740191411
```

The final value includes a +1 uncertainty adjustment and is clamped to the range `[0, 100]`:

```text
accuracy = clamp(rawAccuracy + 1, 0, 100)
```

The constants are kept explicit in the implementation so the calculation is deterministic and testable.

## 4. Position evaluation strategy

The current analyzer evaluates the actual game line one position at a time.

For a game containing `N` played moves, the analyzer performs:

```text
N + 1 position evaluations
```

The sequence is:

```text
Initial position
      |
      v
Evaluate before position
      |
   play move
      |
      v
Evaluate resulting position
      |
      v
Use that result as the next before position
      |
   play next move
      |
     ...
```

This means the after-position evaluation for move `n` becomes the before-position evaluation for move `n + 1`.

There is no second root-constrained search for the played move in V2.

This architecture is intentionally simpler and more robust than the earlier same-root `searchmoves` comparison. It also matches the conceptual structure of a consecutive-position accuracy calculation.

## 5. Team perspective conversion

The engine score itself remains side-to-move relative. The analyzer performs the team-perspective conversion only when calculating the effect of a played move.

Let:

```text
before = engine score before the move

after  = engine score after the move
```

The before score is already from the mover's perspective because the mover is the side to move.

The after score is from the next player's perspective. Therefore:

```text
moverAfter = -after
```

The move comparison is then:

```text
moverBefore
moverAfter
```

For reporting and game-level aggregation, the implementation can retain a common team-relative score representation. Because the win-percentage transformation is symmetric around 50%, consistently negating the score for the opposite team is mathematically equivalent to changing the perspective.

The important invariant is that every move is judged from the team that played that move.

## 6. Mate handling

Mate scores are retained separately from ordinary centipawn scores.

For the current numerical accuracy model, a winning mate is treated as the positive extreme and a losing mate as the negative extreme:

```text
winning mate -> +1000 CP equivalent
losing mate   -> -1000 CP equivalent
```

The original mate information is still preserved in the move analysis so the report does not lose the distinction between a normal CP evaluation and a mate score.

This conversion is deliberately bounded. The analyzer does not attempt to assign arbitrary large centipawn values to different mate distances.

Mate handling remains an area for future validation, particularly around transitions between normal evaluations and forced-mate states.

## 7. Game-level aggregation

Move accuracy alone does not provide a stable game-level measure. V2 therefore uses a volatility-aware aggregation model.

The aggregation starts with a fixed initial RY-relative evaluation of `+15 CP`, followed by the RY-relative evaluation after each played move.

The corresponding win percentages are divided into short overlapping windows. The window size is:

```text
windowSize = max(2, min(8, totalMoves // 10))
```

The initial window is repeated before the normal sliding windows so that the beginning of the game contributes to the volatility estimate.

For each window, the weight is the standard deviation of its win percentages, clamped to:

```text
0.5 <= weight <= 12
```

The final game accuracy is the average of two components:

```text
50% volatility-weighted mean
50% harmonic mean
```

The same underlying move-accuracy calculation is used for player and team summaries.

This aggregation is an engineering choice for V2, not a claim that it is the unique or theoretically optimal measure of four-player chess performance. The raw move-level data remains available so the aggregation model can be changed independently later.

## 8. Input format

The analyzer accepts one four-player PGN game.

The parser is designed around four-player PGN notation such as:

```text
h2-h3
Bi1xc7
Qh14-d10
Ql5xQc5
f2-f3+
```

The original notation is retained for reporting while a normalized UCI move is produced for the engine.

The parser also handles incomplete final rounds. A game may terminate after only one, two, or three moves of a four-move round.

Termination markers such as `#` are treated as game notation, not as chess moves.

Players are assigned strictly by ply:

```text
ply 0 -> Red
ply 1 -> Blue
ply 2 -> Yellow
ply 3 -> Green
ply 4 -> Red
...
```

The round number is:

```text
round = (ply // 4) + 1
```

## 9. Starting position

The analyzer uses the exact four-player starting FEN configured in `config.py`.

It must not be replaced with a normal chess starting FEN.

The position reconstruction is authoritative for the analysis pipeline: the engine receives the starting FEN followed by the normalized moves that lead to the position being evaluated.

## 10. UCI engine interface

The analyzer communicates with a compatible four-player UCI engine using standard UCI commands.

The essential sequence is:

```text
uci
setoption name Threads value N
isready
position fen <4PC FEN> moves <move1> <move2> ...
go depth N
```

The implementation waits for the expected protocol responses, including `uciok`, `readyok`, and `bestmove`, and parses the engine's `info` output.

The current configuration is:

```text
Depth   = 20
Threads = 1
MultiPV = 1
```

`MultiPV = 1` is used because V2 performs a single position evaluation rather than ranking several root moves.

One engine thread is the default because deterministic debugging and reproducibility are more important than maximum throughput during development.

The executable path is machine-specific and belongs in `config.py` or the command-line `--engine` override. It is intentionally not part of the project documentation.

## 11. Repository structure

```text
Variant-Accuracy-Finder/
├── main.py          # CLI entry point and orchestration
├── png.py           # Four-player PGN parser
├── board.py         # Position and move-history state
├── engine.py        # Compatibility wrapper
├── uci_engine.py    # UCI process management and score parsing
├── analyzer.py      # Consecutive-position analysis and perspective conversion
├── report.py        # Accuracy aggregation and TXT report generation
├── config.py        # Configuration and starting FEN
├── README.md        # Project documentation
└── reports/         # Generated text reports
```

The filename `png.py` is historical. Its actual purpose is PGN parsing.

## 12. Command-line usage

Basic usage:

```bash
python main.py <path-to-pgn>
```

Specify the engine explicitly:

```bash
python main.py <path-to-pgn> --engine <path-to-uci-engine>
```

Override the thread count:

```bash
python main.py <path-to-pgn> --engine <path-to-uci-engine> --threads 1
```

The generated report is written to:

```text
reports/<GameNr>_report.txt
```

## 13. Report contents

A V2 report contains the game and engine configuration followed by move-level analysis.

Typical move-level fields include:

```text
Ply
Round
Player
Played move
Before score
After score
Mover-relative before score
Mover-relative after score
Accuracy
Search depth
```

The report also provides player and team summaries.

The raw engine scores and mover-relative scores are intentionally exposed so that numerical anomalies can be diagnosed rather than hidden behind a single accuracy number.

## 14. Correctness invariants

These invariants are more important than optimization:

1. Turn order is always `Red -> Blue -> Yellow -> Green`.
2. Teams are always `RY = Red + Yellow` and `BG = Blue + Green`.
3. Side to move is tracked for every position.
4. Engine scores are interpreted from the current side-to-move perspective.
5. The score after a move is converted back to the mover's perspective before comparison.
6. The exact configured starting FEN is preserved.
7. The position sequence sent to the engine contains exactly the moves leading to the evaluated position.
8. Every played move has a corresponding after-position evaluation unless the engine fails to provide a valid score.
9. Accuracy is never calculated from raw before/after scores with mismatched perspectives.
10. Mate information is not confused with ordinary centipawn scores.
11. No move ranking is inferred when no ranking search was performed.
12. Raw move-level results remain available independently of aggregation.

## 15. Testing strategy

Correctness should be established before performance optimization.

PGN parsing should be tested for player assignment, move normalization, captures, promotions, check/mate markers, comments, and incomplete final rounds.

Position reconstruction should be tested by verifying that every evaluated position contains exactly the expected prefix of the game move list.

Score orientation should be tested explicitly. For example:

```text
Before = +120
After  = -80

Mover-after = +80
CP loss = 40
```

The test must reject the incorrect interpretation of this pair as a 200 CP loss.

The accuracy transformation should be tested independently with fixed CP inputs and expected numerical outputs. The aggregation layer should likewise be tested independently from the UCI process.

Engine communication should verify:

```text
uci      -> uciok
isready  -> readyok
go depth -> bestmove
```

Transposition-table behavior and repeated evaluations should also be tested when changes are made to the search interface. A numerical accuracy system should not be trusted merely because its output looks plausible.

## 16. Known limitations

The current implementation has several deliberate limitations:

- The accuracy curve is adapted from a transparent two-player-style win-percentage model rather than being derived specifically from four-player game-theoretic data.
- Mate transitions require further empirical validation.
- The current search depth is fixed by configuration and can be computationally expensive.
- Consecutive positions are evaluated independently at the UCI level; additional caching or search reuse may improve throughput later.
- Game-level aggregation is an engineering model and requires calibration against large collections of human games before it should be treated as a definitive skill metric.
- The analyzer depends on the target engine correctly supporting the four-player board, move format, and side-to-move score convention.

These limitations should be treated as explicit engineering boundaries, not silently ignored.

## 17. Engineering principles

This project is an experimental accuracy-analysis system, so changes should be evaluated as hypotheses rather than assumptions.

For every proposed modification:

1. State the assumption it depends on.
2. Identify plausible counterexamples.
3. Check the logic against the four-player turn order and team model.
4. Test score orientation explicitly.
5. Separate engine behavior from analyzer behavior.
6. Measure the effect before declaring an optimization successful.
7. Preserve diagnostic data whenever possible.

In particular, an output that appears reasonable is not evidence that the underlying evaluation is correct. Search artifacts, perspective errors, transposition-table contamination, and aggregation mistakes can all produce plausible-looking numbers.

## 18. Design principle

The central principle of Variant Accuracy Finder is:

> The accuracy score should describe the effect of the move that was actually played, from the perspective of the team that played it.

Everything else in the analyzer — position reconstruction, side-to-move handling, score conversion, accuracy mathematics, and aggregation — exists to make that statement precise, reproducible, and testable.
