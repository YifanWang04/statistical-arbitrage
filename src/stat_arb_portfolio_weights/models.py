from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stat_arb_stock_selection import StockSelectionResult


@dataclass(frozen=True)
class ClusterAllocation:
    cluster_id: int
    stock_count: int
    winner_count: int
    loser_count: int
    neutral_count: int
    is_active: bool
    target_gross_exposure: float
    local_long_exposure: float
    local_short_exposure: float
    local_net_exposure: float
    local_gross_exposure: float
    portfolio_long_exposure: float
    portfolio_short_exposure: float
    portfolio_net_exposure: float
    portfolio_gross_exposure: float
    uninvested_gross_exposure: float


@dataclass(frozen=True)
class PortfolioWeightQuality:
    active_cluster_count: int
    inactive_cluster_count: int
    long_exposure: float
    short_exposure: float
    net_exposure: float
    gross_exposure: float
    uninvested_gross_exposure: float
    maximum_active_cluster_local_net_error: float
    maximum_active_cluster_local_gross_error: float
    maximum_cluster_portfolio_gross_error: float
    all_weights_finite: bool


@dataclass(frozen=True)
class PortfolioWeightResult:
    stock_selection_result: StockSelectionResult
    local_weights: tuple[float, ...]
    portfolio_weights: tuple[float, ...]
    cluster_allocations: tuple[ClusterAllocation, ...]
    calculation_version: str
    quality: PortfolioWeightQuality

    @property
    def as_of_date(self) -> date:
        return self.stock_selection_result.as_of_date

    @property
    def tickers(self) -> tuple[str, ...]:
        return self.stock_selection_result.tickers

    @property
    def stock_count(self) -> int:
        return len(self.tickers)

    @property
    def cluster_count(self) -> int:
        return (
            self.stock_selection_result.clustering_result.requested_cluster_count
        )
