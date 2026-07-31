"""IDE entry point: run the coarse 432-combination step-8 grid."""

from datetime import date
from pathlib import Path

from stat_arb_cluster_count import DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
from stat_arb_clustering import SpongeSymConfig
from stat_arb_grid_backtest import (
    DEFAULT_MAX_WORKERS,
    GridBacktestConfig,
    export_grid_backtest_report,
    resolve_grid_date_range,
)
from stat_arb_preprocessing import PreprocessingConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"

# Keep the same sample as the 144-run grid so results remain comparable.
START_DATE = date(2023, 1, 1)
END_DATE = date(2026, 7, 27)

# Use a coarse extension of the original grid. The main additions are the
# paper p=0 baseline and two controls around the original P=90% setting.
# 4 * 3 * 3 * 3 * 4 = 432 combinations.
LOOKBACK_WINDOWS = (5, 10, 20, 30)
DEVIATION_THRESHOLDS = (0.0, 0.03, 0.05)
VARIANCE_THRESHOLDS = (0.85, 0.90, 0.95)
REBALANCE_PERIODS = (3, 5, 10)
TAKE_PROFIT_THRESHOLDS = (0.015, 0.03, 0.05, 0.10)

EXPECTED_COMBINATION_COUNT = 432
INITIAL_NAV = 1.0
ANNUALIZATION_SESSIONS = 252
MAXIMUM_COMBINATIONS = 1_000
CLUSTER_COUNT_ESTIMATION_WINDOW = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
TAU_POSITIVE = 1.0
TAU_NEGATIVE = 1.0
RANDOM_SEED = 0
KMEANS_N_INIT = 10
REPLACE_EXISTING = True
SHOW_PROGRESS = True
MAX_WORKERS = DEFAULT_MAX_WORKERS


def main() -> None:
    preprocessing_config = PreprocessingConfig(
        database_path=DATABASE_PATH,
    )
    grid_config = GridBacktestConfig(
        start_date=START_DATE,
        end_date=END_DATE,
        lookback_windows=LOOKBACK_WINDOWS,
        deviation_thresholds=DEVIATION_THRESHOLDS,
        variance_thresholds=VARIANCE_THRESHOLDS,
        rebalance_periods=REBALANCE_PERIODS,
        take_profit_thresholds=TAKE_PROFIT_THRESHOLDS,
        initial_nav=INITIAL_NAV,
        annualization_sessions=ANNUALIZATION_SESSIONS,
        maximum_combinations=MAXIMUM_COMBINATIONS,
    )
    if grid_config.combination_count != EXPECTED_COMBINATION_COUNT:
        raise RuntimeError(
            "comprehensive grid combination count changed: "
            f"expected {EXPECTED_COMBINATION_COUNT}, "
            f"observed {grid_config.combination_count}"
        )

    requested_start, requested_end = resolve_grid_date_range(
        DATABASE_PATH,
        grid_config,
    )
    output_path = (
        PROJECT_ROOT
        / "outputs"
        / "step8_grid_backtest"
        / (
            "grid_backtest_comprehensive_432_"
            f"{requested_start.isoformat()}_{requested_end.isoformat()}.xlsx"
        )
    )
    result, output = export_grid_backtest_report(
        preprocessing_config,
        grid_config,
        output_path,
        cluster_count_estimation_window=CLUSTER_COUNT_ESTIMATION_WINDOW,
        sponge_config=SpongeSymConfig(
            tau_positive=TAU_POSITIVE,
            tau_negative=TAU_NEGATIVE,
            random_seed=RANDOM_SEED,
            kmeans_n_init=KMEANS_N_INIT,
        ),
        replace_existing=REPLACE_EXISTING,
        show_progress=SHOW_PROGRESS,
        max_workers=MAX_WORKERS,
    )
    print(f"Comprehensive grid workbook exported: {output}")
    print(
        f"Runs: {len(result.runs)}; "
        f"successful: {result.successful_run_count}; "
        f"failed: {result.failed_run_count}; "
        f"best: {result.best_run_id or 'none'}"
    )


if __name__ == "__main__":
    main()
