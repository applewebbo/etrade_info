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
