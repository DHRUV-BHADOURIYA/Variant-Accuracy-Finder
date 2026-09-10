import argparse
from pathlib import Path

from analyzer import analyze_game
from config import ANALYSIS_DEPTH, ENGINE_THREADS, ENGINE_PATH, MULTI_PV, REPORT_DIRECTORY
from pgn_parser import parse_pgn
from report import generate_report, save_report
from uci_engine import UCIEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze one Chess.com 4PC game and produce a text accuracy report."
    )
    parser.add_argument(
        "pgn",
        help="Path to one Chess.com 4PC PGN file",
    )
    parser.add_argument(
        "--engine",
        default=str(ENGINE_PATH),
        help="Path to the 4PC UCI engine executable (default: cli)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=ENGINE_THREADS,
        help=f"Engine threads (default: {ENGINE_THREADS})",
    )
    args = parser.parse_args()

    pgn_path = Path(args.pgn)
    if not pgn_path.is_file():
        raise FileNotFoundError(f"PGN file not found: {pgn_path}")

    game = parse_pgn(pgn_path)

    print("4PC Variant Accuracy Finder")
    print(f"Game: {game.headers.get('GameNr', 'Unknown')}")
    print(f"Moves: {len(game.moves)}")
    print(f"Engine: {args.engine}")
    print(f"Depth: {ANALYSIS_DEPTH}")
    print(f"MultiPV: {MULTI_PV}")
    print(f"Threads: {args.threads}")
    print()

    with UCIEngine(
        engine_path=args.engine,
        threads=args.threads,
        multipv=MULTI_PV,
    ) as engine:
        analyses = analyze_game(game, engine)

    report = generate_report(game, analyses)

    game_number = game.headers.get("GameNr", pgn_path.stem)
    output_path = REPORT_DIRECTORY / f"{game_number}_report.txt"
    save_report(report, output_path)

    print(report)
    print()
    print(f"Report saved to: {output_path}")


if __name__ == "__main__":
    main()
