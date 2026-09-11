import argparse
from pathlib import Path

from analyzer import analyze_game
from config import ANALYSIS_DEPTH, ENGINE_MULTIPV, ENGINE_THREADS, ENGINE_PATH, REPORT_DIRECTORY
from png import parse_pgn
from report import generate_report, save_report
from uci_engine import UCIEngine


def _collect_pgn_files(input_path: Path) -> list[Path]:
    """Return PGN/text files to analyze, in deterministic order."""
    if input_path.is_file():
        return [input_path]

    if input_path.is_dir():
        # Chess.com 4PC exports in this project commonly use .pgn4.txt.
        # Accept .pgn, .pgn4 and .txt so the folder can contain mixed exports.
        files = [
            p
            for p in input_path.iterdir()
            if p.is_file() and p.suffix.lower() in {".pgn", ".pgn4", ".txt"}
        ]
        return sorted(files, key=lambda p: p.name.lower())

    raise FileNotFoundError(f"Input path not found: {input_path}")


def _report_path(game, source_path: Path) -> Path:
    """Choose a stable report filename, preferring the game number."""
    game_number = str(game.headers.get("GameNr", "")).strip()
    stem = game_number or source_path.stem
    return REPORT_DIRECTORY / f"{stem}_report.txt"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze one Chess.com 4PC PGN file or every supported PGN/text file "
            "inside a folder and produce a report for each game."
        )
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        default="png",
        help="Path to one PGN file or a folder containing PGN/text files (default: png)",
    )
    parser.add_argument(
        "--engine",
        default=str(ENGINE_PATH),
        help=f"Path to the 4PC UCI engine executable (default: {ENGINE_PATH})",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=ENGINE_THREADS,
        help=f"Engine threads (default: {ENGINE_THREADS})",
    )
    args = parser.parse_args()

    if args.threads < 1:
        parser.error("--threads must be at least 1")

    input_path = Path(args.input_path)
    pgn_files = _collect_pgn_files(input_path)
    if not pgn_files:
        raise FileNotFoundError(f"No supported PGN/text files found in: {input_path}")

    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    print("4PC Variant Accuracy Finder — V2.2")
    print(f"Input: {input_path}")
    print(f"Games/files found: {len(pgn_files)}")
    print(f"Engine: {args.engine}")
    print(f"Depth: {ANALYSIS_DEPTH}")
    print(f"MultiPV requested: {ENGINE_MULTIPV}")
    print(f"Threads: {args.threads}")
    print("Scoring: Lichess-style before/after position evaluation")
    print("Perspective: moving player's team (RY vs BG)")
    print()

    completed = 0
    failed = 0

    # Keep one Stockfish process alive for the entire batch. This avoids
    # repeatedly starting/stopping the engine between games.
    with UCIEngine(
        engine_path=args.engine,
        threads=args.threads,
        multipv=ENGINE_MULTIPV,
    ) as engine:
        print(f"MultiPV supported: {'yes' if engine.multipv_supported else 'no'}")
        if engine.multipv_supported:
            print(f"MultiPV features: enabled (up to {ENGINE_MULTIPV} candidates)")
        else:
            print("MultiPV features: disabled; core V2 accuracy remains enabled")
        print()

        for index, pgn_path in enumerate(pgn_files, start=1):
            print("=" * 72)
            print(f"GAME {index}/{len(pgn_files)}: {pgn_path.name}")

            try:
                game = parse_pgn(pgn_path)
                if not game.moves:
                    raise ValueError("No 4PC moves were found in the PGN")

                print(f"Game: {game.headers.get('GameNr', 'Unknown')}")
                print(f"Moves: {len(game.moves)}")
                print()

                analyses = analyze_game(game, engine)
                report = generate_report(game, analyses)
                output_path = _report_path(game, pgn_path)
                save_report(report, output_path)

                completed += 1
                print()
                print(f"Report saved to: {output_path}")

            except Exception as exc:
                failed += 1
                print(f"ERROR: {exc}")
                print(f"Skipping file: {pgn_path}")

    print("=" * 72)
    print("BATCH ANALYSIS COMPLETE")
    print(f"Completed: {completed}/{len(pgn_files)}")
    print(f"Failed:    {failed}/{len(pgn_files)}")
    print(f"Reports:   {REPORT_DIRECTORY.resolve()}")


if __name__ == "__main__":
    main()
