from datetime import date
from decimal import Decimal

import pytest

LOT_DEFAULTS = dict(
    symbol="AAPL",
    plan_type="ESPP",
    date_acquired=date(2020, 1, 1),
    sellable_qty=Decimal("10"),
    cost_basis=Decimal("100.00000"),
    tax_status="Long Term",
)


@pytest.mark.django_db
class TestImportLots:
    def test_overwrite_replaces_all_existing(self):
        from app import Lot, import_lots

        Lot.objects.create(**LOT_DEFAULTS)
        new_data = [{**LOT_DEFAULTS, "date_acquired": date(2021, 6, 1)}]
        import_lots(new_data, mode="overwrite")
        assert Lot.objects.count() == 1
        assert Lot.objects.first().date_acquired == date(2021, 6, 1)

    def test_overwrite_with_empty_list_deletes_all(self):
        from app import Lot, import_lots

        Lot.objects.create(**LOT_DEFAULTS)
        import_lots([], mode="overwrite")
        assert Lot.objects.count() == 0

    def test_incremental_adds_new_lots(self):
        from app import Lot, import_lots

        Lot.objects.create(**LOT_DEFAULTS)
        new_lot = {
            **LOT_DEFAULTS,
            "date_acquired": date(2021, 6, 1),
            "cost_basis": Decimal("120.00000"),
        }
        import_lots([new_lot], mode="incremental")
        assert Lot.objects.count() == 2

    def test_incremental_skips_existing_lots(self):
        from app import Lot, import_lots

        Lot.objects.create(**LOT_DEFAULTS)
        import_lots([LOT_DEFAULTS], mode="incremental")
        assert Lot.objects.count() == 1

    def test_incremental_mixed_new_and_existing(self):
        from app import Lot, import_lots

        Lot.objects.create(**LOT_DEFAULTS)
        new_lot = {**LOT_DEFAULTS, "date_acquired": date(2022, 3, 15)}
        import_lots([LOT_DEFAULTS, new_lot], mode="incremental")
        assert Lot.objects.count() == 2


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
