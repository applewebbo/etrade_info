import io
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

LOT_DEFAULTS = dict(
    symbol="AAPL",
    plan_type="ESPP",
    date_acquired=date(2020, 1, 1),
    sellable_qty=Decimal("10"),
    cost_basis=Decimal("100.00000"),
    tax_status="Long Term",
)


@pytest.fixture
def mock_prices(monkeypatch):
    """Patch prices module to avoid network calls in view tests."""
    import prices

    monkeypatch.setattr(prices, "get_stock_price_usd", lambda: Decimal("200.00000"))
    monkeypatch.setattr(prices, "get_eur_usd_rate", lambda: Decimal("1.10000"))
    monkeypatch.setattr(prices, "is_price_stale", lambda ticker: False)
    monkeypatch.setattr(prices, "get_price_direction", lambda ticker: "neutral")


@pytest.mark.django_db
class TestResetView:
    def test_post_deletes_all_lots(self, client):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        assert Lot.objects.count() == 1
        client.post("/reset/")
        assert Lot.objects.count() == 0

    def test_post_returns_hx_redirect(self, client):
        response = client.post("/reset/")
        assert response.status_code == 200
        assert response.headers.get("HX-Redirect") == "/"

    def test_post_with_no_lots_still_succeeds(self, client):
        from app import Lot

        assert Lot.objects.count() == 0
        response = client.post("/reset/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestExportView:
    def test_returns_json_backup_file(self, client):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/export/")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        assert ".json" in response["Content-Disposition"]

    def test_backup_contains_lots_and_sales(self, client):
        import json

        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/export/")
        data = json.loads(response.content)
        assert data["version"] == 1
        assert "exported_at" in data
        assert len(data["lots"]) == 1
        assert data["lots"][0]["symbol"] == "AAPL"
        assert data["lots"][0]["cost_basis"] == "100.00000"
        assert data["sales"] == []

    def test_empty_db_returns_valid_backup(self, client):
        import json

        response = client.get("/export/")
        data = json.loads(response.content)
        assert data["lots"] == []
        assert data["sales"] == []


@pytest.mark.django_db
class TestRestoreView:
    def _backup_file(self, data):
        import json

        return io.BytesIO(json.dumps(data).encode())

    def test_restore_rebuilds_portfolio(self, client):
        from app import Lot, export_backup

        Lot.objects.create(**LOT_DEFAULTS)
        backup = export_backup()
        Lot.objects.all().delete()

        f = self._backup_file(backup)
        f.name = "backup.json"
        response = client.post("/restore/", {"backup": f})
        assert response.status_code == 302
        assert Lot.objects.count() == 1
        assert Lot.objects.first().cost_basis == Decimal("100.00000")

    def test_restore_overwrites_existing_data(self, client):
        from app import Lot, export_backup

        Lot.objects.create(**LOT_DEFAULTS)
        backup = export_backup()
        Lot.objects.all().delete()
        Lot.objects.create(**{**LOT_DEFAULTS, "symbol": "MSFT"})

        f = self._backup_file(backup)
        f.name = "backup.json"
        client.post("/restore/", {"backup": f})
        assert Lot.objects.count() == 1
        assert Lot.objects.first().symbol == "AAPL"

    def test_restore_invalid_json_returns_400(self, client):
        f = io.BytesIO(b"not json")
        f.name = "backup.json"
        response = client.post("/restore/", {"backup": f})
        assert response.status_code == 400

    def test_restore_wrong_version_returns_400(self, client):
        f = self._backup_file({"version": 999, "lots": [], "sales": []})
        f.name = "backup.json"
        response = client.post("/restore/", {"backup": f})
        assert response.status_code == 400

    def test_get_redirects_to_import(self, client):
        response = client.get("/restore/")
        assert response.status_code == 302
        assert response["Location"] == "/import/"

    def test_post_without_file_redirects_to_import(self, client):
        response = client.post("/restore/")
        assert response.status_code == 302
        assert response["Location"] == "/import/"


SALE_DEFAULTS = dict(
    sale_price_usd="200.00000",
    eur_usd_rate="1.100000",
    gross_proceeds_usd="2000.00000",
    net_gain_usd="1000.00000",
    tax_usd="260.00000",
)


@pytest.mark.django_db
class TestSellView:
    def _post_sell(self, client, lot, qty="10", sale_price="200", eur_usd="1.1"):
        return client.post(
            "/sell/",
            {f"qty_{lot.pk}": qty, "sale_price": sale_price, "eur_usd": eur_usd},
        )

    def test_post_creates_sale(self, client):
        from app import Lot, Sale

        lot = Lot.objects.create(**LOT_DEFAULTS)
        self._post_sell(client, lot)
        assert Sale.objects.count() == 1

    def test_post_creates_sale_lot_records(self, client):
        from app import Lot, Sale, SaleLot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        self._post_sell(client, lot)
        sale = Sale.objects.first()
        assert SaleLot.objects.filter(sale=sale).count() == 1
        slot = SaleLot.objects.first()
        assert slot.original_lot_id == lot.pk
        assert slot.qty_sold == Decimal("10")

    def test_post_removes_fully_sold_lot(self, client):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        self._post_sell(client, lot, qty="10")
        assert Lot.objects.count() == 0

    def test_post_reduces_partially_sold_lot(self, client):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        self._post_sell(client, lot, qty="4")
        updated = Lot.objects.get(pk=lot.pk)
        assert updated.sellable_qty == Decimal("6")

    def test_post_returns_sell_success_partial(self, client):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        response = self._post_sell(client, lot)
        assert response.status_code == 200
        assert b"Vendita effettuata" in response.content

    def test_post_sets_hx_trigger_sale_complete(self, client):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        response = self._post_sell(client, lot)
        assert response["HX-Trigger"] == "saleComplete"

    def test_post_with_no_selection_creates_no_sale(self, client):
        from app import Lot, Sale

        Lot.objects.create(**LOT_DEFAULTS)
        client.post("/sell/", {"sale_price": "200", "eur_usd": "1.1"})
        assert Sale.objects.count() == 0

    def test_post_records_correct_sale_totals(self, client):
        from app import Lot, Sale

        lot = Lot.objects.create(**LOT_DEFAULTS)
        self._post_sell(client, lot, qty="10", sale_price="200", eur_usd="1.1")
        sale = Sale.objects.first()
        assert sale.sale_price_usd == Decimal("200")
        assert sale.gross_proceeds_usd == Decimal("2000")
        assert sale.tax_usd == Decimal("260")

    def test_post_stores_given_sale_date(self, client):
        from app import Lot, Sale

        lot = Lot.objects.create(**LOT_DEFAULTS)
        client.post(
            "/sell/",
            {
                f"qty_{lot.pk}": "10",
                "sale_price": "200",
                "eur_usd": "1.1",
                "sale_date": "2024-03-20",
            },
        )
        assert Sale.objects.first().sale_date == date(2024, 3, 20)

    def test_post_without_sale_date_defaults_to_today(self, client):
        from django.utils import timezone

        from app import Lot, Sale

        lot = Lot.objects.create(**LOT_DEFAULTS)
        self._post_sell(client, lot)
        assert Sale.objects.first().sale_date == timezone.localdate()


@pytest.mark.django_db
class TestSaleDeleteView:
    def _create_sale_with_lot(self, sale_date=None):
        from app import Lot, Sale, SaleLot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        kwargs = {k: Decimal(v) for k, v in SALE_DEFAULTS.items()}
        if sale_date:
            kwargs["sale_date"] = sale_date
        sale = Sale.objects.create(**kwargs)
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=lot.pk,
            symbol=lot.symbol,
            plan_type=lot.plan_type,
            date_acquired=lot.date_acquired,
            qty_sold=lot.sellable_qty,
            cost_basis=lot.cost_basis,
            tax_status=lot.tax_status,
            gain_usd=Decimal("1000.00000"),
        )
        lot.delete()
        return sale

    def test_post_restores_deleted_lot(self, client):
        from app import Lot

        sale = self._create_sale_with_lot()
        assert Lot.objects.count() == 0
        client.post(f"/sell/delete/{sale.pk}/")
        assert Lot.objects.count() == 1
        restored = Lot.objects.first()
        assert restored.sellable_qty == Decimal("10")

    def test_post_restores_partial_lot_qty(self, client):
        from app import Lot, Sale, SaleLot

        lot = Lot.objects.create(**{**LOT_DEFAULTS, "sellable_qty": Decimal("6")})
        sale = Sale.objects.create(**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()})
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=lot.pk,
            symbol=lot.symbol,
            plan_type=lot.plan_type,
            date_acquired=lot.date_acquired,
            qty_sold=Decimal("4"),
            cost_basis=lot.cost_basis,
            tax_status=lot.tax_status,
            gain_usd=Decimal("400.00000"),
        )
        client.post(f"/sell/delete/{sale.pk}/")
        updated = Lot.objects.get(pk=lot.pk)
        assert updated.sellable_qty == Decimal("10")

    def test_post_soft_deletes_sale(self, client):
        from app import Sale

        sale = self._create_sale_with_lot()
        client.post(f"/sell/delete/{sale.pk}/")
        sale.refresh_from_db()
        assert sale.deleted_at is not None
        assert Sale.objects.count() == 1

    def test_post_returns_hx_redirect_to_dashboard(self, client):
        sale = self._create_sale_with_lot()
        response = client.post(f"/sell/delete/{sale.pk}/")
        assert response.status_code == 200
        assert response.headers.get("HX-Redirect") == "/"

    def test_past_year_sale_cannot_be_deleted(self, client):
        sale = self._create_sale_with_lot(sale_date=date(2020, 1, 1))
        client.post(f"/sell/delete/{sale.pk}/")
        sale.refresh_from_db()
        assert sale.deleted_at is None

    def test_already_deleted_sale_is_a_noop(self, client):
        from django.utils import timezone

        sale = self._create_sale_with_lot()
        sale.deleted_at = timezone.now()
        sale.save()
        first_deleted_at = sale.deleted_at
        client.post(f"/sell/delete/{sale.pk}/")
        sale.refresh_from_db()
        assert sale.deleted_at == first_deleted_at

    def test_purges_oldest_deletion_beyond_five(self, client):
        from app import Sale

        sales = [self._create_sale_with_lot() for _ in range(6)]
        for sale in sales:
            client.post(f"/sell/delete/{sale.pk}/")
        assert Sale.objects.filter(deleted_at__isnull=False).count() == 5
        assert not Sale.objects.filter(pk=sales[0].pk).exists()

    def test_get_redirects_to_dashboard(self, client):
        response = client.get("/sell/delete/1/")
        assert response.status_code == 302
        assert response.url == "/"

    def test_post_with_unknown_sale_id_is_safe(self, client):
        response = client.post("/sell/delete/99999/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestSaleRestoreView:
    def _soft_deleted_sale(self):
        from django.utils import timezone

        from app import Lot, Sale, SaleLot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        sale = Sale.objects.create(
            **{k: Decimal(v) for k, v in SALE_DEFAULTS.items()},
            deleted_at=timezone.now(),
        )
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=lot.pk,
            symbol=lot.symbol,
            plan_type=lot.plan_type,
            date_acquired=lot.date_acquired,
            qty_sold=lot.sellable_qty,
            cost_basis=lot.cost_basis,
            tax_status=lot.tax_status,
            gain_usd=Decimal("1000.00000"),
        )
        return sale, lot

    def test_post_reduces_lot_again(self, client):
        from app import Lot

        sale, lot = self._soft_deleted_sale()
        client.post(f"/sell/restore/{sale.pk}/")
        assert not Lot.objects.filter(pk=lot.pk).exists()

    def test_post_clears_deleted_at(self, client):
        sale, _ = self._soft_deleted_sale()
        client.post(f"/sell/restore/{sale.pk}/")
        sale.refresh_from_db()
        assert sale.deleted_at is None

    def test_post_returns_hx_redirect_to_import(self, client):
        sale, _ = self._soft_deleted_sale()
        response = client.post(f"/sell/restore/{sale.pk}/")
        assert response.status_code == 200
        assert response.headers.get("HX-Redirect") == "/import/"

    def test_post_reduces_partial_qty_when_lot_qty_exceeds_sale(self, client):
        from django.utils import timezone

        from app import Lot, Sale, SaleLot

        lot = Lot.objects.create(**{**LOT_DEFAULTS, "sellable_qty": Decimal("10")})
        sale = Sale.objects.create(
            **{k: Decimal(v) for k, v in SALE_DEFAULTS.items()},
            deleted_at=timezone.now(),
        )
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=lot.pk,
            symbol=lot.symbol,
            plan_type=lot.plan_type,
            date_acquired=lot.date_acquired,
            qty_sold=Decimal("4"),
            cost_basis=lot.cost_basis,
            tax_status=lot.tax_status,
            gain_usd=Decimal("400.00000"),
        )
        client.post(f"/sell/restore/{sale.pk}/")
        lot.refresh_from_db()
        assert lot.sellable_qty == Decimal("6")

    def test_post_with_unmatched_original_lot_id_is_a_noop(self, client):
        from django.utils import timezone

        from app import Sale, SaleLot

        sale = Sale.objects.create(
            **{k: Decimal(v) for k, v in SALE_DEFAULTS.items()},
            deleted_at=timezone.now(),
        )
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=None,
            symbol="AAPL",
            plan_type="ESPP",
            date_acquired=date(2020, 1, 1),
            qty_sold=Decimal("5"),
            cost_basis=Decimal("100.00000"),
            tax_status="Long Term",
            gain_usd=Decimal("500.00000"),
        )
        response = client.post(f"/sell/restore/{sale.pk}/")
        assert response.status_code == 200
        sale.refresh_from_db()
        assert sale.deleted_at is None

    def test_post_with_no_matching_live_lot_is_a_noop(self, client):
        from django.utils import timezone

        from app import Lot, Sale, SaleLot

        sale = Sale.objects.create(
            **{k: Decimal(v) for k, v in SALE_DEFAULTS.items()},
            deleted_at=timezone.now(),
        )
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=999999,
            symbol="AAPL",
            plan_type="ESPP",
            date_acquired=date(2020, 1, 1),
            qty_sold=Decimal("5"),
            cost_basis=Decimal("100.00000"),
            tax_status="Long Term",
            gain_usd=Decimal("500.00000"),
        )
        client.post(f"/sell/restore/{sale.pk}/")
        assert Lot.objects.count() == 0
        sale.refresh_from_db()
        assert sale.deleted_at is None

    def test_post_on_non_deleted_sale_is_a_noop(self, client):
        from app import Sale

        sale = Sale.objects.create(**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()})
        client.post(f"/sell/restore/{sale.pk}/")
        sale.refresh_from_db()
        assert sale.deleted_at is None

    def test_get_redirects_to_import(self, client):
        response = client.get("/sell/restore/1/")
        assert response.status_code == 302
        assert "/import/" in response.url


