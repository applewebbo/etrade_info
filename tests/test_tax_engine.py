from datetime import date
from decimal import Decimal


def make_lot(cost_basis: str, plan_type: str = "ESPP", tax_status: str = "Long Term"):
    from app import Lot

    return Lot(
        symbol="AAPL",
        plan_type=plan_type,
        date_acquired=date(2020, 1, 1),
        sellable_qty=Decimal("100"),
        cost_basis=Decimal(cost_basis),
        tax_status=tax_status,
    )


class TestCalculateSaleResult:
    def test_single_lot_gain(self):
        from tax_engine import calculate_sale_result

        lot = make_lot("100.00")
        result = calculate_sale_result(
            lots_with_qty=[(lot, Decimal("10"))],
            sale_price_usd=Decimal("200.00"),
            eur_usd_rate=Decimal("1.10"),
        )
        assert result["net_gain_usd"] == Decimal("1000.00")
        assert result["tax_usd"] == Decimal("260.00")

    def test_single_lot_loss_no_tax(self):
        from tax_engine import calculate_sale_result

        lot = make_lot("300.00")
        result = calculate_sale_result(
            lots_with_qty=[(lot, Decimal("10"))],
            sale_price_usd=Decimal("200.00"),
            eur_usd_rate=Decimal("1.10"),
        )
        assert result["net_gain_usd"] == Decimal("-1000.00")
        assert result["tax_usd"] == Decimal("0")

    def test_mixed_lots_gain_and_loss_offset(self):
        from tax_engine import calculate_sale_result

        gain_lot = make_lot("100.00")
        loss_lot = make_lot("300.00")
        result = calculate_sale_result(
            lots_with_qty=[(gain_lot, Decimal("10")), (loss_lot, Decimal("5"))],
            sale_price_usd=Decimal("200.00"),
            eur_usd_rate=Decimal("1.10"),
        )
        # gain: (200-100)*10 = 1000, loss: (200-300)*5 = -500, net = 500
        assert result["net_gain_usd"] == Decimal("500.00")
        assert result["tax_usd"] == Decimal("130.00")

    def test_gross_proceeds(self):
        from tax_engine import calculate_sale_result

        lot = make_lot("50.00")
        result = calculate_sale_result(
            lots_with_qty=[(lot, Decimal("10"))],
            sale_price_usd=Decimal("200.00"),
            eur_usd_rate=Decimal("1.10"),
        )
        assert result["gross_proceeds_usd"] == Decimal("2000.00")

    def test_eur_conversion(self):
        from tax_engine import calculate_sale_result

        lot = make_lot("100.00")
        result = calculate_sale_result(
            lots_with_qty=[(lot, Decimal("10"))],
            sale_price_usd=Decimal("200.00"),
            eur_usd_rate=Decimal("1.10"),
        )
        expected_eur = Decimal("1000.00") / Decimal("1.10")
        assert result["net_gain_eur"] == expected_eur
        assert result["tax_eur"] == Decimal("260.00") / Decimal("1.10")

    def test_net_after_tax(self):
        from tax_engine import calculate_sale_result

        lot = make_lot("100.00")
        result = calculate_sale_result(
            lots_with_qty=[(lot, Decimal("10"))],
            sale_price_usd=Decimal("200.00"),
            eur_usd_rate=Decimal("1.10"),
        )
        # gross=2000, tax=260, net=1740
        assert result["net_after_tax_usd"] == Decimal("1740.00")

    def test_per_lot_breakdown(self):
        from tax_engine import calculate_sale_result

        lot = make_lot("100.00")
        result = calculate_sale_result(
            lots_with_qty=[(lot, Decimal("5"))],
            sale_price_usd=Decimal("200.00"),
            eur_usd_rate=Decimal("1.10"),
        )
        assert len(result["per_lot"]) == 1
        entry = result["per_lot"][0]
        assert entry["qty"] == Decimal("5")
        assert entry["gain_usd"] == Decimal("500.00")
        assert entry["gross_usd"] == Decimal("1000.00")

    def test_zero_qty_excluded(self):
        from tax_engine import calculate_sale_result

        lot = make_lot("100.00")
        result = calculate_sale_result(
            lots_with_qty=[(lot, Decimal("0"))],
            sale_price_usd=Decimal("200.00"),
            eur_usd_rate=Decimal("1.10"),
        )
        assert result["net_gain_usd"] == Decimal("0")
        assert result["tax_usd"] == Decimal("0")
        assert result["per_lot"] == []
