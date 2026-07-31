from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    DEFAULT_VARIANCE_THRESHOLD,
)
from stat_arb_clustering import SpongeSymConfig
from stat_arb_portfolio_weights import (
    PortfolioWeightResult,
    assign_weights_for_date,
)
from stat_arb_preprocessing import PreprocessingConfig
from stat_arb_stock_selection import StockSelectionConfig

from .calculations import simulate_backtest
from .models import (
    BacktestConfig,
    BacktestResearchAudit,
    BacktestResult,
    BacktestTarget,
    TargetWeight,
)
from .repository import BacktestMarketDataRepository


DEFAULT_PROJECT_DEVIATION_THRESHOLD = 0.05


def required_prior_sessions_for_signals(
    preprocessing_config: PreprocessingConfig,
    cluster_count_estimation_window: int,
    *,
    correlation_window: int | None = None,
) -> int:
    signal_window = max(
        (
            preprocessing_config.correlation_window
            if correlation_window is None
            else correlation_window
        ),
        cluster_count_estimation_window,
    )
    # The first Close establishes the price scale but cannot produce a
    # close-to-close return, so it does not count toward the beta window.
    return preprocessing_config.beta_window + signal_window


def run_backtest(
    preprocessing_config: PreprocessingConfig,
    backtest_config: BacktestConfig,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    sponge_config: SpongeSymConfig | None = None,
    selection_config: StockSelectionConfig | None = None,
    show_progress: bool = False,
) -> BacktestResult:
    configured_selection = selection_config or StockSelectionConfig(
        lookback_window=preprocessing_config.correlation_window,
        deviation_threshold=DEFAULT_PROJECT_DEVIATION_THRESHOLD,
    )
    configured_sponge = sponge_config or SpongeSymConfig()
    repository = BacktestMarketDataRepository(preprocessing_config.database_path)
    market_data = repository.load(
        backtest_config,
        minimum_prior_sessions=required_prior_sessions_for_signals(
            preprocessing_config,
            cluster_count_estimation_window,
        ),
    )
    effective_backtest_config = replace(
        backtest_config,
        start_date=market_data.sessions[0],
    )
    research_audit: BacktestResearchAudit | None = None

    def provide_target(as_of_date: date) -> BacktestTarget:
        nonlocal research_audit
        result = assign_weights_for_date(
            preprocessing_config,
            as_of_date,
            cluster_count_estimation_window=cluster_count_estimation_window,
            variance_threshold=variance_threshold,
            sponge_config=configured_sponge,
            selection_config=configured_selection,
        )
        current_audit = research_audit_from_portfolio_weights(result)
        if research_audit is None:
            research_audit = current_audit
        elif research_audit != current_audit:
            raise RuntimeError(
                "signal configuration or source run changed within one backtest"
            )
        return target_from_portfolio_weights(result)

    simulated = simulate_backtest(
        market_data,
        effective_backtest_config,
        provide_target,
        show_progress=show_progress,
    )
    if research_audit is None:
        raise RuntimeError("backtest produced no signal audit metadata")
    data_pipeline_run_id = repository.find_data_pipeline_run_id(
        research_audit.preprocessing_run_id
    )
    return replace(
        simulated,
        research_audit=replace(
            research_audit,
            data_pipeline_run_id=data_pipeline_run_id,
        ),
    )


def research_audit_from_portfolio_weights(
    result: PortfolioWeightResult,
) -> BacktestResearchAudit:
    selection = result.stock_selection_result
    clustering = selection.clustering_result
    cluster_count = clustering.cluster_count_result
    if cluster_count is None:
        raise RuntimeError("portfolio weights are missing cluster-count audit data")
    sponge = clustering.config
    return BacktestResearchAudit(
        cluster_count_estimation_window=(
            cluster_count.cluster_count_estimation_window
        ),
        variance_threshold=cluster_count.variance_threshold,
        selection_lookback_window=selection.config.lookback_window,
        deviation_threshold=selection.config.deviation_threshold,
        tau_positive=sponge.tau_positive,
        tau_negative=sponge.tau_negative,
        embedding_mode=sponge.embedding_mode,
        random_seed=sponge.random_seed,
        kmeans_n_init=sponge.kmeans_n_init,
        kmeans_max_iter=sponge.kmeans_max_iter,
        preprocessing_run_id=clustering.preprocessing_run_id,
        data_pipeline_run_id=None,
        preprocessing_calculation_version=(
            clustering.source_calculation_version
        ),
        cluster_count_calculation_version=cluster_count.calculation_version,
        clustering_calculation_version=clustering.calculation_version,
        stock_selection_calculation_version=selection.calculation_version,
        portfolio_weight_calculation_version=result.calculation_version,
    )


def target_from_portfolio_weights(
    result: PortfolioWeightResult,
) -> BacktestTarget:
    selection = result.stock_selection_result
    clustering = selection.clustering_result
    weights = tuple(
        TargetWeight(
            ticker=ticker,
            portfolio_weight=result.portfolio_weights[index],
            market_cap_rank=clustering.market_cap_ranks[index],
            cluster_id=clustering.cluster_labels[index],
            cumulative_deviation=selection.cumulative_deviations[index],
            classification=selection.classifications[index],
            local_weight=result.local_weights[index],
        )
        for index, ticker in enumerate(result.tickers)
        if result.portfolio_weights[index] > 0.0
    )
    return BacktestTarget(
        as_of_date=result.as_of_date,
        cluster_count=result.cluster_count,
        active_cluster_count=result.quality.active_cluster_count,
        inactive_cluster_count=result.quality.inactive_cluster_count,
        weights=weights,
        calculation_version=(
            f"{clustering.source_calculation_version}|"
            f"{clustering.calculation_version}|"
            f"{selection.calculation_version}|"
            f"{result.calculation_version}"
        ),
    )


def export_backtest_report(
    preprocessing_config: PreprocessingConfig,
    backtest_config: BacktestConfig,
    output_path: Path,
    *,
    cluster_count_estimation_window: int = DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    variance_threshold: float = DEFAULT_VARIANCE_THRESHOLD,
    sponge_config: SpongeSymConfig | None = None,
    selection_config: StockSelectionConfig | None = None,
    replace_existing: bool = False,
    show_progress: bool = False,
) -> tuple[BacktestResult, Path]:
    from .excel import export_backtest_workbook

    result = run_backtest(
        preprocessing_config,
        backtest_config,
        cluster_count_estimation_window=cluster_count_estimation_window,
        variance_threshold=variance_threshold,
        sponge_config=sponge_config,
        selection_config=selection_config,
        show_progress=show_progress,
    )
    output = export_backtest_workbook(
        result,
        output_path,
        replace_existing=replace_existing,
    )
    return result, output
