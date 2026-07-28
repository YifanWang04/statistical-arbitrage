from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from stat_arb_cluster_count import DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
from stat_arb_clustering import SpongeSymConfig
from stat_arb_preprocessing import PreprocessingConfig
from stat_arb_preprocessing.config import DEFAULT_DATABASE

from .application import (
    export_grid_backtest_report,
    resolve_grid_date_range,
)
from .models import (
    DEFAULT_DEVIATION_THRESHOLDS,
    DEFAULT_LOOKBACK_WINDOWS,
    DEFAULT_MAXIMUM_COMBINATIONS,
    DEFAULT_REBALANCE_PERIODS,
    DEFAULT_TAKE_PROFIT_THRESHOLDS,
    DEFAULT_VARIANCE_THRESHOLDS,
    GridBacktestConfig,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "date must use YYYY-MM-DD"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stat-arb-grid-backtest",
        description=(
            "Run the step-8 five-parameter grid over the authoritative "
            "step-7 backtest and export an Excel ranking report."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser(
        "export",
        help="Run the grid and export the five-sheet metrics workbook",
    )
    export.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export.add_argument("--start-date", type=_date, required=True)
    export.add_argument("--end-date", type=_date, required=True)
    export.add_argument(
        "--lookback-windows",
        nargs="+",
        type=int,
        default=DEFAULT_LOOKBACK_WINDOWS,
    )
    export.add_argument(
        "--deviation-thresholds",
        nargs="+",
        type=float,
        default=DEFAULT_DEVIATION_THRESHOLDS,
    )
    export.add_argument(
        "--variance-thresholds",
        nargs="+",
        type=float,
        default=DEFAULT_VARIANCE_THRESHOLDS,
    )
    export.add_argument(
        "--rebalance-periods",
        nargs="+",
        type=int,
        default=DEFAULT_REBALANCE_PERIODS,
    )
    export.add_argument(
        "--take-profit-thresholds",
        nargs="+",
        type=float,
        default=DEFAULT_TAKE_PROFIT_THRESHOLDS,
    )
    export.add_argument("--initial-nav", type=float, default=1.0)
    export.add_argument("--annualization-sessions", type=int, default=252)
    export.add_argument(
        "--maximum-combinations",
        type=int,
        default=DEFAULT_MAXIMUM_COMBINATIONS,
    )
    export.add_argument(
        "--cluster-count-estimation-window",
        type=int,
        default=DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    )
    export.add_argument("--tau-positive", type=float, default=1.0)
    export.add_argument("--tau-negative", type=float, default=1.0)
    export.add_argument("--seed", type=int, default=0)
    export.add_argument("--n-init", type=int, default=10)
    export.add_argument("--output", type=Path, default=None)
    export.add_argument("--replace", action="store_true")
    export.add_argument("--no-progress", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        preprocessing_config = PreprocessingConfig(
            database_path=args.database.resolve(),
        )
        grid_config = GridBacktestConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            lookback_windows=tuple(args.lookback_windows),
            deviation_thresholds=tuple(args.deviation_thresholds),
            variance_thresholds=tuple(args.variance_thresholds),
            rebalance_periods=tuple(args.rebalance_periods),
            take_profit_thresholds=tuple(
                args.take_profit_thresholds
            ),
            initial_nav=args.initial_nav,
            annualization_sessions=args.annualization_sessions,
            maximum_combinations=args.maximum_combinations,
        )
        requested_start, requested_end = resolve_grid_date_range(
            preprocessing_config.database_path,
            grid_config,
        )
        output = args.output or Path(
            "outputs/step8_grid_backtest/"
            f"grid_backtest_{requested_start.isoformat()}_"
            f"{requested_end.isoformat()}.xlsx"
        )
        result, exported = export_grid_backtest_report(
            preprocessing_config,
            grid_config,
            output,
            cluster_count_estimation_window=(
                args.cluster_count_estimation_window
            ),
            sponge_config=SpongeSymConfig(
                tau_positive=args.tau_positive,
                tau_negative=args.tau_negative,
                random_seed=args.seed,
                kmeans_n_init=args.n_init,
            ),
            replace_existing=args.replace,
            show_progress=not args.no_progress,
        )
        print(f"Grid backtest workbook: {exported}")
        print(
            f"Range: {result.requested_start_date} "
            f"(effective {result.effective_start_date}) to "
            f"{result.effective_end_date}; "
            f"runs={len(result.runs)}; "
            f"successful={result.successful_run_count}; "
            f"failed={result.failed_run_count}"
        )
        print(f"Best run: {result.best_run_id or 'none'}")
        print("No grid-backtest result was persisted to DuckDB.")
        return 2 if result.failed_run_count else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
