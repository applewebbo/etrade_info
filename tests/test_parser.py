from datetime import date
from decimal import Decimal

import pandas as pd
import pytest


@pytest.fixture
def sample_xlsx(tmp_path):
    data = {
        "Record Type": ["Purchase", "Grant", "Overall Total"],
        "Symbol": ["AAPL", "AAPL", None],
        "Plan Type": ["ESPP", "Rest. Stock", None],
        "Date Acquired": ["31-JAN-2015", "15-OCT-2016", None],
        "Sellable Qty.": [28.0, 8.0, None],
        "Expected Gain/Loss": [7974.05, 2241.96, None],
        "Tax Status": ["Long Term", "Long Term", None],
        "Est. Market Value": [8646.96, 2470.56, None],
        "Grant Number": [1990, None, None],
        "Grant Date": ["01-AUG-2014", None, None],
        "Vest Period": [0, None, None],
        "Vest Date": ["31-JAN-2015", None, None],
        "Release Date": [None, None, None],
        "Pending Sale Qty.": [0, 0, None],
        "Type": [None, None, None],
        "Class": [None, "A", None],
        "Exercise Price": [20.427625, 0, None],
        "Value At Exercise": [0, 0, None],
        "Exercise Date": [None, None, None],
        "Type.1": [None, "RSU", None],
        "Class.1": ["A", None, None],
        "Purchase Price": [20.427625, 0.0, None],
        "Purchased Qty.": [36, 0, None],
        "Shares Withheld ": [0, 0, None],
        "Net Shares": [36, 8, None],
        "Discount Percent": ["15%", None, None],
        "Grant Date FMV": ["$24.03", "--", None],
        "Purchase Date FMV": ["$29.29", "$28.58", None],
        "Transferable Date": [None, None, None],
        "First Sellable Date": ["Qualified", None, None],
        "Est. Cost Basis (per share):": [24.03250, 28.57500, None],
        "Expected Gain/Loss.1": [284.78750, 280.24500, None],
        "Tax Status.1": ["Long Term", "Long Term", None],
    }
    df = pd.DataFrame(data)
    xlsx_path = tmp_path / "test_sellable.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sellable", index=False)
    return str(xlsx_path)


class TestParseXlsx:
    def test_returns_list(self, sample_xlsx):
        from xlsx_parser import parse_sellable_xlsx

        result = parse_sellable_xlsx(sample_xlsx)
        assert isinstance(result, list)

    def test_excludes_overall_total_row(self, sample_xlsx):
        from xlsx_parser import parse_sellable_xlsx

        result = parse_sellable_xlsx(sample_xlsx)
        assert len(result) == 2

    def test_espp_lot_fields(self, sample_xlsx):
        from xlsx_parser import parse_sellable_xlsx

        result = parse_sellable_xlsx(sample_xlsx)
        espp = next(lot for lot in result if lot["plan_type"] == "ESPP")
        assert espp["symbol"] == "AAPL"
        assert espp["date_acquired"] == date(2015, 1, 31)
        assert espp["cost_basis"] == Decimal("24.0325")
        assert espp["tax_status"] == "Long Term"
        assert espp["sellable_qty"] == Decimal("28.0")

    def test_rest_stock_normalized_to_rsu(self, sample_xlsx):
        from xlsx_parser import parse_sellable_xlsx

        result = parse_sellable_xlsx(sample_xlsx)
        rsu = next(lot for lot in result if lot["plan_type"] == "RSU")
        assert rsu["symbol"] == "AAPL"
        assert rsu["date_acquired"] == date(2016, 10, 15)
        assert rsu["cost_basis"] == Decimal("28.575")

    def test_all_required_keys_present(self, sample_xlsx):
        from xlsx_parser import parse_sellable_xlsx

        result = parse_sellable_xlsx(sample_xlsx)
        required = {
            "symbol",
            "plan_type",
            "date_acquired",
            "sellable_qty",
            "cost_basis",
            "tax_status",
        }
        for lot in result:
            assert required <= lot.keys()

    def test_parse_date_from_string_without_date_attr(self):
        from xlsx_parser import _parse_date

        assert _parse_date("2015-01-31") == date(2015, 1, 31)

    def test_parse_date_from_datetime_object(self):
        import datetime

        from xlsx_parser import _parse_date

        dt = datetime.datetime(2015, 1, 31, 0, 0)
        assert _parse_date(dt) == date(2015, 1, 31)
