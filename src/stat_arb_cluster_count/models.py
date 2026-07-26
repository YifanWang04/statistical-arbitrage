from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ClusterCountQuality:
    maximum_asymmetry: float
    trace: float
    raw_eigenvalue_sum: float
    trace_difference: float
    minimum_raw_eigenvalue: float
    adjusted_negative_eigenvalue_count: int
    numerical_rank: int


@dataclass(frozen=True)
class ClusterCountResult:
    as_of_date: date
    window_start: date
    window_end: date
    snapshot_id: str
    preprocessing_run_id: str
    beta_window: int
    cluster_count_estimation_window: int
    return_basis: str
    source_calculation_version: str
    calculation_version: str
    tickers: tuple[str, ...]
    variance_threshold: float
    raw_eigenvalues: tuple[float, ...]
    effective_eigenvalues: tuple[float, ...]
    cumulative_variance: tuple[float, ...]
    cumulative_explained_ratio: tuple[float, ...]
    total_variance: float
    selected_k: int
    quality: ClusterCountQuality

    @property
    def stock_count(self) -> int:
        return len(self.tickers)
