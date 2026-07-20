from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from .application import build_preprocessing, get_snapshot
from .config import DEFAULT_DATABASE, PreprocessingConfig
from .excel import export_snapshot_workbook


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stat-arb-preprocessing",
        description="Build and export market-residual preprocessing snapshots.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build rolling beta and residual returns")
    build.add_argument("--database", type=Path, default=DEFAULT_DATABASE)

    export = subparsers.add_parser("export", help="Export a point-in-time Excel snapshot")
    export.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export.add_argument("--as-of-date", type=_date, required=True)
    export.add_argument("--output", type=Path, default=None)
    export.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = PreprocessingConfig(database_path=args.database.resolve())
        if args.command == "build":
            run_id = build_preprocessing(config)
            print(f"Completed preprocessing run {run_id}")
            print(f"Database: {config.database_path}")
            return 0
        if args.command == "export":
            output = args.output or Path(
                f"outputs/preprocessing/preprocessing_snapshot_{args.as_of_date.isoformat()}.xlsx"
            )
            snapshot = get_snapshot(config, args.as_of_date, cache=True)
            exported = export_snapshot_workbook(
                snapshot,
                output,
                replace_existing=args.replace,
            )
            print(f"Excel snapshot: {exported}")
            print(
                f"Stocks: selected={snapshot.selected_stock_count}, "
                f"valid={snapshot.valid_stock_count}, excluded={snapshot.excluded_stock_count}"
            )
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1
