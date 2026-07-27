from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
)
from stat_arb_clustering import SpongeSymConfig
from stat_arb_preprocessing import (
    DEFAULT_CLUSTERING_CORRELATION_WINDOW,
    PreprocessingConfig,
)
from stat_arb_preprocessing.config import DEFAULT_DATABASE
from stat_arb_stock_selection import StockSelectionConfig

from .application import export_portfolio_weights_report


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stat-arb-portfolio-weights",
        description=(
            "Assign equal long-only weights to previous losers within clusters "
            "and normalize "
            "each cluster to 1/K of total portfolio gross exposure."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser(
        "export",
        help="Calculate portfolio weights and export an audit workbook",
    )
    export.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export.add_argument("--as-of-date", type=_date, required=True)
    export.add_argument(
        "--lookback-window",
        type=int,
        default=DEFAULT_CLUSTERING_CORRELATION_WINDOW,
        help="Shared paper w for clustering and stock selection",
    )
    export.add_argument(
        "--deviation-threshold",
        type=float,
        default=0.05,
        help=(
            "Project p in arithmetic-return units; defaults to 0.05 "
            "(five percentage points; the paper baseline is 0)"
        ),
    )
    export.add_argument(
        "--cluster-count-estimation-window",
        type=int,
        default=DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    )
    export.add_argument(
        "--variance-threshold",
        type=float,
        default=DEFAULT_VARIANCE_THRESHOLD,
    )
    export.add_argument("--tau-positive", type=float, default=1.0)
    export.add_argument("--tau-negative", type=float, default=1.0)
    export.add_argument("--seed", type=int, default=0)
    export.add_argument("--n-init", type=int, default=10)
    export.add_argument("--output", type=Path, default=None)
    export.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        preprocessing_config = PreprocessingConfig(
            database_path=args.database.resolve(),
            correlation_window=args.lookback_window,
        )
        selection_config = StockSelectionConfig(
            lookback_window=args.lookback_window,
            deviation_threshold=args.deviation_threshold,
        )
        sponge_config = SpongeSymConfig(
            tau_positive=args.tau_positive,
            tau_negative=args.tau_negative,
            random_seed=args.seed,
            kmeans_n_init=args.n_init,
        )
        output = args.output or Path(
            "outputs/step6_portfolio_weights/"
            f"portfolio_weights_{args.as_of_date.isoformat()}.xlsx"
        )
        result, exported = export_portfolio_weights_report(
            preprocessing_config,
            args.as_of_date,
            output,
            cluster_count_estimation_window=args.cluster_count_estimation_window,
            variance_threshold=args.variance_threshold,
            sponge_config=sponge_config,
            selection_config=selection_config,
            replace_existing=args.replace,
        )
        print(f"Portfolio-weight workbook: {exported}")
        print(
            f"As-of date: {result.as_of_date}; stocks={result.stock_count}; "
            f"K={result.cluster_count}"
        )
        print(
            f"Clusters: active={result.quality.active_cluster_count}; "
            f"inactive={result.quality.inactive_cluster_count}"
        )
        print(
            f"Exposure: long={result.quality.long_exposure:.12f}; "
            f"short={result.quality.short_exposure:.12f}; "
            f"net={result.quality.net_exposure:.12f}; "
            f"gross={result.quality.gross_exposure:.12f}; "
            f"uninvested={result.quality.uninvested_gross_exposure:.12f}"
        )
        print("No portfolio-weight result was persisted to DuckDB.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
