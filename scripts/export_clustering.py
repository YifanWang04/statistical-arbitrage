"""IDE entry point: calculate SPONGE_sym clusters and export the audit workbook."""

from datetime import date
from pathlib import Path

from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
)
from stat_arb_clustering import SpongeSymConfig, export_clustering_report
from stat_arb_preprocessing import (
    DEFAULT_CLUSTERING_CORRELATION_WINDOW,
    PreprocessingConfig,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"
AS_OF_DATE = date(2026, 7, 17)
CLUSTERING_CORRELATION_WINDOW = DEFAULT_CLUSTERING_CORRELATION_WINDOW
CLUSTER_COUNT_ESTIMATION_WINDOW = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
VARIANCE_THRESHOLD = DEFAULT_VARIANCE_THRESHOLD
TAU_POSITIVE = 1.0
TAU_NEGATIVE = 1.0
RANDOM_SEED = 0
KMEANS_N_INIT = 10
OUTPUT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "clustering"
    / f"sponge_sym_clusters_{AS_OF_DATE.isoformat()}.xlsx"
)
REPLACE_EXISTING = True


def main() -> None:
    preprocessing_config = PreprocessingConfig(
        database_path=DATABASE_PATH,
        correlation_window=CLUSTERING_CORRELATION_WINDOW,
    )
    sponge_config = SpongeSymConfig(
        tau_positive=TAU_POSITIVE,
        tau_negative=TAU_NEGATIVE,
        random_seed=RANDOM_SEED,
        kmeans_n_init=KMEANS_N_INIT,
    )
    result, output = export_clustering_report(
        preprocessing_config,
        AS_OF_DATE,
        OUTPUT_PATH,
        cluster_count_estimation_window=CLUSTER_COUNT_ESTIMATION_WINDOW,
        variance_threshold=VARIANCE_THRESHOLD,
        sponge_config=sponge_config,
        replace_existing=REPLACE_EXISTING,
    )
    print(f"SPONGE_sym workbook exported: {output}")
    print(
        f"Stocks: {result.stock_count}; K: {result.requested_cluster_count}; "
        f"embedding: {result.embedding.shape}"
    )
    print(
        f"Seed: {result.config.random_seed}; "
        f"n_init: {result.config.kmeans_n_init}"
    )
    print("No clustering or cluster-count result was persisted to DuckDB.")


if __name__ == "__main__":
    main()

