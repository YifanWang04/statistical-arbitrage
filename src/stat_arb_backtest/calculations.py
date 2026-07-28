from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
import math

import numpy as np
import pandas as pd
from tqdm.auto import tqdm

from .models import (
    BacktestConfig,
    BacktestMarketData,
    BacktestResult,
    BacktestTarget,
    DailyPerformance,
    MissingDataAudit,
    PerformanceMetrics,
    PositionLotRecord,
    RebalanceEvent,
    TargetWeightRecord,
    TradeRecord,
)


CALCULATION_VERSION = "long_only_close_to_close_stateful_v2"
TargetProvider = Callable[[date], BacktestTarget]
UNIT_TOLERANCE = 1e-12


@dataclass
class _Position:
    units: float
    last_valid_close: float
    pending_liquidation: bool = False
    is_frozen: bool = False

    @property
    def value(self) -> float:
        return self.units * self.last_valid_close


@dataclass
class _OpenPositionLot:
    lot_id: str
    ticker: str
    buy_trade_id: int
    buy_event_id: int | None
    buy_date: date
    buy_price: float
    bought_units: float
    buy_notional: float
    sold_units: float = 0.0
    sale_proceeds: float = 0.0
    first_sell_date: date | None = None
    final_sell_date: date | None = None
    final_sell_price: float | None = None

    @property
    def remaining_units(self) -> float:
        return max(self.bought_units - self.sold_units, 0.0)


