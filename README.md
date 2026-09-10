# Variant Accuracy Finder

V1 specification and project context for a four-player team-chess accuracy analyzer.

Maintainer / developer: Dhruv

## 1. What this project is

Variant Accuracy Finder is a Python-based analyzer intended to calculate move accuracy for four-player chess games, initially targeting Chess.com 4PC games in the Teams format.

The goal is not to reproduce a website's proprietary accuracy implementation. The first version establishes a transparent, reproducible, engine-based accuracy system that can later be validated and improved.

The analyzer takes one 4PC PGN game, reconstructs the game move-by-move, asks a compatible 4PC UCI engine to evaluate the position before and after every move, compares the played move with the best available move, calculates move accuracy using the agreed Lichess formula, and writes a text report.

This README is intentionally detailed so that another AI agent can enter the project and immediately understand the rules, assumptions, architecture, current implementation, and intended direction.

## 2. Game model

This is four-player team chess, not ordinary two-player chess.

The fixed move order is:

```text
Red -> Blue -> Yellow -> Green -> Red -> ...
```

The teams are:

```text
Blue + Green = BG
Red + Yellow = RY
```

Therefore the strategic opposition is:

```text
BG vs RY
```

The engine always tracks the actual side to move. Do not replace the four-player turn sequence with a conventional white/black model.

### Critical score convention

The engine's centipawn score is interpreted from the perspective of the current side to move, exactly as agreed for the engine integration.

Therefore:

```text
+100 CP = the current side to move is better by 100 CP
-100 CP = the current side to move is worse by 100 CP
```

This remains true regardless of whether the current side belongs to RY or BG.

After a move is played, the side to move changes. Therefore an evaluation of the resulting position is initially from the next player's perspective and must be negated to obtain the mover's perspective.

For a normal CP evaluation:

```text
mover_score_before = before_score
mover_score_after  = -after_score
```

Then:

```text
cp_loss = max(0, mover_score_before - mover_score_after)
```

Do not compare the raw before and after scores without accounting for the side-to-move change.

## 3. Search/evaluation philosophy

The project uses a team-search interpretation of negamax principles adapted to four-player team chess.

The analyzer itself does not force a fixed team perspective onto the engine. It relies on the engine's side-to-move-relative score semantics.

Do not introduce a permanent `engine_team` setting into the analyzer unless the project requirements explicitly change. The intended V1 behavior is symmetric STM-relative evaluation.

The analyzer should treat the engine as authoritative for the position evaluation and legal move interpretation. It should not attempt to implement a second chess rules engine in V1.

## 4. Input

V1 accepts exactly one PGN game as input.

The expected source is a Chess.com 4PC PGN in the Teams format. Typical headers include fields such as:

```text
[GameNr "..."]
[Variant "Teams"]
[RuleVariants "..."]
[StartFen4 "4PC"]
[Red "..."]
[Blue "..."]
[Yellow "..."]
[Green "..."]
[Result "..."]
```

The move list uses Chess.com 4PC notation such as:

```text
h2-h3
Bi1xc7
Qh14-d10
Ql5xQc5
f2-f3+
```

The parser must preserve the original notation for reporting while also producing the coordinate move expected by the UCI engine.

The parser must support incomplete final rounds. A game can end after only one, two, or three moves of a four-move round.

For example, this is valid:

```text
7. Qg1xb6+ .. #
```

The lone `#` is a termination marker, not a chess move.

## 5. Exact starting position

V1 uses the known 4PC starting FEN supplied by the project/engine integration.

It is stored in `config.py` as `START_FEN`. Do not silently replace it with a normal chess FEN.

The analyzer reconstructs the game by sending the starting FEN followed by the normalized moves to the UCI engine.

## 6. UCI requirements

The target engine is a compatible four-player UCI engine. The analyzer must not depend on a particular engine brand or external engine link.

The required UCI workflow is standard:

```text
uci
setoption name Threads value N
setoption name MultiPV value 3
isready
position fen <4PC FEN> moves <move1> <move2> ...
go depth 20
```

The implementation waits for `uciok`, `readyok`, and `bestmove` and parses standard `info` lines.

V1 defaults to:

```text
Depth   = 20
MultiPV = 3
Threads = 1
```

Threads are deliberately set to 1 initially because reproducibility and debugging are more important than maximum throughput in V1.

The local executable path belongs in `config.py` or can be overridden with `--engine`. Do not document or hard-code a public engine name in this project documentation.

## 7. Why MultiPV = 3

MultiPV is not required for the mathematical accuracy calculation.

The primary accuracy comparison is:

```text
best position evaluation before the move
vs.
played resulting-position evaluation after the move
```

MultiPV=3 is nevertheless useful because it allows V1 to identify whether the played move was among the engine's top three principal variations and, if so, report its rank.

If the played move is not present in the top three, V1 reports the rank as unavailable. It must not invent a rank.

Later versions may use larger MultiPV or a targeted search for the played move, but that is outside V1.

## 8. Accuracy formula

The project explicitly chose the Lichess accuracy formula for V1, even though it was designed around conventional two-player chess.

