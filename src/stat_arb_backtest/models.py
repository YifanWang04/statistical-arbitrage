from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import pandas as pd


MISSING_PRICE_POLICY_FREEZE = "freeze_and_audit"


@dataclass(frozen=True)
class BacktestConfig:
    start_date: date
    end_date: date
    rebalance_period: int = 3
    take_profit_threshold: float = 0.05
    initial_nav: float = 1.0
    annualization_sessions: int = 252
    missing_price_policy: str = MISSING_PRICE_POLICY_FREEZE

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        for name, value in (
            ("rebalance_period", self.rebalance_period),
            ("annualization_sessions", self.annualization_sessions),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name, value, minimum, inclusive in (
            (
                "take_profit_threshold",
                self.take_profit_threshold,
                0.0,
                False,
            ),
            ("initial_nav", self.initial_nav, 0.0, False),
        ):
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a finite positive number") from exc
            if (
                not math.isfinite(numeric)
                or numeric < minimum
                or (not inclusive and numeric == minimum)
            ):
                raise ValueError(f"{name} must be a finite positive number")
            object.__setattr__(self, name, numeric)
        if self.missing_price_policy != MISSING_PRICE_POLICY_FREEZE:
            raise ValueError(
                "missing_price_policy must be 'freeze_and_audit'"
            )


@dataclass(frozen=True)
class BacktestMarketData:
    previous_session: date
    sessions: tuple[date, ...]
    closes: pd.DataFrame

    def __post_init__(self) -> None:
        if not self.sessions:
            raise ValueError("backtest sessions must not be empty")
        if tuple(sorted(self.sessions)) != self.sessions:
            raise ValueError("backtest sessions must be strictly ordered")
        if len(set(self.sessions)) != len(self.sessions):
            raise ValueError("backtest sessions must be unique")
        if self.previous_session >= self.sessions[0]:
            raise ValueError("previous_session must precede the first session")
        expected = (self.previous_session, *self.sessions)
        observed = tuple(self.closes.index)
        if observed != expected:
            raise ValueError(
                "close-price index must contain previous_session followed by sessions"
            )
        if "SPY" not in self.closes.columns:
            raise ValueError("close prices must contain SPY")


@dataclass(frozen=True)
class TargetWeight:
    ticker: str
    portfolio_weight: float
    market_cap_rank: int | None = None
    cluster_id: int | None = None
    cumulative_deviation: float | None = None
    classification: str | None = None
    local_weight: float | None = None

    def __post_init__(self) -> None:
        ticker = str(self.ticker).strip().upper()
        if not ticker:
            raise ValueError("target ticker must not be blank")
        try:
            weight = float(self.portfolio_weight)
        except (TypeError, ValueError) as exc:
            raise ValueError("portfolio_weight must be finite and non-negative") from exc
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError("portfolio_weight must be finite and non-negative")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "portfolio_weight", weight)


@dataclass(frozen=True)
class BacktestTarget:
    as_of_date: date
    cluster_count: int
    active_cluster_count: int
    weights: tuple[TargetWeight, ...]
    inactive_cluster_count: int | None = None
    calculation_version: str = "backtest_target_v1"

    def __post_init__(self) -> None:
        if (
            isinstance(self.cluster_count, bool)
            or not isinstance(self.cluster_count, int)
            or self.cluster_count < 1
        ):
            raise ValueError("cluster_count must be a positive integer")
        if not 0 <= self.active_cluster_count <= self.cluster_count:
            raise ValueError("active_cluster_count must be between zero and K")
        if len({weight.ticker for weight in self.weights}) != len(self.weights):
            raise ValueError("target tickers must be unique")
        total = sum(weight.portfolio_weight for weight in self.weights)
        if total > 1.0 + 1e-12:
            raise ValueError("target portfolio weights must not exceed one")
        inactive = self.inactive_cluster_count
        expected_inactive = self.cluster_count - self.active_cluster_count
        if inactive is None:
            object.__setattr__(self, "inactive_cluster_count", expected_inactive)
        elif inactive != expected_inactive:
            raise ValueError("active and inactive clusters must reconcile to K")

    @property
    def target_gross_exposure(self) -> float:
        return sum(weight.portfolio_weight for weight in self.weights)


@dataclass(frozen=True)
class DailyPerformance:
    trade_date: date
    strategy_return: float
    nav: float
    round_id: int
    round_return: float
    holding_day: int
    cash_value: float
    cash_weight: float
    gross_exposure: float
    frozen_value: float
    frozen_exposure: float
    position_count: int
    missing_position_count: int
    spy_return: float
    spy_nav: float
    trigger_reason: str | None


@dataclass(frozen=True)
class RebalanceEvent:
    event_id: int
    event_date: date
    effective_date: date
    reason: str
    round_id: int
    held_sessions: int
    round_return: float
    nav: float
    cluster_count: int
    active_cluster_count: int
    inactive_cluster_count: int
    target_gross_exposure: float
    frozen_value: float
    available_capital: float


@dataclass(frozen=True)
class TargetWeightRecord:
    event_id: int
    effective_date: date
    ticker: str
    market_cap_rank: int | None
    cluster_id: int | None
    cumulative_deviation: float | None
    classification: str | None
    local_weight: float | None
    portfolio_weight: float


@dataclass(frozen=True)
class TradeRecord:
    event_id: int | None
    trade_date: date
    ticker: str
    side: str
    value_before: float
    value_after: float
    trade_notional: float
    status: str
    reason: str
    trade_id: int = 0
    execution_price: float | None = None
    units_before: float = 0.0
    units_traded: float = 0.0
    units_after: float = 0.0
    executed_notional: float = 0.0

    @property
    def requested_notional(self) -> float:
        return self.trade_notional


@dataclass(frozen=True)
class PositionLotRecord:
    lot_id: str
    ticker: str
    buy_trade_id: int
    buy_event_id: int | None
    buy_date: date
    buy_price: float
    bought_units: float
    buy_notional: float
    sold_units: float
    remaining_units: float
    first_sell_date: date | None
    final_sell_date: date | None
    matched_sell_vwap: float | None
    final_sell_price: float | None
    sale_proceeds: float
    realized_pnl: float
    realized_return: float | None
    lot_return: float | None
    status: str


@dataclass(frozen=True)
class MissingDataAudit:
    trade_date: date
    ticker: str
    event: str
    action: str
    last_valid_close: float | None
    position_value: float
    details: str


@dataclass(frozen=True)
class PerformanceMetrics:
    session_count: int
    total_return: float
    annualized_return: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    starting_nav: float
    ending_nav: float


@dataclass(frozen=True)
class PeriodPerformance:
    frequency: str
    period_start: date
    period_end: date
    session_count: int
    strategy_return: float
    spy_return: float
    excess_return: float
    strategy_annualized_volatility: float
    spy_annualized_volatility: float
    strategy_sharpe_ratio: float | None
    spy_sharpe_ratio: float | None
    strategy_max_drawdown: float
    spy_max_drawdown: float


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    daily_performance: tuple[DailyPerformance, ...]
    rebalance_events: tuple[RebalanceEvent, ...]
    target_weights: tuple[TargetWeightRecord, ...]
    trades: tuple[TradeRecord, ...]
    position_lots: tuple[PositionLotRecord, ...]
    fifo_reconciliation_status: str
    missing_data_audit: tuple[MissingDataAudit, ...]
    strategy_metrics: PerformanceMetrics
    spy_metrics: PerformanceMetrics
    calculation_version: str