def simulate_backtest(
    market_data: BacktestMarketData,
    config: BacktestConfig,
    target_provider: TargetProvider,
    *,
    show_progress: bool = False,
) -> BacktestResult:
    if market_data.sessions[0] != config.start_date:
        raise ValueError("market-data first session must equal start_date")
    if market_data.sessions[-1] != config.end_date:
        raise ValueError("market-data last session must equal end_date")

    initial_target = target_provider(config.start_date)
    if initial_target.as_of_date != config.start_date:
        raise ValueError("target as-of date does not match its effective date")

    positions: dict[str, _Position] = {}
    cash = config.initial_nav
    trades: list[TradeRecord] = []
    missing_audit: list[MissingDataAudit] = []
    previous = market_data.previous_session
    for target in initial_target.weights:
        if target.portfolio_weight == 0.0:
            continue
        desired_value = config.initial_nav * target.portfolio_weight
        close = _finite_close(market_data.closes, previous, target.ticker)
        if close is None:
            trades.append(
                TradeRecord(
                    event_id=1,
                    trade_date=previous,
                    ticker=target.ticker,
                    side="BUY",
                    value_before=0.0,
                    value_after=0.0,
                    trade_notional=desired_value,
                    status="unfilled_missing_close",
                    reason="initial",
                    execution_price=None,
                    units_before=0.0,
                    units_traded=0.0,
                    units_after=0.0,
                    executed_notional=0.0,
                )
            )
            missing_audit.append(
                MissingDataAudit(
                    trade_date=previous,
                    ticker=target.ticker,
                    event="initial_rebalance",
                    action="buy_unfilled_cash_retained",
                    last_valid_close=None,
                    position_value=0.0,
                    details=(
                        "Initial target ticker has no valid execution close; "
                        "target allocation remains cash."
                    ),
                )
            )
            continue
        bought_units = desired_value / close
        positions[target.ticker] = _Position(
            units=bought_units,
            last_valid_close=close,
        )
        cash -= desired_value
        trades.append(
            TradeRecord(
                event_id=1,
                trade_date=previous,
                ticker=target.ticker,
                side="BUY",
                value_before=0.0,
                value_after=desired_value,
                trade_notional=desired_value,
                status="executed",
                reason="initial",
                execution_price=close,
                units_before=0.0,
                units_traded=bought_units,
                units_after=bought_units,
                executed_notional=desired_value,
            )
        )
    if abs(cash) < 1e-12:
        cash = 0.0

    events = [
        RebalanceEvent(
            event_id=1,
            event_date=previous,
            effective_date=config.start_date,
            reason="initial",
            round_id=1,
            held_sessions=0,
            round_return=0.0,
            nav=config.initial_nav,
            cluster_count=initial_target.cluster_count,
            active_cluster_count=initial_target.active_cluster_count,
            inactive_cluster_count=initial_target.inactive_cluster_count or 0,
            target_gross_exposure=initial_target.target_gross_exposure,
            frozen_value=0.0,
            available_capital=config.initial_nav,
        )
    ]
    target_records = _target_records(1, initial_target)
    daily: list[DailyPerformance] = []
    previous_nav = config.initial_nav
    round_start_nav = config.initial_nav
    spy_nav = config.initial_nav
    round_id = 1
    holding_day = 0

    sessions = tqdm(
        market_data.sessions,
        desc="Backtest",
        unit="session",
        dynamic_ncols=True,
        disable=not show_progress,
    )
    for session_index, trade_date in enumerate(sessions):
        holding_day += 1
        recovered_to_remove: list[str] = []
        for ticker, position in list(positions.items()):
            close = _finite_close(market_data.closes, trade_date, ticker)
            if close is not None:
                was_frozen = position.is_frozen
                position.last_valid_close = close
                position.is_frozen = False
                if position.pending_liquidation:
                    recovered_value = position.value
                    recovered_units = position.units
                    cash += recovered_value
                    trades.append(
                        TradeRecord(
                            event_id=None,
                            trade_date=trade_date,
                            ticker=ticker,
                            side="SELL",
                            value_before=recovered_value,
                            value_after=0.0,
                            trade_notional=recovered_value,
                            status="executed",
                            reason="recovery_liquidation",
                            execution_price=close,
                            units_before=recovered_units,
                            units_traded=recovered_units,
                            units_after=0.0,
                            executed_notional=recovered_value,
                        )
                    )
                    missing_audit.append(
                        MissingDataAudit(
                            trade_date=trade_date,
                            ticker=ticker,
                            event="price_recovery",
                            action="recovered_liquidated",
                            last_valid_close=close,
                            position_value=recovered_value,
                            details=(
                                "Pending obsolete position recovered a valid close "
                                "and was sold to cash without topping up the target."
                            ),
                        )
                    )
                    recovered_to_remove.append(ticker)
                elif was_frozen:
                    missing_audit.append(
                        MissingDataAudit(
                            trade_date=trade_date,
                            ticker=ticker,
                            event="price_recovery",
                            action="recovered_marked",
                            last_valid_close=close,
                            position_value=position.value,
                            details=(
                                "Valid close recovered; cumulative price movement "
                                "is reflected in the position value."
                            ),
                        )
                    )
            else:
                position.is_frozen = True
                missing_audit.append(
                    MissingDataAudit(
                        trade_date=trade_date,
                        ticker=ticker,
                        event="daily_valuation",
                        action="missing_close_carried",
                        last_valid_close=position.last_valid_close,
                        position_value=position.value,
                        details=(
                            "No valid close; prior mark carried and trading disabled."
                        ),
                    )
                )
        for ticker in recovered_to_remove:
            positions.pop(ticker)
        nav = cash + sum(position.value for position in positions.values())
        strategy_return = nav / previous_nav - 1.0
        spy_return = _price_return(
            market_data.closes,
            previous if trade_date == config.start_date else daily[-1].trade_date,
            trade_date,
            "SPY",
        )
        spy_nav *= 1.0 + spy_return
        gross = sum(position.value for position in positions.values())
        frozen = sum(
            position.value for position in positions.values() if position.is_frozen
        )
        round_return = nav / round_start_nav - 1.0
        trigger_reason: str | None = None
        has_next_session = session_index + 1 < len(market_data.sessions)
        if has_next_session:
            if holding_day >= config.rebalance_period:
                trigger_reason = "scheduled"
            elif round_return >= config.take_profit_threshold:
                trigger_reason = "stop_win"
        daily.append(
            DailyPerformance(
                trade_date=trade_date,
                strategy_return=strategy_return,
                nav=nav,
                round_id=round_id,
                round_return=round_return,
                holding_day=holding_day,
                cash_value=cash,
                cash_weight=cash / nav,
                gross_exposure=gross / nav,
                frozen_value=frozen,
                frozen_exposure=frozen / nav,
                position_count=len(positions),
                missing_position_count=sum(
                    position.is_frozen for position in positions.values()
                ),
                spy_return=spy_return,
                spy_nav=spy_nav,
                trigger_reason=trigger_reason,
            )
        )

        if trigger_reason is not None:
            effective_date = market_data.sessions[session_index + 1]
            replacement = target_provider(effective_date)
            if replacement.as_of_date != effective_date:
                raise ValueError(
                    "target as-of date does not match its effective date"
                )
            event_id = len(events) + 1
            positions, cash, event_trades, event_audit, frozen_value = (
                _rebalance_positions(
                    positions=positions,
                    cash=cash,
                    closes=market_data.closes,
                    trade_date=trade_date,
                    nav=nav,
                    target=replacement,
                    event_id=event_id,
                    reason=trigger_reason,
                )
            )
            trades.extend(event_trades)
            missing_audit.extend(event_audit)
            events.append(
                RebalanceEvent(
                    event_id=event_id,
                    event_date=trade_date,
                    effective_date=effective_date,
                    reason=trigger_reason,
                    round_id=round_id,
                    held_sessions=holding_day,
                    round_return=round_return,
                    nav=nav,
                    cluster_count=replacement.cluster_count,
                    active_cluster_count=replacement.active_cluster_count,
                    inactive_cluster_count=(
                        replacement.inactive_cluster_count or 0
                    ),
                    target_gross_exposure=replacement.target_gross_exposure,
                    frozen_value=frozen_value,
                    available_capital=nav - frozen_value,
                )
            )
            target_records.extend(_target_records(event_id, replacement))
            round_id += 1
            holding_day = 0
            round_start_nav = nav
        previous_nav = nav

    strategy_metrics = calculate_performance_metrics(
        [row.strategy_return for row in daily],
        config.initial_nav,
        daily[-1].nav,
        config.annualization_sessions,
    )
    spy_metrics = calculate_performance_metrics(
        [row.spy_return for row in daily],
        config.initial_nav,
        daily[-1].spy_nav,
        config.annualization_sessions,
    )
    numbered_trades = tuple(
        replace(trade, trade_id=trade_id)
        for trade_id, trade in enumerate(trades, start=1)
    )
    position_lots = _build_position_lots(numbered_trades)
    return BacktestResult(
        config=config,
        daily_performance=tuple(daily),
        rebalance_events=tuple(events),
        target_weights=tuple(target_records),
        trades=numbered_trades,
        position_lots=position_lots,
        fifo_reconciliation_status="OK",
        missing_data_audit=tuple(missing_audit),
        strategy_metrics=strategy_metrics,
        spy_metrics=spy_metrics,
        calculation_version=CALCULATION_VERSION,
    )


