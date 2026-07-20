from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .securities import (
    common_stock_exclusion_reason,
    issuer_key,
    primary_ticker_override,
)


PRICE_COLUMNS = (
    "ticker",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "market_cap_close",
    "adjusted_close",
    "volume",
    "dividends",
    "stock_splits",
    "capital_gains",
    "price_return",
    "total_return",
    "source",
)


def _load_yfinance() -> Any:
    import yfinance as yf

    return yf


def _empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=PRICE_COLUMNS)


def _normalise_field_name(value: object) -> str:
    return str(value).strip().lower().replace(" ", "_")


def normalise_yahoo_download(raw: pd.DataFrame, tickers: Iterable[str]) -> pd.DataFrame:
    """Convert yfinance's single- or multi-ticker layout into a stable long table."""

    if raw is None or raw.empty:
        return _empty_prices()

    requested = list(dict.fromkeys(str(t).upper() for t in tickers))
    frames: list[pd.DataFrame] = []

    for ticker in requested:
        frame: pd.DataFrame | None = None
        if isinstance(raw.columns, pd.MultiIndex):
            level_zero = set(map(str, raw.columns.get_level_values(0)))
            level_one = set(map(str, raw.columns.get_level_values(1)))
            if ticker in level_zero:
                frame = raw[ticker].copy()
            elif ticker in level_one:
                frame = raw.xs(ticker, axis=1, level=1).copy()
        elif len(requested) == 1:
            frame = raw.copy()

        if frame is None or frame.empty:
            continue

        frame = frame.sort_index().copy()
        frame.columns = [_normalise_field_name(column) for column in frame.columns]
        frame = frame.rename(columns={"adj_close": "adjusted_close", "stock_splits": "stock_splits"})
        index = pd.to_datetime(frame.index)
        if index.tz is not None:
            index = index.tz_localize(None)
        frame["trade_date"] = index.date
        frame["ticker"] = ticker

        for column in (
            "open",
            "high",
            "low",
            "close",
            "adjusted_close",
            "volume",
            "dividends",
            "stock_splits",
            "capital_gains",
        ):
            if column not in frame:
                frame[column] = pd.NA

        frame["price_return"] = pd.to_numeric(frame["close"], errors="coerce").pct_change(
            fill_method=None
        )
        split_ratio = pd.to_numeric(frame["stock_splits"], errors="coerce").fillna(0.0)
        split_ratio = split_ratio.where(split_ratio > 0, 1.0)
        future_split_factor = split_ratio.iloc[::-1].cumprod().iloc[::-1] / split_ratio
        frame["market_cap_close"] = (
            pd.to_numeric(frame["close"], errors="coerce") * future_split_factor
        )
        frame["total_return"] = pd.to_numeric(
            frame["adjusted_close"], errors="coerce"
        ).pct_change(fill_method=None)
        frame["source"] = "yfinance"
        frames.append(frame.loc[:, PRICE_COLUMNS])

    if not frames:
        return _empty_prices()

    result = pd.concat(frames, ignore_index=True)
    result = result.dropna(subset=["trade_date"]).drop_duplicates(
        subset=["ticker", "trade_date"], keep="last"
    )
    return result.sort_values(["ticker", "trade_date"], ignore_index=True)


