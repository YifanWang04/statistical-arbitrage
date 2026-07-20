from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class SnapshotQuality:
    maximum_asymmetry: float
    minimum_correlation: float
    maximum_correlation: float
    minimum_eigenvalue: float
    numerical_rank: int
    has_non_finite_values: bool


@dataclass(frozen=True)
class PreprocessingRun:
    run_id: str
    beta_window: int
    correlation_window: int
    beta_alignment: str
    missing_policy: str
    calculation_version: str
    variance_epsilon: float
    return_basis: str


@dataclass(frozen=True)
class PreprocessingSnapshot:
    snapshot_id: str
    preprocessing_run_id: str
    as_of_date: date
    window_start: date
    window_end: date
    beta_window: int
    correlation_window: int
    beta_alignment: str
    missing_policy: str
    calculation_version: str
    variance_epsilon: float
    return_basis: str
    tickers: tuple[str, ...]
    market_cap_ranks: tuple[int, ...]
    beta_matrix: pd.DataFrame
    stock_return_matrix: pd.DataFrame
    market_returns: pd.Series
    residual_matrix: pd.DataFrame
    correlation_matrix: pd.DataFrame
    exclusions: pd.DataFrame
    selected_stock_count: int
    quality: SnapshotQuality

    @property
    def valid_stock_count(self) -> int:
        return len(self.tickers)

    @property
    def excluded_stock_count(self) -> int:
        return len(self.exclusions)
