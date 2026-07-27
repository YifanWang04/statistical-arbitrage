from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import pandas as pd
from openpyxl import load_workbook

from stat_arb_backtest import (
    BacktestConfig,
    BacktestMarketData,
    BacktestTarget,
    TargetWeight,
    calculate_performance_metrics,
    export_backtest_workbook,
    run_backtest,
    simulate_backtest,
)
from stat_arb_backtest.cli import build_parser
from stat_arb_preprocessing import PreprocessingConfig, build_preprocessing
from tests.test_preprocessing import build_test_database


class BacktestCalculationTests(unittest.TestCase):
    def test_progress_bar_wraps_backtest_sessions_when_enabled(self) -> None:
        previous = date(2026, 1, 2)
        start = date(2026, 1, 5)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 101.0],
                "SPY": [100.0, 101.0],
            },
            index=pd.Index([previous, start], name="trade_date"),
        )
        target = BacktestTarget(
            start,
            1,
            1,
            (TargetWeight("AAA", 1.0),),
        )

        with patch(
            "stat_arb_backtest.calculations.tqdm",
            side_effect=lambda iterable, **_: iterable,
        ) as progress:
            simulate_backtest(
                BacktestMarketData(previous, (start,), closes),
                BacktestConfig(start, start),
                lambda _: target,
                show_progress=True,
            )

        progress.assert_called_once()
        self.assertEqual(progress.call_args.kwargs["desc"], "Backtest")
        self.assertEqual(progress.call_args.kwargs["unit"], "session")
        self.assertFalse(progress.call_args.kwargs["disable"])

    def test_fixed_positions_drift_between_rebalances(self) -> None:
        previous = date(2026, 1, 2)
        start = date(2026, 1, 5)
        end = date(2026, 1, 6)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 110.0, 121.0],
                "BBB": [100.0, 100.0, 100.0],
                "SPY": [100.0, 101.0, 102.0],
            },
            index=pd.Index([previous, start, end], name="trade_date"),
        )
        market_data = BacktestMarketData(
            previous_session=previous,
            sessions=(start, end),
            closes=closes,
        )
        target = BacktestTarget(
            as_of_date=start,
            cluster_count=1,
            active_cluster_count=1,
            weights=(
                TargetWeight(ticker="AAA", portfolio_weight=0.5),
                TargetWeight(ticker="BBB", portfolio_weight=0.5),
            ),
        )

        result = simulate_backtest(
            market_data,
            BacktestConfig(
                start_date=start,
                end_date=end,
                rebalance_period=3,
                take_profit_threshold=1.0,
            ),
            lambda as_of_date: target,
        )

        self.assertAlmostEqual(result.daily_performance[0].nav, 1.05)
        self.assertAlmostEqual(result.daily_performance[0].strategy_return, 0.05)
        self.assertAlmostEqual(result.daily_performance[1].nav, 1.105)
        self.assertAlmostEqual(
            result.daily_performance[1].strategy_return,
            1.105 / 1.05 - 1.0,
        )
        self.assertEqual(len(result.trades), 2)

    def test_all_cash_target_earns_zero_and_produces_no_infinite_ratios(
        self,
    ) -> None:
        previous = date(2026, 1, 2)
        sessions = tuple(pd.bdate_range("2026-01-05", periods=2).date)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 110.0, 90.0],
                "SPY": [100.0, 101.0, 99.0],
            },
            index=pd.Index((previous, *sessions), name="trade_date"),
        )
        target = BacktestTarget(
            as_of_date=sessions[0],
            cluster_count=1,
            active_cluster_count=0,
            weights=(TargetWeight("AAA", 0.0),),
        )

        result = simulate_backtest(
            BacktestMarketData(previous, sessions, closes),
            BacktestConfig(
                start_date=sessions[0],
                end_date=sessions[-1],
            ),
            lambda _: target,
        )

        self.assertEqual(
            [row.strategy_return for row in result.daily_performance],
            [0.0, 0.0],
        )
        self.assertEqual(
            [row.cash_weight for row in result.daily_performance],
            [1.0, 1.0],
        )
        self.assertEqual(result.strategy_metrics.ending_nav, 1.0)
        self.assertIsNone(result.strategy_metrics.sharpe_ratio)
        self.assertIsNone(result.strategy_metrics.sortino_ratio)

    def test_scheduled_rebalance_applies_new_target_after_third_return(self) -> None:
        previous = date(2026, 1, 2)
        sessions = tuple(
            pd.bdate_range("2026-01-05", periods=4).date
        )
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 110.0, 121.0, 133.1, 146.41],
                "BBB": [100.0, 100.0, 100.0, 100.0, 110.0],
                "SPY": [100.0, 100.0, 100.0, 100.0, 100.0],
            },
            index=pd.Index((previous, *sessions), name="trade_date"),
        )
        initial = BacktestTarget(
            as_of_date=sessions[0],
            cluster_count=1,
            active_cluster_count=1,
            weights=(TargetWeight("AAA", 1.0),),
        )
        replacement = BacktestTarget(
            as_of_date=sessions[3],
            cluster_count=1,
            active_cluster_count=1,
            weights=(TargetWeight("BBB", 1.0),),
        )

        result = simulate_backtest(
            BacktestMarketData(
                previous_session=previous,
                sessions=sessions,
                closes=closes,
            ),
            BacktestConfig(
                start_date=sessions[0],
                end_date=sessions[-1],
                rebalance_period=3,
                take_profit_threshold=1.0,
            ),
            {sessions[0]: initial, sessions[3]: replacement}.__getitem__,
        )

        self.assertAlmostEqual(result.daily_performance[2].nav, 1.331)
        self.assertEqual(result.daily_performance[2].trigger_reason, "scheduled")
        self.assertAlmostEqual(result.daily_performance[3].strategy_return, 0.10)
        self.assertAlmostEqual(result.daily_performance[3].nav, 1.4641)
        self.assertEqual(
            [
                (event.reason, event.event_date, event.effective_date)
                for event in result.rebalance_events
            ],
            [
                ("initial", previous, sessions[0]),
                ("scheduled", sessions[2], sessions[3]),
            ],
        )

    def test_stop_win_at_exact_threshold_changes_next_session_target(self) -> None:
        previous = date(2026, 1, 2)
        sessions = tuple(pd.bdate_range("2026-01-05", periods=3).date)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 105.0, 115.5, 127.05],
                "BBB": [100.0, 100.0, 102.0, 103.0],
                "SPY": [100.0, 100.0, 100.0, 100.0],
            },
            index=pd.Index((previous, *sessions), name="trade_date"),
        )
        initial = BacktestTarget(
            sessions[0],
            1,
            1,
            (TargetWeight("AAA", 1.0),),
        )
        replacement = BacktestTarget(
            sessions[1],
            1,
            1,
            (TargetWeight("BBB", 1.0),),
        )

        result = simulate_backtest(
            BacktestMarketData(previous, sessions, closes),
            BacktestConfig(
                start_date=sessions[0],
                end_date=sessions[-1],
                take_profit_threshold=0.05,
            ),
            {sessions[0]: initial, sessions[1]: replacement}.__getitem__,
        )

        self.assertEqual(result.daily_performance[0].trigger_reason, "stop_win")
        self.assertEqual(result.daily_performance[1].round_id, 2)
        self.assertEqual(result.daily_performance[1].holding_day, 1)
        self.assertAlmostEqual(result.daily_performance[1].strategy_return, 0.02)
        self.assertEqual(result.rebalance_events[1].event_date, sessions[0])
        self.assertEqual(result.rebalance_events[1].effective_date, sessions[1])
        self.assertEqual(result.rebalance_events[1].reason, "stop_win")

    def test_missing_position_is_frozen_then_liquidated_on_recovery(self) -> None:
        previous = date(2026, 1, 2)
        sessions = tuple(pd.bdate_range("2026-01-05", periods=3).date)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, float("nan"), float("nan"), 120.0],
                "BBB": [100.0, 150.0, 150.0, 150.0],
                "CCC": [100.0, 100.0, 100.0, 100.0],
                "SPY": [100.0, 100.0, 100.0, 100.0],
            },
            index=pd.Index((previous, *sessions), name="trade_date"),
        )
        initial = BacktestTarget(
            sessions[0],
            1,
            1,
            (TargetWeight("AAA", 0.5), TargetWeight("BBB", 0.5)),
        )
        replacement = BacktestTarget(
            sessions[1],
            1,
            1,
            (TargetWeight("CCC", 1.0),),
        )

        result = simulate_backtest(
            BacktestMarketData(previous, sessions, closes),
            BacktestConfig(
                start_date=sessions[0],
                end_date=sessions[-1],
                rebalance_period=3,
                take_profit_threshold=0.20,
            ),
            {sessions[0]: initial, sessions[1]: replacement}.__getitem__,
        )

        self.assertEqual(result.daily_performance[0].trigger_reason, "stop_win")
        self.assertAlmostEqual(result.rebalance_events[1].frozen_value, 0.5)
        self.assertAlmostEqual(result.rebalance_events[1].available_capital, 0.75)
        self.assertAlmostEqual(result.daily_performance[1].nav, 1.25)
        self.assertAlmostEqual(result.daily_performance[2].nav, 1.35)
        recovery_sales = [
            trade
            for trade in result.trades
            if trade.reason == "recovery_liquidation"
        ]
        self.assertEqual(len(recovery_sales), 1)
        self.assertEqual(recovery_sales[0].ticker, "AAA")
        self.assertAlmostEqual(recovery_sales[0].trade_notional, 0.6)
        self.assertIn(
            "recovered_liquidated",
            [audit.action for audit in result.missing_data_audit],
        )

    def test_frozen_position_still_in_target_is_retained_on_recovery(self) -> None:
        previous = date(2026, 1, 2)
        sessions = tuple(pd.bdate_range("2026-01-05", periods=2).date)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, float("nan"), 120.0],
                "BBB": [100.0, 150.0, 150.0],
                "CCC": [100.0, 100.0, 100.0],
                "SPY": [100.0, 100.0, 100.0],
            },
            index=pd.Index((previous, *sessions), name="trade_date"),
        )
        targets = {
            sessions[0]: BacktestTarget(
                sessions[0],
                1,
                1,
                (TargetWeight("AAA", 0.5), TargetWeight("BBB", 0.5)),
            ),
            sessions[1]: BacktestTarget(
                sessions[1],
                1,
                1,
                (TargetWeight("AAA", 0.5), TargetWeight("CCC", 0.5)),
            ),
        }

        result = simulate_backtest(
            BacktestMarketData(previous, sessions, closes),
            BacktestConfig(
                start_date=sessions[0],
                end_date=sessions[-1],
                take_profit_threshold=0.20,
            ),
            targets.__getitem__,
        )

        self.assertEqual(result.daily_performance[0].trigger_reason, "stop_win")
        self.assertAlmostEqual(result.daily_performance[1].nav, 1.35)
        self.assertEqual(result.daily_performance[1].position_count, 2)
        self.assertNotIn(
            "recovery_liquidation",
            [trade.reason for trade in result.trades],
        )
        self.assertIn(
            "frozen_retained_target",
            [audit.action for audit in result.missing_data_audit],
        )
        self.assertIn(
            "recovered_marked",
            [audit.action for audit in result.missing_data_audit],
        )

    def test_scheduled_reason_wins_when_threshold_is_reached_on_day_three(
        self,
    ) -> None:
        previous = date(2026, 1, 2)
        sessions = tuple(pd.bdate_range("2026-01-05", periods=4).date)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 100.0, 100.0, 105.0, 105.0],
                "BBB": [100.0, 100.0, 100.0, 100.0, 100.0],
                "SPY": [100.0, 100.0, 100.0, 100.0, 100.0],
            },
            index=pd.Index((previous, *sessions), name="trade_date"),
        )
        targets = {
            sessions[0]: BacktestTarget(
                sessions[0],
                1,
                1,
                (TargetWeight("AAA", 1.0),),
            ),
            sessions[3]: BacktestTarget(
                sessions[3],
                1,
                1,
                (TargetWeight("BBB", 1.0),),
            ),
        }

        result = simulate_backtest(
            BacktestMarketData(previous, sessions, closes),
            BacktestConfig(
                start_date=sessions[0],
                end_date=sessions[-1],
                take_profit_threshold=0.05,
            ),
            targets.__getitem__,
        )

        self.assertIsNone(result.daily_performance[0].trigger_reason)
        self.assertIsNone(result.daily_performance[1].trigger_reason)
        self.assertEqual(result.daily_performance[2].trigger_reason, "scheduled")
        self.assertEqual(result.rebalance_events[1].reason, "scheduled")

    def test_performance_metrics_use_compounding_and_zero_risk_free_rate(
        self,
    ) -> None:
        returns = (0.02, -0.01, 0.03, -0.02)
        ending_nav = float(pd.Series(returns).add(1.0).prod())

        metrics = calculate_performance_metrics(
            returns,
            starting_nav=1.0,
            ending_nav=ending_nav,
            annualization_sessions=252,
        )

        expected_mean = float(pd.Series(returns).mean())
        expected_std = float(pd.Series(returns).std(ddof=1))
        expected_downside = float(
            pd.Series([-0.01, -0.02]).std(ddof=1)
        )
        self.assertAlmostEqual(metrics.total_return, ending_nav - 1.0)
        self.assertAlmostEqual(
            metrics.annualized_return,
            ending_nav ** (252 / 4) - 1.0,
        )
        self.assertAlmostEqual(
            metrics.sharpe_ratio,
            (252**0.5) * expected_mean / expected_std,
        )
        self.assertAlmostEqual(
            metrics.sortino_ratio,
            (252**0.5) * expected_mean / expected_downside,
        )

    def test_unfilled_initial_buy_stays_cash_and_is_audited(self) -> None:
        previous = date(2026, 1, 2)
        start = date(2026, 1, 5)
        closes = pd.DataFrame(
            {
                "AAA": [float("nan"), 100.0],
                "SPY": [100.0, 101.0],
            },
            index=pd.Index((previous, start), name="trade_date"),
        )
        target = BacktestTarget(
            start,
            1,
            1,
            (TargetWeight("AAA", 1.0),),
        )

        result = simulate_backtest(
            BacktestMarketData(previous, (start,), closes),
            BacktestConfig(start, start),
            lambda _: target,
        )

        self.assertAlmostEqual(result.daily_performance[0].nav, 1.0)
        self.assertAlmostEqual(result.daily_performance[0].cash_weight, 1.0)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].side, "BUY")
        self.assertEqual(result.trades[0].status, "unfilled_missing_close")
        self.assertAlmostEqual(result.trades[0].trade_notional, 1.0)
        self.assertEqual(
            [audit.action for audit in result.missing_data_audit],
            ["buy_unfilled_cash_retained"],
        )

    def test_target_weight_audit_keeps_only_positive_weights(self) -> None:
        previous = date(2026, 1, 2)
        start = date(2026, 1, 5)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 110.0],
                "BBB": [100.0, 90.0],
                "CCC": [100.0, 105.0],
                "SPY": [100.0, 101.0],
            },
            index=pd.Index((previous, start), name="trade_date"),
        )
        target = BacktestTarget(
            start,
            2,
            1,
            (
                TargetWeight(
                    "AAA",
                    0.5,
                    market_cap_rank=1,
                    cluster_id=0,
                    cumulative_deviation=-0.10,
                    classification="previous_loser",
                    local_weight=1.0,
                ),
                TargetWeight(
                    "BBB",
                    0.0,
                    market_cap_rank=2,
                    cluster_id=0,
                    cumulative_deviation=0.10,
                    classification="previous_winner",
                    local_weight=0.0,
                ),
                TargetWeight(
                    "CCC",
                    0.0,
                    market_cap_rank=3,
                    cluster_id=1,
                    cumulative_deviation=0.0,
                    classification="neutral",
                    local_weight=0.0,
                ),
            ),
        )

        result = simulate_backtest(
            BacktestMarketData(previous, (start,), closes),
            BacktestConfig(start, start),
            lambda _: target,
        )

        self.assertEqual(
            [row.ticker for row in result.target_weights],
            ["AAA"],
        )
        self.assertTrue(
            all(row.portfolio_weight > 0.0 for row in result.target_weights)
        )
        self.assertAlmostEqual(result.daily_performance[0].nav, 1.05)
        self.assertAlmostEqual(
            result.rebalance_events[0].target_gross_exposure,
            0.5,
        )
        self.assertEqual(
            result.calculation_version,
            "long_only_close_to_close_stateful_v2",
        )


