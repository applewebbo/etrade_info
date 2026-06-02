import datetime
from decimal import Decimal


class FakeLot:
    def __init__(self, date_acquired, qty, plan_type="ESPP"):
        self.date_acquired = date_acquired
        self.sellable_qty = Decimal(str(qty))
        self.plan_type = plan_type
        self.symbol = "AAPL"
        self.cost_basis = Decimal("100.00000")
        self.tax_status = "Long Term"


RATE_START = Decimal("0.9689")  # EUR per 1 USD, Jan 2 2025
RATE_END = Decimal("0.8511")  # EUR per 1 USD, Dec 31 2025
PRICE_START = Decimal("242.30")
PRICE_END = Decimal("272.57")
YEAR = 2025


class TestCalculateIvafe:
    def test_lot_held_full_year_uses_365_days(self):
        from ivafe_engine import calculate_ivafe

        lot = FakeLot(datetime.date(2022, 5, 15), 10)
        result = calculate_ivafe([lot], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR)
        assert result["rows"][0]["days_held"] == 365

    def test_lot_held_full_year_ivafe_is_end_value_times_rate(self):
        from ivafe_engine import calculate_ivafe

        lot = FakeLot(datetime.date(2022, 5, 15), 10)
        result = calculate_ivafe([lot], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR)
        expected_value_end_eur = Decimal("10") * PRICE_END * RATE_END
        expected_ivafe = expected_value_end_eur * Decimal("0.002")
        assert result["total_ivafe_eur"] == expected_ivafe

    def test_lot_acquired_during_year_prorated(self):
        from ivafe_engine import calculate_ivafe

        lot = FakeLot(datetime.date(2025, 6, 1), 5)
        result = calculate_ivafe([lot], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR)
        days = (datetime.date(2025, 12, 31) - datetime.date(2025, 6, 1)).days + 1
        assert result["rows"][0]["days_held"] == days
        expected_ivafe = (
            (Decimal("5") * PRICE_END * RATE_END) * Decimal("0.002") * Decimal(days) / Decimal(365)
        )
        assert result["total_ivafe_eur"] == expected_ivafe

    def test_lot_acquired_after_year_excluded(self):
        from ivafe_engine import calculate_ivafe

        lot = FakeLot(datetime.date(2026, 1, 15), 10)
        result = calculate_ivafe([lot], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR)
        assert result["total_ivafe_eur"] == Decimal("0")
        assert len(result["rows"]) == 0

    def test_start_value_present_only_for_pre_year_lots(self):
        from ivafe_engine import calculate_ivafe

        lot_pre = FakeLot(datetime.date(2022, 5, 15), 10)
        lot_during = FakeLot(datetime.date(2025, 3, 1), 5)
        result = calculate_ivafe(
            [lot_pre, lot_during], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR
        )
        assert result["rows"][0]["value_start_eur"] is not None
        assert result["rows"][1]["value_start_eur"] is None

    def test_total_value_start_excludes_during_year_lots(self):
        from ivafe_engine import calculate_ivafe

        lot_pre = FakeLot(datetime.date(2022, 5, 15), 10)
        lot_during = FakeLot(datetime.date(2025, 6, 1), 5)
        result = calculate_ivafe(
            [lot_pre, lot_during], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR
        )
        expected = Decimal("10") * PRICE_START * RATE_START
        assert result["total_value_start_eur"] == expected

    def test_total_value_end_includes_all_lots_within_year(self):
        from ivafe_engine import calculate_ivafe

        lot_pre = FakeLot(datetime.date(2022, 5, 15), 10)
        lot_during = FakeLot(datetime.date(2025, 6, 1), 5)
        result = calculate_ivafe(
            [lot_pre, lot_during], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR
        )
        expected = (Decimal("10") + Decimal("5")) * PRICE_END * RATE_END
        assert result["total_value_end_eur"] == expected

    def test_lot_acquired_on_jan_1_counts_as_365_days(self):
        from ivafe_engine import calculate_ivafe

        lot = FakeLot(datetime.date(2025, 1, 1), 10)
        result = calculate_ivafe([lot], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR)
        assert result["rows"][0]["days_held"] == 365

    def test_lot_acquired_on_dec_31_counts_as_1_day(self):
        from ivafe_engine import calculate_ivafe

        lot = FakeLot(datetime.date(2025, 12, 31), 10)
        result = calculate_ivafe([lot], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR)
        assert result["rows"][0]["days_held"] == 1

    def test_empty_lots_returns_zeros(self):
        from ivafe_engine import calculate_ivafe

        result = calculate_ivafe([], PRICE_START, PRICE_END, RATE_START, RATE_END, YEAR)
        assert result["total_ivafe_eur"] == Decimal("0")
        assert result["total_value_start_eur"] == Decimal("0")
        assert result["total_value_end_eur"] == Decimal("0")