@pytest.mark.django_db
class TestDashboardSales:
    def test_dashboard_shows_sales_section_when_sales_exist(self, client):
        from app import Sale

        Sale.objects.create(**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()})
        response = client.get("/")
        assert response.status_code == 200
        assert b"Vendite effettuate" in response.content

    def test_dashboard_no_sales_section_when_empty(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"Vendite effettuate" not in response.content

    def test_dashboard_excludes_soft_deleted_sales(self, client):
        from django.utils import timezone

        from app import Sale

        Sale.objects.create(
            **{k: Decimal(v) for k, v in SALE_DEFAULTS.items()},
            deleted_at=timezone.now(),
        )
        response = client.get("/")
        assert b"Vendite effettuate" not in response.content

    def test_dashboard_shows_year_selector_with_multiple_years(self, client):
        from app import Sale

        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2023, 5, 1)}
        )
        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2024, 5, 1)}
        )
        response = client.get("/")
        assert b'value="2023"' in response.content
        assert b'value="2024"' in response.content

    def test_dashboard_year_selector_has_no_duplicate_options_for_same_year(self, client):
        from app import Sale

        for i in range(3):
            Sale.objects.create(
                **{
                    **{k: Decimal(v) for k, v in SALE_DEFAULTS.items()},
                    "sale_date": date(2024, i + 1, 1),
                }
            )
        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2023, 5, 1)}
        )
        response = client.get("/")
        assert response.content.count(b'value="2024"') == 1

    def test_dashboard_defaults_to_most_recent_sale_year(self, client):
        from app import Sale

        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2023, 5, 1)}
        )
        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2024, 5, 1)}
        )
        response = client.get("/")
        assert b'value="2024" selected' in response.content

    def test_dashboard_lists_sales_for_selected_year_in_chronological_order(self, client):
        from app import Sale

        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2024, 6, 1)}
        )
        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2024, 1, 1)}
        )
        response = client.get("/?year=2024")
        content = response.content.decode()
        assert content.index("01/01/2024") < content.index("01/06/2024")

    def test_dashboard_excludes_other_years(self, client):
        from app import Sale

        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2023, 5, 1)}
        )
        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2024, 5, 1)}
        )
        response = client.get("/?year=2024")
        assert b"01/05/2023" not in response.content
        assert b"01/05/2024" in response.content

    def test_dashboard_shows_delete_button_for_current_year_sale(self, client):
        from app import Sale

        Sale.objects.create(**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()})
        response = client.get("/")
        assert b"Elimina" in response.content

    def test_dashboard_hides_delete_button_for_past_year_sale(self, client):
        from app import Sale

        Sale.objects.create(
            **{**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()}, "sale_date": date(2020, 1, 1)}
        )
        response = client.get("/?year=2020")
        assert b"Elimina" not in response.content


