"""Step-8 parameter-grid backtesting over the authoritative step-7 engine."""

from .application import (
    build_grid_run_specs,
    export_grid_backtest_report,
    resolve_grid_date_range,
    run_grid_backtest,
)
from .excel import export_grid_backtest_workbook
from .metrics import calculate_grid_run_metrics
from .models import (
    DEFAULT_DEVIATION_THRESHOLDS,
    DEFAULT_LOOKBACK_WINDOWS,
    DEFAULT_LOOKBACK_YEARS,
    DEFAULT_MAXIMUM_COMBINATIONS,
    DEFAULT_REBALANCE_PERIODS,
    DEFAULT_TAKE_PROFIT_THRESHOLDS,
    DEFAULT_VARIANCE_THRESHOLDS,
    GRID_CALCULATION_VERSION,
    GridBacktestConfig,
    GridBacktestResult,
    GridRunMetrics,
    GridRunResult,
    GridRunSpec,
)

__all__ = [
    "DEFAULT_DEVIATION_THRESHOLDS",
    "DEFAULT_LOOKBACK_WINDOWS",
    "DEFAULT_LOOKBACK_YEARS",
    "DEFAULT_MAXIMUM_COMBINATIONS",
    "DEFAULT_REBALANCE_PERIODS",
    "DEFAULT_TAKE_PROFIT_THRESHOLDS",
    "DEFAULT_VARIANCE_THRESHOLDS",
    "GRID_CALCULATION_VERSION",
    "GridBacktestConfig",
    "GridBacktestResult",
    "GridRunMetrics",
    "GridRunResult",
    "GridRunSpec",
    "build_grid_run_specs",
    "calculate_grid_run_metrics",
    "export_grid_backtest_report",
    "export_grid_backtest_workbook",
    "resolve_grid_date_range",
    "run_grid_backtest",
]
