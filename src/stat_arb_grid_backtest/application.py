from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from itertools import product
from pathlib import Path
from threading import Lock, RLock

import duckdb
from threadpoolctl import threadpool_limits
from tqdm.auto import tqdm

from stat_arb_backtest import (
    BacktestConfig,
    BacktestTarget,
    required_prior_sessions_for_signals,
    simulate_backtest,
    target_from_portfolio_weights,
)
from stat_arb_backtest.repository import BacktestMarketDataRepository
from stat_arb_cluster_count import (
    DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW,
    ClusterCountResult,
    calculate_cluster_counts,
)
from stat_arb_clustering import SpongeSymConfig, cluster_stocks_from_snapshot
from stat_arb_portfolio_weights import assign_portfolio_weights
from stat_arb_preprocessing import (
    PreprocessingConfig,
    PreprocessingSnapshot,
    get_snapshot,
)
from stat_arb_stock_selection import (
    StockSelectionConfig,
    identify_stocks_to_trade,
)

from .metrics import calculate_grid_run_metrics
from .models import (
    GridBacktestConfig,
    GridBacktestResult,
    GridRunResult,
    GridRunSpec,
)

DEFAULT_MAX_WORKERS = 5


class _ClusterCountCache:
    def __init__(
        self,
        preprocessing_config: PreprocessingConfig,
        estimation_window: int,
        variance_thresholds: tuple[float, ...],
    ) -> None:
        self.estimation_config = replace(
            preprocessing_config,
            correlation_window=estimation_window,
        )
        self.variance_thresholds = variance_thresholds
        self._values: dict[date, dict[float, ClusterCountResult]] = {}
        self._errors: dict[date, Exception] = {}
        self._lock = RLock()
        self._date_locks: dict[date, Lock] = {}

    def get(self, as_of_date: date) -> dict[float, ClusterCountResult]:
        values, _ = self._get_or_build(as_of_date, include_snapshot=False)
        return values

    def get_with_snapshot(
        self,
        as_of_date: date,
    ) -> tuple[
        dict[float, ClusterCountResult],
        PreprocessingSnapshot,
    ]:
        values, snapshot = self._get_or_build(
            as_of_date,
            include_snapshot=True,
        )
        if snapshot is None:
            raise RuntimeError("cluster-count snapshot was not returned")
        return values, snapshot

    def _get_or_build(
        self,
        as_of_date: date,
        *,
        include_snapshot: bool,
    ) -> tuple[
        dict[float, ClusterCountResult],
        PreprocessingSnapshot | None,
    ]:
        date_lock = self._date_lock(as_of_date)
        with date_lock:
            with self._lock:
                if as_of_date in self._errors:
                    raise self._errors[as_of_date]
                cached = self._values.get(as_of_date)

            snapshot: PreprocessingSnapshot | None = None
            if cached is None or include_snapshot:
                try:
                    snapshot = get_snapshot(
                        self.estimation_config,
                        as_of_date,
                        cache=False,
                        read_only=True,
                    )
                    if cached is None:
                        results = calculate_cluster_counts(
                            snapshot,
                            self.variance_thresholds,
                        )
                        cached = {
                            result.variance_threshold: result
                            for result in results
                        }
                except Exception as exc:
                    if cached is None:
                        with self._lock:
                            self._errors[as_of_date] = exc
                    raise

            if cached is None:
                raise RuntimeError("cluster-count cache did not produce a value")

            with self._lock:
                self._values.setdefault(as_of_date, cached)
                return self._values[as_of_date], snapshot

    def _date_lock(self, as_of_date: date) -> Lock:
        with self._lock:
            return self._date_locks.setdefault(as_of_date, Lock())