def _rebalance_positions(
    *,
    positions: dict[str, _Position],
    cash: float,
    closes: pd.DataFrame,
    trade_date: date,
    nav: float,
    target: BacktestTarget,
    event_id: int,
    reason: str,
) -> tuple[
    dict[str, _Position],
    float,
    list[TradeRecord],
    list[MissingDataAudit],
    float,
]:
    trades: list[TradeRecord] = []
    audit: list[MissingDataAudit] = []
    target_by_ticker = {
        weight.ticker: weight
        for weight in target.weights
        if weight.portfolio_weight > 0.0
    }
    frozen_tickers = {
        ticker for ticker, position in positions.items() if position.is_frozen
    }
    for ticker in frozen_tickers:
        remains_in_target = ticker in target_by_ticker
        positions[ticker].pending_liquidation = not remains_in_target
        details = (
            "No valid close at the rebalance boundary; position remains "
            "in the new target, is retained without adjustment, and is "
            "excluded from new target capital."
            if remains_in_target
            else "No valid close at the rebalance boundary; obsolete position "
            "is retained pending a recovery sale and is excluded from new "
            "target capital."
        )
        audit.append(
            MissingDataAudit(
                trade_date=trade_date,
                ticker=ticker,
                event="rebalance",
                action=(
                    "frozen_retained_target"
                    if remains_in_target
                    else "frozen_pending_liquidation"
                ),
                last_valid_close=positions[ticker].last_valid_close,
                position_value=positions[ticker].value,
                details=details,
            )
        )
    frozen_value = sum(positions[ticker].value for ticker in frozen_tickers)
    available_capital = nav - frozen_value

    desired_values: dict[str, float] = {}
    for ticker, weight in target_by_ticker.items():
        desired_value = available_capital * weight.portfolio_weight
        if ticker in frozen_tickers:
            audit.append(
                MissingDataAudit(
                    trade_date=trade_date,
                    ticker=ticker,
                    event="rebalance",
                    action="buy_unfilled_existing_frozen_position",
                    last_valid_close=positions[ticker].last_valid_close,
                    position_value=positions[ticker].value,
                    details=(
                        "Ticker remains in the target but its old position is "
                        "frozen; no adjustment or additional purchase is made."
                    ),
                )
            )
            continue
        close = _finite_close(closes, trade_date, ticker)
        if close is None:
            trades.append(
                TradeRecord(
                    event_id=event_id,
                    trade_date=trade_date,
                    ticker=ticker,
                    side="BUY",
                    value_before=0.0,
                    value_after=0.0,
                    trade_notional=desired_value,
                    status="unfilled_missing_close",
                    reason=reason,
                    execution_price=None,
                    units_before=0.0,
                    units_traded=0.0,
                    units_after=0.0,
                    executed_notional=0.0,
                )
            )
            audit.append(
                MissingDataAudit(
                    trade_date=trade_date,
                    ticker=ticker,
                    event="rebalance",
                    action="buy_unfilled_cash_retained",
                    last_valid_close=None,
                    position_value=0.0,
                    details=(
                        "Target ticker has no valid execution close; its target "
                        "allocation remains cash."
                    ),
                )
            )
            continue
        desired_values[ticker] = desired_value

    tradable_tickers = set(positions) - frozen_tickers
    all_tickers = tradable_tickers | set(desired_values)
    current_values = {
        ticker: positions[ticker].value if ticker in positions else 0.0
        for ticker in all_tickers
    }

    for ticker in sorted(all_tickers):
        desired = desired_values.get(ticker, 0.0)
        current = current_values[ticker]
        if desired >= current - 1e-14:
            continue
        reduction = current - desired
        close = _finite_close(closes, trade_date, ticker)
        if close is None:
            raise RuntimeError("tradable position unexpectedly has no close")
        units_before = positions[ticker].units
        units_after = 0.0 if desired <= 1e-14 else desired / close
        units_traded = units_before - units_after
        cash += reduction
        if desired <= 1e-14:
            positions.pop(ticker, None)
        else:
            positions[ticker] = _Position(
                units=units_after,
                last_valid_close=close,
            )
        trades.append(
            TradeRecord(
                event_id=event_id,
                trade_date=trade_date,
                ticker=ticker,
                side="SELL",
                value_before=current,
                value_after=max(desired, 0.0),
                trade_notional=reduction,
                status="executed",
                reason=reason,
                execution_price=close,
                units_before=units_before,
                units_traded=units_traded,
                units_after=units_after,
                executed_notional=reduction,
            )
        )

    for ticker in sorted(all_tickers):
        desired = desired_values.get(ticker, 0.0)
        current = current_values[ticker]
        if desired <= current + 1e-14:
            continue
        increase = desired - current
        if increase > cash + 1e-12:
            raise RuntimeError("rebalance would require leverage")
        close = _finite_close(closes, trade_date, ticker)
        if close is None:
            raise RuntimeError("target position unexpectedly has no close")
        units_before = positions[ticker].units if ticker in positions else 0.0
        units_after = desired / close
        units_traded = units_after - units_before
        cash -= increase
        positions[ticker] = _Position(
            units=units_after,
            last_valid_close=close,
        )
        trades.append(
            TradeRecord(
                event_id=event_id,
                trade_date=trade_date,
                ticker=ticker,
                side="BUY",
                value_before=current,
                value_after=desired,
                trade_notional=increase,
                status="executed",
                reason=reason,
                execution_price=close,
                units_before=units_before,
                units_traded=units_traded,
                units_after=units_after,
                executed_notional=increase,
            )
        )

    if cash < 0.0 and abs(cash) < 1e-12:
        cash = 0.0
    return positions, cash, trades, audit, frozen_value


