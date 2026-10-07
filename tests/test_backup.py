from datetime import date
from decimal import Decimal

import pytest

LOT_DEFAULTS = dict(
    symbol="AAPL",
    plan_type="ESPP",
    date_acquired=date(2020, 1, 1),
    grant_date=date(2019, 8, 1),
    sellable_qty=Decimal("10.0000"),
    cost_basis=Decimal("100.00000"),
    tax_status="Long Term",
)

SALE_DEFAULTS = dict(
    sale_price_usd=Decimal("200.00000"),
    eur_usd_rate=Decimal("1.100000"),
    gross_proceeds_usd=Decimal("2000.00000"),
    net_gain_usd=Decimal("1000.00000"),
    tax_usd=Decimal("260.00000"),
)


@pytest.mark.django_db
class TestBackupRoundTrip:
    def _make_sale(self):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**SALE_DEFAULTS)
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=42,
            symbol="AAPL",
            plan_type="RSU",
            date_acquired=date(2021, 3, 15),
            grant_date=date(2020, 3, 15),
            qty_sold=Decimal("5.0000"),
            cost_basis=Decimal("150.00000"),
            tax_status="Long Term",
            gain_usd=Decimal("250.00000"),
        )
        return sale

    def test_export_then_restore_preserves_lot(self):
        from app import Lot, export_backup, restore_backup

        Lot.objects.create(**LOT_DEFAULTS)
        data = export_backup()
        Lot.objects.all().delete()

        restore_backup(data)
        lot = Lot.objects.get()
        assert lot.symbol == "AAPL"
        assert lot.grant_date == date(2019, 8, 1)
        assert lot.sellable_qty == Decimal("10.0000")
        assert lot.cost_basis == Decimal("100.00000")

    def test_export_then_restore_preserves_sale_and_timestamp(self):
        from app import Sale, SaleLot, export_backup, restore_backup

        original = self._make_sale()
        data = export_backup()
        Sale.objects.all().delete()

        restore_backup(data)
        sale = Sale.objects.get()
        assert sale.created_at == original.created_at
        assert sale.tax_usd == Decimal("260.00000")
        slot = SaleLot.objects.get()
        assert slot.original_lot_id == 42
        assert slot.grant_date == date(2020, 3, 15)
        assert slot.qty_sold == Decimal("5.0000")

    def test_export_then_restore_preserves_sale_date(self):
        from app import Sale, export_backup, restore_backup

        sale = self._make_sale()
        sale.sale_date = date(2023, 6, 10)
        sale.save()
        data = export_backup()
        Sale.objects.all().delete()

        restore_backup(data)
        assert Sale.objects.get().sale_date == date(2023, 6, 10)

    def test_restore_backup_without_sale_date_falls_back_to_created_at(self):
        from app import Sale, export_backup, restore_backup

        original = self._make_sale()
        data = export_backup()
        data["sales"][0].pop("sale_date")
        Sale.objects.all().delete()

        restore_backup(data)
        assert Sale.objects.get().sale_date == original.created_at.date()

    def test_restore_handles_null_grant_dates(self):
        from app import Lot, export_backup, restore_backup

        Lot.objects.create(**{**LOT_DEFAULTS, "grant_date": None})
        data = export_backup()
        Lot.objects.all().delete()

        restore_backup(data)
        assert Lot.objects.get().grant_date is None

    def test_restore_rejects_non_dict(self):
        from app import BackupError, restore_backup

        with pytest.raises(BackupError):
            restore_backup(["not", "a", "dict"])
