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

from .application import (
    DEFAULT_PROJECT_DEVIATION_THRESHOLD,
    export_backtest_report,
)
from .models import BacktestConfig
from .naming import default_backtest_output_path


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stat-arb-backtest",
        description=(
            "Run the stateful long-only price-return backtest with event-driven "
            "rebalancing and export an audit workbook."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser(
        "export",
        help="Run a backtest and export the six-sheet audit workbook",
    )
    export.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export.add_argument(
        "--start-date",
        type=_date,
        required=True,
        help=(
            "Earliest permitted start date; rolls forward to the next SPY "
            "trading session"
        ),
    )
    export.add_argument("--end-date", type=_date, required=True)
    export.add_argument(
        "--rebalance-period",
        type=int,
        default=3,
        help="Number of earned daily returns before scheduled rebalance",
    )
    export.add_argument(
        "--take-profit-threshold",
        type=float,
        default=0.05,
        help="Compounded round NAV return that triggers an early rebalance",
    )
    export.add_argument("--initial-nav", type=float, default=1.0)
    export.add_argument("--annualization-sessions", type=int, default=252)
    export.add_argument(
        "--lookback-window",
        type=int,
        default=DEFAULT_CLUSTERING_CORRELATION_WINDOW,
        help="Shared paper w for clustering and stock selection",
    )
    export.add_argument(
        "--deviation-threshold",
        type=float,
        default=DEFAULT_PROJECT_DEVIATION_THRESHOLD,
        help="Project p; defaults to 0.05 while the paper baseline is 0",
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
    export.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the backtest progress bar",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        preprocessing_config = PreprocessingConfig(
            database_path=args.database.resolve(),
            correlation_window=args.lookback_window,
        )
        backtest_config = BacktestConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            rebalance_period=args.rebalance_period,
            take_profit_threshold=args.take_profit_threshold,
            initial_nav=args.initial_nav,
            annualization_sessions=args.annualization_sessions,
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
        output = args.output or default_backtest_output_path(
            args.start_date,
            args.end_date,
            lookback_window=selection_config.lookback_window,
            deviation_threshold=selection_config.deviation_threshold,
            variance_threshold=args.variance_threshold,
            rebalance_period=backtest_config.rebalance_period,
            take_profit_threshold=backtest_config.take_profit_threshold,
        )
        result, exported = export_backtest_report(
            preprocessing_config,
            backtest_config,
            output,
            cluster_count_estimation_window=(
                args.cluster_count_estimation_window
            ),
            variance_threshold=args.variance_threshold,
            sponge_config=sponge_config,
            selection_config=selection_config,
            replace_existing=args.replace,
            show_progress=not args.no_progress,
        )
        print(f"Backtest workbook: {exported}")
        effective_start = result.config.start_date
        start_description = (
            f"{args.start_date} (effective {effective_start})"
            if effective_start != args.start_date
            else str(effective_start)
        )
        print(
            f"Range: {start_description} to {result.config.end_date}; "
            f"sessions={result.strategy_metrics.session_count}; "
            f"events={len(result.rebalance_events)}"
        )
        print(
            f"Strategy ending NAV={result.strategy_metrics.ending_nav:.12f}; "
            f"total return={result.strategy_metrics.total_return:.6%}"
        )
        print("No backtest result was persisted to DuckDB.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
