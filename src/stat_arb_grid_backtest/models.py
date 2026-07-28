from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import reduce
import math
from operator import mul

from stat_arb_clustering import SpongeSymConfig


DEFAULT_LOOKBACK_WINDOWS = (5, 10, 20)
DEFAULT_DEVIATION_THRESHOLDS = (0.0, 0.05)
DEFAULT_VARIANCE_THRESHOLDS = (0.85, 0.90)
DEFAULT_REBALANCE_PERIODS = (3, 5, 10)
DEFAULT_TAKE_PROFIT_THRESHOLDS = (0.03, 0.05)
DEFAULT_LOOKBACK_YEARS = 3
DEFAULT_MAXIMUM_COMBINATIONS = 1_000
GRID_CALCULATION_VERSION = "five_parameter_grid_backtest_v1"


@dataclass(frozen=True)
class GridBacktestConfig:
    start_date: date | None = None
    end_date: date | None = None
    lookback_windows: tuple[int, ...] = DEFAULT_LOOKBACK_WINDOWS
    deviation_thresholds: tuple[float, ...] = DEFAULT_DEVIATION_THRESHOLDS
    variance_thresholds: tuple[float, ...] = DEFAULT_VARIANCE_THRESHOLDS
    rebalance_periods: tuple[int, ...] = DEFAULT_REBALANCE_PERIODS
    take_profit_thresholds: tuple[float, ...] = (
        DEFAULT_TAKE_PROFIT_THRESHOLDS
    )
    initial_nav: float = 1.0
    annualization_sessions: int = 252
    default_lookback_years: int = DEFAULT_LOOKBACK_YEARS
    maximum_combinations: int = DEFAULT_MAXIMUM_COMBINATIONS

    def __post_init__(self) -> None:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must not be after end_date")
        object.__setattr__(
            self,
            "lookback_windows",
            _normalize_positive_ints(
                "lookback_windows",
                self.lookback_windows,
                minimum=2,
            ),
        )
        object.__setattr__(
            self,
            "rebalance_periods",
            _normalize_positive_ints(
                "rebalance_periods",
                self.rebalance_periods,
            ),
        )
        object.__setattr__(
            self,
            "deviation_thresholds",
            _normalize_floats(
                "deviation_thresholds",
                self.deviation_thresholds,
                minimum=0.0,
                minimum_inclusive=True,
            ),
        )
        object.__setattr__(
            self,
            "variance_thresholds",
            _normalize_floats(
                "variance_thresholds",
                self.variance_thresholds,
                minimum=0.0,
                minimum_inclusive=False,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "take_profit_thresholds",
            _normalize_floats(
                "take_profit_thresholds",
                self.take_profit_thresholds,
                minimum=0.0,
                minimum_inclusive=False,
            ),
        )
        for name, value in (
            ("annualization_sessions", self.annualization_sessions),
            ("default_lookback_years", self.default_lookback_years),
            ("maximum_combinations", self.maximum_combinations),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        try:
            initial_nav = float(self.initial_nav)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "initial_nav must be a finite positive number"
            ) from exc
        if not math.isfinite(initial_nav) or initial_nav <= 0.0:
            raise ValueError("initial_nav must be a finite positive number")
        object.__setattr__(self, "initial_nav", initial_nav)
        if self.combination_count > self.maximum_combinations:
            raise ValueError(
                "grid contains "
                f"{self.combination_count} combinations, exceeding "
                f"maximum_combinations={self.maximum_combinations}"
            )

    @property
    def combination_count(self) -> int:
        return reduce(
            mul,
            (
                len(self.lookback_windows),
                len(self.deviation_thresholds),
                len(self.variance_thresholds),
                len(self.rebalance_periods),
                len(self.take_profit_thresholds),
            ),
            1,
        )


@dataclass(frozen=True)
class GridRunSpec:
    run_id: str
    lookback_window: int
    deviation_threshold: float
    variance_threshold: float
    rebalance_period: int
    take_profit_threshold: float


@dataclass(frozen=True)
class GridRunMetrics:
    session_count: int
    starting_nav: float
    ending_nav: float
    total_return: float
    annualized_return: float | None
    mean_daily_return: float
    annualized_volatility: float | None
    sharpe_ratio: float | None
    annualized_downside_volatility: float | None
    sortino_ratio: float | None
    maximum_drawdown: float
    drawdown_peak_date: date | None
    drawdown_trough_date: date | None
    drawdown_recovery_date: date | None
    calmar_ratio: float | None
    positive_session_count: int
    negative_session_count: int
    zero_session_count: int
    win_rate: float
    average_positive_return: float | None
    average_negative_return: float | None
    payoff_ratio: float | None
    profit_factor: float | None
    best_daily_return: float
    worst_daily_return: float
    skewness: float | None
    excess_kurtosis: float | None
    daily_var_95: float
    daily_cvar_95: float
    spy_total_return: float
    spy_annualized_return: float | None
    spy_annualized_volatility: float | None
    spy_sharpe_ratio: float | None
    spy_sortino_ratio: float | None
    spy_maximum_drawdown: float
    spy_calmar_ratio: float | None
    excess_total_return: float
    excess_annualized_return: float | None
    spy_correlation: float | None
    spy_beta: float | None
    annualized_alpha: float | None
    tracking_error: float | None
    information_ratio: float | None
    initial_event_count: int
    scheduled_event_count: int
    stop_win_event_count: int
    average_held_sessions: float | None
    average_cluster_count: float
    average_active_cluster_count: float
    average_inactive_cluster_count: float
    average_target_gross_exposure: float
    average_gross_exposure: float
    average_cash_weight: float
    average_frozen_exposure: float
    average_position_count: float
    minimum_position_count: int
    maximum_position_count: int
    missing_session_count: int
    missing_audit_count: int
    annualized_two_way_turnover: float
    fifo_reconciliation_status: str
    overall_qc: str


@dataclass(frozen=True)
class GridRunResult:
    spec: GridRunSpec
    status: str
    metrics: GridRunMetrics | None = None
    rank: int | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class GridBacktestResult:
    config: GridBacktestConfig
    requested_start_date: date
    requested_end_date: date
    effective_start_date: date
    effective_end_date: date
    beta_window: int
    cluster_count_estimation_window: int
    sponge_config: SpongeSymConfig
    runs: tuple[GridRunResult, ...]
    best_run_id: str | None
    overall_qc: str
    calculation_version: str = GRID_CALCULATION_VERSION

    @property
    def successful_run_count(self) -> int:
        return sum(run.status == "SUCCESS" for run in self.runs)

    @property
    def failed_run_count(self) -> int:
        return sum(run.status == "FAILED" for run in self.runs)

    @property
    def best_run(self) -> GridRunResult | None:
        return next(
            (
                run
                for run in self.runs
                if run.spec.run_id == self.best_run_id
            ),
            None,
        )


def _normalize_positive_ints(
    name: str,
    values: tuple[int, ...],
    *,
    minimum: int = 1,
) -> tuple[int, ...]:
    normalized: list[int] = []
    for value in values:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < minimum
        ):
            raise ValueError(
                f"{name} values must be integers of at least {minimum}"
            )
        normalized.append(value)
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return tuple(sorted(set(normalized)))


def _normalize_floats(
    name: str,
    values: tuple[float, ...],
    *,
    minimum: float,
    minimum_inclusive: bool,
    maximum: float | None = None,
) -> tuple[float, ...]:
    normalized: list[float] = []
    for value in values:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} values must be finite numbers") from exc
        if (
            not math.isfinite(numeric)
            or numeric < minimum
            or (numeric == minimum and not minimum_inclusive)
            or (maximum is not None and numeric > maximum)
        ):
            raise ValueError(f"{name} contains an out-of-range value")
        normalized.append(numeric)
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return tuple(sorted(set(normalized)))
