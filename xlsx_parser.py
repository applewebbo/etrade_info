from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd


def parse_sellable_xlsx(file_path: str | Path) -> list[dict]:
    df = pd.read_excel(str(file_path), sheet_name="Sellable")
    df = df[df["Record Type"] != "Overall Total"]
    df = df.dropna(subset=["Symbol"])
    return [_row_to_lot(row) for _, row in df.iterrows()]


def _row_to_lot(row) -> dict:
    return {
        "symbol": str(row["Symbol"]),
        "plan_type": "RSU" if row["Plan Type"] == "Rest. Stock" else "ESPP",
        "date_acquired": _parse_date(row["Date Acquired"]),
        "sellable_qty": Decimal(str(float(row["Sellable Qty."]))),
        "cost_basis": Decimal(str(round(float(row["Est. Cost Basis (per share):"]), 5))),
        "tax_status": str(row["Tax Status.1"]),
    }


def _parse_date(value) -> date:
    if hasattr(value, "date"):
        return value.date()
    return pd.to_datetime(str(value)).date()
