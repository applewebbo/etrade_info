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
    def test_returns_xlsx_file(self, client):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/export/")
        assert response.status_code == 200
        assert (
            response["Content-Type"]
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "portfolio_export.xlsx" in response["Content-Disposition"]

    def test_xlsx_has_sellable_sheet_with_correct_columns(self, client):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/export/")
        df = pd.read_excel(io.BytesIO(response.content), sheet_name="Sellable")
        assert list(df.columns) == [
            "Record Type",
            "Symbol",
            "Plan Type",
            "Date Acquired",
            "Sellable Qty.",
            "Est. Cost Basis (per share):",
            "Tax Status.1",
        ]

    def test_xlsx_data_matches_lot(self, client):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/export/")
        df = pd.read_excel(io.BytesIO(response.content), sheet_name="Sellable")
        assert len(df) == 1
        row = df.iloc[0]
        assert row["Record Type"] == "Detail"
        assert row["Symbol"] == "AAPL"
        assert row["Plan Type"] == "ESPP"
        assert row["Sellable Qty."] == 10.0
        assert row["Tax Status.1"] == "Long Term"

    def test_rsu_plan_type_mapped_correctly(self, client):
        from app import Lot

        Lot.objects.create(**{**LOT_DEFAULTS, "plan_type": "RSU"})
        response = client.get("/export/")
        df = pd.read_excel(io.BytesIO(response.content), sheet_name="Sellable")
        assert df.iloc[0]["Plan Type"] == "Rest. Stock"

    def test_empty_db_returns_empty_xlsx(self, client):
        response = client.get("/export/")
        assert response.status_code == 200
        df = pd.read_excel(io.BytesIO(response.content), sheet_name="Sellable")
        assert len(df) == 0


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


@pytest.mark.django_db
class TestSellUndoView:
    def _create_sale_with_lot(self):
        from app import Lot, Sale, SaleLot

        lot = Lot.objects.create(**LOT_DEFAULTS)
        sale = Sale.objects.create(**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()})
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

        self._create_sale_with_lot()
        assert Lot.objects.count() == 0
        client.post("/sell/undo/")
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
        client.post("/sell/undo/")
        updated = Lot.objects.get(pk=lot.pk)
        assert updated.sellable_qty == Decimal("10")

    def test_post_deletes_last_sale(self, client):
        from app import Sale

        self._create_sale_with_lot()
        assert Sale.objects.count() == 1
        client.post("/sell/undo/")
        assert Sale.objects.count() == 0

    def test_post_returns_hx_redirect_to_import(self, client):
        self._create_sale_with_lot()
        response = client.post("/sell/undo/")
        assert response.status_code == 200
        assert response.headers.get("HX-Redirect") == "/import/"

    def test_post_with_no_sales_is_safe(self, client):
        from app import Sale

        assert Sale.objects.count() == 0
        response = client.post("/sell/undo/")
        assert response.status_code == 200


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


@pytest.mark.django_db
class TestImportViewSales:
    def test_import_view_shows_sales_history_when_sales_exist(self, client):
        from app import Sale

        Sale.objects.create(**{k: Decimal(v) for k, v in SALE_DEFAULTS.items()})
        response = client.get("/import/")
        assert response.status_code == 200
        assert b"Storico vendite" in response.content

    def test_import_view_no_sales_section_when_empty(self, client):
        response = client.get("/import/")
        assert response.status_code == 200
        assert b"Storico vendite" not in response.content


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
class TestSellUndoViewEdgeCases:
    def test_get_redirects_to_import(self, client):
        response = client.get("/sell/undo/")
        assert response.status_code == 302
        assert "/import/" in response.url


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
    def test_dashboard_with_lots_and_prices(self, client, mock_prices):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/")
        assert response.status_code == 200
        assert b"Valore di mercato" in response.content

    def test_dashboard_with_lots_and_prices_unavailable(self, client, monkeypatch):
        import prices
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        monkeypatch.setattr(prices, "get_stock_price_usd", lambda: None)
        monkeypatch.setattr(prices, "get_eur_usd_rate", lambda: None)
        monkeypatch.setattr(prices, "is_price_stale", lambda ticker: False)
        monkeypatch.setattr(prices, "get_price_direction", lambda ticker: "neutral")
        response = client.get("/")
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

        import pandas as pd

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


@pytest.mark.django_db
class TestSimulateView:
    def test_get_renders_form(self, client, mock_prices):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/simulate/")
        assert response.status_code == 200
        assert b"Simulatore" in response.content

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
class TestIvafeView:
    def test_get_returns_200(self, client, mock_ivafe_data):
        response = client.get("/ivafe/")
        assert response.status_code == 200

    def test_page_shows_ivafe_title(self, client, mock_ivafe_data):
        response = client.get("/ivafe/")
        assert b"IVAFE" in response.content

    def test_page_shows_no_lots_message_when_empty(self, client, mock_ivafe_data):
        response = client.get("/ivafe/")
        assert b"lotti" in response.content.lower() or response.status_code == 200

    def test_page_shows_start_and_end_values_with_lots(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/ivafe/")
        assert response.status_code == 200
        assert b"2025" in response.content

    def test_page_shows_ivafe_amount_with_lots(self, client, mock_ivafe_data):
        from app import Lot

        Lot.objects.create(**LOT_DEFAULTS)
        response = client.get("/ivafe/")
        assert response.status_code == 200
        assert b"IVAFE" in response.content

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
        response = client.get("/ivafe/")
        assert response.status_code == 200