@pytest.mark.django_db
class TestImportViewDeletedSales:
    def test_shows_recent_deletions_section_when_present(self, client):
        from django.utils import timezone

        from app import Sale

        Sale.objects.create(
            **{k: Decimal(v) for k, v in SALE_DEFAULTS.items()},
            deleted_at=timezone.now(),
        )
        response = client.get("/import/")
        assert response.status_code == 200
        assert b"Gestisci Vendite" in response.content
        assert b"Ripristina" in response.content
        assert b"Qui puoi vedere le ultime vendite eliminate dalla dashboard." in response.content

    def test_no_deletions_section_when_empty(self, client):
        response = client.get("/import/")
        assert response.status_code == 200
        assert b"Gestisci Vendite" not in response.content

    def test_shows_only_last_five_deletions(self, client):
        from django.utils import timezone

        from app import Sale

        for i in range(6):
            Sale.objects.create(
                **{
                    **{k: Decimal(v) for k, v in SALE_DEFAULTS.items()},
                    "sale_date": date(2025, 1, i + 1),
                },
                deleted_at=timezone.now(),
            )
        response = client.get("/import/")
        assert response.content.count(b"/sell/restore/") == 5

    def test_no_storico_vendite_card(self, client):
        from app import Sale

        Sale.objects.create(**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()})
        response = client.get("/import/")
        assert b"Storico vendite" not in response.content
        assert b"Annulla ultima vendita" not in response.content


