from decimal import Decimal


def fixed_fetcher(value: str):
    """Returns a fetcher that always returns the given value."""

    def _fetch(ticker: str) -> Decimal:
        return Decimal(value)

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