class _TargetCache:
    def __init__(
        self,
        preprocessing_config: PreprocessingConfig,
        lookback_window: int,
        deviation_thresholds: tuple[float, ...],
        variance_thresholds: tuple[float, ...],
        cluster_counts: _ClusterCountCache,
        sponge_config: SpongeSymConfig,
    ) -> None:
        self.preprocessing_config = replace(
            preprocessing_config,
            correlation_window=lookback_window,
        )
        self.lookback_window = lookback_window
        self.deviation_thresholds = deviation_thresholds
        self.variance_thresholds = variance_thresholds
        self.cluster_counts = cluster_counts
        self.sponge_config = sponge_config
        self._built_dates: set[date] = set()
        self._targets: dict[
            tuple[date, float, float],
            BacktestTarget,
        ] = {}
        self._errors: dict[tuple[date, float, float], Exception] = {}
        self._lock = RLock()
        self._date_locks: dict[date, Lock] = {}

    def get(
        self,
        as_of_date: date,
        variance_threshold: float,
        deviation_threshold: float,
    ) -> BacktestTarget:
        self._ensure_date(as_of_date)
        key = (as_of_date, variance_threshold, deviation_threshold)
        with self._lock:
            if key in self._errors:
                raise self._errors[key]
            return self._targets[key]

    def _ensure_date(self, as_of_date: date) -> None:
        with self._lock:
            if as_of_date in self._built_dates:
                return
            date_lock = self._date_locks.setdefault(as_of_date, Lock())

        with date_lock:
            with self._lock:
                if as_of_date in self._built_dates:
                    return

            targets: dict[tuple[date, float, float], BacktestTarget] = {}
            errors: dict[tuple[date, float, float], Exception] = {}
            try:
                if (
                    self.lookback_window
                    == self.cluster_counts.estimation_config.correlation_window
                ):
                    cluster_counts, snapshot = (
                        self.cluster_counts.get_with_snapshot(as_of_date)
                    )
                else:
                    cluster_counts = self.cluster_counts.get(as_of_date)
                    snapshot = get_snapshot(
                        self.preprocessing_config,
                        as_of_date,
                        cache=False,
                        read_only=True,
                    )
            except Exception as exc:
                errors.update(self._errors_for_all(as_of_date, exc))
            else:
                for variance_threshold in self.variance_thresholds:
                    try:
                        clustering = cluster_stocks_from_snapshot(
                            snapshot,
                            cluster_counts[variance_threshold],
                            sponge_config=self.sponge_config,
                        )
                    except Exception as exc:
                        for deviation_threshold in self.deviation_thresholds:
                            errors[
                                (
                                    as_of_date,
                                    variance_threshold,
                                    deviation_threshold,
                                )
                            ] = exc
                        continue

                    for deviation_threshold in self.deviation_thresholds:
                        key = (
                            as_of_date,
                            variance_threshold,
                            deviation_threshold,
                        )
                        try:
                            selection = identify_stocks_to_trade(
                                clustering,
                                snapshot.stock_return_matrix,
                                StockSelectionConfig(
                                    lookback_window=self.lookback_window,
                                    deviation_threshold=deviation_threshold,
                                ),
                            )
                            weights = assign_portfolio_weights(selection)
                            targets[key] = target_from_portfolio_weights(weights)
                        except Exception as exc:
                            errors[key] = exc

            with self._lock:
                self._targets.update(targets)
                self._errors.update(errors)
                self._built_dates.add(as_of_date)

    def _errors_for_all(
        self,
        as_of_date: date,
        error: Exception,
    ) -> dict[tuple[date, float, float], Exception]:
        errors: dict[tuple[date, float, float], Exception] = {}
        for variance_threshold in self.variance_thresholds:
            for deviation_threshold in self.deviation_thresholds:
                errors[
                    (
                        as_of_date,
                        variance_threshold,
                        deviation_threshold,
                    )
                ] = error
        return errors


def build_grid_run_specs(
    config: GridBacktestConfig,
) -> tuple[GridRunSpec, ...]:
    parameter_sets = product(
        config.lookback_windows,
        config.deviation_thresholds,
        config.variance_thresholds,
        config.rebalance_periods,
        config.take_profit_thresholds,
    )
    return tuple(
        GridRunSpec(
            run_id=f"G{index:04d}",
            lookback_window=lookback_window,
            deviation_threshold=deviation_threshold,
            variance_threshold=variance_threshold,
            rebalance_period=rebalance_period,
            take_profit_threshold=take_profit_threshold,
        )
        for index, (
            lookback_window,
            deviation_threshold,
            variance_threshold,
            rebalance_period,
            take_profit_threshold,
        ) in enumerate(parameter_sets, start=1)
    )