@pytest.mark.django_db
class TestSellViewEdgeCases:
    def test_get_redirects_to_simulate(self, client):
        response = client.get("/sell/")
        assert response.status_code == 302
        assert "/simulate/" in response.url

    def test_post_with_invalid_sale_price_redirects(self, client):
        response = client.post("/sell/", {"sale_price": "not-a-number", "eur_usd": "1.1"})
        assert response.status_code == 302
        assert "/simulate/" in response.url

    def test_post_with_zero_sale_price_redirects(self, client):
        response = client.post("/sell/", {"sale_price": "0", "eur_usd": "1.1"})
        assert response.status_code == 302
        assert "/simulate/" in response.url

    def test_post_with_invalid_qty_treats_lot_as_unselected(self, client):
        from app import Lot, Sale

        lot = Lot.objects.create(**LOT_DEFAULTS)
        response = client.post(
            "/sell/",
            {f"qty_{lot.pk}": "not-a-number", "sale_price": "200", "eur_usd": "1.1"},
        )
        assert response.status_code == 200
        assert Sale.objects.count() == 0


@pytest.mark.django_db
class TestSimulateLotsView:
    def test_returns_lot_tables_partial(self, client, mock_prices):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/simulate/lots/")
        assert response.status_code == 200
        assert b"sim-form" in response.content

    def test_excludes_deleted_lots(self, client, mock_prices):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        pk = lot.pk
        lot.delete()
        response = client.get("/simulate/lots/")
        assert f"qty_{pk}".encode() not in response.content

    def test_shows_updated_qty_after_sell(self, client, mock_prices):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        lot.sellable_qty = Decimal("3")
        lot.save()
        response = client.get("/simulate/lots/")
        assert b"3" in response.content


@pytest.mark.django_db
class TestDashboardView:
    def test_page_links_tailwind_css(self, client, mock_prices):
        response = client.get("/")
        content = response.content.decode()
        assert "/static/css/tailwind.css" in content
        assert "/static/css/custom.css" in content
        assert "/static/blades.min.css" not in content
        assert "/static/pico.colors.min.css" not in content

    def test_dashboard_with_lots_defers_portfolio_body_to_htmx(self, client, mock_prices):
        """Regression test: the dashboard view used to call _portfolio_context()
        synchronously, blocking the whole response on a live yfinance round-trip
        (~2s). It now returns instantly and defers the priced body to /portfolio/
        via HTMX (hx-trigger="load"), so first paint doesn't wait on the network."""
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/")
        assert response.status_code == 200
        assert b'hx-get="/portfolio/"' in response.content
        assert b"Valore di mercato" not in response.content

    def test_dashboard_without_lots_has_no_portfolio_fragment(self, client):
        response = client.get("/")
        assert b'hx-get="/portfolio/"' not in response.content


@pytest.mark.django_db
class TestPortfolioFragment:
    def test_returns_kpi_and_table_with_prices(self, client, mock_prices):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/portfolio/")
        assert response.status_code == 200
        assert b"Valore di mercato" in response.content

    def test_with_prices_unavailable(self, client, monkeypatch):
        import prices
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        monkeypatch.setattr(prices, "get_stock_price_usd", lambda: None)
        monkeypatch.setattr(prices, "get_eur_usd_rate", lambda: None)
        monkeypatch.setattr(prices, "is_price_stale", lambda ticker: False)
        monkeypatch.setattr(prices, "get_price_direction", lambda ticker: "neutral")
        response = client.get("/portfolio/")
        assert response.status_code == 200
        assert b"quotazioni" in response.content


