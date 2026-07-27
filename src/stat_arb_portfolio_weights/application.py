from __future__ import annotations

from datetime import date
from pathlib import Path

from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
)
from stat_arb_clustering import SpongeSymConfig
from stat_arb_preprocessing import PreprocessingConfig
from stat_arb_stock_selection import (
    StockSelectionConfig,
    identify_stocks_for_date,
)

from .calculations import assign_portfolio_weights
from .excel import export_portfolio_weight_workbook
from .models import PortfolioWeightResult


def assign_weights_for_date(
    preprocessing_config: PreprocessingConfig,
    as_of_date: date,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    sponge_config: SpongeSymConfig | None = None,
    selection_config: StockSelectionConfig | None = None,
) -> PortfolioWeightResult:
    selection_result = identify_stocks_for_date(
        preprocessing_config,
        as_of_date,
        cluster_count_estimation_window=cluster_count_estimation_window,
        variance_threshold=variance_threshold,
        sponge_config=sponge_config,
        selection_config=selection_config,
    )
    return assign_portfolio_weights(selection_result)


def export_portfolio_weights_report(
    preprocessing_config: PreprocessingConfig,
    as_of_date: date,
    output_path: Path,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    sponge_config: SpongeSymConfig | None = None,
    selection_config: StockSelectionConfig | None = None,
    replace_existing: bool = False,
) -> tuple[PortfolioWeightResult, Path]:
    result = assign_weights_for_date(
        preprocessing_config,
        as_of_date,
        cluster_count_estimation_window=cluster_count_estimation_window,
        variance_threshold=variance_threshold,
        sponge_config=sponge_config,
        selection_config=selection_config,
    )
    output = export_portfolio_weight_workbook(
        result,
        output_path,
        replace_existing=replace_existing,
    )
    return result, output