class YahooFinanceDataSource:
    """Yahoo-backed source with explicit, documented point-in-time limitations."""

    def __init__(self, yf_module: Any | None = None) -> None:
        self._yf = yf_module

    @property
    def yf(self) -> Any:
        if self._yf is None:
            self._yf = _load_yfinance()
        return self._yf

    def discover_current_common_stock_proxies(
        self,
        exchanges: tuple[str, ...],
        candidate_pool_size: int | None,
    ) -> pd.DataFrame:
        """Discover current common-stock proxies; this is not a historical security master."""

        query = self.yf.EquityQuery("is-in", ["exchange", *exchanges])
        quotes: list[dict[str, Any]] = []
        offset = 0
        page_size = 250

        while True:
            response = self.yf.screen(
                query,
                offset=offset,
                size=page_size,
                sortField="intradaymarketcap",
                sortAsc=False,
            )
            page = response.get("quotes", []) if isinstance(response, dict) else []
            if not page:
                break
            quotes.extend(page)
            offset += len(page)

            total = response.get("total") if isinstance(response, dict) else None
            if len(page) < page_size or (isinstance(total, int) and offset >= total):
                break

        discovered_at = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        for quote in quotes:
            ticker = str(quote.get("symbol", "")).strip().upper()
            quote_type = str(quote.get("quoteType", "")).strip().upper()
            exchange = str(quote.get("exchange", "")).strip().upper()
            long_name = quote.get("longName")
            if exchange not in exchanges:
                continue
            if common_stock_exclusion_reason(ticker, quote_type, long_name) is not None:
                continue
            key = issuer_key(long_name, ticker)
            rows.append(
                {
                    "ticker": ticker,
                    "short_name": quote.get("shortName"),
                    "long_name": long_name,
                    "issuer_key": key,
                    "primary_ticker_override": primary_ticker_override(key),
                    "exchange": exchange,
                    "quote_type": quote_type,
                    "currency": quote.get("currency"),
                    "current_market_cap": quote.get("marketCap"),
                    "candidate_pool_rank": 0,
                    "discovered_at": discovered_at,
                    "is_common_stock_proxy": True,
                    "ff12_code": pd.NA,
                    "source": "yfinance_current_screener",
                }
            )

        result = pd.DataFrame(rows)
        if result.empty:
            return pd.DataFrame(
                columns=(
                    "ticker",
                    "short_name",
                    "long_name",
                    "issuer_key",
                    "primary_ticker_override",
                    "exchange",
                    "quote_type",
                    "currency",
                    "current_market_cap",
                    "candidate_pool_rank",
                    "discovered_at",
                    "is_common_stock_proxy",
                    "ff12_code",
                    "source",
                )
            )

        result = result.drop_duplicates("ticker", keep="first").copy()
        result["current_market_cap"] = pd.to_numeric(
            result["current_market_cap"], errors="coerce"
        )
        issuer_ranking = (
            result.groupby("issuer_key", as_index=False, dropna=False)["current_market_cap"]
            .max()
            .sort_values(
                ["current_market_cap", "issuer_key"],
                ascending=[False, True],
                na_position="last",
            )
            .reset_index(drop=True)
        )
        issuer_ranking["candidate_pool_rank"] = range(1, len(issuer_ranking) + 1)
        if candidate_pool_size is not None:
            issuer_ranking = issuer_ranking.head(candidate_pool_size)

        result = result.merge(
            issuer_ranking.loc[:, ["issuer_key", "candidate_pool_rank"]],
            on="issuer_key",
            how="inner",
            validate="many_to_one",
            suffixes=("_discard", ""),
        )
        result = result.drop(columns=["candidate_pool_rank_discard"])
        result = result.sort_values(
            ["candidate_pool_rank", "current_market_cap", "ticker"],
            ascending=[True, False, True],
            na_position="last",
            ignore_index=True,
        )
        return result

    def download_prices(
        self,
        tickers: Iterable[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        symbols = list(dict.fromkeys(str(t).upper() for t in tickers))
        if not symbols:
            return _empty_prices()
        raw = self.yf.download(
            symbols,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            actions=True,
            threads=True,
            repair=False,
            keepna=False,
            progress=False,
            multi_level_index=True,
        )
        return normalise_yahoo_download(raw, symbols)

    def download_shares(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        raw = self.yf.Ticker(ticker).get_shares_full(
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
        )
        if raw is None or len(raw) == 0:
            return pd.DataFrame(
                columns=("ticker", "effective_date", "shares_outstanding", "source")
            )

        if isinstance(raw, pd.DataFrame):
            values = raw.iloc[:, 0]
        else:
            values = pd.Series(raw)

        index = pd.to_datetime(values.index)
        if index.tz is not None:
            index = index.tz_localize(None)
        result = pd.DataFrame(
            {
                "ticker": ticker.upper(),
                "effective_date": index.date,
                "shares_outstanding": pd.to_numeric(values.to_numpy(), errors="coerce"),
                "source": "yfinance_get_shares_full",
            }
        )
        result = result.dropna(subset=["shares_outstanding"])
        result = result[result["shares_outstanding"] > 0]
        result["shares_outstanding"] = result["shares_outstanding"].round().astype("int64")
        return result.drop_duplicates(
            subset=["ticker", "effective_date"], keep="last"
        ).sort_values("effective_date", ignore_index=True)
