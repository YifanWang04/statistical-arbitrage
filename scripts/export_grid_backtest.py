"""IDE entry point: run step 8 and export the grid-ranking workbook."""

from datetime import date
from pathlib import Path

from stat_arb_cluster_count import DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
from stat_arb_clustering import SpongeSymConfig
from stat_arb_grid_backtest import (
    GridBacktestConfig,
    export_grid_backtest_report,
    resolve_grid_date_range,
)
from stat_arb_preprocessing import PreprocessingConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"

# The start and end dates are included SPY return dates.
START_DATE = date(2025, 1, 1)
END_DATE = date(2026, 7, 27)

LOOKBACK_WINDOWS = (5, 10, 20)
DEVIATION_THRESHOLDS = (0.1, 0.05) ## deviation > p  → winner; deviation < -p → loser
VARIANCE_THRESHOLDS = (0.90,) ## 元组，即使一个元素，也需要保留逗号
REBALANCE_PERIODS = (3, 5, 10)
TAKE_PROFIT_THRESHOLDS = (0.03, 0.05)

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
    requested_start, requested_end = resolve_grid_date_range(
        DATABASE_PATH,
        grid_config,
    )
    output_path = (
        PROJECT_ROOT
        / "outputs"
        / "step8_grid_backtest"
        / (
            f"grid_backtest_{requested_start.isoformat()}_"
            f"{requested_end.isoformat()}.xlsx"
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
    )
    print(f"Grid backtest workbook exported: {output}")
    print(
        f"Runs: {len(result.runs)}; "
        f"successful: {result.successful_run_count}; "
        f"failed: {result.failed_run_count}; "
        f"best: {result.best_run_id or 'none'}"
    )


if __name__ == "__main__":
    main()
