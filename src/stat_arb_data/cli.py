from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from .application import build_database, upgrade_database_catalog
from .config import PipelineConfig, default_end_date
from .database import DuckDBInspector
from .viewer import open_database_ui


DEFAULT_DATABASE = Path("data/yahoo_market_data.duckdb")


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stat-arb-data",
        description="Download and browse the Yahoo approximate market-data baseline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="Build a DuckDB database from yfinance")
    download.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    download.add_argument("--start", type=_date, default=date(2020, 1, 1))
    download.add_argument("--end", type=_date, default=default_end_date())
    download.add_argument("--top-n", type=int, default=500)
    download.add_argument(
        "--candidate-pool-size",
        type=int,
        default=None,
        help=(
            "Optional current-issuer market-cap prefilter. "
            "Omit it to retain every currently discoverable common-stock issuer."
        ),
    )
    download.add_argument("--price-batch-size", type=int, default=100)
    download.add_argument(
        "--replace",
        action="store_true",
        help="Explicitly replace an existing database file",
    )

    inspect = subparsers.add_parser("inspect", help="Print table counts and recent quality rows")
    inspect.add_argument("--database", type=Path, default=DEFAULT_DATABASE)

    open_ui = subparsers.add_parser("open", help="Open the database in the official DuckDB UI")
    open_ui.add_argument("--database", type=Path, default=DEFAULT_DATABASE)

    upgrade = subparsers.add_parser(
        "upgrade-catalog",
        help="Upgrade a legacy database catalog without downloading data again",
    )
    upgrade.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    return parser


def run_download(args: argparse.Namespace) -> int:
    database = args.database.resolve()
    config = PipelineConfig(
        database_path=database,
        start_date=args.start,
        end_date=args.end,
        top_n=args.top_n,
        candidate_pool_size=args.candidate_pool_size,
        price_batch_size=args.price_batch_size,
    )
    run_id = build_database(config, replace_existing=args.replace)
    print(f"Completed run {run_id}")
    print(f"Database: {database}")
    return 0


def run_inspect(args: argparse.Namespace) -> int:
    database = args.database.resolve()
    if not database.exists():
        raise FileNotFoundError(f"Database does not exist: {database}")
    with DuckDBInspector(database) as inspector:
        for name, count in inspector.table_counts():
            print(f"{name:<32} {count:>12,}")
        print("\nRecent issues:")
        issues = inspector.recent_download_issues(limit=20)
        print("None" if issues.empty else issues.to_string(index=False))
    return 0


def run_open(args: argparse.Namespace) -> int:
    open_database_ui(args.database)
    return 0


def run_upgrade_catalog(args: argparse.Namespace) -> int:
    database = args.database.resolve()
    upgraded = upgrade_database_catalog(database)
    if upgraded:
        print(f"Catalog upgraded: {database}")
    else:
        print(f"Catalog is already current: {database}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = build_parser().parse_args(argv)
    try:
        if args.command == "download":
            return run_download(args)
        if args.command == "inspect":
            return run_inspect(args)
        if args.command == "open":
            return run_open(args)
        if args.command == "upgrade-catalog":
            return run_upgrade_catalog(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1
