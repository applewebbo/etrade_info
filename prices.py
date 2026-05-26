import time
from collections.abc import Callable
from decimal import Decimal

import yfinance as yf

CACHE_TTL = 60  # seconds

_cache: dict[str, tuple[Decimal, float]] = {}
_last_known: dict[str, Decimal] = {}
_prev_price: dict[str, Decimal] = {}
_fetch_failed: set[str] = set()


def _now() -> float:
    return time.monotonic()


def _fetch_yfinance(ticker: str) -> Decimal:
    data = yf.Ticker(ticker)
    price = data.fast_info["last_price"]
    return Decimal(str(round(float(price), 4)))


def get_price(ticker: str, fetcher: Callable[[str], Decimal] | None = None) -> Decimal | None:
    """Return cached or live price. Falls back to stale/last-known on error; None if never fetched."""
    now = _now()
    cached = _cache.get(ticker)
    if cached and (now - cached[1]) < CACHE_TTL:
        _fetch_failed.discard(ticker)
        return cached[0]

    fetch = fetcher or _fetch_yfinance
    try:
        price = fetch(ticker)
        old = _last_known.get(ticker)
        if old is not None and old != price:
            _prev_price[ticker] = old
        _cache[ticker] = (price, now)
        _last_known[ticker] = price
        _fetch_failed.discard(ticker)
        return price
    except Exception:
        _fetch_failed.add(ticker)
        if cached:
            return cached[0]
        return _last_known.get(ticker)


def get_price_direction(ticker: str) -> str:
    """Return 'up', 'down', or 'neutral' based on last two fetched prices."""
    current = _last_known.get(ticker)
    prev = _prev_price.get(ticker)
    if current is None or prev is None:
        return "neutral"
    if current > prev:
        return "up"
    if current < prev:
        return "down"
    return "neutral"


def is_price_stale(ticker: str) -> bool:
    """True if the last fetch attempt for this ticker failed."""
    return ticker in _fetch_failed


def get_stock_price_usd(ticker: str = "AAPL") -> Decimal | None:
    return get_price(ticker)


def get_eur_usd_rate() -> Decimal | None:
    return get_price("EURUSD=X")


def clear_cache() -> None:
    _cache.clear()
    _last_known.clear()
    _prev_price.clear()
    _fetch_failed.clear()