@pytest.mark.django_db
class TestPricesFragment:
    def test_get_returns_price_header_partial(self, client, mock_prices):
        response = client.get("/prices/")
        assert response.status_code == 200

    def test_get_with_prices_unavailable(self, client, monkeypatch):
        import prices

        monkeypatch.setattr(prices, "get_stock_price_usd", lambda: None)
        monkeypatch.setattr(prices, "get_eur_usd_rate", lambda: None)
        monkeypatch.setattr(prices, "is_price_stale", lambda ticker: False)
        monkeypatch.setattr(prices, "get_price_direction", lambda ticker: "neutral")
        response = client.get("/prices/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestImportViewPost:
    def test_post_with_xlsx_imports_lots(self, client):
        from app import Lot

        data = {
            "Record Type": ["Purchase"],
            "Symbol": ["AAPL"],
            "Plan Type": ["ESPP"],
            "Date Acquired": ["31-JAN-2015"],
            "Sellable Qty.": [10.0],
            "Est. Cost Basis (per share):": [100.0],
            "Tax Status.1": ["Long Term"],
        }
        import io

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame(data).to_excel(writer, sheet_name="Sellable", index=False)
        buf.seek(0)
        buf.name = "test.xlsx"

        response = client.post(
            "/import/",
            {"xlsx": buf, "mode": "overwrite"},
            format="multipart",
        )
        assert response.status_code == 302
        assert Lot.objects.count() == 1

    def test_post_with_gl_xlsx_imports_sales_and_redirects_to_tasse(self, client, monkeypatch):
        import io

        import bdi_rates
        from app import Sale

        monkeypatch.setattr(
            bdi_rates, "get_bdi_eur_usd_rate", lambda d, fetcher=None: Decimal("1.10")
        )

        data = {
            "Record Type": ["Sell"],
            "Symbol": ["AAPL"],
            "Plan Type": ["RS"],
            "Quantity": [2],
            "Date Acquired": ["10/15/2022"],
            "Adjusted Cost Basis Per Share": [146.54],
            "Date Sold": ["05/12/2024"],
            "Total Proceeds": [589.99],
            "Capital Gains Status": ["Long"],
            "Grant Date": ["09/26/2021"],
            "Order Number": [102663927.0],
        }
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame(data).to_excel(writer, sheet_name="G&L_Expanded", index=False)
        buf.seek(0)
        buf.name = "gl.xlsx"

        response = client.post(
            "/import/",
            {"gl_xlsx": buf, "gl_mode": "overwrite", "year": "2024"},
            format="multipart",
        )
        assert response.status_code == 302
        assert response["Location"] == "/tasse/?year=2024"
        assert Sale.objects.count() == 1
        assert Sale.objects.first().order_number == "102663927"

    def test_post_with_gl_xlsx_current_year_unmatched_tranche_flags_redirect(
        self, client, monkeypatch
    ):
        import io

        from django.utils import timezone

        import bdi_rates

        current_year = timezone.localdate().year

        monkeypatch.setattr(
            bdi_rates, "get_bdi_eur_usd_rate", lambda d, fetcher=None: Decimal("1.10")
        )

        data = {
            "Record Type": ["Sell"],
            "Symbol": ["AAPL"],
            "Plan Type": ["RS"],
            "Quantity": [2],
            "Date Acquired": ["10/15/2022"],
            "Adjusted Cost Basis Per Share": [146.54],
            "Date Sold": [f"05/12/{current_year}"],
            "Total Proceeds": [589.99],
            "Capital Gains Status": ["Long"],
            "Grant Date": ["09/26/2021"],
            "Order Number": [102663927.0],
        }
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            pd.DataFrame(data).to_excel(writer, sheet_name="G&L_Expanded", index=False)
        buf.seek(0)
        buf.name = "gl.xlsx"

        response = client.post(
            "/import/",
            {
                "gl_xlsx": buf,
                "gl_mode": "overwrite",
                "year": str(current_year),
                "update_portfolio": "on",
            },
            format="multipart",
        )
        assert response.status_code == 302
        assert response["Location"] == f"/tasse/?year={current_year}&unmatched=1"


@pytest.mark.django_db
class TestSimulateView:
    def test_get_renders_form(self, client, mock_prices):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/simulate/")
        assert response.status_code == 200
        assert b"Simulatore" in response.content

    def test_get_shows_sale_date_input_defaulting_to_today(self, client, mock_prices):
        from django.utils import timezone

        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/simulate/")
        assert timezone.localdate().isoformat().encode() in response.content

    def test_post_returns_simulation_result(self, client, mock_prices):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        response = client.post(
            "/simulate/",
            {f"qty_{lot.pk}": "5", "sale_price": "200"},
        )
        assert response.status_code == 200
        assert b"Risultato simulazione" in response.content

    def test_post_with_invalid_qty_treats_lot_as_unselected(self, client, mock_prices):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        response = client.post(
            "/simulate/",
            {f"qty_{lot.pk}": "not-a-number", "sale_price": "200"},
        )
        assert response.status_code == 200

    def test_post_without_sale_date_uses_live_rate(self, client, mock_prices):
        from app import Lot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        response = client.post(
            "/simulate/",
            {f"qty_{lot.pk}": "5", "sale_price": "200"},
        )
        assert b'"eur_usd": "1.10000"' in response.content

    def test_post_with_past_sale_date_uses_bdi_historical_rate(
        self, client, mock_prices, monkeypatch
    ):
        import bdi_rates
        from app import Lot

        monkeypatch.setattr(
            bdi_rates, "get_bdi_eur_usd_rate", lambda d, fetcher=None: Decimal("0.80000")
        )
        lot = Lot.objects.create(**LOT_DEFAULTS)
        response = client.post(
            "/simulate/",
            {f"qty_{lot.pk}": "5", "sale_price": "200", "sale_date": "2024-01-15"},
        )
        assert response.status_code == 200
        assert b'"eur_usd": "1.25"' in response.content

    def test_post_with_past_date_and_unavailable_rate_shows_message(
        self, client, mock_prices, monkeypatch
    ):
        import bdi_rates
        from app import Lot

        monkeypatch.setattr(bdi_rates, "get_bdi_eur_usd_rate", lambda d, fetcher=None: None)
        lot = Lot.objects.create(**LOT_DEFAULTS)
        response = client.post(
            "/simulate/",
            {f"qty_{lot.pk}": "5", "sale_price": "200", "sale_date": "2024-01-15"},
        )
        assert response.status_code == 200
        assert b"cambio storico non disponibile" in response.content.lower()


class TestHoldingPeriodLabel:
    def test_exactly_three_years_is_long_term(self):
        from app import _holding_period_label

        acquired = date(2021, 6, 15)
        today = date(2024, 6, 15)
        assert _holding_period_label(acquired, today) == "Long Term"

    def test_one_day_short_of_three_years_is_short_term(self):
        from app import _holding_period_label

        acquired = date(2021, 6, 15)
        today = date(2024, 6, 14)
        assert _holding_period_label(acquired, today) == "Short Term"

    def test_leap_day_acquisition_falls_back_to_feb_28(self):
        from app import _holding_period_label

        acquired = date(2020, 2, 29)
        today = date(2023, 2, 28)
        assert _holding_period_label(acquired, today) == "Long Term"

    def test_leap_day_acquisition_short_term_before_feb_28(self):
        from app import _holding_period_label

        acquired = date(2020, 2, 29)
        today = date(2023, 2, 27)
        assert _holding_period_label(acquired, today) == "Short Term"


@pytest.mark.django_db
class TestResolveSaleRate:
    def test_today_uses_live_rate(self, monkeypatch):
        from django.utils import timezone

        import prices
        from app import _resolve_sale_rate

        monkeypatch.setattr(prices, "get_eur_usd_rate", lambda: Decimal("1.20000"))
        assert _resolve_sale_rate(timezone.localdate()) == Decimal("1.20000")

    def test_past_date_uses_bdi_rate(self, monkeypatch):
        import bdi_rates
        from app import _resolve_sale_rate

        # bdi_rates returns EUR per 1 USD ("Quantita' di valuta estera per 1
        # Dollaro"); _resolve_sale_rate must invert it to USD per 1 EUR so it
        # matches the division-based conversion used everywhere else.
        monkeypatch.setattr(
            bdi_rates, "get_bdi_eur_usd_rate", lambda d, fetcher=None: Decimal("0.80000")
        )
        assert _resolve_sale_rate(date(2024, 1, 15)) == Decimal("1.25")

    def test_future_date_uses_live_rate(self, monkeypatch):
        from django.utils import timezone

        import prices
        from app import _resolve_sale_rate

        monkeypatch.setattr(prices, "get_eur_usd_rate", lambda: Decimal("1.20000"))
        future = date(timezone.localdate().year + 1, 1, 1)
        assert _resolve_sale_rate(future) == Decimal("1.20000")


class TestParseSaleDate:
    def test_valid_iso_string(self):
        from app import _parse_sale_date

        assert _parse_sale_date("2024-01-15") == date(2024, 1, 15)

    def test_invalid_string_falls_back_to_today(self):
        from django.utils import timezone

        from app import _parse_sale_date

        assert _parse_sale_date("not-a-date") == timezone.localdate()

    def test_none_falls_back_to_today(self):
        from django.utils import timezone

        from app import _parse_sale_date

        assert _parse_sale_date(None) == timezone.localdate()


@pytest.fixture
def mock_ivafe_data(monkeypatch):
    """Patch external calls used by the IVAFE view."""
    import bdi_rates

    monkeypatch.setattr(
        bdi_rates,
        "get_bdi_eur_usd_rate",
        lambda target_date, fetcher=None: Decimal("0.9689"),
    )

    import yfinance as yf

    class _FakeDF:
        def __init__(self, value):
            self._value = value

        @property
        def empty(self):
            return False

        def __getitem__(self, key):
            return self

        @property
        def iloc(self):
            return _IlocHelper(self._value)

    class _IlocHelper:
        def __init__(self, value):
            self._value = value

        def __getitem__(self, idx):
            return _Item(self._value)

    class _Item:
        def __init__(self, value):
            self._value = value

        def item(self):
            return float(self._value)

    monkeypatch.setattr(yf, "download", lambda *a, **kw: _FakeDF(Decimal("250.00")))


@pytest.mark.django_db
class TestTasseView:
    def test_get_returns_200(self, client, mock_ivafe_data):
        response = client.get("/tasse/")
        assert response.status_code == 200

    def test_page_shows_tasse_title(self, client, mock_ivafe_data):
        response = client.get("/tasse/")
        assert b"Tasse" in response.content

    def test_page_shows_ivafe_section(self, client, mock_ivafe_data):
        response = client.get("/tasse/")
        assert b"IVAFE" in response.content

    def test_page_shows_no_lots_message_when_empty(self, client, mock_ivafe_data):
        response = client.get("/tasse/")
        assert b"lotti" in response.content.lower() or response.status_code == 200

    def test_unmatched_query_param_shows_warning(self, client, mock_ivafe_data):
        response = client.get("/tasse/?unmatched=2")
        assert response.status_code == 200
        assert b"non hanno trovato una corrispondenza" in response.content

    def test_invalid_unmatched_query_param_is_ignored(self, client, mock_ivafe_data):
        response = client.get("/tasse/?unmatched=not-a-number")
        assert response.status_code == 200
        assert b"non hanno trovato una corrispondenza" not in response.content

    def test_page_shows_start_and_end_values_with_lots(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/tasse/")
        assert response.status_code == 200
        assert b"2025" in response.content

    def test_page_shows_ivafe_amount_with_lots(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/tasse/")
        assert response.status_code == 200
        assert b"IVAFE" in response.content

    def test_page_shows_partial_year_lot(self, client, mock_ivafe_data):
        from datetime import date

        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2025, 6, 1)})
        response = client.get("/tasse/")
        assert response.status_code == 200

    def test_detail_table_groups_full_year_lots_into_one_dashed_row(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        Lot.objects.create(**{**LOT_DEFAULTS, "plan_type": "RSU", "symbol": "AAPL"})
        response = client.get("/tasse/")
        assert response.status_code == 200
        # both full-year lots collapse into one detail row with qty 20 (10+10),
        # so the per-type plan_type text should not appear as a row label.
        assert response.content.count(b">ESPP<") == 0
        assert response.content.count(b">RSU<") == 0
        assert b">20<" in response.content  # combined qty: 10 + 10

    def test_page_handles_empty_price_dataframe(self, client, monkeypatch):
        import bdi_rates

        monkeypatch.setattr(
            bdi_rates,
            "get_bdi_eur_usd_rate",
            lambda target_date, fetcher=None: Decimal("0.9689"),
        )
        import yfinance as yf

        class _EmptyDF:
            @property
            def empty(self):
                return True

        monkeypatch.setattr(yf, "download", lambda *a, **kw: _EmptyDF())
        response = client.get("/tasse/")
        assert response.status_code == 200

    def test_page_handles_bdi_unavailable(self, client, monkeypatch):
        import bdi_rates

        monkeypatch.setattr(
            bdi_rates,
            "get_bdi_eur_usd_rate",
            lambda target_date, fetcher=None: None,
        )
        import yfinance as yf

        monkeypatch.setattr(
            yf, "download", lambda *a, **kw: (_ for _ in ()).throw(Exception("fail"))
        )
        response = client.get("/tasse/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestTasseYearSelector:
    def test_current_year_always_included_and_selectable(self, client, mock_ivafe_data):
        response = client.get("/tasse/")
        assert response.status_code == 200
        assert b"<select" in response.content
        assert b"2026" in response.content

    def test_multiple_years_shows_selector_with_all_options(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)})
        response = client.get("/tasse/")
        assert response.status_code == 200
        assert b"<select" in response.content
        assert b"2020" in response.content
        assert b"2025" in response.content

    def test_selecting_year_changes_computation_year(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)})
        response = client.get("/tasse/", {"year": 2021})
        assert response.status_code == 200
        assert b"2021" in response.content

    def test_invalid_year_falls_back_to_default(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)})
        response = client.get("/tasse/", {"year": "not-a-year"})
        assert response.status_code == 200
        assert b"2025" in response.content

    def test_out_of_range_year_falls_back_to_default(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)})
        response = client.get("/tasse/", {"year": "1999"})
        assert response.status_code == 200
        assert b"2025" in response.content


