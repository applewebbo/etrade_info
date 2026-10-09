from datetime import date
from decimal import Decimal

import pandas as pd
import pytest


@pytest.fixture
def sample_gl_xlsx(tmp_path):
    data = {
        "Record Type": ["Summary", "Sell", "Sell", "Sell"],
        "Symbol": [None, "AAPL", "AAPL", "AAPL"],
        "Plan Type": [None, "RS", "RS", "ESPP"],
        "Quantity": [None, 2, 6, 4],
        "Date Acquired": [None, "10/15/2022", "10/15/2021", "07/29/2022"],
        "Adjusted Cost Basis": [None, 293.08, 862.56, 657.296],
        "Adjusted Cost Basis Per Share": [None, 146.54, 143.76, 164.324],
        "Date Sold": [None, "05/12/2026", "05/12/2026", "05/14/2026"],
        "Total Proceeds": [None, 589.99, 1769.959998, 1199.97],
        "Proceeds Per Share": [None, 294.995, 294.993333, 299.9925],
        "Gain/Loss": [26580.94, 589.99, 1769.959998, 647.44],
        "Capital Gains Status": [None, "Long", "Long", "Long"],
        "Grant Date": [None, "09/26/2021", "09/29/2019", "02/01/2022"],
        "Order Number": [None, 102663927.0, 102663927.0, 102788881.0],
    }
    df = pd.DataFrame(data)
    xlsx_path = tmp_path / "gl.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="G&L_Expanded", index=False)
    return str(xlsx_path)


class TestParseGainsLosses:
    def test_returns_one_order_per_order_number(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        assert len(result) == 2

    def test_excludes_summary_row(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        order_numbers = {o["order_number"] for o in result}
        assert None not in order_numbers

    def test_groups_tranches_under_same_order(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        order = next(o for o in result if o["order_number"] == "102663927")
        assert len(order["tranches"]) == 2

    def test_sale_date_from_date_sold(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        order = next(o for o in result if o["order_number"] == "102663927")
        assert order["sale_date"] == date(2026, 5, 12)

    def test_sale_price_is_weighted_average(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        order = next(o for o in result if o["order_number"] == "102663927")
        expected = (Decimal("589.99") + Decimal("1769.959998")) / Decimal("8")
        assert order["sale_price_usd"] == expected.quantize(Decimal("0.00001"))

    def test_single_tranche_order(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        order = next(o for o in result if o["order_number"] == "102788881")
        assert len(order["tranches"]) == 1
        assert order["sale_price_usd"] == Decimal("1199.97") / Decimal("4")

    def test_tranche_fields(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        order = next(o for o in result if o["order_number"] == "102788881")
        tranche = order["tranches"][0]
        assert tranche["symbol"] == "AAPL"
        assert tranche["plan_type"] == "ESPP"
        assert tranche["date_acquired"] == date(2022, 7, 29)
        assert tranche["grant_date"] == date(2022, 2, 1)
        assert tranche["qty"] == Decimal("4")
        assert tranche["cost_basis"] == Decimal("164.324")
        assert tranche["tax_status"] == "Long Term"

    def test_plan_type_rs_normalized_to_rsu(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        order = next(o for o in result if o["order_number"] == "102663927")
        assert all(t["plan_type"] == "RSU" for t in order["tranches"])

    def test_grant_date_none_when_missing(self, sample_gl_xlsx):
        from gl_parser import parse_gains_losses_xlsx

        df = pd.read_excel(sample_gl_xlsx, sheet_name="G&L_Expanded")
        df.loc[1, "Grant Date"] = None
        with pd.ExcelWriter(sample_gl_xlsx, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="G&L_Expanded", index=False)

        result = parse_gains_losses_xlsx(sample_gl_xlsx)
        order = next(o for o in result if o["order_number"] == "102663927")
        tranche = next(t for t in order["tranches"] if t["grant_date"] is None)
        assert tranche is not None

    def test_parse_date_from_datetime_object(self):
        import datetime

        from gl_parser import _parse_date

        dt = datetime.datetime(2026, 5, 12, 0, 0)
        assert _parse_date(dt) == date(2026, 5, 12)
