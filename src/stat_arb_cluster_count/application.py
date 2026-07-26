from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from stat_arb_preprocessing import PreprocessingConfig, get_snapshot

from .calculations import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
    calculate_cluster_count,
)
from .excel import export_cluster_count_workbook
from .models import ClusterCountResult


def calculate_cluster_count_for_date(
    preprocessing_config: PreprocessingConfig,
    as_of_date: date,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
) -> ClusterCountResult:
    estimation_config = replace(
        preprocessing_config,
        correlation_window=cluster_count_estimation_window,
    )
    snapshot = get_snapshot(estimation_config, as_of_date, cache=False)
    return calculate_cluster_count(snapshot, variance_threshold)


def export_cluster_count_report(
    preprocessing_config: PreprocessingConfig,
    as_of_date: date,
    output_path: Path,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    replace_existing: bool = False,
) -> tuple[ClusterCountResult, Path]:
    result = calculate_cluster_count_for_date(
        preprocessing_config,
        as_of_date,
        cluster_count_estimation_window=cluster_count_estimation_window,
        variance_threshold=variance_threshold,
    )
    output = export_cluster_count_workbook(
        result,
        output_path,
        replace_existing=replace_existing,
    )
    return result, output