@pytest.mark.django_db
class TestTasseInProgressYearPreview:
    def test_current_year_uses_live_price_and_rate(self, client, mock_ivafe_data, mock_prices):
        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)})
        response = client.get("/tasse/", {"year": 2026})
        assert response.status_code == 200
        assert b"200,00" in response.content  # live AAPL price from mock_prices

    def test_current_year_shows_provisional_disclaimer(self, client, mock_ivafe_data, mock_prices):
        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)})
        response = client.get("/tasse/", {"year": 2026})
        assert response.status_code == 200
        assert b"provvisori" in response.content.lower()

    def test_past_year_does_not_show_provisional_disclaimer(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)})
        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"provvisori" not in response.content.lower()

    def test_current_year_ivafe_inverts_live_rate_to_eur_per_usd(
        self, client, mock_ivafe_data, mock_prices, monkeypatch
    ):
        import prices
        from app import Lot

        # Live rate is USD per 1 EUR; calculate_ivafe needs EUR per 1 USD
        # (the same convention Banca d'Italia's historical rate uses), so
        # 1.25 USD/EUR must become 0.8 EUR/USD, not be used as-is.
        monkeypatch.setattr(prices, "get_eur_usd_rate", lambda: Decimal("1.25000"))
        Lot.objects.create(**{**LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)})
        response = client.get("/tasse/", {"year": 2026})
        assert response.status_code == 200
        assert b"0,8000" in response.content


