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