def resolve_grid_date_range(
    database_path: Path,
    config: GridBacktestConfig,
) -> tuple[date, date]:
    latest_session = _latest_spy_session(database_path)
    if config.end_date > latest_session:
        raise ValueError(
            f"end_date exceeds latest SPY session {latest_session}"
        )
    return config.start_date, config.end_date


def run_grid_backtest(
    preprocessing_config: PreprocessingConfig,
    grid_config: GridBacktestConfig,
    *,
    cluster_count_estimation_window: int = (
        DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
    ),
    sponge_config: SpongeSymConfig | None = None,
    show_progress: bool = False,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> GridBacktestResult:
    _validate_max_workers(max_workers)
    with threadpool_limits(limits=1):
        return _run_grid_backtest(
            preprocessing_config,
            grid_config,
            cluster_count_estimation_window=(
                cluster_count_estimation_window
            ),
            sponge_config=sponge_config,
            show_progress=show_progress,
            max_workers=max_workers,
        )


def _run_grid_backtest(
    preprocessing_config: PreprocessingConfig,
    grid_config: GridBacktestConfig,
    *,
    cluster_count_estimation_window: int,
    sponge_config: SpongeSymConfig | None,
    show_progress: bool,
    max_workers: int,
) -> GridBacktestResult:
    configured_grid = grid_config
    requested_start, requested_end = resolve_grid_date_range(
        preprocessing_config.database_path,
        configured_grid,
    )
    market_request = BacktestConfig(
        start_date=requested_start,
        end_date=requested_end,
        initial_nav=configured_grid.initial_nav,
        annualization_sessions=configured_grid.annualization_sessions,
    )
    market_data = BacktestMarketDataRepository(
        preprocessing_config.database_path
    ).load(
        market_request,
        minimum_prior_sessions=required_prior_sessions_for_signals(
            preprocessing_config,
            cluster_count_estimation_window,
            correlation_window=max(configured_grid.lookback_windows),
        ),
    )
    effective_start = market_data.sessions[0]
    effective_end = market_data.sessions[-1]
    configured_sponge = sponge_config or SpongeSymConfig()
    specs = build_grid_run_specs(configured_grid)
    cluster_counts = _ClusterCountCache(
        preprocessing_config,
        cluster_count_estimation_window,
        configured_grid.variance_thresholds,
    )
    runs_by_id: dict[str, GridRunResult] = {}
    progress = tqdm(
        total=len(specs),
        desc="Grid backtest",
        unit="run",
        dynamic_ncols=True,
        disable=not show_progress,
    )
    execution_order = sorted(
        configured_grid.lookback_windows,
        key=lambda lookback_window: (
            lookback_window != cluster_count_estimation_window,
            lookback_window,
        ),
    )
    targets_by_lookback = {
        lookback_window: _TargetCache(
            preprocessing_config,
            lookback_window,
            configured_grid.deviation_thresholds,
            configured_grid.variance_thresholds,
            cluster_counts,
            configured_sponge,
        )
        for lookback_window in configured_grid.lookback_windows
    }

    def run_spec(spec: GridRunSpec) -> GridRunResult:
        targets = targets_by_lookback[spec.lookback_window]
        try:
            backtest_config = BacktestConfig(
                start_date=effective_start,
                end_date=effective_end,
                rebalance_period=spec.rebalance_period,
                take_profit_threshold=spec.take_profit_threshold,
                initial_nav=configured_grid.initial_nav,
                annualization_sessions=(
                    configured_grid.annualization_sessions
                ),
            )
            result = simulate_backtest(
                market_data,
                backtest_config,
                lambda as_of_date: targets.get(
                    as_of_date,
                    spec.variance_threshold,
                    spec.deviation_threshold,
                ),
                show_progress=False,
            )
            return GridRunResult(
                spec=spec,
                status="SUCCESS",
                metrics=calculate_grid_run_metrics(result),
            )
        except Exception as exc:
            return GridRunResult(
                spec=spec,
                status="FAILED",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    execution_specs = _interleave_specs_by_lookback(
        specs,
        execution_order,
    )
    effective_workers = min(max_workers, len(execution_specs))
    try:
        with ThreadPoolExecutor(
            max_workers=effective_workers,
            thread_name_prefix="grid-run",
        ) as executor:
            futures = {
                executor.submit(run_spec, spec): spec
                for spec in execution_specs
            }
            for future in as_completed(futures):
                run = future.result()
                runs_by_id[run.spec.run_id] = run
                progress.update(1)
    finally:
        progress.close()
    runs = tuple(runs_by_id[spec.run_id] for spec in specs)
    ranked_runs = _rank_runs(runs)
    best_run_id = next(
        (
            run.spec.run_id
            for run in ranked_runs
            if run.rank == 1
        ),
        None,
    )
    overall_qc = (
        "OK"
        if all(
            run.status == "SUCCESS"
            and run.metrics is not None
            and run.metrics.overall_qc == "OK"
            for run in ranked_runs
        )
        else "CHECK"
    )
    return GridBacktestResult(
        config=configured_grid,
        requested_start_date=requested_start,
        requested_end_date=requested_end,
        effective_start_date=effective_start,
        effective_end_date=effective_end,
        beta_window=preprocessing_config.beta_window,
        cluster_count_estimation_window=cluster_count_estimation_window,
        sponge_config=configured_sponge,
        runs=ranked_runs,
        best_run_id=best_run_id,
        overall_qc=overall_qc,
    )


def export_grid_backtest_report(
    preprocessing_config: PreprocessingConfig,
    grid_config: GridBacktestConfig,
    output_path: Path,
    *,
    cluster_count_estimation_window: int = (
        DEFAULT_CLUSTER_COUNT_ESTIMATION_WINDOW
    ),
    sponge_config: SpongeSymConfig | None = None,
    replace_existing: bool = False,
    show_progress: bool = False,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> tuple[GridBacktestResult, Path]:
    from .excel import export_grid_backtest_workbook

    result = run_grid_backtest(
        preprocessing_config,
        grid_config,
        cluster_count_estimation_window=cluster_count_estimation_window,
        sponge_config=sponge_config,
        show_progress=show_progress,
        max_workers=max_workers,
    )
    output = export_grid_backtest_workbook(
        result,
        output_path,
        replace_existing=replace_existing,
    )
    return result, output


def _rank_runs(
    runs: tuple[GridRunResult, ...],
) -> tuple[GridRunResult, ...]:
    rankable = [
        run
        for run in runs
        if run.status == "SUCCESS"
        and run.metrics is not None
        and run.metrics.sharpe_ratio is not None
    ]
    rankable.sort(
        key=lambda run: (
            -float(run.metrics.sharpe_ratio),
            -_descending_optional(run.metrics.annualized_return),
            abs(run.metrics.maximum_drawdown),
            run.spec.run_id,
        )
    )
    ranks = {
        run.spec.run_id: rank
        for rank, run in enumerate(rankable, start=1)
    }
    return tuple(
        replace(run, rank=ranks.get(run.spec.run_id))
        for run in runs
    )


def _descending_optional(value: float | None) -> float:
    return float(value) if value is not None else float("-inf")


def _interleave_specs_by_lookback(
    specs: tuple[GridRunSpec, ...],
    lookback_order: list[int],
) -> tuple[GridRunSpec, ...]:
    pending = {
        lookback: [
            spec for spec in specs if spec.lookback_window == lookback
        ]
        for lookback in lookback_order
    }
    interleaved: list[GridRunSpec] = []
    while any(pending.values()):
        for lookback in lookback_order:
            if pending[lookback]:
                interleaved.append(pending[lookback].pop(0))
    return tuple(interleaved)


def _validate_max_workers(max_workers: int) -> None:
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or max_workers < 1
    ):
        raise ValueError("max_workers must be a positive integer")


def _latest_spy_session(database_path: Path) -> date:
    resolved = Path(database_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Database does not exist: {resolved}")
    with duckdb.connect(str(resolved), read_only=True) as connection:
        row = connection.execute(
            """
            SELECT MAX(trade_date)
            FROM market_data.market_returns
            WHERE ticker = 'SPY'
            """
        ).fetchone()
    if row is None or row[0] is None:
        raise ValueError("database contains no SPY trading sessions")
    return row[0]
