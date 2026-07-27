from __future__ import annotations

import numpy as np

from stat_arb_stock_selection import (
    NEUTRAL,
    PREVIOUS_LOSER,
    PREVIOUS_WINNER,
    StockSelectionResult,
)

from .models import (
    ClusterAllocation,
    PortfolioWeightQuality,
    PortfolioWeightResult,
)


CALCULATION_VERSION = "long_only_equal_cluster_gross_weight_v2"


def assign_portfolio_weights(
    selection_result: StockSelectionResult,
) -> PortfolioWeightResult:
    labels, classifications = _validated_inputs(selection_result)
    cluster_count = selection_result.clustering_result.requested_cluster_count
    target_cluster_gross = 1.0 / cluster_count
    portfolio_scale = 1.0 / cluster_count

    local_weights = np.zeros(selection_result.stock_count, dtype=float)
    allocations: list[ClusterAllocation] = []

    for cluster_id in range(cluster_count):
        cluster_mask = labels == cluster_id
        winner_mask = cluster_mask & (classifications == PREVIOUS_WINNER)
        loser_mask = cluster_mask & (classifications == PREVIOUS_LOSER)
        neutral_mask = cluster_mask & (classifications == NEUTRAL)
        winner_count = int(winner_mask.sum())
        loser_count = int(loser_mask.sum())
        neutral_count = int(neutral_mask.sum())
        is_active = loser_count > 0

        if is_active:
            local_weights[loser_mask] = 1.0 / loser_count

        cluster_local = local_weights[cluster_mask]
        cluster_portfolio = cluster_local * portfolio_scale
        allocations.append(
            ClusterAllocation(
                cluster_id=cluster_id,
                stock_count=int(cluster_mask.sum()),
                winner_count=winner_count,
                loser_count=loser_count,
                neutral_count=neutral_count,
                is_active=is_active,
                target_gross_exposure=target_cluster_gross,
                local_long_exposure=float(cluster_local[cluster_local > 0].sum()),
                local_short_exposure=float(
                    cluster_local[cluster_local < 0].sum()
                ),
                local_net_exposure=float(cluster_local.sum()),
                local_gross_exposure=float(np.abs(cluster_local).sum()),
                portfolio_long_exposure=float(
                    cluster_portfolio[cluster_portfolio > 0].sum()
                ),
                portfolio_short_exposure=float(
                    cluster_portfolio[cluster_portfolio < 0].sum()
                ),
                portfolio_net_exposure=float(cluster_portfolio.sum()),
                portfolio_gross_exposure=float(
                    np.abs(cluster_portfolio).sum()
                ),
                uninvested_gross_exposure=(
                    0.0 if is_active else target_cluster_gross
                ),
            )
        )

    portfolio_weights = local_weights * portfolio_scale
    active_allocations = tuple(
        allocation for allocation in allocations if allocation.is_active
    )
    active_count = len(active_allocations)
    expected_invested_gross = active_count / cluster_count
    gross_exposure = float(np.abs(portfolio_weights).sum())
    quality = PortfolioWeightQuality(
        active_cluster_count=active_count,
        inactive_cluster_count=cluster_count - active_count,
        long_exposure=float(portfolio_weights[portfolio_weights > 0].sum()),
        short_exposure=float(portfolio_weights[portfolio_weights < 0].sum()),
        net_exposure=float(portfolio_weights.sum()),
        gross_exposure=gross_exposure,
        uninvested_gross_exposure=1.0 - expected_invested_gross,
        maximum_active_cluster_local_net_error=max(
            (
                abs(allocation.local_net_exposure - 1.0)
                for allocation in active_allocations
            ),
            default=0.0,
        ),
        maximum_active_cluster_local_gross_error=max(
            (
                abs(allocation.local_gross_exposure - 1.0)
                for allocation in active_allocations
            ),
            default=0.0,
        ),
        maximum_cluster_portfolio_gross_error=max(
            (
                abs(
                    allocation.portfolio_gross_exposure
                    - (
                        allocation.target_gross_exposure
                        if allocation.is_active
                        else 0.0
                    )
                )
                for allocation in allocations
            ),
            default=0.0,
        ),
        all_weights_finite=bool(
            np.isfinite(local_weights).all()
            and np.isfinite(portfolio_weights).all()
        ),
    )
    return PortfolioWeightResult(
        stock_selection_result=selection_result,
        local_weights=tuple(map(float, local_weights)),
        portfolio_weights=tuple(map(float, portfolio_weights)),
        cluster_allocations=tuple(allocations),
        calculation_version=CALCULATION_VERSION,
        quality=quality,
    )


def _validated_inputs(
    selection_result: StockSelectionResult,
) -> tuple[np.ndarray, np.ndarray]:
    clustering = selection_result.clustering_result
    stock_count = selection_result.stock_count
    cluster_count = clustering.requested_cluster_count
    if cluster_count < 1:
        raise ValueError("requested cluster count must be positive")
    if len(set(selection_result.tickers)) != stock_count:
        raise ValueError("stock-selection tickers must be unique")
    if len(clustering.cluster_labels) != stock_count:
        raise ValueError("cluster labels do not match stock-selection tickers")
    if len(clustering.market_cap_ranks) != stock_count:
        raise ValueError("market-cap ranks do not match stock-selection tickers")
    if len(selection_result.cumulative_deviations) != stock_count:
        raise ValueError(
            "cumulative deviations do not match stock-selection tickers"
        )
    if len(selection_result.classifications) != stock_count:
        raise ValueError("classifications do not match stock-selection tickers")

    labels = np.asarray(clustering.cluster_labels)
    if (
        not np.issubdtype(labels.dtype, np.integer)
        or not np.array_equal(np.unique(labels), np.arange(cluster_count))
    ):
        raise ValueError(
            "cluster labels must contain every 0-based cluster exactly as assigned"
        )
    labels = labels.astype(int)
    observed_sizes = tuple(
        map(int, np.bincount(labels, minlength=cluster_count))
    )
    if observed_sizes != clustering.cluster_sizes:
        raise ValueError("cluster sizes do not reconcile with cluster labels")

    classifications = np.asarray(
        selection_result.classifications,
        dtype=object,
    )
    allowed = {PREVIOUS_WINNER, PREVIOUS_LOSER, NEUTRAL}
    invalid = sorted(set(map(str, classifications)) - allowed)
    if invalid:
        raise ValueError(f"unsupported stock classifications: {invalid}")
    deviations = np.asarray(
        selection_result.cumulative_deviations,
        dtype=float,
    )
    if not bool(np.isfinite(deviations).all()):
        raise ValueError("cumulative deviations contain non-finite values")
    return labels, classifications