def _build_position_lots(
    trades: tuple[TradeRecord, ...],
) -> tuple[PositionLotRecord, ...]:
    open_lots: dict[str, list[_OpenPositionLot]] = {}
    all_lots: list[_OpenPositionLot] = []
    bought_units_by_ticker: dict[str, float] = {}
    sold_units_by_ticker: dict[str, float] = {}

    for trade in trades:
        if trade.status != "executed":
            if (
                trade.execution_price is not None
                or abs(trade.units_traded) > UNIT_TOLERANCE
                or abs(trade.executed_notional) > UNIT_TOLERANCE
            ):
                raise RuntimeError("unfilled trade contains executed values")
            continue
        price = trade.execution_price
        if (
            price is None
            or not math.isfinite(price)
            or price <= 0.0
            or not math.isfinite(trade.units_traded)
            or trade.units_traded <= UNIT_TOLERANCE
        ):
            raise RuntimeError("executed trade must have positive price and units")
        expected_notional = price * trade.units_traded
        if not math.isclose(
            expected_notional,
            trade.executed_notional,
            rel_tol=1e-10,
            abs_tol=1e-12,
        ):
            raise RuntimeError("trade price, units, and notional do not reconcile")
        expected_units = (
            trade.units_after - trade.units_before
            if trade.side == "BUY"
            else trade.units_before - trade.units_after
        )
        if not math.isclose(
            expected_units,
            trade.units_traded,
            rel_tol=1e-10,
            abs_tol=1e-12,
        ):
            raise RuntimeError("trade before/after units do not reconcile")

        if trade.side == "BUY":
            lot = _OpenPositionLot(
                lot_id=f"LOT{len(all_lots) + 1:06d}",
                ticker=trade.ticker,
                buy_trade_id=trade.trade_id,
                buy_event_id=trade.event_id,
                buy_date=trade.trade_date,
                buy_price=price,
                bought_units=trade.units_traded,
                buy_notional=trade.executed_notional,
            )
            all_lots.append(lot)
            open_lots.setdefault(trade.ticker, []).append(lot)
            bought_units_by_ticker[trade.ticker] = (
                bought_units_by_ticker.get(trade.ticker, 0.0)
                + trade.units_traded
            )
            continue
        if trade.side != "SELL":
            raise RuntimeError(f"unsupported executed trade side: {trade.side}")

        sold_units_by_ticker[trade.ticker] = (
            sold_units_by_ticker.get(trade.ticker, 0.0)
            + trade.units_traded
        )
        units_to_match = trade.units_traded
        ticker_lots = open_lots.setdefault(trade.ticker, [])
        while units_to_match > UNIT_TOLERANCE and ticker_lots:
            lot = ticker_lots[0]
            allocated_units = min(units_to_match, lot.remaining_units)
            if lot.first_sell_date is None:
                lot.first_sell_date = trade.trade_date
            lot.sold_units += allocated_units
            lot.sale_proceeds += allocated_units * price
            units_to_match -= allocated_units
            if lot.remaining_units <= UNIT_TOLERANCE:
                lot.sold_units = lot.bought_units
                lot.final_sell_date = trade.trade_date
                lot.final_sell_price = price
                ticker_lots.pop(0)
        if units_to_match > UNIT_TOLERANCE:
            raise RuntimeError(
                f"FIFO sell exceeds open buy lots for {trade.ticker}"
            )

    lot_records: list[PositionLotRecord] = []
    remaining_units_by_ticker: dict[str, float] = {}
    for lot in all_lots:
        sold_units = min(lot.sold_units, lot.bought_units)
        remaining_units = max(lot.bought_units - sold_units, 0.0)
        if sold_units <= UNIT_TOLERANCE:
            status = "OPEN"
        elif remaining_units <= UNIT_TOLERANCE:
            status = "CLOSED"
        else:
            status = "PARTIALLY_CLOSED"
        matched_sell_vwap = (
            lot.sale_proceeds / sold_units
            if sold_units > UNIT_TOLERANCE
            else None
        )
        realized_pnl = lot.sale_proceeds - sold_units * lot.buy_price
        realized_return = (
            realized_pnl / (sold_units * lot.buy_price)
            if sold_units > UNIT_TOLERANCE
            else None
        )
        lot_return = (
            lot.sale_proceeds / lot.buy_notional - 1.0
            if status == "CLOSED"
            else None
        )
        remaining_units_by_ticker[lot.ticker] = (
            remaining_units_by_ticker.get(lot.ticker, 0.0)
            + remaining_units
        )
        lot_records.append(
            PositionLotRecord(
                lot_id=lot.lot_id,
                ticker=lot.ticker,
                buy_trade_id=lot.buy_trade_id,
                buy_event_id=lot.buy_event_id,
                buy_date=lot.buy_date,
                buy_price=lot.buy_price,
                bought_units=lot.bought_units,
                buy_notional=lot.buy_notional,
                sold_units=sold_units,
                remaining_units=remaining_units,
                first_sell_date=lot.first_sell_date,
                final_sell_date=lot.final_sell_date,
                matched_sell_vwap=matched_sell_vwap,
                final_sell_price=lot.final_sell_price,
                sale_proceeds=lot.sale_proceeds,
                realized_pnl=realized_pnl,
                realized_return=realized_return,
                lot_return=lot_return,
                status=status,
            )
        )

    tickers = set(bought_units_by_ticker) | set(sold_units_by_ticker)
    for ticker in tickers:
        expected_remaining = (
            bought_units_by_ticker.get(ticker, 0.0)
            - sold_units_by_ticker.get(ticker, 0.0)
        )
        observed_remaining = remaining_units_by_ticker.get(ticker, 0.0)
        if not math.isclose(
            expected_remaining,
            observed_remaining,
            rel_tol=1e-10,
            abs_tol=1e-12,
        ):
            raise RuntimeError(
                f"FIFO remaining units do not reconcile for {ticker}"
            )
    return tuple(lot_records)


