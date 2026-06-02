import datetime
from decimal import Decimal

_BDI_URL = "https://tassidicambio.bancaditalia.it/terzevalute-wf-web/rest/v1.0/dailyTimeSeries"


def _default_fetcher(params: dict) -> dict:
    import requests

    resp = requests.get(
        _BDI_URL,
        params=params,
        headers={"Accept": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_bdi_eur_usd_rate(
    target_date: datetime.date,
    fetcher=None,
) -> Decimal | None:
    """
    Return EUR per 1 USD from Banca d'Italia for the last available business day
    on or before target_date (7-day lookback to handle weekends/holidays).
    fetcher: optional callable(params: dict) -> dict, used in tests.
    """
    start = target_date - datetime.timedelta(days=7)
    params = {
        "startDate": start.isoformat(),
        "endDate": target_date.isoformat(),
        "baseCurrencyIsoCode": "EUR",
        "currencyIsoCode": "USD",
    }
    fn = fetcher or _default_fetcher
    data = fn(params)
    rates = data.get("rates", [])
    if not rates:
        return None
    return Decimal(rates[-1]["avgRate"])
