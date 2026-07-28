from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import numpy as np
import pandas as pd

from stat_arb_backtest import BacktestResult

from .models import GridRunMetrics


@dataclass(frozen=True)
class _ReturnStatistics:
    mean_daily_return: float
    annualized_volatility: float | None
    annualized_downside_volatility: float | None
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


def calculate_grid_run_metrics(result: BacktestResult) -> GridRunMetrics:
    daily = result.daily_performance
    strategy_returns = np.asarray(
        [row.strategy_return for row in daily],
        dtype=float,
    )
    spy_returns = np.asarray(
        [row.spy_return for row in daily],
        dtype=float,
    )
    trade_dates = tuple(row.trade_date for row in daily)
    strategy_nav = np.asarray([row.nav for row in daily], dtype=float)
    spy_nav = np.asarray([row.spy_nav for row in daily], dtype=float)
    annualization = result.config.annualization_sessions

    strategy = _return_statistics(
        strategy_returns,
        strategy_nav,
        trade_dates,
        result.strategy_metrics.annualized_return,
        result.config.initial_nav,
        result.config.start_date,
        annualization,
    )
    spy = _return_statistics(
        spy_returns,
        spy_nav,
        trade_dates,
        result.spy_metrics.annualized_return,
        result.config.initial_nav,
        result.config.start_date,
        annualization,
    )
    spy_correlation, spy_beta, alpha, tracking_error, information_ratio = (
        _relative_statistics(
            strategy_returns,
            spy_returns,
            annualization,
        )
    )
    noninitial_events = tuple(
        event
        for event in result.rebalance_events
        if event.reason != "initial"
    )
    nav_by_date = {row.trade_date: row.nav for row in daily}
    turnover_sum = sum(
        trade.executed_notional / nav_by_date[trade.trade_date]
        for trade in result.trades
        if trade.status == "executed"
        and trade.reason != "initial"
        and trade.trade_date in nav_by_date
        and nav_by_date[trade.trade_date] > 0.0
    )
    annualized_two_way_turnover = (
        0.5 * turnover_sum * annualization / len(daily)
    )

    events = result.rebalance_events
    daily_rows = result.daily_performance
    finite_and_reconciled = all(
        _all_finite(
            row.strategy_return,
            row.nav,
            row.spy_return,
            row.spy_nav,
            row.gross_exposure,
            row.cash_weight,
            row.frozen_exposure,
        )
        and math.isclose(
            row.cash_weight + row.gross_exposure,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-10,
        )
        for row in daily_rows
    )
    overall_qc = (
        "OK"
        if finite_and_reconciled
        and result.fifo_reconciliation_status == "OK"
        else "CHECK"
    )

    return GridRunMetrics(
        session_count=result.strategy_metrics.session_count,
        starting_nav=result.strategy_metrics.starting_nav,
        ending_nav=result.strategy_metrics.ending_nav,
        total_return=result.strategy_metrics.total_return,
        annualized_return=result.strategy_metrics.annualized_return,
        mean_daily_return=strategy.mean_daily_return,
        annualized_volatility=strategy.annualized_volatility,
        sharpe_ratio=result.strategy_metrics.sharpe_ratio,
        annualized_downside_volatility=(
            strategy.annualized_downside_volatility
        ),
        sortino_ratio=result.strategy_metrics.sortino_ratio,
        maximum_drawdown=strategy.maximum_drawdown,
        drawdown_peak_date=strategy.drawdown_peak_date,
        drawdown_trough_date=strategy.drawdown_trough_date,
        drawdown_recovery_date=strategy.drawdown_recovery_date,
        calmar_ratio=strategy.calmar_ratio,
        positive_session_count=strategy.positive_session_count,
        negative_session_count=strategy.negative_session_count,
        zero_session_count=strategy.zero_session_count,
        win_rate=strategy.win_rate,
        average_positive_return=strategy.average_positive_return,
        average_negative_return=strategy.average_negative_return,
        payoff_ratio=strategy.payoff_ratio,
        profit_factor=strategy.profit_factor,
        best_daily_return=strategy.best_daily_return,
        worst_daily_return=strategy.worst_daily_return,
        skewness=strategy.skewness,
        excess_kurtosis=strategy.excess_kurtosis,
        daily_var_95=strategy.daily_var_95,
        daily_cvar_95=strategy.daily_cvar_95,
        spy_total_return=result.spy_metrics.total_return,
        spy_annualized_return=result.spy_metrics.annualized_return,
        spy_annualized_volatility=spy.annualized_volatility,
        spy_sharpe_ratio=result.spy_metrics.sharpe_ratio,
        spy_sortino_ratio=result.spy_metrics.sortino_ratio,
        spy_maximum_drawdown=spy.maximum_drawdown,
        spy_calmar_ratio=spy.calmar_ratio,
        excess_total_return=(
            result.strategy_metrics.total_return
            - result.spy_metrics.total_return
        ),
        excess_annualized_return=_optional_difference(
            result.strategy_metrics.annualized_return,
            result.spy_metrics.annualized_return,
        ),
        spy_correlation=spy_correlation,
        spy_beta=spy_beta,
        annualized_alpha=alpha,
        tracking_error=tracking_error,
        information_ratio=information_ratio,
        initial_event_count=sum(event.reason == "initial" for event in events),
        scheduled_event_count=sum(
            event.reason == "scheduled" for event in events
        ),
        stop_win_event_count=sum(
            event.reason == "stop_win" for event in events
        ),
        average_held_sessions=_mean_or_none(
            [event.held_sessions for event in noninitial_events]
        ),
        average_cluster_count=float(
            np.mean([event.cluster_count for event in events])
        ),
        average_active_cluster_count=float(
            np.mean([event.active_cluster_count for event in events])
        ),
        average_inactive_cluster_count=float(
            np.mean([event.inactive_cluster_count for event in events])
        ),
        average_target_gross_exposure=float(
            np.mean([event.target_gross_exposure for event in events])
        ),
        average_gross_exposure=float(
            np.mean([row.gross_exposure for row in daily_rows])
        ),
        average_cash_weight=float(
            np.mean([row.cash_weight for row in daily_rows])
        ),
        average_frozen_exposure=float(
            np.mean([row.frozen_exposure for row in daily_rows])
        ),
        average_position_count=float(
            np.mean([row.position_count for row in daily_rows])
        ),
        minimum_position_count=min(row.position_count for row in daily_rows),
        maximum_position_count=max(row.position_count for row in daily_rows),
        missing_session_count=sum(
            row.missing_position_count > 0 for row in daily_rows
        ),
        missing_audit_count=len(result.missing_data_audit),
        annualized_two_way_turnover=float(annualized_two_way_turnover),
        fifo_reconciliation_status=result.fifo_reconciliation_status,
        overall_qc=overall_qc,
    )


