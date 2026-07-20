from __future__ import annotations

import unittest

import pandas as pd

from stat_arb_data.yahoo import YahooFinanceDataSource, normalise_yahoo_download


class FakeYahoo:
    last_screen_kwargs: dict[str, object] = {}

    class EquityQuery:
        def __init__(self, operator: str, operand: list[str]) -> None:
            self.operator = operator
            self.operand = operand

    @staticmethod
    def screen(*_args: object, **kwargs: object) -> dict[str, object]:
        FakeYahoo.last_screen_kwargs = kwargs
        if kwargs["offset"]:
            return {"quotes": [], "total": 3}
        return {
            "total": 3,
            "quotes": [
                {
                    "symbol": "AAA",
                    "exchange": "NYQ",
                    "quoteType": "EQUITY",
                    "longName": "AAA Corporation",
                    "marketCap": 1_000_000,
                },
                {"symbol": "ETF", "exchange": "NYQ", "quoteType": "ETF"},
                {"symbol": "OTC", "exchange": "PNK", "quoteType": "EQUITY"},
            ],
        }


class FakeMarketCapYahoo:
    EquityQuery = FakeYahoo.EquityQuery

    @staticmethod
    def screen(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "total": 3,
            "quotes": [
                {"symbol": "BIG", "longName": "Big Inc.", "exchange": "NYQ", "quoteType": "EQUITY", "marketCap": 300},
                {"symbol": "MID", "longName": "Mid Inc.", "exchange": "NMS", "quoteType": "EQUITY", "marketCap": 200},
                {"symbol": "SMALL", "longName": "Small Inc.", "exchange": "ASE", "quoteType": "EQUITY", "marketCap": 100},
            ],
        }


class FakeSecurityTypesYahoo:
    EquityQuery = FakeYahoo.EquityQuery

    @staticmethod
    def screen(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "total": 7,
            "quotes": [
                {"symbol": "GOOG", "longName": "Alphabet Inc.", "exchange": "NMS", "quoteType": "EQUITY", "marketCap": 400},
                {"symbol": "GOOGL", "longName": "Alphabet Inc.", "exchange": "NMS", "quoteType": "EQUITY", "marketCap": 401},
                {"symbol": "JPM-PC", "longName": "JPMorgan Chase & Co.", "exchange": "NYQ", "quoteType": "EQUITY", "marketCap": None},
                {"symbol": "SPAC-WT", "longName": "Example Warrants", "exchange": "NYQ", "quoteType": "EQUITY", "marketCap": 50},
                {"symbol": "SPAC-UN", "longName": "Example Units", "exchange": "NYQ", "quoteType": "EQUITY", "marketCap": 60},
                {"symbol": "COMMON", "longName": "Common Company", "exchange": "NYQ", "quoteType": "EQUITY", "marketCap": 300},
                {"symbol": "ETF", "longName": "Index ETF", "exchange": "NYQ", "quoteType": "ETF", "marketCap": 500},
            ],
        }


class YahooNormalisationTests(unittest.TestCase):
    def test_normalises_multi_ticker_prices_and_separates_return_types(self) -> None:
        dates = pd.to_datetime(["2020-01-02", "2020-01-03"])
        columns = pd.MultiIndex.from_product(
            [["AAA"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
        )
        raw = pd.DataFrame(
            [[10, 11, 9, 10, 10, 100], [11, 12, 10, 11, 12, 120]],
            index=dates,
            columns=columns,
        )

        result = normalise_yahoo_download(raw, ["AAA"])

        self.assertAlmostEqual(result.loc[1, "price_return"], 0.1)
        self.assertAlmostEqual(result.loc[1, "total_return"], 0.2)
        self.assertEqual(result.loc[0, "trade_date"].isoformat(), "2020-01-02")

    def test_reconstructs_as_traded_close_for_market_cap_across_split(self) -> None:
        dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
        columns = pd.MultiIndex.from_product(
            [["AAA"], ["Close", "Adj Close", "Stock Splits"]]
        )
        raw = pd.DataFrame(
            [[10.0, 9.0, 0.0], [11.0, 10.0, 2.0], [12.0, 11.0, 0.0]],
            index=dates,
            columns=columns,
        )

        result = normalise_yahoo_download(raw, ["AAA"])

        self.assertEqual(result["market_cap_close"].tolist(), [20.0, 11.0, 12.0])
        self.assertAlmostEqual(result.loc[1, "price_return"], 0.1)

    def test_current_screener_uses_equity_and_exchange_proxy(self) -> None:
        source = YahooFinanceDataSource(FakeYahoo())
        result = source.discover_current_common_stock_proxies(("ASE", "NYQ"), 1000)

        self.assertEqual(result["ticker"].tolist(), ["AAA"])
        self.assertEqual(result.loc[0, "candidate_pool_rank"], 1)
        self.assertEqual(result.loc[0, "current_market_cap"], 1_000_000)
        self.assertTrue(result.loc[0, "is_common_stock_proxy"])
        self.assertEqual(result.loc[0, "issuer_key"], "aaa corporation")
        self.assertTrue(pd.isna(result.loc[0, "ff12_code"]))
        self.assertEqual(FakeYahoo.last_screen_kwargs["sortField"], "intradaymarketcap")
        self.assertFalse(FakeYahoo.last_screen_kwargs["sortAsc"])

    def test_candidate_pool_keeps_only_requested_market_cap_leaders(self) -> None:
        source = YahooFinanceDataSource(FakeMarketCapYahoo())

        result = source.discover_current_common_stock_proxies(("ASE", "NMS", "NYQ"), 2)

        self.assertEqual(result["ticker"].tolist(), ["BIG", "MID"])
        self.assertEqual(result["candidate_pool_rank"].tolist(), [1, 2])

    def test_excludes_non_common_securities_and_groups_share_classes_by_issuer(self) -> None:
        source = YahooFinanceDataSource(FakeSecurityTypesYahoo())

        result = source.discover_current_common_stock_proxies(("NMS", "NYQ"), None)

        self.assertEqual(result["ticker"].tolist(), ["GOOGL", "GOOG", "COMMON"])
        alphabet = result[result["issuer_key"] == "alphabet inc"]
        self.assertEqual(alphabet["candidate_pool_rank"].tolist(), [1, 1])
        self.assertEqual(alphabet["primary_ticker_override"].tolist(), ["GOOG", "GOOG"])
        self.assertNotIn("JPM-PC", result["ticker"].tolist())
        self.assertNotIn("SPAC-WT", result["ticker"].tolist())
        self.assertNotIn("SPAC-UN", result["ticker"].tolist())


if __name__ == "__main__":
    unittest.main()
