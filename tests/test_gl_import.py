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


def _current_year():
    from django.utils import timezone

    return timezone.localdate().year


def _lot_kwargs(**overrides):
    kwargs = {
        "symbol": "AAPL",
        "plan_type": "RSU",
        "date_acquired": date(2022, 10, 15),
        "cost_basis": Decimal("146.54000"),
        "sellable_qty": Decimal("5"),
        "tax_status": "Long Term",
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.django_db
@pytest.mark.usefixtures("fixed_rate")
class TestImportGainsLossesPortfolioUpdate:
    def _current_year_order(self, **overrides):
        return _order(sale_date=date(_current_year(), 5, 12), **overrides)

    def test_matches_and_reduces_live_lot(self):
        from app import Lot, import_gains_losses

        Lot.objects.create(**_lot_kwargs())
        import_gains_losses([self._current_year_order()], mode="overwrite", year=_current_year())
        lot = Lot.objects.get(date_acquired=date(2022, 10, 15))
        assert lot.sellable_qty == Decimal("3")

    def test_deletes_lot_fully_consumed(self):
        from app import Lot, import_gains_losses

        Lot.objects.create(**_lot_kwargs(sellable_qty=Decimal("2")))
        import_gains_losses([self._current_year_order()], mode="overwrite", year=_current_year())
        assert not Lot.objects.filter(date_acquired=date(2022, 10, 15)).exists()

    def test_sale_lot_records_matched_original_lot_id(self):
        from app import Lot, SaleLot, import_gains_losses

        lot = Lot.objects.create(**_lot_kwargs())
        import_gains_losses([self._current_year_order()], mode="overwrite", year=_current_year())
        slot = SaleLot.objects.get(date_acquired=date(2022, 10, 15))
        assert slot.original_lot_id == lot.pk

    def test_unmatched_tranche_leaves_no_lot_behind(self):
        from app import Lot, import_gains_losses

        import_gains_losses([self._current_year_order()], mode="overwrite", year=_current_year())
        assert Lot.objects.count() == 0

    def test_past_year_never_mutates_portfolio_even_when_flag_set(self):
        from app import Lot, import_gains_losses

        Lot.objects.create(**_lot_kwargs())
        import_gains_losses([_order()], mode="overwrite", year=2024, update_portfolio=True)
        lot = Lot.objects.get(date_acquired=date(2022, 10, 15))
        assert lot.sellable_qty == Decimal("5")

    def test_update_portfolio_false_skips_mutation_for_current_year(self):
        from app import Lot, import_gains_losses

        Lot.objects.create(**_lot_kwargs())
        import_gains_losses(
            [self._current_year_order()],
            mode="overwrite",
            year=_current_year(),
            update_portfolio=False,
        )
        lot = Lot.objects.get(date_acquired=date(2022, 10, 15))
        assert lot.sellable_qty == Decimal("5")

    def test_sale_lot_has_no_original_lot_id_when_update_portfolio_false(self):
        from app import Lot, SaleLot, import_gains_losses

        Lot.objects.create(**_lot_kwargs())
        import_gains_losses(
            [self._current_year_order()],
            mode="overwrite",
            year=_current_year(),
            update_portfolio=False,
        )
        assert all(sl.original_lot_id is None for sl in SaleLot.objects.all())

    def test_overwrite_rerun_is_idempotent_on_portfolio(self):
        from app import Lot, import_gains_losses

        Lot.objects.create(**_lot_kwargs())
        year = _current_year()
        import_gains_losses([self._current_year_order()], mode="overwrite", year=year)
        import_gains_losses([self._current_year_order()], mode="overwrite", year=year)
        lot = Lot.objects.get(date_acquired=date(2022, 10, 15))
        assert lot.sellable_qty == Decimal("3")

    def test_unmatched_tranche_is_reported(self):
        from app import import_gains_losses

        warnings = []
        import_gains_losses(
            [self._current_year_order()],
            mode="overwrite",
            year=_current_year(),
            unmatched_warnings=warnings,
        )
        assert len(warnings) == 2
        assert warnings[0]["symbol"] == "AAPL"
        assert warnings[0]["date_acquired"] == date(2022, 10, 15)

    def test_matched_tranche_is_not_reported(self):
        from app import Lot, import_gains_losses

        Lot.objects.create(**_lot_kwargs())
        Lot.objects.create(
            **_lot_kwargs(date_acquired=date(2021, 10, 15), cost_basis=Decimal("143.76000"))
        )
        warnings = []
        import_gains_losses(
            [self._current_year_order()],
            mode="overwrite",
            year=_current_year(),
            unmatched_warnings=warnings,
        )
        assert warnings == []

    def test_past_year_never_reports_unmatched(self):
        from app import import_gains_losses

        warnings = []
        import_gains_losses([_order()], mode="overwrite", year=2024, unmatched_warnings=warnings)
        assert warnings == []

    def test_overwrite_delete_does_not_double_restore_already_deleted_sale(self):
        from app import Lot, Sale, import_gains_losses

        Lot.objects.create(**_lot_kwargs())
        year = _current_year()
        import_gains_losses([self._current_year_order()], mode="overwrite", year=year)
        sale = Sale.objects.get(order_number="102663927")
        from django.utils import timezone

        from app import _restore_sale_to_portfolio

        _restore_sale_to_portfolio(sale)
        sale.deleted_at = timezone.now()
        sale.save()
        lot = Lot.objects.get(date_acquired=date(2022, 10, 15))
        assert lot.sellable_qty == Decimal("5")

        import_gains_losses([self._current_year_order()], mode="overwrite", year=year)
        lot.refresh_from_db()
        assert lot.sellable_qty == Decimal("3")

    def test_overwrite_with_extended_second_import_does_not_duplicate_sales(self):
        from app import Sale, import_gains_losses

        year = _current_year()
        first_order = self._current_year_order()
        import_gains_losses([first_order], mode="overwrite", year=year)
        second_order = _order(order_number="999999999", sale_date=date(year, 6, 20))
        import_gains_losses([first_order, second_order], mode="overwrite", year=year)
        assert Sale.objects.count() == 2
        assert Sale.objects.filter(order_number="102663927").count() == 1
        assert Sale.objects.filter(order_number="999999999").count() == 1
