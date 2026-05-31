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


SALE_DEFAULTS = dict(
    sale_price_usd=Decimal("200.00000"),
    eur_usd_rate=Decimal("1.100000"),
    gross_proceeds_usd=Decimal("2000.00000"),
    net_gain_usd=Decimal("1000.00000"),
    tax_usd=Decimal("260.00000"),
)


@pytest.mark.django_db
class TestSale:
    def test_create_and_retrieve(self):
        from app import Sale

        sale = Sale.objects.create(**SALE_DEFAULTS)
        retrieved = Sale.objects.get(pk=sale.pk)
        assert retrieved.sale_price_usd == Decimal("200.00000")
        assert retrieved.tax_usd == Decimal("260.00000")

    def test_ordering_newest_first(self):
        from app import Sale

        sale1 = Sale.objects.create(**SALE_DEFAULTS)
        sale2 = Sale.objects.create(
            **{**SALE_DEFAULTS, "gross_proceeds_usd": Decimal("4000.00000")}
        )
        sales = list(Sale.objects.all())
        assert sales[0].pk == sale2.pk
        assert sales[1].pk == sale1.pk

    def test_gross_proceeds_eur_property(self):
        from app import Sale

        sale = Sale.objects.create(**SALE_DEFAULTS)
        assert sale.gross_proceeds_eur == Decimal("2000.00000") / Decimal("1.100000")

    def test_tax_eur_property(self):
        from app import Sale

        sale = Sale.objects.create(**SALE_DEFAULTS)
        assert sale.tax_eur == Decimal("260.00000") / Decimal("1.100000")


@pytest.mark.django_db
class TestSaleLot:
    def test_create_and_retrieve(self):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**SALE_DEFAULTS)
        slot = SaleLot.objects.create(
            sale=sale,
            original_lot_id=99,
            symbol="AAPL",
            plan_type="ESPP",
            date_acquired=date(2020, 1, 1),
            qty_sold=Decimal("5.0000"),
            cost_basis=Decimal("100.00000"),
            tax_status="Long Term",
            gain_usd=Decimal("500.00000"),
        )
        assert SaleLot.objects.get(pk=slot.pk).qty_sold == Decimal("5.0000")

    def test_cascade_delete_with_sale(self):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**SALE_DEFAULTS)
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=1,
            symbol="AAPL",
            plan_type="ESPP",
            date_acquired=date(2020, 1, 1),
            qty_sold=Decimal("10.0000"),
            cost_basis=Decimal("100.00000"),
            tax_status="Long Term",
            gain_usd=Decimal("1000.00000"),
        )
        assert SaleLot.objects.count() == 1
        sale.delete()
        assert SaleLot.objects.count() == 0

    def test_total_qty_property(self):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**SALE_DEFAULTS)
        slot_defaults = dict(
            sale=sale,
            original_lot_id=1,
            symbol="AAPL",
            plan_type="ESPP",
            date_acquired=date(2020, 1, 1),
            cost_basis=Decimal("100.00000"),
            tax_status="Long Term",
            gain_usd=Decimal("500.00000"),
        )
        SaleLot.objects.create(**{**slot_defaults, "qty_sold": Decimal("3.0000")})
        SaleLot.objects.create(
            **{**slot_defaults, "original_lot_id": 2, "qty_sold": Decimal("7.0000")}
        )
        assert sale.total_qty == Decimal("10")