def _return_statistics(
    returns: np.ndarray,
    ending_navs: np.ndarray,
    trade_dates: tuple[date, ...],
    annualized_return: float | None,
    starting_nav: float,
    start_date: date,
    annualization_sessions: int,
) -> _ReturnStatistics:
    if (
        returns.ndim != 1
        or returns.size < 1
        or ending_navs.shape != returns.shape
        or len(trade_dates) != returns.size
        or not bool(np.isfinite(returns).all())
        or not bool(np.isfinite(ending_navs).all())
    ):
        raise ValueError("return and NAV series must be aligned and finite")
    count = int(returns.size)
    standard_deviation = (
        float(np.std(returns, ddof=1)) if count > 1 else 0.0
    )
    annualized_volatility = (
        float(math.sqrt(annualization_sessions) * standard_deviation)
        if standard_deviation > 0.0
        else None
    )
    negative = returns[returns < 0.0]
    downside_deviation = (
        float(np.std(negative, ddof=1)) if negative.size > 1 else 0.0
    )
    annualized_downside = (
        float(math.sqrt(annualization_sessions) * downside_deviation)
        if downside_deviation > 0.0
        else None
    )
    (
        maximum_drawdown,
        peak_date,
        trough_date,
        recovery_date,
    ) = _maximum_drawdown(
        starting_nav,
        ending_navs,
        start_date,
        trade_dates,
    )
    calmar = (
        float(annualized_return / abs(maximum_drawdown))
        if annualized_return is not None and maximum_drawdown < 0.0
        else None
    )
    positive = returns[returns > 0.0]
    negative = returns[returns < 0.0]
    average_positive = (
        float(np.mean(positive)) if positive.size else None
    )
    average_negative = (
        float(np.mean(negative)) if negative.size else None
    )
    payoff_ratio = (
        float(average_positive / abs(average_negative))
        if average_positive is not None
        and average_negative is not None
        and average_negative != 0.0
        else None
    )
    negative_sum = float(np.sum(negative))
    profit_factor = (
        float(np.sum(positive) / abs(negative_sum))
        if negative_sum < 0.0
        else None
    )
    series = pd.Series(returns)
    skewness = _finite_or_none(series.skew()) if count >= 3 else None
    excess_kurtosis = _finite_or_none(series.kurt()) if count >= 4 else None
    daily_var_95 = float(np.quantile(returns, 0.05, method="linear"))
    tail = returns[returns <= daily_var_95]
    daily_cvar_95 = float(np.mean(tail))

    return _ReturnStatistics(
        mean_daily_return=float(np.mean(returns)),
        annualized_volatility=annualized_volatility,
        annualized_downside_volatility=annualized_downside,
        maximum_drawdown=maximum_drawdown,
        drawdown_peak_date=peak_date,
        drawdown_trough_date=trough_date,
        drawdown_recovery_date=recovery_date,
        calmar_ratio=calmar,
        positive_session_count=int(positive.size),
        negative_session_count=int(negative.size),
        zero_session_count=int(np.count_nonzero(returns == 0.0)),
        win_rate=float(positive.size / count),
        average_positive_return=average_positive,
        average_negative_return=average_negative,
        payoff_ratio=payoff_ratio,
        profit_factor=profit_factor,
        best_daily_return=float(np.max(returns)),
        worst_daily_return=float(np.min(returns)),
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
        daily_var_95=daily_var_95,
        daily_cvar_95=daily_cvar_95,
    )


