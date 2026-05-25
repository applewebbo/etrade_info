from datetime import date
from decimal import Decimal

import pytest


@pytest.mark.django_db
class TestLot:
    def test_create_and_retrieve(self):
        from app import Lot

        lot = Lot.objects.create(
            symbol="AAPL",
            plan_type="ESPP",
            date_acquired=date(2015, 1, 31),
            sellable_qty=Decimal("28.0000"),
            cost_basis=Decimal("24.03250"),
            tax_status="Long Term",
        )
        retrieved = Lot.objects.get(pk=lot.pk)
        assert retrieved.symbol == "AAPL"
        assert retrieved.plan_type == "ESPP"
        assert retrieved.cost_basis == Decimal("24.03250")
        assert retrieved.tax_status == "Long Term"

    def test_ordering_by_date_acquired(self):
        from app import Lot

        Lot.objects.create(
            symbol="AAPL",
            plan_type="RSU",
            date_acquired=date(2018, 10, 15),
            sellable_qty=Decimal("4"),
            cost_basis=Decimal("38.78250"),
            tax_status="Long Term",
        )
        Lot.objects.create(
            symbol="AAPL",
            plan_type="ESPP",
            date_acquired=date(2015, 1, 31),
            sellable_qty=Decimal("28"),
            cost_basis=Decimal("24.03250"),
            tax_status="Long Term",
        )
        lots = list(Lot.objects.all())
        assert lots[0].date_acquired < lots[1].date_acquired

    def test_str_representation(self):
        from app import Lot

        lot = Lot(symbol="AAPL", plan_type="ESPP", date_acquired=date(2015, 1, 31))
        assert "AAPL" in str(lot)
        assert "ESPP" in str(lot)
