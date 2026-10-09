from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

_PLAN_TYPE_MAP = {"RS": "RSU"}
_TAX_STATUS_MAP = {"Long": "Long Term", "Short": "Short Term"}


def parse_gains_losses_xlsx(file_path: str | Path) -> list[dict]:
    """Parse the E*TRADE 'Gains & Losses' export into one entry per Order Number.

    Each order aggregates its tranche rows and derives sale_price_usd as the
    weighted average proceeds per share across the whole order.
    """
    df = pd.read_excel(str(file_path), sheet_name="G&L_Expanded")
    df = df[df["Record Type"] == "Sell"]
    df = df.dropna(subset=["Order Number"])

    orders: dict[str, dict] = {}
    for _, row in df.iterrows():
        order_number = str(int(row["Order Number"]))
        order = orders.setdefault(
            order_number,
            {
                "order_number": order_number,
                "sale_date": _parse_date(row["Date Sold"]),
                "tranches": [],
                "_total_qty": Decimal("0"),
                "_total_proceeds": Decimal("0"),
            },
        )
        order["tranches"].append(_row_to_tranche(row))
        order["_total_qty"] += Decimal(str(row["Quantity"]))
        order["_total_proceeds"] += Decimal(str(round(float(row["Total Proceeds"]), 5)))

    result = []
    for order in orders.values():
        total_proceeds = order.pop("_total_proceeds")
        total_qty = order.pop("_total_qty")
        order["sale_price_usd"] = (total_proceeds / total_qty).quantize(Decimal("0.00001"))
        result.append(order)
    return result


def _row_to_tranche(row) -> dict:
    return {
        "symbol": str(row["Symbol"]),
        "plan_type": _PLAN_TYPE_MAP.get(str(row["Plan Type"]), str(row["Plan Type"])),
        "date_acquired": _parse_date(row["Date Acquired"]),
        "grant_date": _parse_optional_date(row.get("Grant Date")),
        "qty": Decimal(str(row["Quantity"])),
        "cost_basis": Decimal(str(round(float(row["Adjusted Cost Basis Per Share"]), 5))),
        "tax_status": _TAX_STATUS_MAP.get(
            str(row["Capital Gains Status"]), str(row["Capital Gains Status"])
        ),
    }


def _parse_date(value) -> date:
    if hasattr(value, "date"):
        return value.date()
    return pd.to_datetime(str(value)).date()


def _parse_optional_date(value) -> date | None:
    if value is None or pd.isna(value):
        return None
    return _parse_date(value)
