"""IDE entry point: run step 7 and export the audit workbook."""

from datetime import date
from pathlib import Path

from stat_arb_backtest import BacktestConfig, export_backtest_report
from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
)
from stat_arb_clustering import SpongeSymConfig
from stat_arb_preprocessing import (
    DEFAULT_CLUSTERING_CORRELATION_WINDOW,
    PreprocessingConfig,
)
from stat_arb_stock_selection import StockSelectionConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"
START_DATE = date(2023, 1, 1)
END_DATE = date(2026, 7, 27)
## w window for correlation matrix calculation, used in clustering and stock selection
LOOKBACK_WINDOW = 10
## p deviation threshold for stock selection
DEVIATION_THRESHOLD = 0.03
## P variance threshold for clustering, used in cluster count estimation and clustering
VARIANCE_THRESHOLD = 0.9
## l rebalance period in days
REBALANCE_PERIOD = 10
## q
TAKE_PROFIT_THRESHOLD = 0.015

INITIAL_NAV = 1.0
ANNUALIZATION_SESSIONS = 252
CLUSTER_COUNT_ESTIMATION_WINDOW = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
TAU_POSITIVE = 1.0
TAU_NEGATIVE = 1.0
RANDOM_SEED = 0
KMEANS_N_INIT = 10
OUTPUT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "step7_backtest"
    / f"backtest_{START_DATE.isoformat()}_{END_DATE.isoformat()}.xlsx"
)
REPLACE_EXISTING = True
SHOW_PROGRESS = True


def main() -> None:
    preprocessing_config = PreprocessingConfig(
        database_path=DATABASE_PATH,
        correlation_window=LOOKBACK_WINDOW,
    )
    backtest_config = BacktestConfig(
        start_date=START_DATE,
        end_date=END_DATE,
        rebalance_period=REBALANCE_PERIOD,
        take_profit_threshold=TAKE_PROFIT_THRESHOLD,
        initial_nav=INITIAL_NAV,
        annualization_sessions=ANNUALIZATION_SESSIONS,
    )
    result, output = export_backtest_report(
        preprocessing_config,
        backtest_config,
        OUTPUT_PATH,
        cluster_count_estimation_window=CLUSTER_COUNT_ESTIMATION_WINDOW,
        variance_threshold=VARIANCE_THRESHOLD,
        sponge_config=SpongeSymConfig(
            tau_positive=TAU_POSITIVE,
            tau_negative=TAU_NEGATIVE,
            random_seed=RANDOM_SEED,
            kmeans_n_init=KMEANS_N_INIT,
        ),
        selection_config=StockSelectionConfig(
            lookback_window=LOOKBACK_WINDOW,
            deviation_threshold=DEVIATION_THRESHOLD,
        ),
        replace_existing=REPLACE_EXISTING,
        show_progress=SHOW_PROGRESS,
    )
    print(f"Backtest workbook exported: {output}")
    print(
        f"Sessions: {result.strategy_metrics.session_count}; "
        f"events: {len(result.rebalance_events)}; "
        f"ending NAV: {result.strategy_metrics.ending_nav:.12f}"
    )


if __name__ == "__main__":
    main()
