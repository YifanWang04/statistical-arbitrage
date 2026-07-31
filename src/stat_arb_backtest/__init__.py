"""Stateful backtesting and event-driven rebalancing."""

from .calculations import (
    CALCULATION_VERSION,
    calculate_period_performance,
    calculate_performance_metrics,
    simulate_backtest,
)
from .application import (
    DEFAULT_PROJECT_DEVIATION_THRESHOLD,
    export_backtest_report,
    required_prior_sessions_for_signals,
    run_backtest,
    target_from_portfolio_weights,
)
from .excel import export_backtest_workbook
from .models import (
    MISSING_PRICE_POLICY_FREEZE,
    BacktestConfig,
    BacktestMarketData,
    BacktestResult,
    BacktestTarget,
    DailyPerformance,
    MissingDataAudit,
    PeriodPerformance,
    PerformanceMetrics,
    PositionLotRecord,
    RebalanceEvent,
    TargetWeight,
    TargetWeightRecord,
    TradeRecord,
)

__all__ = [
    "CALCULATION_VERSION",
    "DEFAULT_PROJECT_DEVIATION_THRESHOLD",
    "MISSING_PRICE_POLICY_FREEZE",
    "BacktestConfig",
    "BacktestMarketData",
    "BacktestResult",
    "BacktestTarget",
    "DailyPerformance",
    "MissingDataAudit",
    "PeriodPerformance",
    "PerformanceMetrics",
    "PositionLotRecord",
    "RebalanceEvent",
    "TargetWeight",
    "TargetWeightRecord",
    "TradeRecord",
    "calculate_period_performance",
    "calculate_performance_metrics",
    "export_backtest_report",
    "export_backtest_workbook",
    "required_prior_sessions_for_signals",
    "run_backtest",
    "simulate_backtest",
    "target_from_portfolio_weights",
]
