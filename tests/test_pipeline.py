from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from stat_arb_data.config import PipelineConfig
from stat_arb_data.pipeline import DataPipeline


class FakeSource:
    def discover_current_common_stock_proxies(
        self, exchanges: tuple[str, ...], candidate_pool_size: int | None
    ) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        return pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "short_name": ticker,
                    "long_name": f"{ticker} Corporation",
                    "issuer_key": f"{ticker.lower()} corporation",
                    "primary_ticker_override": None,
                    "exchange": "NYQ",
                    "quote_type": "EQUITY",
                    "currency": "USD",
                    "current_market_cap": float(3_000_000 - index),
                    "candidate_pool_rank": index,
                    "discovered_at": now,
                    "is_common_stock_proxy": True,
                    "ff12_code": pd.NA,
                    "source": "fake",
                }
                for index, ticker in enumerate(("AAA", "BBB"), start=1)
            ]
        )

    def download_prices(
        self, tickers: list[str], start_date: date, end_date: date
    ) -> pd.DataFrame:
        dates = [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)]
        if tickers == ["SPY"]:
            return pd.DataFrame(
                [self._price_row("SPY", day, 100.0 + index) for index, day in enumerate(dates)]
            )

        closes = {
            "AAA": [10.0, 10.0, 11.0],
            "BBB": [4.0, 6.0, 6.0],
        }
        return pd.DataFrame(
            [
                self._price_row(ticker, day, close)
                for ticker in tickers
                for day, close in zip(dates, closes[ticker], strict=True)
            ]
        )

    def download_shares(
        self, ticker: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        shares = {"AAA": 100, "BBB": 200}[ticker]
        return pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "effective_date": date(2020, 1, 2),
                    "shares_outstanding": shares,
                    "source": "fake",
                }
            ]
        )

    @staticmethod
    def _price_row(ticker: str, trade_date: date, close: float) -> dict[str, object]:
        return {
            "ticker": ticker,
            "trade_date": trade_date,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "market_cap_close": close,
            "adjusted_close": close,
            "volume": 100.0,
            "dividends": 0.0,
            "stock_splits": 0.0,
            "capital_gains": 0.0,
            "price_return": 0.0,
            "total_return": 0.0,
            "source": "fake",
        }


class DataPipelineTests(unittest.TestCase):
    def test_offline_pipeline_builds_browsable_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "offline.duckdb"
            config = PipelineConfig(
                database_path=database,
                start_date=date(2020, 1, 1),
                end_date=date(2020, 1, 6),
                top_n=1,
            )

            run_id = DataPipeline(config, source=FakeSource()).run()

            with duckdb.connect(str(database), read_only=True) as connection:
                run = connection.execute(
                    "SELECT status FROM audit.pipeline_runs WHERE run_id = ?", [run_id]
                ).fetchone()
                selected = connection.execute(
                    """
                    SELECT eligible_date, ticker
                    FROM market_data.universe_membership
                    ORDER BY eligible_date
                    """
                ).fetchall()
                ff12_values = connection.execute(
                    "SELECT DISTINCT ff12_code FROM market_data.security_master"
                ).fetchall()
                browse_rows = connection.execute(
                    "SELECT COUNT(*) FROM browse.daily_universe"
                ).fetchone()[0]
                return_basis = connection.execute(
                    "SELECT setting_value FROM audit.settings WHERE setting_key = 'return_basis'"
                ).fetchone()

            self.assertEqual(run, ("completed",))
            self.assertEqual(
                selected,
                [(date(2020, 1, 3), "AAA"), (date(2020, 1, 6), "BBB")],
            )
            self.assertEqual(ff12_values, [(None,)])
            self.assertEqual(browse_rows, 2)
            self.assertEqual(
                return_basis,
                ("split_consistent_close_price_return_excluding_dividends",),
            )


if __name__ == "__main__":
    unittest.main()
