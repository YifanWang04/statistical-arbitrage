from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Lock
from time import sleep
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from stat_arb_backtest import BacktestMarketData, BacktestTarget, TargetWeight
from stat_arb_grid_backtest import GridBacktestConfig, run_grid_backtest
from stat_arb_grid_backtest.application import (
    _ClusterCountCache,
    _TargetCache,
)
from stat_arb_clustering import SpongeSymConfig
from stat_arb_preprocessing import PreprocessingConfig


class GridParallelismTests(unittest.TestCase):
    def test_max_workers_runs_five_grid_combinations_concurrently(self) -> None:
        previous = date(2026, 1, 2)
        sessions = (
            date(2026, 1, 5),
            date(2026, 1, 6),
        )
        closes = pd.DataFrame(
            {
                "AAA": (100.0, 101.0, 102.0),
                "SPY": (100.0, 100.5, 101.0),
            },
            index=pd.Index((previous, *sessions), name="trade_date"),
        )
        market_data = BacktestMarketData(previous, sessions, closes)
        target = BacktestTarget(
            sessions[0],
            cluster_count=1,
            active_cluster_count=1,
            weights=(TargetWeight("AAA", 1.0),),
        )
        config = GridBacktestConfig(
            start_date=sessions[0],
            end_date=sessions[-1],
            lookback_windows=(5, 10, 20),
            deviation_thresholds=(0.0,),
            variance_thresholds=(0.90,),
            rebalance_periods=(2, 3),
            take_profit_thresholds=(1.0,),
        )
        guard = Lock()
        active = 0
        maximum_active = 0

        def delayed_simulation(*args, **kwargs):
            nonlocal active, maximum_active
            with guard:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                sleep(0.05)
                return SimpleNamespace()
            finally:
                with guard:
                    active -= 1

        with (
            patch(
                "stat_arb_grid_backtest.application.resolve_grid_date_range",
                return_value=(sessions[0], sessions[-1]),
            ),
            patch(
                "stat_arb_grid_backtest.application.BacktestMarketDataRepository",
                return_value=SimpleNamespace(load=lambda _: market_data),
            ),
            patch(
                "stat_arb_grid_backtest.application._TargetCache.get",
                side_effect=lambda as_of_date, *_: replace(
                    target,
                    as_of_date=as_of_date,
                ),
            ),
            patch(
                "stat_arb_grid_backtest.application.simulate_backtest",
                side_effect=delayed_simulation,
            ),
            patch(
                "stat_arb_grid_backtest.application.calculate_grid_run_metrics",
                return_value=SimpleNamespace(
                    sharpe_ratio=1.0,
                    annualized_return=0.1,
                    maximum_drawdown=-0.1,
                    overall_qc="OK",
                ),
            ),
        ):
            observed = run_grid_backtest(
                PreprocessingConfig(Path("unused.duckdb")),
                config,
                max_workers=5,
            )

        self.assertEqual(maximum_active, 5)
        self.assertEqual(
            [run.spec.run_id for run in observed.runs],
            [f"G{index:04d}" for index in range(1, 7)],
        )

    def test_target_cache_builds_a_shared_date_only_once(self) -> None:
        as_of_date = date(2026, 1, 5)
        preprocessing = PreprocessingConfig(Path("unused.duckdb"))
        snapshot = SimpleNamespace(stock_return_matrix="raw")
        cluster_count = SimpleNamespace(variance_threshold=0.90)

        def delayed_snapshot(*args, **kwargs):
            sleep(0.03)
            return snapshot

        with (
            patch(
                "stat_arb_grid_backtest.application.get_snapshot",
                side_effect=delayed_snapshot,
            ) as get_snapshot,
            patch(
                "stat_arb_grid_backtest.application.calculate_cluster_counts",
                return_value=(cluster_count,),
            ),
            patch(
                "stat_arb_grid_backtest.application.cluster_stocks_from_snapshot",
                return_value="cluster",
            ) as cluster,
            patch(
                "stat_arb_grid_backtest.application.identify_stocks_to_trade",
                return_value="selection",
            ),
            patch(
                "stat_arb_grid_backtest.application.assign_portfolio_weights",
                return_value="weights",
            ),
            patch(
                "stat_arb_grid_backtest.application.target_from_portfolio_weights",
                return_value="target",
            ),
        ):
            cluster_counts = _ClusterCountCache(
                preprocessing,
                20,
                (0.90,),
            )
            targets = _TargetCache(
                preprocessing,
                5,
                (0.05,),
                (0.90,),
                cluster_counts,
                SpongeSymConfig(),
            )
            with ThreadPoolExecutor(max_workers=5) as executor:
                observed = tuple(
                    executor.map(
                        lambda _: targets.get(as_of_date, 0.90, 0.05),
                        range(5),
                    )
                )

        self.assertEqual(observed, ("target",) * 5)
        self.assertEqual(get_snapshot.call_count, 2)
        self.assertEqual(cluster.call_count, 1)


if __name__ == "__main__":
    unittest.main()
