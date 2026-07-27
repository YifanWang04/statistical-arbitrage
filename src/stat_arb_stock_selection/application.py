from __future__ import annotations

from datetime import date
from pathlib import Path

from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
    calculate_cluster_count_for_date,
)
from stat_arb_clustering import (
    SpongeSymConfig,
    cluster_stocks_from_snapshot,
)
from stat_arb_preprocessing import PreprocessingConfig, get_snapshot

from .calculations import identify_stocks_to_trade
from .excel import export_stock_selection_workbook
from .models import StockSelectionConfig, StockSelectionResult


def identify_stocks_for_date(
    preprocessing_config: PreprocessingConfig,
    as_of_date: date,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    sponge_config: SpongeSymConfig | None = None,
    selection_config: StockSelectionConfig | None = None,
) -> StockSelectionResult:
    configured_selection = selection_config or StockSelectionConfig(
        lookback_window=preprocessing_config.correlation_window,
    )
    if (
        configured_selection.lookback_window
        != preprocessing_config.correlation_window
    ):
        raise ValueError(
            "paper baseline requires selection lookback_window to equal "
            "preprocessing correlation_window"
        )

    cluster_count = calculate_cluster_count_for_date(
        preprocessing_config,
        as_of_date,
        cluster_count_estimation_window=cluster_count_estimation_window,
        variance_threshold=variance_threshold,
    )
    snapshot = get_snapshot(
        preprocessing_config,
        as_of_date,
        cache=False,
    )
    clustering = cluster_stocks_from_snapshot(
        snapshot,
        cluster_count,
        sponge_config=sponge_config,
    )
    return identify_stocks_to_trade(
        clustering,
        snapshot.stock_return_matrix,
        configured_selection,
    )


def export_stock_selection_report(
    preprocessing_config: PreprocessingConfig,
    as_of_date: date,
    output_path: Path,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    sponge_config: SpongeSymConfig | None = None,
    selection_config: StockSelectionConfig | None = None,
    replace_existing: bool = False,
) -> tuple[StockSelectionResult, Path]:
    result = identify_stocks_for_date(
        preprocessing_config,
        as_of_date,
        cluster_count_estimation_window=cluster_count_estimation_window,
        variance_threshold=variance_threshold,
        sponge_config=sponge_config,
        selection_config=selection_config,
    )
    output = export_stock_selection_workbook(
        result,
        output_path,
        replace_existing=replace_existing,
    )
    return result, output