def calculate_performance_metrics(
    daily_returns: list[float] | tuple[float, ...],
    starting_nav: float,
    ending_nav: float,
    annualization_sessions: int,
) -> PerformanceMetrics:
    returns = np.asarray(daily_returns, dtype=float)
    if returns.ndim != 1 or returns.size < 1:
        raise ValueError("daily_returns must contain at least one observation")
    if not bool(np.isfinite(returns).all()):
        raise ValueError("daily_returns must be finite")
    count = int(returns.size)
    total_return = float(ending_nav / starting_nav - 1.0)
    annualized = (
        float((ending_nav / starting_nav) ** (annualization_sessions / count) - 1.0)
        if starting_nav > 0.0 and ending_nav > 0.0
        else None
    )
    standard_deviation = float(np.std(returns, ddof=1)) if count > 1 else 0.0
    sharpe = (
        float(math.sqrt(annualization_sessions) * np.mean(returns) / standard_deviation)
        if standard_deviation > 0.0
        else None
    )
    negative = returns[returns < 0.0]
    downside_deviation = (
        float(np.std(negative, ddof=1)) if negative.size > 1 else 0.0
    )
    sortino = (
        float(math.sqrt(annualization_sessions) * np.mean(returns) / downside_deviation)
        if downside_deviation > 0.0
        else None
    )
    return PerformanceMetrics(
        session_count=count,
        total_return=total_return,
        annualized_return=annualized,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        starting_nav=float(starting_nav),
        ending_nav=float(ending_nav),
    )