SALE_DEFAULTS = dict(
    sale_price_usd=Decimal("200.00000"),
    eur_usd_rate=Decimal("1.100000"),
    gross_proceeds_usd=Decimal("2000.00000"),
    net_gain_usd=Decimal("1000.00000"),
    tax_usd=Decimal("260.00000"),
)

SALE_LOT_DEFAULTS = dict(
    original_lot_id=1,
    symbol="AAPL",
    plan_type="ESPP",
    date_acquired=date(2020, 1, 1),
    qty_sold=Decimal("10"),
    cost_basis=Decimal("100.00000"),
    tax_status="Long Term",
    gain_usd=Decimal("1000.00000"),
)


@pytest.mark.django_db
class TestQuadroVenditeSection:
    def test_no_sales_shows_empty_message(self, client, mock_ivafe_data):
        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"Nessuna vendita" in response.content

    def test_sale_in_selected_year_shows_totals(self, client, mock_ivafe_data):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2025, 6, 15)})
        SaleLot.objects.create(sale=sale, **SALE_LOT_DEFAULTS)

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"Nessuna vendita" not in response.content
        assert b"1.818,18" in response.content  # gross proceeds EUR (2000/1.1)

    def test_multiple_sales_sum_totals(self, client, mock_ivafe_data):
        from app import Sale, SaleLot

        sale1 = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2025, 3, 1)})
        SaleLot.objects.create(sale=sale1, **SALE_LOT_DEFAULTS)
        sale2 = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2025, 9, 1)})
        SaleLot.objects.create(sale=sale2, **{**SALE_LOT_DEFAULTS, "qty_sold": Decimal("5")})

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"1.818,18" in response.content  # net gain EUR total: 2 x (1000/1.1)

    def test_sale_outside_selected_year_is_excluded(self, client, mock_ivafe_data):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2024, 6, 15)})
        SaleLot.objects.create(sale=sale, **SALE_LOT_DEFAULTS)

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"Nessuna vendita" in response.content

    def test_rt73_tax_nets_losses_against_gains_across_sales(self, client, mock_ivafe_data):
        from app import Sale, SaleLot

        gain_sale = Sale.objects.create(
            **{
                **SALE_DEFAULTS,
                "sale_date": date(2025, 3, 1),
                "gross_proceeds_usd": Decimal("3000.00000"),
                "net_gain_usd": Decimal("1000.00000"),
                "tax_usd": Decimal("260.00000"),
                "eur_usd_rate": Decimal("1.000000"),
            }
        )
        SaleLot.objects.create(sale=gain_sale, **SALE_LOT_DEFAULTS)
        loss_sale = Sale.objects.create(
            **{
                **SALE_DEFAULTS,
                "sale_date": date(2025, 9, 1),
                "gross_proceeds_usd": Decimal("1000.00000"),
                "net_gain_usd": Decimal("-500.00000"),
                "tax_usd": Decimal("0.00000"),
                "eur_usd_rate": Decimal("1.000000"),
            }
        )
        SaleLot.objects.create(
            sale=loss_sale, **{**SALE_LOT_DEFAULTS, "gain_usd": Decimal("-500.00000")}
        )

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        # Annual net gain across sales: 1000 - 500 = 500 -> RT73 = 26% x 500 = 130.
        # Summing each sale's own (loss-clamped-to-zero) tax would wrongly give 260
        # (the gain_sale's own stored tax_usd, legitimately still shown in its own
        # row of the per-sale "Vendita" table above the Quadro RT summary).
        assert b"130,00" in response.content

    def test_quadro_rt_notes_show_computed_cost_basis(self, client, mock_ivafe_data):
        from app import Sale, SaleLot

        sale = Sale.objects.create(
            **{
                **SALE_DEFAULTS,
                "sale_date": date(2025, 6, 15),
                "gross_proceeds_usd": Decimal("3000.00000"),
                "net_gain_usd": Decimal("1200.00000"),
            }
        )
        SaleLot.objects.create(sale=sale, **SALE_LOT_DEFAULTS)

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"Note Quadro RT" in response.content
        assert b"1.636,36" in response.content  # cost basis EUR: (3000-1200)/1.1


