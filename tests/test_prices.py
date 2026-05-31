from decimal import Decimal


def fixed_fetcher(value: str):
    """Returns a fetcher that always returns the given value."""

    def _fetch(ticker: str) -> Decimal:
        return Decimal(value)

    return _fetch


def failing_fetcher():
    """Returns a fetcher that always raises an exception."""

    def _fetch(ticker: str) -> Decimal:
        msg = "Network error"
        raise ConnectionError(msg)

    return _fetch


def counting_fetcher(value: str):
    """Returns a fetcher that counts how many times it was called."""
    calls = []

    def _fetch(ticker: str) -> Decimal:
        calls.append(ticker)
        return Decimal(value)

    return _fetch, calls


class TestGetPrice:
    def setup_method(self):
        from prices import clear_cache

        clear_cache()

    def test_returns_decimal(self):
        from prices import get_price

        result = get_price("AAPL", fetcher=fixed_fetcher("308.82"))
        assert isinstance(result, Decimal)
        assert result == Decimal("308.82")

    def test_cache_hit_skips_fetcher(self):
        from prices import get_price

        fetcher, calls = counting_fetcher("308.82")
        get_price("AAPL", fetcher=fetcher)
        get_price("AAPL", fetcher=fetcher)
        assert len(calls) == 1

    def test_different_tickers_cached_independently(self):
        from prices import get_price

        fetcher_aapl, calls_aapl = counting_fetcher("308.82")
        fetcher_fx, calls_fx = counting_fetcher("1.085")
        get_price("AAPL", fetcher=fetcher_aapl)
        get_price("EURUSD=X", fetcher=fetcher_fx)
        get_price("AAPL", fetcher=fetcher_aapl)
        get_price("EURUSD=X", fetcher=fetcher_fx)
        assert len(calls_aapl) == 1
        assert len(calls_fx) == 1

    def test_cache_expires_after_ttl(self, monkeypatch):
        import prices
        from prices import get_price

        fetcher, calls = counting_fetcher("308.82")

        # Fake time: first call at t=0, second at t=TTL+1
        times = [0, prices.CACHE_TTL + 1]
        monkeypatch.setattr(prices, "_now", lambda: times.pop(0))

        get_price("AAPL", fetcher=fetcher)
        get_price("AAPL", fetcher=fetcher)
        assert len(calls) == 2

    def test_clear_cache_forces_refetch(self):
        from prices import clear_cache, get_price

        fetcher, calls = counting_fetcher("308.82")
        get_price("AAPL", fetcher=fetcher)
        clear_cache()
        get_price("AAPL", fetcher=fetcher)
        assert len(calls) == 2

    def test_fetch_error_returns_stale_cache(self, monkeypatch):
        import prices
        from prices import get_price, is_price_stale

        # Warm the cache at t=0
        times = [0, prices.CACHE_TTL + 1]
        monkeypatch.setattr(prices, "_now", lambda: times.pop(0))

        get_price("AAPL", fetcher=fixed_fetcher("308.82"))
        # Cache expired, fetch fails → should return stale cached value
        result = get_price("AAPL", fetcher=failing_fetcher())
        assert result == Decimal("308.82")
        assert is_price_stale("AAPL")

    def test_fetch_error_with_no_cache_returns_none(self):
        from prices import get_price, is_price_stale

        result = get_price("AAPL", fetcher=failing_fetcher())
        assert result is None
        assert is_price_stale("AAPL")

    def test_successful_fetch_clears_stale_flag(self):
        from prices import get_price, is_price_stale

        get_price("AAPL", fetcher=failing_fetcher())
        assert is_price_stale("AAPL")
        get_price("AAPL", fetcher=fixed_fetcher("310.00"))
        assert not is_price_stale("AAPL")


class TestPriceDirection:
    def setup_method(self):
        from prices import clear_cache

        clear_cache()

    def test_neutral_when_no_data(self):
        from prices import get_price_direction

        assert get_price_direction("AAPL") == "neutral"

    def test_neutral_on_first_fetch(self):
        from prices import get_price, get_price_direction

        get_price("AAPL", fetcher=fixed_fetcher("308.82"))
        assert get_price_direction("AAPL") == "neutral"

    def test_up_when_price_increases(self, monkeypatch):
        import prices
        from prices import get_price, get_price_direction

        times = [0, prices.CACHE_TTL + 1]
        monkeypatch.setattr(prices, "_now", lambda: times.pop(0))
        get_price("AAPL", fetcher=fixed_fetcher("300.00"))
        get_price("AAPL", fetcher=fixed_fetcher("310.00"))
        assert get_price_direction("AAPL") == "up"

    def test_down_when_price_decreases(self, monkeypatch):
        import prices
        from prices import get_price, get_price_direction

        times = [0, prices.CACHE_TTL + 1]
        monkeypatch.setattr(prices, "_now", lambda: times.pop(0))
        get_price("AAPL", fetcher=fixed_fetcher("310.00"))
        get_price("AAPL", fetcher=fixed_fetcher("300.00"))
        assert get_price_direction("AAPL") == "down"

    def test_neutral_when_price_unchanged(self, monkeypatch):
        import prices
        from prices import get_price, get_price_direction

        times = [0, prices.CACHE_TTL + 1]
        monkeypatch.setattr(prices, "_now", lambda: times.pop(0))
        get_price("AAPL", fetcher=fixed_fetcher("308.82"))
        get_price("AAPL", fetcher=fixed_fetcher("308.82"))
        assert get_price_direction("AAPL") == "neutral"

    def test_neutral_when_current_equals_prev(self):
        import prices
        from prices import get_price_direction

        prices._last_known["AAPL"] = Decimal("200.00")
        prices._prev_price["AAPL"] = Decimal("200.00")
        assert get_price_direction("AAPL") == "neutral"


class TestConvenienceFunctions:
    def setup_method(self):
        from prices import clear_cache

        clear_cache()

    def test_get_stock_price_usd(self, monkeypatch):
        import prices

        monkeypatch.setattr(prices, "_fetch_yfinance", fixed_fetcher("308.82"))
        result = prices.get_stock_price_usd()
        assert result == Decimal("308.82")

    def test_get_eur_usd_rate(self, monkeypatch):
        import prices

        monkeypatch.setattr(prices, "_fetch_yfinance", fixed_fetcher("1.0850"))
        result = prices.get_eur_usd_rate()
        assert result == Decimal("1.0850")

    def test_fetch_yfinance_calls_yfinance_api(self, monkeypatch):
        import yfinance as yf

        import prices

        class FakeFastInfo(dict):
            pass

        class FakeTicker:
            def __init__(self, ticker):
                self.fast_info = FakeFastInfo({"last_price": 308.82})

        monkeypatch.setattr(yf, "Ticker", FakeTicker)
        result = prices._fetch_yfinance("AAPL")
        assert result == Decimal("308.82")
