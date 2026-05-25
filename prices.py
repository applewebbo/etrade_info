import time
from collections.abc import Callable
from decimal import Decimal

import yfinance as yf

CACHE_TTL = 60  # seconds

_cache: dict[str, tuple[Decimal, float]] = {}


def _now() -> float:
    return time.monotonic()


def _fetch_yfinance(ticker: str) -> Decimal:
    data = yf.Ticker(ticker)
    price = data.fast_info["last_price"]
    return Decimal(str(round(float(price), 4)))


def get_price(ticker: str, fetcher: Callable[[str], Decimal] | None = None) -> Decimal:
    """Return price for ticker, using 60s in-memory cache."""
    now = _now()
    cached = _cache.get(ticker)
    if cached and (now - cached[1]) < CACHE_TTL:
        return cached[0]
    fetch = fetcher or _fetch_yfinance
    price = fetch(ticker)
    _cache[ticker] = (price, now)
    return price


def get_stock_price_usd(ticker: str = "AAPL") -> Decimal:
    return get_price(ticker)


def get_eur_usd_rate() -> Decimal:
    return get_price("EURUSD=X")


def clear_cache() -> None:
    _cache.clear()
