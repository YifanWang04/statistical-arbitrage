from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from stat_arb_preprocessing import PreprocessingConfig
from stat_arb_preprocessing.config import DEFAULT_DATABASE

from .application import export_cluster_count_report
from .calculations import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stat-arb-cluster-count",
        description="Determine K from cumulative variance explained by correlation eigenvalues.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser(
        "export",
        help="Calculate K for one as-of date and export an auditable workbook",
    )
    export.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export.add_argument("--as-of-date", type=_date, required=True)
    export.add_argument(
        "--variance-threshold",
        type=float,
        default=DEFAULT_VARIANCE_THRESHOLD,
    )
    export.add_argument(
        "--cluster-count-estimation-window",
        "--cluster-count-window",
        dest="cluster_count_estimation_window",
        type=int,
        default=DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
        help=(
            "Prior trading sessions used only to estimate K "
            "(paper baseline: 20; --cluster-count-window is a legacy alias)"
        ),
    )
    export.add_argument("--output", type=Path, default=None)
    export.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = PreprocessingConfig(database_path=args.database.resolve())
        output = args.output or Path(
            "outputs/step3_cluster_count/"
            f"cluster_count_{args.as_of_date.isoformat()}.xlsx"
        )
        result, exported = export_cluster_count_report(
            config,
            args.as_of_date,
            output,
            cluster_count_estimation_window=args.cluster_count_estimation_window,
            variance_threshold=args.variance_threshold,
            replace_existing=args.replace,
        )
        print(f"Cluster-count workbook: {exported}")
        print(
            f"As-of date: {result.as_of_date}; stocks={result.stock_count}; "
            f"threshold={result.variance_threshold:.2%}; K={result.selected_k}"
        )
        print(
            f"Clustering correlation window: {config.correlation_window}; "
            "cluster-count estimation window: "
            f"{result.cluster_count_estimation_window}"
        )
        print("No correlation matrix, eigenvalues, or K result was cached.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