def _target_records(
    event_id: int,
    target: BacktestTarget,
) -> list[TargetWeightRecord]:
    return [
        TargetWeightRecord(
            event_id=event_id,
            effective_date=target.as_of_date,
            ticker=weight.ticker,
            market_cap_rank=weight.market_cap_rank,
            cluster_id=weight.cluster_id,
            cumulative_deviation=weight.cumulative_deviation,
            classification=weight.classification,
            local_weight=weight.local_weight,
            portfolio_weight=weight.portfolio_weight,
        )
        for weight in target.weights
        if weight.portfolio_weight > 0.0
    ]


def _finite_close(
    closes: pd.DataFrame,
    trade_date: date,
    ticker: str,
) -> float | None:
    if ticker not in closes.columns:
        return None
    value = closes.at[trade_date, ticker]
    if pd.isna(value):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0.0:
        return None
    return numeric


def _price_return(
    closes: pd.DataFrame,
    previous_date: date,
    trade_date: date,
    ticker: str,
) -> float:
    previous_close = _finite_close(closes, previous_date, ticker)
    current_close = _finite_close(closes, trade_date, ticker)
    if previous_close is None or current_close is None:
        raise ValueError(
            f"{ticker} close is missing for {previous_date} or {trade_date}"
        )
    return current_close / previous_close - 1.0