def _maximum_drawdown(
    starting_nav: float,
    ending_navs: np.ndarray,
    start_date: date,
    trade_dates: tuple[date, ...],
) -> tuple[float, date | None, date | None, date | None]:
    navs = np.concatenate(([float(starting_nav)], ending_navs))
    dates = (start_date, *trade_dates)
    running_max = np.maximum.accumulate(navs)
    drawdowns = navs / running_max - 1.0
    trough_index = int(np.argmin(drawdowns))
    maximum_drawdown = float(drawdowns[trough_index])
    if maximum_drawdown >= 0.0:
        return 0.0, None, None, None
    peak_index = int(np.argmax(navs[: trough_index + 1]))
    recovery_index = next(
        (
            index
            for index in range(trough_index + 1, len(navs))
            if navs[index] >= navs[peak_index] - 1e-12
        ),
        None,
    )
    return (
        maximum_drawdown,
        dates[peak_index],
        dates[trough_index],
        dates[recovery_index] if recovery_index is not None else None,
    )


def _relative_statistics(
    strategy: np.ndarray,
    benchmark: np.ndarray,
    annualization_sessions: int,
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]:
    if strategy.shape != benchmark.shape:
        raise ValueError("strategy and benchmark returns must be aligned")
    count = int(strategy.size)
    benchmark_variance = (
        float(np.var(benchmark, ddof=1)) if count > 1 else 0.0
    )
    strategy_std = float(np.std(strategy, ddof=1)) if count > 1 else 0.0
    benchmark_std = (
        float(np.std(benchmark, ddof=1)) if count > 1 else 0.0
    )
    covariance = (
        float(np.cov(strategy, benchmark, ddof=1)[0, 1])
        if count > 1
        else 0.0
    )
    correlation = (
        float(covariance / (strategy_std * benchmark_std))
        if strategy_std > 0.0 and benchmark_std > 0.0
        else None
    )
    beta = (
        float(covariance / benchmark_variance)
        if benchmark_variance > 0.0
        else None
    )
    alpha = (
        float(
            annualization_sessions
            * (np.mean(strategy) - beta * np.mean(benchmark))
        )
        if beta is not None
        else None
    )
    active = strategy - benchmark
    active_std = float(np.std(active, ddof=1)) if count > 1 else 0.0
    tracking_error = (
        float(math.sqrt(annualization_sessions) * active_std)
        if active_std > 0.0
        else None
    )
    information_ratio = (
        float(
            math.sqrt(annualization_sessions)
            * np.mean(active)
            / active_std
        )
        if active_std > 0.0
        else None
    )
    return correlation, beta, alpha, tracking_error, information_ratio


def _optional_difference(
    left: float | None,
    right: float | None,
) -> float | None:
    if left is None or right is None:
        return None
    return float(left - right)


def _mean_or_none(values: list[int]) -> float | None:
    return float(np.mean(values)) if values else None


def _finite_or_none(value: float) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _all_finite(*values: float) -> bool:
    return all(math.isfinite(float(value)) for value in values)