@pytest.mark.django_db
class TestTasseIvafeSoldLots:
    def test_sold_lot_included_without_current_lots(self, client, mock_ivafe_data):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2025, 6, 15)})
        SaleLot.objects.create(sale=sale, **SALE_LOT_DEFAULTS)

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"nessun lotto" not in response.content.lower()
        assert (
            b"2.200,00" in response.content
        )  # value_end_eur: 200 (sale price) * 10 * 1.1 (eur_usd_rate)

    def test_old_disclaimer_about_sold_lots_is_removed(self, client, mock_ivafe_data):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2025, 6, 15)})
        SaleLot.objects.create(sale=sale, **SALE_LOT_DEFAULTS)

        response = client.get("/tasse/", {"year": 2025})
        assert b"lotti attualmente presenti nel database" not in response.content

    def test_sold_lot_outside_selected_year_is_excluded(self, client, mock_ivafe_data):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2024, 6, 15)})
        SaleLot.objects.create(sale=sale, **SALE_LOT_DEFAULTS)

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"Nessun lotto" in response.content

    def test_sold_lot_and_current_lot_both_contribute(self, client, mock_ivafe_data):
        from app import Lot, Sale, SaleLot

        Lot.objects.create(**LOT_DEFAULTS)
        sale = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2025, 6, 15)})
        SaleLot.objects.create(sale=sale, **SALE_LOT_DEFAULTS)

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        assert b"nessun lotto" not in response.content.lower()

    def test_sold_lots_from_same_sale_acquired_before_year_are_grouped(
        self, client, mock_ivafe_data
    ):
        from app import Sale, SaleLot

        sale = Sale.objects.create(**{**SALE_DEFAULTS, "sale_date": date(2025, 6, 15)})
        SaleLot.objects.create(
            sale=sale, **{**SALE_LOT_DEFAULTS, "date_acquired": date(2020, 1, 1)}
        )
        SaleLot.objects.create(
            sale=sale, **{**SALE_LOT_DEFAULTS, "date_acquired": date(2021, 1, 1)}
        )

        response = client.get("/tasse/", {"year": 2025})
        assert response.status_code == 200
        # combined value_end_eur for 20 shares (10+10): 200 * 20 * 1.1, grouped into one row
        # in the Quadro RW table (the per-lot detail table above stays ungrouped).
        assert b"4.400,00" in response.content


@pytest.mark.django_db
class TestReleasesView:
    def test_page_renders(self, client):
        response = client.get("/novita/")
        assert response.status_code == 200

    def test_context_carries_the_release_list(self, client):
        from releases import RELEASES

        response = client.get("/novita/")
        assert response.context["releases"] == RELEASES

    def test_footer_version_links_to_the_page(self, client):
        from releases import RELEASES

        response = client.get("/")
        content = response.content.decode()
        assert 'href="/novita/"' in content
        assert RELEASES[0]["version"] in content

    def test_footer_links_to_source_repository(self, client):
        response = client.get("/")
        content = response.content.decode()
        assert "github.com/applewebbo/etrade_info" in content

    def test_footer_shows_copyright(self, client):
        response = client.get("/")
        content = response.content.decode()
        assert "©" in content


class TestReleasesData:
    def test_every_entry_is_well_formed(self):
        from releases import RELEASES

        for entry in RELEASES:
            assert entry["version"]
            assert not entry["version"].startswith("v")
            assert 2 <= len(entry["notes"]) <= 4
            assert all(note.strip() for note in entry["notes"])

    def test_entries_are_ordered_newest_first(self):
        from releases import RELEASES

        dates = [entry["date"] for entry in RELEASES]
        assert dates == sorted(dates, reverse=True)
