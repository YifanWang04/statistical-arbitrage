from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path


DEFAULT_BACKTEST_OUTPUT_DIRECTORY = Path("outputs/step7_backtest")


def backtest_parameter_suffix(
    *,
    lookback_window: int,
    deviation_threshold: float,
    variance_threshold: float,
    rebalance_period: int,
    take_profit_threshold: float,
) -> str:
    """Return a compact, deterministic suffix for the five core inputs."""
    return (
        f"_w{_compact_number(lookback_window)}"
        f"p{_percentage_token(deviation_threshold)}"
        f"P{_percentage_token(variance_threshold)}"
        f"l{_compact_number(rebalance_period)}"
        f"q{_percentage_token(take_profit_threshold)}"
    )


def default_backtest_output_path(
    start_date: date,
    end_date: date,
    *,
    lookback_window: int,
    deviation_threshold: float,
    variance_threshold: float,
    rebalance_period: int,
    take_profit_threshold: float,
    output_directory: Path = DEFAULT_BACKTEST_OUTPUT_DIRECTORY,
) -> Path:
    suffix = backtest_parameter_suffix(
        lookback_window=lookback_window,
        deviation_threshold=deviation_threshold,
        variance_threshold=variance_threshold,
        rebalance_period=rebalance_period,
        take_profit_threshold=take_profit_threshold,
    )
    return Path(output_directory) / (
        f"backtest_{start_date.isoformat()}_{end_date.isoformat()}{suffix}.xlsx"
    )


def _percentage_token(value: float) -> str:
    return _compact_number(Decimal(str(value)) * Decimal("100"))


def _compact_number(value: int | float | Decimal) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("filename parameter values must be finite")
    return format(number.normalize(), "f")
