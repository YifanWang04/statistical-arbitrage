"""IDE entry point: calculate K for one date and export the result workbook."""

from datetime import date
from pathlib import Path

from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    export_cluster_count_report,
)
from stat_arb_preprocessing import (
    DEFAULT_CLUSTERING_CORRELATION_WINDOW,
    PreprocessingConfig,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "yahoo_market_data.duckdb"
AS_OF_DATE = date(2026, 7, 17)
VARIANCE_THRESHOLD = 0.90
CLUSTERING_CORRELATION_WINDOW = DEFAULT_CLUSTERING_CORRELATION_WINDOW
CLUSTER_COUNT_ESTIMATION_WINDOW = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
OUTPUT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "step3_cluster_count"
    / f"cluster_count_{AS_OF_DATE.isoformat()}.xlsx"
)
REPLACE_EXISTING = True


def main() -> None:
    config = PreprocessingConfig(
        database_path=DATABASE_PATH,
        correlation_window=CLUSTERING_CORRELATION_WINDOW,
    )
    result, output = export_cluster_count_report(
        config,
        AS_OF_DATE,
        OUTPUT_PATH,
        cluster_count_estimation_window=CLUSTER_COUNT_ESTIMATION_WINDOW,
        variance_threshold=VARIANCE_THRESHOLD,
        replace_existing=REPLACE_EXISTING,
    )
    print(f"Cluster-count workbook exported: {output}")
    print(
        f"Stocks: {result.stock_count}; threshold: {result.variance_threshold:.2%}; "
        f"K: {result.selected_k}"
    )
    print(
        f"Clustering correlation window: {config.correlation_window}; "
        "cluster-count estimation window: "
        f"{result.cluster_count_estimation_window}"
    )
    print("No correlation matrix, eigenvalues, or K result was cached.")


if __name__ == "__main__":
    main()

