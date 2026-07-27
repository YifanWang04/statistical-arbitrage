from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import pandas as pd

from stat_arb_clustering import SpongeSymResult


PREVIOUS_WINNER = "previous_winner"
PREVIOUS_LOSER = "previous_loser"
NEUTRAL = "neutral"


@dataclass(frozen=True)
class StockSelectionConfig:
    lookback_window: int = 5
    deviation_threshold: float = 0.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.lookback_window, bool)
            or not isinstance(self.lookback_window, int)
            or self.lookback_window < 2
        ):
            raise ValueError("lookback_window must be an integer of at least 2")
        try:
            threshold = float(self.deviation_threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "deviation_threshold must be a finite non-negative number"
            ) from exc
        if not math.isfinite(threshold) or threshold < 0.0:
            raise ValueError(
                "deviation_threshold must be a finite non-negative number"
            )
        object.__setattr__(self, "deviation_threshold", threshold)


@dataclass(frozen=True)
class StockSelectionQuality:
    winner_count: int
    loser_count: int
    neutral_count: int
    maximum_daily_cluster_sum_error: float
    maximum_cumulative_cluster_sum_error: float
    all_inputs_finite: bool


@dataclass(frozen=True)
class StockSelectionResult:
    clustering_result: SpongeSymResult
    window_start: date
    window_end: date
    raw_return_matrix: pd.DataFrame
    cluster_mean_return_matrix: pd.DataFrame
    daily_deviation_matrix: pd.DataFrame
    cumulative_deviations: tuple[float, ...]
    classifications: tuple[str, ...]
    config: StockSelectionConfig
    calculation_version: str
    quality: StockSelectionQuality

    @property
    def as_of_date(self) -> date:
        return self.clustering_result.as_of_date

    @property
    def tickers(self) -> tuple[str, ...]:
        return self.clustering_result.tickers

    @property
    def stock_count(self) -> int:
        return len(self.tickers)

    @property
    def winner_tickers(self) -> tuple[str, ...]:
        return tuple(
            ticker
            for ticker, classification in zip(
                self.tickers,
                self.classifications,
                strict=True,
            )
            if classification == PREVIOUS_WINNER
        )

    @property
    def loser_tickers(self) -> tuple[str, ...]:
        return tuple(
            ticker
            for ticker, classification in zip(
                self.tickers,
                self.classifications,
                strict=True,
            )
            if classification == PREVIOUS_LOSER
        )

    @property
    def neutral_tickers(self) -> tuple[str, ...]:
        return tuple(
            ticker
            for ticker, classification in zip(
                self.tickers,
                self.classifications,
                strict=True,
            )
            if classification == NEUTRAL
        )
