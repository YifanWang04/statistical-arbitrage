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

from .application import export_stock_selection_report
from .models import StockSelectionConfig


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stat-arb-stock-selection",
        description=(
            "Identify previous winners and losers from cumulative raw-return "
            "deviations within SPONGE_sym clusters."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser(
        "export",
        help="Calculate stock classifications and export an audit workbook",
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
            "outputs/step5_stock_selection/"
            f"stock_signals_{args.as_of_date.isoformat()}.xlsx"
        )
        result, exported = export_stock_selection_report(
            preprocessing_config,
            args.as_of_date,
            output,
            cluster_count_estimation_window=args.cluster_count_estimation_window,
            variance_threshold=args.variance_threshold,
            sponge_config=sponge_config,
            selection_config=selection_config,
            replace_existing=args.replace,
        )
        print(f"Stock-selection workbook: {exported}")
        print(
            f"As-of date: {result.as_of_date}; stocks={result.stock_count}; "
            f"K={result.clustering_result.requested_cluster_count}"
        )
        print(
            f"Signals: winners={result.quality.winner_count}; "
            f"losers={result.quality.loser_count}; "
            f"neutral={result.quality.neutral_count}"
        )
        print(
            f"Paper inputs: w={result.config.lookback_window}; "
            f"p={result.config.deviation_threshold}; raw returns through "
            f"{result.window_end}"
        )
        print("No stock-selection, clustering, or cluster-count result was persisted.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