class BacktestIntegrationTests(unittest.TestCase):
    def test_run_backtest_uses_existing_pipeline_without_result_tables(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, dates = build_test_database(Path(directory))
            add_close_prices(database)
            preprocessing_config = PreprocessingConfig(
                database_path=database,
                beta_window=40,
                correlation_window=5,
            )
            build_preprocessing(preprocessing_config)
            sessions = tuple(value.date() for value in dates[-4:])

            result = run_backtest(
                preprocessing_config,
                BacktestConfig(
                    start_date=sessions[0],
                    end_date=sessions[-1],
                    take_profit_threshold=1.0,
                ),
            )

            self.assertEqual(
                tuple(row.trade_date for row in result.daily_performance),
                sessions,
            )
            self.assertEqual(
                [event.reason for event in result.rebalance_events],
                ["initial", "scheduled"],
            )
            with duckdb.connect(str(database), read_only=True) as connection:
                backtest_tables = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema IN ('backtest', 'portfolio_backtest')
                       OR table_name LIKE '%backtest%'
                    """
                ).fetchone()[0]
            self.assertEqual(backtest_tables, 0)

    def test_excel_contains_six_audit_sheets_and_refuses_overwrite(self) -> None:
        previous = date(2026, 1, 2)
        start = date(2026, 1, 5)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 105.0],
                "BBB": [100.0, 95.0],
                "SPY": [100.0, 102.0],
            },
            index=pd.Index((previous, start), name="trade_date"),
        )
        target = BacktestTarget(
            start,
            1,
            1,
            (
                TargetWeight(
                    "AAA",
                    1.0,
                    market_cap_rank=1,
                    cluster_id=0,
                    cumulative_deviation=-0.10,
                    classification="previous_loser",
                    local_weight=1.0,
                ),
                TargetWeight(
                    "BBB",
                    0.0,
                    market_cap_rank=2,
                    cluster_id=0,
                    cumulative_deviation=0.10,
                    classification="previous_winner",
                    local_weight=0.0,
                ),
            ),
        )
        result = simulate_backtest(
            BacktestMarketData(previous, (start,), closes),
            BacktestConfig(start, start),
            lambda _: target,
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "backtest.xlsx"
            export_backtest_workbook(result, output)

            workbook = load_workbook(output, data_only=False, read_only=False)
            self.assertEqual(
                workbook.sheetnames,
                [
                    "Summary",
                    "Daily_Performance",
                    "Rebalance_Events",
                    "Target_Weights",
                    "Trades",
                    "Missing_Data_Audit",
                ],
            )
            summary = workbook["Summary"]
            summary_rows = {
                summary.cell(row, 1).value: row
                for row in range(2, summary.max_row + 1)
            }
            self.assertAlmostEqual(
                summary.cell(
                    summary_rows["Strategy total return"],
                    2,
                ).value,
                result.strategy_metrics.total_return,
            )
            self.assertEqual(workbook["Daily_Performance"].max_row, 2)
            self.assertEqual(workbook["Rebalance_Events"]["C2"].value, "initial")
            target_sheet = workbook["Target_Weights"]
            self.assertEqual(target_sheet.max_row, 2)
            self.assertEqual(target_sheet["C2"].value, "AAA")
            self.assertGreater(target_sheet["I2"].value, 0.0)
            self.assertEqual(workbook["Trades"]["D2"].value, "BUY")
            self.assertEqual(workbook["Missing_Data_Audit"].max_row, 1)
            self.assertEqual(
                summary.cell(summary_rows["Target-weight rows"], 2).value,
                1,
            )
            self.assertEqual(
                workbook["Daily_Performance"].freeze_panes,
                "A2",
            )
            self.assertEqual(
                workbook["Daily_Performance"].auto_filter.ref,
                "A1:P2",
            )
            self.assertEqual(
                workbook["Daily_Performance"]["A2"].number_format,
                "yyyy-mm-dd",
            )
            self.assertEqual(
                workbook["Daily_Performance"]["B2"].number_format,
                "0.0000%",
            )
            self.assertEqual(target_sheet["B2"].number_format, "yyyy-mm-dd")
            self.assertEqual(target_sheet["I2"].number_format, "0.000000")
            self.assertEqual(target_sheet.column_dimensions["A"].width, 11.0)
            self.assertEqual(target_sheet["A1"].fill.fill_type, "solid")
            self.assertTrue(
                str(target_sheet["A1"].fill.fgColor.rgb).endswith("1F4E78")
            )
            self.assertEqual(target_sheet["A2"].fill.fill_type, "solid")
            self.assertTrue(
                str(target_sheet["A2"].fill.fgColor.rgb).endswith("F8FAFC")
            )
            target_conditional_ranges = list(
                target_sheet.conditional_formatting
            )
            self.assertEqual(len(target_conditional_ranges), 1)
            target_rules = target_sheet.conditional_formatting[
                target_conditional_ranges[0]
            ]
            self.assertEqual(len(target_rules), 1)
            self.assertEqual(
                target_rules[0].formula,
                ['G2="previous_loser"'],
            )
            workbook.close()

            with self.assertRaises(FileExistsError):
                export_backtest_workbook(result, output)

    def test_excel_export_removes_temporary_file_after_save_failure(self) -> None:
        previous = date(2026, 1, 2)
        start = date(2026, 1, 5)
        closes = pd.DataFrame(
            {
                "AAA": [100.0, 101.0],
                "SPY": [100.0, 101.0],
            },
            index=pd.Index((previous, start), name="trade_date"),
        )
        target = BacktestTarget(
            start,
            1,
            1,
            (TargetWeight("AAA", 1.0),),
        )
        result = simulate_backtest(
            BacktestMarketData(previous, (start,), closes),
            BacktestConfig(start, start),
            lambda _: target,
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "backtest.xlsx"
            with patch(
                "openpyxl.workbook.workbook.Workbook.save",
                side_effect=RuntimeError("save failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "save failed"):
                    export_backtest_workbook(result, output)

            self.assertFalse(output.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cli_requires_explicit_range_and_uses_project_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "export",
                "--start-date",
                "2026-01-05",
                "--end-date",
                "2026-01-09",
            ]
        )

        self.assertEqual(args.rebalance_period, 3)
        self.assertAlmostEqual(args.take_profit_threshold, 0.05)
        self.assertAlmostEqual(args.deviation_threshold, 0.05)
        self.assertEqual(args.lookback_window, 5)
        self.assertFalse(args.no_progress)


def add_close_prices(database: Path) -> None:
    with duckdb.connect(str(database)) as connection:
        prices = connection.execute(
            """
            SELECT ticker, trade_date, price_return
            FROM market_data.daily_prices
            ORDER BY ticker, trade_date
            """
        ).fetchdf()
        prices["close"] = (
            prices.assign(growth=1.0 + prices["price_return"])
            .groupby("ticker")["growth"]
            .cumprod()
            .mul(100.0)
        )
        market = connection.execute(
            """
            SELECT trade_date, market_return
            FROM market_data.market_returns
            WHERE ticker = 'SPY'
            ORDER BY trade_date
            """
        ).fetchdf()
        market["close"] = (1.0 + market["market_return"]).cumprod() * 100.0
        connection.register("close_prices", prices)
        connection.register("market_closes", market)
        try:
            connection.execute(
                """
                UPDATE market_data.daily_prices AS target
                SET close = source.close
                FROM close_prices AS source
                WHERE target.ticker = source.ticker
                  AND target.trade_date = source.trade_date
                """
            )
            connection.execute(
                """
                UPDATE market_data.market_returns AS target
                SET close = source.close
                FROM market_closes AS source
                WHERE target.ticker = 'SPY'
                  AND target.trade_date = source.trade_date
                """
            )
        finally:
            connection.unregister("close_prices")
            connection.unregister("market_closes")


if __name__ == "__main__":
    unittest.main()