This choice is intentional. Do not replace it merely because four-player chess has different game-theoretic properties. If unusual behavior appears, record it and investigate it empirically before changing the formula.

For a normal centipawn score:

```text
winPercent(cp) = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)
```

Then:

```text
accuracy = 103.1668 * exp(-0.04354 * (winPercentBefore - winPercentAfter)) - 3.1669
```

Finally clamp the result to:

```text
0 <= accuracy <= 100
```

For a move, `winPercentBefore` is computed from the best evaluation before the move, while `winPercentAfter` is computed from the played move's resulting evaluation after converting that evaluation back to the mover's perspective.

The formula is therefore applied to the mover-relative pair:

```text
best_cp
mover_after_cp
```

## 9. Mate handling

Mate scores are fundamentally different from ordinary centipawn scores.

V1 preserves mate information as a separate score type instead of blindly converting mate values into arbitrary CP numbers.

If a before/after comparison crosses a mate state and a principled CP-equivalent comparison cannot be made, V1 reports the mate information but excludes that move from normal CP-loss/accuracy aggregation.

This is deliberately conservative. Do not invent a mate-to-CP conversion without validating its effect on the accuracy metric.

Mate handling is a future improvement area.

## 10. What V1 calculates

For every played move, V1 records:

```text
Ply
Round
Player
Original move notation
Normalized UCI move
Best engine move
Best CP / mate score
Played resulting-position CP / mate score
CP loss
Accuracy
MultiPV rank
Search depth
```

The four players are assigned strictly by ply:

```text
ply 0 -> Red
ply 1 -> Blue
ply 2 -> Yellow
ply 3 -> Green
ply 4 -> Red
...
```

The round is:

```text
round = (ply // 4) + 1
```

Thus one complete round consists of four moves.

## 11. Aggregation

V1 reports per-player accuracy using the arithmetic mean of the valid per-move accuracies for that player.

Team accuracy is the arithmetic mean of the valid player/move accuracies belonging to that team.

Therefore:

```text
RY = Red + Yellow
BG = Blue + Green
```

Mate-excluded moves do not contribute to the normal CP-based averages.

This is a V1 aggregation decision, not a claim that this is the mathematically optimal four-player game accuracy aggregation.

The raw move-level results must remain available so that aggregation can be changed later without redesigning the engine-analysis layer.

## 12. What V1 does NOT attempt to reproduce

Do not claim that this project reproduces Chess.com's proprietary accuracy number.

Chess.com uses its own accuracy methodology, including its Expected Points / CAPS-based approach. The exact proprietary calculation is not the target of this V1.

V1 instead uses the explicitly chosen Lichess formula because it is transparent and reproducible.

There is also no universally accepted accuracy formula for chess variants or four-player chess. The project should therefore distinguish clearly between:

```text
engine evaluation
move CP loss
Lichess-formula move accuracy
player/team aggregation
```

These are separate concepts.

## 13. Current architecture

The repository currently uses this structure:

```text
Variant-Accuracy-Finder/
├── main.py          # CLI entry point and orchestration
├── png.py           # Chess.com 4PC PGN parser
├── board.py         # Position/move-history state
├── engine.py        # Public compatibility wrapper for UCI engine
├── uci_engine.py    # Actual UCI process and info-line implementation
├── analyzer.py      # Before/after analysis and move comparison
├── report.py        # Accuracy calculations and TXT report generation
├── config.py        # V1 constants and starting FEN
├── README.md        # This project specification
└── reports/         # Generated TXT reports
```

The file name `png.py` is retained because it already existed in the project; its purpose is PGN parsing.

## 14. Current analysis algorithm

For every move in the PGN:

```text
1. Start from the current position.
2. Search the position at depth 20.
3. Record MultiPV lines and the best line.
4. Record the best move and best STM-relative score.
5. Append the played move to a copied position state.
6. Search the resulting position at depth 20.
7. Record the resulting STM-relative score.
8. Negate the resulting score to obtain mover-relative score.
9. Calculate CP loss.
10. Calculate Lichess accuracy.
11. Determine MultiPV rank if the played move is in the top 3.
12. Store the move result.
13. Advance the real game state.
```

This means V1 intentionally performs two depth-20 searches per played move.

That is expensive. It is nevertheless preferred initially because the implementation is easier to reason about and validate.

Do not optimize this before correctness is established.

## 15. Important implementation constraints

Another agent modifying this project should preserve the following unless there is a demonstrated reason to change them:

1. Four-player turn order is Red -> Blue -> Yellow -> Green.
2. Teams are BG vs RY.
3. Side to move is always tracked.
4. Scores are always interpreted from the current side-to-move perspective.
5. Post-move scores must be negated when converted back to the mover's perspective.
6. The starting FEN must remain exact.
7. Standard UCI commands should be used.
8. V1 search depth is 20.
9. V1 MultiPV is 3.
10. V1 defaults to one engine thread for reproducibility.
11. V1 uses the Lichess accuracy formula.
12. Mate must not be converted to arbitrary CP values.
13. Do not invent a MultiPV rank when the played move is outside the requested MultiPV set.
14. Preserve raw move-level data.
15. Output V1 is TXT.
16. PGNs may have incomplete final rounds.
17. Do not introduce a fixed engine-team perspective into the analyzer.
18. Do not silently replace the four-player team model with ordinary two-player negamax assumptions.

