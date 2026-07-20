from __future__ import annotations

import re


_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")
_PREFERRED_TICKER = re.compile(r"-P[A-Z]$")
_NON_COMMON_TICKER = re.compile(r"-(?:W|WS|WT|U|UN|R|RT)$")
_NON_COMMON_NAME = re.compile(r"\b(?:warrant|warrants|unit|units|right|rights)\b", re.IGNORECASE)


# Explicit user decisions take precedence over the liquidity fallback used for
# other multi-class issuers.
PRIMARY_TICKER_BY_ISSUER = {
    "alphabet inc": "GOOG",
}


def issuer_key(long_name: object, ticker: object) -> str:
    """Return a deterministic Yahoo approximation of an issuer identifier."""

    name = "" if long_name is None else str(long_name).strip().casefold()
    normalised = _NON_ALPHANUMERIC.sub(" ", name).strip()
    if normalised:
        return normalised
    return str(ticker).strip().upper().casefold()


def primary_ticker_override(key: str) -> str | None:
    return PRIMARY_TICKER_BY_ISSUER.get(key)


def common_stock_exclusion_reason(
    ticker: object,
    quote_type: object,
    long_name: object = None,
) -> str | None:
    """Classify obvious non-common securities returned by Yahoo as EQUITY."""

    symbol = str(ticker).strip().upper()
    kind = str(quote_type).strip().upper()
    name = "" if long_name is None else str(long_name).strip()

    if not symbol:
        return "missing_ticker"
    if kind != "EQUITY":
        return "not_equity"
    if _PREFERRED_TICKER.search(symbol):
        return "preferred_stock"
    if _NON_COMMON_TICKER.search(symbol):
        return "warrant_unit_or_right"
    if _NON_COMMON_NAME.search(name):
        return "warrant_unit_or_right"
    return None
