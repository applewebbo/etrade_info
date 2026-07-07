import datetime
from decimal import Decimal


def _fetcher(rates_list):
    def fetcher(params):
        return {"rates": rates_list}

    return fetcher


class TestGetBdiEurUsdRate:
    def test_returns_decimal_for_valid_date(self):
        from bdi_rates import get_bdi_eur_usd_rate

        fetcher = _fetcher([{"referenceDate": "2025-01-02", "avgRate": "0.9689"}])
        result = get_bdi_eur_usd_rate(datetime.date(2025, 1, 2), fetcher=fetcher)
        assert result == Decimal("0.9689")

    def test_returns_last_rate_when_range_has_multiple(self):
        from bdi_rates import get_bdi_eur_usd_rate

        fetcher = _fetcher(
            [
                {"referenceDate": "2025-12-29", "avgRate": "0.8499"},
                {"referenceDate": "2025-12-30", "avgRate": "0.8506"},
                {"referenceDate": "2025-12-31", "avgRate": "0.8511"},
            ]
        )
        result = get_bdi_eur_usd_rate(datetime.date(2025, 12, 31), fetcher=fetcher)
        assert result == Decimal("0.8511")

    def test_returns_none_when_no_rates(self):
        from bdi_rates import get_bdi_eur_usd_rate

        fetcher = _fetcher([])
        result = get_bdi_eur_usd_rate(datetime.date(2025, 1, 1), fetcher=fetcher)
        assert result is None

    def test_queries_lookback_window_before_target(self):
        from bdi_rates import get_bdi_eur_usd_rate

        captured = {}

        def fetcher(params):
            captured.update(params)
            return {"rates": []}

        get_bdi_eur_usd_rate(datetime.date(2025, 1, 1), fetcher=fetcher)
        assert captured["endDate"] == "2025-01-01"
        assert captured["startDate"] < "2025-01-01"

    def test_handles_holiday_by_returning_last_business_day(self):
        from bdi_rates import get_bdi_eur_usd_rate

        # Jan 1 is holiday, Jan 2 is the first business day
        fetcher = _fetcher([{"referenceDate": "2025-01-02", "avgRate": "0.9689"}])
        result = get_bdi_eur_usd_rate(datetime.date(2025, 1, 1), fetcher=fetcher)
        assert result == Decimal("0.9689")


class TestDefaultFetcher:
    def test_calls_bdi_endpoint_and_returns_json(self, monkeypatch):
        import requests

        import bdi_rates

        captured = {}

        class _FakeResponse:
            def raise_for_status(self):
                captured["raised"] = True

            def json(self):
                return {"rates": [{"avgRate": "0.9689"}]}

        def fake_get(url, params, headers, timeout):
            captured.update(url=url, params=params, headers=headers, timeout=timeout)
            return _FakeResponse()

        monkeypatch.setattr(requests, "get", fake_get)
        result = bdi_rates._default_fetcher({"startDate": "2025-01-01"})
        assert result == {"rates": [{"avgRate": "0.9689"}]}
        assert captured["url"] == bdi_rates._BDI_URL
        assert captured["params"] == {"startDate": "2025-01-01"}
        assert captured["raised"] is True