## 16. Current local usage

The intended command-line form is:

```bash
python main.py <path-to-pgn>
```

or:

```bash
python main.py <path-to-pgn> --engine <path-to-uci-engine>
```

Optional thread override:

```bash
python main.py <path-to-pgn> --engine <path-to-uci-engine> --threads 1
```

The configured executable path is machine-specific and should not be copied into documentation or treated as a project-wide requirement.

The report is written under:

```text
reports/<GameNr>_report.txt
```

## 17. Testing strategy

The first priority is correctness, not speed.

When testing a new version, verify these independently.

### PGN parsing

Confirm that Red, Blue, Yellow, and Green are assigned to consecutive plies in exactly that order.

Confirm that Chess.com notation is normalized correctly, including:

```text
h2-h3      -> h2h3
Bi1xc7     -> i1c7
Qh14-d10   -> h14d10
Ql5xQc5    -> l5c5
```

Check promotions, captures, check markers, mate markers, comments, and incomplete final rounds.

### Position sequence

For every ply, verify that the engine receives:

```text
starting FEN + all moves before the position being evaluated
```

and that the played move itself is included for the after-position search.

### Score orientation

This is the most important numerical test.

If before-search returns:

```text
+120
```

and after-search returns:

```text
-80
```

then the mover-relative after score is:

```text
+80
```

and the CP loss is:

```text
120 - 80 = 40
```

It is NOT 200 CP.

If before is `-50` and after is `-70`, then mover-after is `+70`, so the raw difference is negative and CP loss is clamped to zero.

### Accuracy

Test the Lichess formula independently with known CP pairs before trusting full-game output.

### Engine communication

Confirm:

```text
uci -> uciok
isready -> readyok
go depth 20 -> bestmove
```

and inspect actual `info` lines emitted by the local engine.

## 18. Known V1 limitations

V1 is deliberately incomplete in several areas:

- It does not reproduce proprietary Chess.com CAPS2 accuracy.
- It does not claim that Lichess accuracy is theoretically optimal for 4PC.
- Mate transitions are not fully integrated into the numerical accuracy model.
- MultiPV is only 3.
- The played move's rank is unknown when it is outside the returned MultiPV set.
- The analyzer performs two full depth-20 searches per move.
- There is no caching/position reuse optimization yet.
- There is no sophisticated game-level accuracy model yet.
- Player/team aggregation is a simple arithmetic mean.
- The implementation depends on the target engine correctly supporting the required 4PC UCI position and move format.

These are known limitations, not bugs by themselves.

## 19. Planned direction after V1

The correct development order is:

```text
V1 correctness
    -> validate PGN reconstruction
    -> validate UCI position sequence
    -> validate STM score orientation
    -> validate accuracy math
    -> validate reports
    -> benchmark
    -> optimize
    -> improve mate handling
    -> improve move ranking
    -> investigate stronger accuracy models
```

Potential future improvements include:

- More efficient search reuse.
- Transposition-aware analysis across consecutive positions.
- Better handling of mate scores.
- Larger or adaptive MultiPV.
- Searching the played move directly when it is outside MultiPV.
- Better game-level and team-level aggregation.
- Variant-specific expected-points or win-probability models.
- Calibration against large collections of human games.
- Performance profiling and parallel analysis after correctness is proven.
- Additional output formats after the TXT format is stable.

Do not implement these simply because they sound stronger. Each should be justified with tests or measurable benefit.

## 20. Engineering philosophy for future AI agents

This project is being developed as an experimental engine-analysis system, so an AI agent working on it must challenge assumptions instead of automatically agreeing with them.

For every proposed change:

1. Identify what assumption the change relies on.
2. Consider what could make that assumption false.
3. Test the logic against the four-player turn order and team model.
4. Check whether score orientation changes anywhere in the pipeline.
5. Distinguish a real correctness issue from a performance issue or a metric-design choice.
6. Prefer evidence from tests, engine output, and reproducible examples over intuition.
7. Do not silently change agreed semantics.
8. If the current design is wrong, say so explicitly and explain the failure mode.

The project should evolve from a known-correct baseline rather than from a collection of unvalidated optimizations.

## 21. Current status

V1 source files have been created and implemented in the `main` branch.

The first local execution should be treated as an integration test. The expected initial debugging targets are:

```text
PGN parsing
-> engine process startup
-> UCI handshake
-> 4PC position command
-> 4PC move sequence
-> depth-20 info parsing
-> score orientation
-> accuracy calculation
-> TXT report
```

Do not assume the analyzer is numerically trustworthy merely because it starts successfully. The first complete game should be manually checked at several plies before using its accuracy numbers for comparisons.

## 22. Project objective

The long-term objective is a reliable, transparent, variant-aware accuracy analyzer for four-player team chess.

V1 is the baseline. The immediate goal is not to produce a sophisticated metric; it is to establish a correct data and evaluation pipeline on which stronger metrics can be built without losing the ability to audit individual moves.
