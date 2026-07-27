from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
    ClusterCountResult,
    calculate_cluster_count_for_date,
)
from stat_arb_preprocessing import (
    PreprocessingConfig,
    PreprocessingSnapshot,
    get_snapshot,
)

from .calculations import cluster_sponge_sym
from .excel import export_clustering_workbook
from .models import SpongeSymConfig, SpongeSymResult


def cluster_stocks_from_snapshot(
    snapshot: PreprocessingSnapshot,
    cluster_count: ClusterCountResult,
    *,
    sponge_config: SpongeSymConfig | None = None,
) -> SpongeSymResult:
    if cluster_count.as_of_date != snapshot.as_of_date:
        raise ValueError(
            "cluster-count and clustering snapshots must have the same as-of date"
        )
    if (
        cluster_count.preprocessing_run_id != snapshot.preprocessing_run_id
        or cluster_count.beta_window != snapshot.beta_window
        or cluster_count.return_basis != snapshot.return_basis
        or cluster_count.source_calculation_version != snapshot.calculation_version
    ):
        raise ValueError(
            "cluster-count and clustering snapshots must use the same "
            "preprocessing run and return conventions"
        )
    if cluster_count.selected_k > snapshot.valid_stock_count:
        raise ValueError(
            "selected K exceeds the number of stocks in the clustering snapshot: "
            f"K={cluster_count.selected_k}, stocks={snapshot.valid_stock_count}"
        )
    result = cluster_sponge_sym(
        snapshot,
        cluster_count.selected_k,
        sponge_config,
    )
    return replace(result, cluster_count_result=cluster_count)


def cluster_stocks_for_date(
    preprocessing_config: PreprocessingConfig,
    as_of_date: date,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    sponge_config: SpongeSymConfig | None = None,
) -> SpongeSymResult:
    cluster_count = calculate_cluster_count_for_date(
        preprocessing_config,
        as_of_date,
        cluster_count_estimation_window=cluster_count_estimation_window,
        variance_threshold=variance_threshold,
    )
    clustering_snapshot = get_snapshot(
        preprocessing_config,
        as_of_date,
        cache=False,
    )
    return cluster_stocks_from_snapshot(
        clustering_snapshot,
        cluster_count,
        sponge_config=sponge_config,
    )


def export_clustering_report(
    preprocessing_config: PreprocessingConfig,
    as_of_date: date,
    output_path: Path,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    sponge_config: SpongeSymConfig | None = None,
    replace_existing: bool = False,
) -> tuple[SpongeSymResult, Path]:
    result = cluster_stocks_for_date(
        preprocessing_config,
        as_of_date,
        cluster_count_estimation_window=cluster_count_estimation_window,
        variance_threshold=variance_threshold,
        sponge_config=sponge_config,
    )
    output = export_clustering_workbook(
        result,
        output_path,
        replace_existing=replace_existing,
    )
    return result, output
