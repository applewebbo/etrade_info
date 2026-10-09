from datetime import date
from decimal import Decimal

import pytest


def _order(order_number="102663927", sale_date=date(2024, 5, 12), **overrides):
    order = {
        "order_number": order_number,
        "sale_date": sale_date,
        "sale_price_usd": Decimal("294.99500"),
        "tranches": [
            {
                "symbol": "AAPL",
                "plan_type": "RSU",
                "date_acquired": date(2022, 10, 15),
                "grant_date": date(2021, 9, 26),
                "qty": Decimal("2"),
                "cost_basis": Decimal("146.54000"),
                "tax_status": "Long Term",
            },
            {
                "symbol": "AAPL",
                "plan_type": "RSU",
                "date_acquired": date(2021, 10, 15),
                "grant_date": date(2019, 9, 29),
                "qty": Decimal("6"),
                "cost_basis": Decimal("143.76000"),
                "tax_status": "Long Term",
            },
        ],
    }
    order.update(overrides)
    return order


@pytest.fixture
def fixed_rate(monkeypatch):
    monkeypatch.setattr("app._resolve_sale_rate", lambda sale_date: Decimal("1.10"))


@pytest.mark.django_db
@pytest.mark.usefixtures("fixed_rate")
class TestImportGainsLosses:
    def test_creates_one_sale_per_order(self):
        from app import Sale, import_gains_losses

        created = import_gains_losses([_order()], mode="overwrite", year=2024)
        assert created == 1
        assert Sale.objects.count() == 1
        assert Sale.objects.first().order_number == "102663927"

    def test_creates_one_sale_lot_per_tranche(self):
        from app import SaleLot, import_gains_losses

        import_gains_losses([_order()], mode="overwrite", year=2024)
        assert SaleLot.objects.count() == 2

    def test_sale_lot_has_no_original_lot_id(self):
        from app import SaleLot, import_gains_losses

        import_gains_losses([_order()], mode="overwrite", year=2024)
        assert all(sl.original_lot_id is None for sl in SaleLot.objects.all())

    def test_computes_gain_from_sale_price_and_cost_basis(self):
        from app import Sale, import_gains_losses

        import_gains_losses([_order()], mode="overwrite", year=2024)
        sale = Sale.objects.first()
        gross = Decimal("294.99500") * Decimal("8")
        cost = Decimal("146.54000") * Decimal("2") + Decimal("143.76000") * Decimal("6")
        assert sale.gross_proceeds_usd == gross
        assert sale.net_gain_usd == gross - cost

    def test_skips_orders_outside_selected_year(self):
        from app import Sale, import_gains_losses

        import_gains_losses([_order(sale_date=date(2023, 5, 12))], mode="overwrite", year=2024)
        assert Sale.objects.count() == 0

    def test_overwrite_is_idempotent_on_rerun(self):
        from app import Sale, import_gains_losses

        import_gains_losses([_order()], mode="overwrite", year=2024)
        import_gains_losses([_order()], mode="overwrite", year=2024)
        assert Sale.objects.count() == 1

    def test_overwrite_replaces_previously_imported_orders(self):
        from app import Sale, import_gains_losses

        import_gains_losses([_order()], mode="overwrite", year=2024)
        other = _order(order_number="999999999")
        import_gains_losses([other], mode="overwrite", year=2024)
        assert Sale.objects.count() == 1
        assert Sale.objects.first().order_number == "999999999"

    def test_overwrite_does_not_touch_manual_sales(self):
        from app import Sale, import_gains_losses

        Sale.objects.create(
            sale_date=date(2024, 3, 1),
            sale_price_usd=Decimal("100.00000"),
            eur_usd_rate=Decimal("1.10"),
            gross_proceeds_usd=Decimal("1000.00000"),
            net_gain_usd=Decimal("100.00000"),
            tax_usd=Decimal("26.00000"),
        )
        import_gains_losses([_order()], mode="overwrite", year=2024)
        assert Sale.objects.filter(order_number__isnull=True).count() == 1
        assert Sale.objects.filter(order_number__isnull=False).count() == 1

    def test_incremental_skips_already_recorded_order(self):
        from app import Sale, import_gains_losses

        import_gains_losses([_order()], mode="incremental", year=2024)
        created = import_gains_losses([_order()], mode="incremental", year=2024)
        assert created == 0
        assert Sale.objects.count() == 1

    def test_incremental_adds_missing_order(self):
        from app import Sale, import_gains_losses

        import_gains_losses([_order()], mode="incremental", year=2024)
        other = _order(order_number="999999999")
        created = import_gains_losses([other], mode="incremental", year=2024)
        assert created == 1
        assert Sale.objects.count() == 2

    def test_returns_zero_when_rate_unavailable(self, monkeypatch):
        from app import Sale, import_gains_losses

        monkeypatch.setattr("app._resolve_sale_rate", lambda sale_date: None)
        created = import_gains_losses([_order()], mode="overwrite", year=2024)
        assert created == 0
        assert Sale.objects.count() == 0
