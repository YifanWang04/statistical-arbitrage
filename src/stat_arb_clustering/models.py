from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import pandas as pd

from stat_arb_cluster_count import ClusterCountResult


PAPER_TEXT_EMBEDDING = "paper_text"
SIGNET_COMPAT_EMBEDDING = "signet_compat"
SUPPORTED_EMBEDDING_MODES = (
    PAPER_TEXT_EMBEDDING,
    SIGNET_COMPAT_EMBEDDING,
)


@dataclass(frozen=True)
class SpongeSymConfig:
    tau_positive: float = 1.0
    tau_negative: float = 1.0
    random_seed: int = 0
    kmeans_n_init: int = 10
    kmeans_max_iter: int = 300
    embedding_mode: str = PAPER_TEXT_EMBEDDING

    def __post_init__(self) -> None:
        for name, value in (
            ("tau_positive", self.tau_positive),
            ("tau_negative", self.tau_negative),
        ):
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a finite positive number") from exc
            if not math.isfinite(numeric) or numeric <= 0.0:
                raise ValueError(f"{name} must be a finite positive number")
            object.__setattr__(self, name, numeric)

        for name, value, minimum in (
            ("kmeans_n_init", self.kmeans_n_init, 1),
            ("kmeans_max_iter", self.kmeans_max_iter, 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
            or not 0 <= self.random_seed <= 2**32 - 1
        ):
            raise ValueError(
                "random_seed must be an integer between 0 and 2**32 - 1"
            )
        if self.embedding_mode not in SUPPORTED_EMBEDDING_MODES:
            raise ValueError(
                "embedding_mode must be one of "
                f"{', '.join(SUPPORTED_EMBEDDING_MODES)}"
            )


@dataclass(frozen=True)
class SpongeSymQuality:
    maximum_input_asymmetry: float
    maximum_reconstruction_error: float
    minimum_input_correlation: float
    maximum_input_correlation: float
    zero_positive_degree_count: int
    zero_negative_degree_count: int
    maximum_generalized_eigen_residual: float
    kmeans_inertia: float
    kmeans_iterations: int
    nonempty_cluster_count: int
    minimum_cluster_size: int
    maximum_cluster_size: int


@dataclass(frozen=True)
class SpongeSymResult:
    as_of_date: date
    clustering_window_start: date
    clustering_window_end: date
    clustering_snapshot_id: str
    preprocessing_run_id: str
    beta_window: int
    clustering_correlation_window: int
    return_basis: str
    source_calculation_version: str
    calculation_version: str
    requested_cluster_count: int
    tickers: tuple[str, ...]
    market_cap_ranks: tuple[int, ...]
    cluster_labels: tuple[int, ...]
    cluster_sizes: tuple[int, ...]
    generalized_eigenvalues: tuple[float, ...]
    embedding_weights: tuple[float, ...]
    generalized_eigen_residuals: tuple[float, ...]
    positive_degrees: tuple[float, ...]
    negative_degrees: tuple[float, ...]
    embedding: pd.DataFrame
    config: SpongeSymConfig
    quality: SpongeSymQuality
    cluster_count_result: ClusterCountResult | None = None

    @property
    def stock_count(self) -> int:
        return len(self.tickers)

    @property
    def embedding_dimension(self) -> int:
        return len(self.generalized_eigenvalues)
