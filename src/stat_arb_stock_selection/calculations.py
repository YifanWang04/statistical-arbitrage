from __future__ import annotations

import numpy as np
import pandas as pd

from stat_arb_clustering import SpongeSymResult

from .models import (
    NEUTRAL,
    PREVIOUS_LOSER,
    PREVIOUS_WINNER,
    StockSelectionConfig,
    StockSelectionQuality,
    StockSelectionResult,
)


CALCULATION_VERSION = "raw_return_cluster_deviation_v1"


def identify_stocks_to_trade(
    clustering_result: SpongeSymResult,
    raw_return_matrix: pd.DataFrame,
    config: StockSelectionConfig | None = None,
) -> StockSelectionResult:
    selection_config = config or StockSelectionConfig()
    returns = _validated_returns(
        clustering_result,
        raw_return_matrix,
        selection_config,
    )
    labels = np.asarray(clustering_result.cluster_labels, dtype=int)
    cluster_ids = tuple(range(clustering_result.requested_cluster_count))

    cluster_means = pd.DataFrame(
        {
            cluster_id: returns.iloc[:, labels == cluster_id].mean(axis=1)
            for cluster_id in cluster_ids
        },
        index=returns.index,
    )
    cluster_means.columns.name = "cluster_id"

    daily_deviations = returns.copy()
    for column_index, cluster_id in enumerate(labels):
        daily_deviations.iloc[:, column_index] = (
            returns.iloc[:, column_index] - cluster_means.loc[:, cluster_id]
        )

    cumulative = daily_deviations.sum(axis=0).to_numpy(dtype=float)
    threshold = selection_config.deviation_threshold
    classifications = tuple(
        PREVIOUS_WINNER
        if value > threshold
        else PREVIOUS_LOSER
        if value < -threshold
        else NEUTRAL
        for value in cumulative
    )

    daily_cluster_errors = [
        abs(float(daily_deviations.iloc[row_index, labels == cluster_id].sum()))
        for row_index in range(len(daily_deviations))
        for cluster_id in cluster_ids
    ]
    cumulative_cluster_errors = [
        abs(float(cumulative[labels == cluster_id].sum()))
        for cluster_id in cluster_ids
    ]
    quality = StockSelectionQuality(
        winner_count=classifications.count(PREVIOUS_WINNER),
        loser_count=classifications.count(PREVIOUS_LOSER),
        neutral_count=classifications.count(NEUTRAL),
        maximum_daily_cluster_sum_error=max(daily_cluster_errors, default=0.0),
        maximum_cumulative_cluster_sum_error=max(
            cumulative_cluster_errors,
            default=0.0,
        ),
        all_inputs_finite=True,
    )
    return StockSelectionResult(
        clustering_result=clustering_result,
        window_start=returns.index[0].date(),
        window_end=returns.index[-1].date(),
        raw_return_matrix=returns,
        cluster_mean_return_matrix=cluster_means,
        daily_deviation_matrix=daily_deviations,
        cumulative_deviations=tuple(map(float, cumulative)),
        classifications=classifications,
        config=selection_config,
        calculation_version=CALCULATION_VERSION,
        quality=quality,
    )


def _validated_returns(
    clustering_result: SpongeSymResult,
    raw_return_matrix: pd.DataFrame,
    config: StockSelectionConfig,
) -> pd.DataFrame:
    tickers = clustering_result.tickers
    if len(set(tickers)) != len(tickers):
        raise ValueError("clustering tickers must be unique")
    if len(clustering_result.cluster_labels) != len(tickers):
        raise ValueError("cluster labels do not match clustering tickers")
    if len(clustering_result.market_cap_ranks) != len(tickers):
        raise ValueError("market-cap ranks do not match clustering tickers")
    if clustering_result.clustering_correlation_window != config.lookback_window:
        raise ValueError(
            "paper baseline requires the stock-selection lookback to equal "
            "the clustering correlation window"
        )
    if raw_return_matrix.shape != (config.lookback_window, len(tickers)):
        raise ValueError(
            "raw return matrix shape does not match the configured lookback "
            f"and stock count: got {raw_return_matrix.shape}, expected "
            f"({config.lookback_window}, {len(tickers)})"
        )
    if tuple(map(str, raw_return_matrix.columns)) != tickers:
        raise ValueError("raw return columns must exactly match clustering tickers")

    returns = raw_return_matrix.copy()
    try:
        returns.index = pd.DatetimeIndex(returns.index, name="trade_date")
    except (TypeError, ValueError) as exc:
        raise ValueError("raw return index must contain valid trade dates") from exc
    if returns.index.has_duplicates or not returns.index.is_monotonic_increasing:
        raise ValueError("raw return dates must be unique and increasing")
    if (
        returns.index[0].date() != clustering_result.clustering_window_start
        or returns.index[-1].date() != clustering_result.clustering_window_end
    ):
        raise ValueError(
            "raw return dates must match the clustering lookback window"
        )
    try:
        returns = returns.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("raw returns must be numeric") from exc
    values = returns.to_numpy(dtype=float)
    if not bool(np.isfinite(values).all()):
        raise ValueError("raw return matrix contains non-finite values")

    labels = np.asarray(clustering_result.cluster_labels)
    expected_labels = np.arange(clustering_result.requested_cluster_count)
    if (
        not np.issubdtype(labels.dtype, np.integer)
        or not np.array_equal(np.unique(labels), expected_labels)
    ):
        raise ValueError(
            "cluster labels must contain every 0-based cluster exactly as assigned"
        )
    observed_sizes = tuple(
        map(
            int,
            np.bincount(
                labels.astype(int),
                minlength=clustering_result.requested_cluster_count,
            ),
        )
    )
    if observed_sizes != clustering_result.cluster_sizes:
        raise ValueError("cluster sizes do not reconcile with cluster labels")
    return returns
