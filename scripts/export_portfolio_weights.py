"""IDE entry point: assign portfolio weights and export the result workbook."""

from datetime import date
from pathlib import Path

from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
)
from stat_arb_clustering import SpongeSymConfig
from stat_arb_portfolio_weights import export_portfolio_weights_report
from stat_arb_preprocessing import (
    DEFAULT_CLUSTERING_CORRELATION_WINDOW,
    PreprocessingConfig,
)
from stat_arb_stock_selection import StockSelectionConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"
AS_OF_DATE = date(2026, 7, 17)
LOOKBACK_WINDOW = DEFAULT_CLUSTERING_CORRELATION_WINDOW
DEVIATION_THRESHOLD = 0.05
CLUSTER_COUNT_ESTIMATION_WINDOW = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
VARIANCE_THRESHOLD = DEFAULT_VARIANCE_THRESHOLD
TAU_POSITIVE = 1.0
TAU_NEGATIVE = 1.0
RANDOM_SEED = 0
KMEANS_N_INIT = 10
OUTPUT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "portfolio_weights"
    / f"portfolio_weights_{AS_OF_DATE.isoformat()}.xlsx"
)
REPLACE_EXISTING = True


def main() -> None:
    preprocessing_config = PreprocessingConfig(
        database_path=DATABASE_PATH,
        correlation_window=LOOKBACK_WINDOW,
    )
    selection_config = StockSelectionConfig(
        lookback_window=LOOKBACK_WINDOW,
        deviation_threshold=DEVIATION_THRESHOLD,
    )
    sponge_config = SpongeSymConfig(
        tau_positive=TAU_POSITIVE,
        tau_negative=TAU_NEGATIVE,
        random_seed=RANDOM_SEED,
        kmeans_n_init=KMEANS_N_INIT,
    )
    result, output = export_portfolio_weights_report(
        preprocessing_config,
        AS_OF_DATE,
        OUTPUT_PATH,
        cluster_count_estimation_window=CLUSTER_COUNT_ESTIMATION_WINDOW,
        variance_threshold=VARIANCE_THRESHOLD,
        sponge_config=sponge_config,
        selection_config=selection_config,
        replace_existing=REPLACE_EXISTING,
    )
    print(f"Portfolio-weight workbook exported: {output}")
    print(
        f"Stocks: {result.stock_count}; K: {result.cluster_count}; "
        f"active clusters: {result.quality.active_cluster_count}"
    )
    print(
        f"Gross exposure: {result.quality.gross_exposure:.12f}; "
        f"uninvested: {result.quality.uninvested_gross_exposure:.12f}"
    )


if __name__ == "__main__":
    main()
