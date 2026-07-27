from __future__ import annotations

from datetime import date
import uuid

import numpy as np
import pandas as pd

from .config import PreprocessingConfig
from .models import PreprocessingSnapshot, SnapshotQuality


def build_snapshot_from_frames(
    *,
    preprocessing_run_id: str,
    return_basis: str,
    as_of_date: date,
    window_dates: tuple[date, ...],
    membership: pd.DataFrame,
    daily_residuals: pd.DataFrame,
    config: PreprocessingConfig,
) -> PreprocessingSnapshot:
    if len(window_dates) != config.correlation_window:
        raise ValueError(
            f"Expected {config.correlation_window} correlation dates, got {len(window_dates)}"
        )
    if membership.empty:
        raise ValueError(f"No universe membership exists for {as_of_date}")

    ordered_membership = membership.sort_values("market_cap_rank").reset_index(drop=True)
    expected_dates = pd.Index(pd.to_datetime(window_dates), name="trade_date")
    exclusions: list[dict[str, object]] = []
    valid_tickers: list[str] = []
    ranks: list[int] = []

    residuals = daily_residuals.copy()
    residuals["trade_date"] = pd.to_datetime(residuals["trade_date"])
    residuals["ticker"] = residuals["ticker"].astype(str)
    membership_tickers = tuple(
        str(value) for value in ordered_membership["ticker"]
    )
    membership_ranks = tuple(
        int(value) for value in ordered_membership["market_cap_rank"]
    )

    indexed = residuals.set_index(["trade_date", "ticker"]).sort_index()
    expected_index = pd.MultiIndex.from_product(
        (expected_dates, membership_tickers),
        names=("trade_date", "ticker"),
    )
    aligned = indexed.reindex(expected_index)
    wide_cache: dict[str, pd.DataFrame] = {}

    def wide(column: str) -> pd.DataFrame:
        if column not in wide_cache:
            wide_cache[column] = (
                aligned[column]
                .unstack("ticker")
                .reindex(index=expected_dates, columns=membership_tickers)
            )
        return wide_cache[column]

    residual_matrix_all = wide("market_residual_return")
    invalid_mask = (
        ~wide("is_valid").eq(True)
        | residual_matrix_all.isna()
    )
    incomplete = invalid_mask.any(axis=0)
    invalid_reasons = wide("exclusion_reason").where(invalid_mask)
    reason_values = invalid_reasons.to_numpy(dtype=object)
    reason_present = ~pd.isna(reason_values)
    has_reason = reason_present.any(axis=0)
    first_reason_rows = reason_present.argmax(axis=0)
    first_reason_values = np.full(len(membership_tickers), None, dtype=object)
    reason_columns = np.flatnonzero(has_reason)
    first_reason_values[reason_columns] = reason_values[
        first_reason_rows[reason_columns],
        reason_columns,
    ]
    first_invalid_reasons = dict(
        zip(membership_tickers, first_reason_values, strict=True)
    )

    complete_tickers = [
        ticker for ticker in membership_tickers if not bool(incomplete[ticker])
    ]
    zero_variance: dict[str, bool] = {}
    if complete_tickers:
        complete_values = (
            residual_matrix_all.loc[:, complete_tickers]
            .astype(float)
            .to_numpy()
        )
        standard_deviations = np.std(complete_values, axis=0, ddof=1)
        zero_variance = {
            ticker: bool(standard_deviation <= config.variance_epsilon)
            for ticker, standard_deviation in zip(
                complete_tickers,
                standard_deviations,
                strict=True,
            )
        }

    for ticker, rank in zip(
        membership_tickers,
        membership_ranks,
        strict=True,
    ):
        if bool(incomplete[ticker]):
            raw_reason = first_invalid_reasons[ticker]
            reason = (
                "missing_residual_row"
                if pd.isna(raw_reason)
                else str(raw_reason)
            )
            exclusions.append(
                {
                    "ticker": ticker,
                    "market_cap_rank": rank,
                    "reason": f"incomplete_residual_window:{reason}",
                }
            )
        elif zero_variance[ticker]:
            exclusions.append(
                {
                    "ticker": ticker,
                    "market_cap_rank": rank,
                    "reason": "zero_residual_variance",
                }
            )
        else:
            valid_tickers.append(ticker)
            ranks.append(rank)

    if len(valid_tickers) < 2:
        raise ValueError(
            f"At least 2 valid stocks are required for {as_of_date}; got {len(valid_tickers)}"
        )

    def matrix(column: str) -> pd.DataFrame:
        return wide(column).reindex(columns=valid_tickers).astype(float)

    beta_matrix = matrix("beta")
    stock_return_matrix = matrix("stock_return")
    residual_matrix = matrix("market_residual_return")
    market_frame = matrix("market_return")
    market_returns = market_frame.iloc[:, 0].rename("SPY")
    if not market_frame.eq(market_returns, axis=0).all().all():
        raise ValueError("Market returns are inconsistent across stocks")

    correlation_matrix = residual_matrix.corr()
    values = correlation_matrix.to_numpy(dtype=float)
    has_non_finite = not bool(np.isfinite(values).all())
    if has_non_finite:
        raise ValueError("Correlation matrix contains non-finite values")
    maximum_asymmetry = float(np.max(np.abs(values - values.T)))
    minimum_correlation = float(np.min(values))
    maximum_correlation = float(np.max(values))
    eigenvalues = np.linalg.eigvalsh((values + values.T) / 2.0)
    minimum_eigenvalue = float(np.min(eigenvalues))
    numerical_rank = int(np.linalg.matrix_rank(values, tol=1e-10))
    if maximum_asymmetry > 1e-12:
        raise ValueError(f"Correlation matrix is not symmetric: {maximum_asymmetry}")
    if minimum_correlation < -1.0 - 1e-12 or maximum_correlation > 1.0 + 1e-12:
        raise ValueError("Correlation matrix contains values outside [-1, 1]")
    if not np.allclose(np.diag(values), 1.0, atol=1e-12):
        raise ValueError("Correlation matrix diagonal is not one")
    if minimum_eigenvalue < -1e-10:
        raise ValueError(f"Correlation matrix is not positive semidefinite: {minimum_eigenvalue}")

    exclusions_frame = pd.DataFrame(
        exclusions,
        columns=("ticker", "market_cap_rank", "reason"),
    ).sort_values("market_cap_rank", ignore_index=True)
    quality = SnapshotQuality(
        maximum_asymmetry=maximum_asymmetry,
        minimum_correlation=minimum_correlation,
        maximum_correlation=maximum_correlation,
        minimum_eigenvalue=minimum_eigenvalue,
        numerical_rank=numerical_rank,
        has_non_finite_values=has_non_finite,
    )
    return PreprocessingSnapshot(
        snapshot_id=str(uuid.uuid4()),
        preprocessing_run_id=preprocessing_run_id,
        as_of_date=as_of_date,
        window_start=window_dates[0],
        window_end=window_dates[-1],
        beta_window=config.beta_window,
        correlation_window=config.correlation_window,
        beta_alignment=config.beta_alignment,
        missing_policy=config.missing_policy,
        calculation_version=config.calculation_version,
        variance_epsilon=config.variance_epsilon,
        return_basis=return_basis,
        tickers=tuple(valid_tickers),
        market_cap_ranks=tuple(ranks),
        beta_matrix=beta_matrix,
        stock_return_matrix=stock_return_matrix,
        market_returns=market_returns,
        residual_matrix=residual_matrix,
        correlation_matrix=correlation_matrix,
        exclusions=exclusions_frame,
        selected_stock_count=len(ordered_membership),
        quality=quality,
    )
