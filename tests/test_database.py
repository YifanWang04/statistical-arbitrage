from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from stat_arb_data.database import DuckDBDataset


class DuckDBMembershipTests(unittest.TestCase):
    def test_catalog_has_three_clear_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.duckdb"
            with DuckDBDataset(path) as dataset:
                dataset.initialise()

            with duckdb.connect(str(path), read_only=True) as connection:
                schemas = connection.execute(
                    """
                    SELECT schema_name
                    FROM information_schema.schemata
                    WHERE schema_name IN ('market_data', 'audit', 'browse')
                    ORDER BY schema_name
                    """
                ).fetchall()

            self.assertEqual(schemas, [("audit",), ("browse",), ("market_data",)])

    def test_membership_uses_previous_market_session_and_historical_shares(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.duckdb"
            with DuckDBDataset(path) as dataset:
                dataset.initialise()
                now = datetime.now(timezone.utc)
                securities = pd.DataFrame(
                    [
                        {
                            "ticker": ticker,
                            "short_name": ticker,
                            "long_name": ticker,
                            "issuer_key": ticker.lower(),
                            "primary_ticker_override": None,
                            "exchange": "NYQ",
                            "quote_type": "EQUITY",
                            "currency": "USD",
                            "current_market_cap": 1_000_000.0,
                            "candidate_pool_rank": index,
                            "discovered_at": now,
                            "is_common_stock_proxy": True,
                            "ff12_code": pd.NA,
                            "source": "test",
                        }
                        for index, ticker in enumerate(("AAA", "BBB", "CCC"), start=1)
                    ]
                )
                dataset.save_security_master(securities)

                rows = []
                closes = {
                    ("AAA", "2020-01-02"): 10.0,
                    ("BBB", "2020-01-02"): 4.0,
                    ("CCC", "2020-01-02"): 100.0,
                    ("AAA", "2020-01-03"): 10.0,
                    ("BBB", "2020-01-03"): 6.0,
                    ("CCC", "2020-01-03"): 100.0,
                }
                for (ticker, trade_date), close in closes.items():
                    rows.append(
                        {
                            "ticker": ticker,
                            "trade_date": date_from_string(trade_date),
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
                            "source": "test",
                        }
                    )
                dataset.save_daily_prices(pd.DataFrame(rows))
                dataset.save_shares_outstanding(
                    pd.DataFrame(
                        [
                            {
                                "ticker": "AAA",
                                "effective_date": date_from_string("2020-01-02"),
                                "shares_outstanding": 100,
                                "source": "test",
                            },
                            {
                                "ticker": "BBB",
                                "effective_date": date_from_string("2020-01-02"),
                                "shares_outstanding": 200,
                                "source": "test",
                            },
                        ]
                    ),
                )
                dataset.save_market_prices(
                    pd.DataFrame(
                        [
                            {
                                "ticker": "SPY",
                                "trade_date": date_from_string(day),
                                "close": 100.0,
                                "adjusted_close": 100.0,
                                "price_return": 0.0,
                                "total_return": 0.0,
                                "source": "test",
                            }
                            for day in ("2020-01-02", "2020-01-03", "2020-01-06")
                        ]
                    ),
                )

                dataset.materialise_universe(top_n=2)
                membership = dataset.universe_membership()

                self.assertEqual(membership["ticker"].tolist(), ["AAA", "BBB", "BBB", "AAA"])
                self.assertEqual(
                    membership.iloc[0]["ranking_date"].date().isoformat(), "2020-01-02"
                )
                self.assertNotIn("CCC", membership["ticker"].tolist())
                latest = dataset.latest_universe()
                self.assertEqual(latest["ticker"].tolist(), ["BBB", "AAA"])

            with duckdb.connect(str(path), read_only=True) as connection:
                browse_objects = connection.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'browse'
                    ORDER BY table_name
                    """
                ).fetchall()
            self.assertEqual(
                browse_objects,
                [("daily_quality",), ("daily_universe",), ("latest_universe",)],
            )

    def test_daily_universe_keeps_one_line_per_issuer_and_honours_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "issuers.duckdb"
            with DuckDBDataset(path) as dataset:
                dataset.initialise()
                now = datetime.now(timezone.utc)
                definitions = (
                    ("GOOG", "alphabet inc", "GOOG", 10.0, 100.0),
                    ("GOOGL", "alphabet inc", "GOOG", 11.0, 1_000.0),
                    ("BRK-A", "berkshire hathaway inc", None, 100.0, 1.0),
                    ("BRK-B", "berkshire hathaway inc", None, 5.0, 500.0),
                    ("OTHER", "other inc", None, 4.0, 100.0),
                )
                dataset.save_security_master(
                    pd.DataFrame(
                        [
                            {
                                "ticker": ticker,
                                "short_name": ticker,
                                "long_name": issuer,
                                "issuer_key": issuer,
                                "primary_ticker_override": override,
                                "exchange": "NYQ",
                                "quote_type": "EQUITY",
                                "currency": "USD",
                                "current_market_cap": 1_000_000.0,
                                "candidate_pool_rank": index,
                                "discovered_at": now,
                                "is_common_stock_proxy": True,
                                "ff12_code": pd.NA,
                                "source": "test",
                            }
                            for index, (ticker, issuer, override, _close, _volume) in enumerate(
                                definitions, start=1
                            )
                        ]
                    )
                )

                price_rows = []
                share_rows = []
                for ticker, _issuer, _override, close, volume in definitions:
                    for day in ("2020-01-02", "2020-01-03"):
                        price_rows.append(
                            {
                                "ticker": ticker,
                                "trade_date": date_from_string(day),
                                "open": close,
                                "high": close,
                                "low": close,
                                "close": close,
                                "market_cap_close": close,
                                "adjusted_close": close,
                                "volume": volume,
                                "dividends": 0.0,
                                "stock_splits": 0.0,
                                "capital_gains": 0.0,
                                "price_return": 0.01,
                                "total_return": 0.02,
                                "source": "test",
                            }
                        )
                    share_rows.append(
                        {
                            "ticker": ticker,
                            "effective_date": date_from_string("2020-01-02"),
                            "shares_outstanding": 100,
                            "source": "test",
                        }
                    )
                dataset.save_daily_prices(pd.DataFrame(price_rows))
                dataset.save_shares_outstanding(pd.DataFrame(share_rows))
                dataset.save_market_prices(
                    pd.DataFrame(
                        [
                            {
                                "ticker": "SPY",
                                "trade_date": date_from_string(day),
                                "close": close,
                                "adjusted_close": adjusted,
                                "price_return": price_return,
                                "total_return": total_return,
                                "source": "test",
                            }
                            for day, close, adjusted, price_return, total_return in (
                                ("2020-01-02", 100.0, 100.0, 0.01, 0.02),
                                ("2020-01-03", 101.0, 102.0, 0.01, 0.02),
                            )
                        ]
                    )
                )

                dataset.materialise_universe(top_n=3)
                latest = dataset.latest_universe()

                self.assertEqual(latest["ticker"].tolist(), ["GOOG", "BRK-B", "OTHER"])
                self.assertEqual(latest["issuer_key"].nunique(), 3)
                self.assertEqual(
                    latest.loc[latest["ticker"] == "GOOG", "primary_selection_method"].item(),
                    "explicit_primary_override",
                )
                self.assertTrue((latest["strategy_return"] == latest["price_return"]).all())

            with duckdb.connect(str(path), read_only=True) as connection:
                market_return = connection.execute(
                    "SELECT market_return FROM market_data.market_returns ORDER BY trade_date LIMIT 1"
                ).fetchone()
            self.assertEqual(market_return, (0.01,))

    def test_market_cap_aligns_split_adjusted_price_with_reported_shares(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.duckdb"
            with DuckDBDataset(path) as dataset:
                dataset.initialise()
                dataset.save_security_master(
                    pd.DataFrame(
                        [
                            {
                                "ticker": "AAA",
                                "short_name": "AAA",
                                "long_name": "AAA Inc.",
                                "issuer_key": "aaa inc",
                                "primary_ticker_override": None,
                                "exchange": "NYQ",
                                "quote_type": "EQUITY",
                                "currency": "USD",
                                "current_market_cap": 2_000.0,
                                "candidate_pool_rank": 1,
                                "discovered_at": datetime.now(timezone.utc),
                                "is_common_stock_proxy": True,
                                "ff12_code": pd.NA,
                                "source": "test",
                            }
                        ]
                    )
                )
                dataset.save_daily_prices(
                    pd.DataFrame(
                        [
                            {
                                "ticker": "AAA",
                                "trade_date": date_from_string(day),
                                "open": close,
                                "high": close,
                                "low": close,
                                "close": close,
                                "market_cap_close": market_cap_close,
                                "adjusted_close": close,
                                "volume": 100.0,
                                "dividends": 0.0,
                                "stock_splits": split,
                                "capital_gains": 0.0,
                                "price_return": 0.0,
                                "total_return": 0.0,
                                "source": "test",
                            }
                            for day, close, market_cap_close, split in (
                                ("2020-01-02", 10.0, 20.0, 0.0),
                                ("2020-01-03", 11.0, 11.0, 2.0),
                            )
                        ]
                    )
                )
                dataset.save_shares_outstanding(
                    pd.DataFrame(
                        [
                            {
                                "ticker": "AAA",
                                "effective_date": date_from_string("2020-01-02"),
                                "shares_outstanding": 100,
                                "source": "test",
                            }
                        ]
                    )
                )
                dataset.save_market_prices(
                    pd.DataFrame(
                        [
                            {
                                "ticker": "SPY",
                                "trade_date": date_from_string(day),
                                "close": 100.0,
                                "adjusted_close": 100.0,
                                "price_return": 0.0,
                                "total_return": 0.0,
                                "source": "test",
                            }
                            for day in ("2020-01-02", "2020-01-03")
                        ]
                    )
                )
                dataset.materialise_universe(top_n=1)

            with duckdb.connect(str(path), read_only=True) as connection:
                caps = connection.execute(
                    """
                    SELECT trade_date, shares_outstanding, market_cap
                    FROM market_data.daily_market_cap
                    ORDER BY trade_date
                    """
                ).fetchall()
            self.assertEqual(
                caps,
                [
                    (date_from_string("2020-01-02"), 100, 2_000.0),
                    (date_from_string("2020-01-03"), 200, 2_200.0),
                ],
            )


def date_from_string(value: str):
    return pd.Timestamp(value).date()


if __name__ == "__main__":
    unittest.main()
