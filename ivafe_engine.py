import calendar
import datetime
from decimal import Decimal

IVAFE_RATE = Decimal("0.002")  # 2‰


def calculate_ivafe(
    lots,
    price_start_usd: Decimal,
    price_end_usd: Decimal,
    rate_start_eur_per_usd: Decimal,
    rate_end_eur_per_usd: Decimal,
    year: int,
    sold_lots=None,
) -> dict:
    """
    Compute IVAFE (2‰) for the reference year.

    rate_start/rate_end: EUR per 1 USD (from Banca d'Italia avgRate).
    value_eur = value_usd * rate_eur_per_usd.
    Days held: max(date_acquired, Jan 1) to Dec 31, inclusive.
    Lots acquired after Dec 31 of the reference year are excluded.

    `sold_lots`, if given, is an iterable of SaleLot-like objects (each with
    `date_acquired`, `qty_sold`, and a `sale` relation exposing `sale_date`,
    `sale_price_usd`, `eur_usd_rate`) whose disposal fell within `year`. Their
    days held run to the sale date instead of Dec 31, and their end value is
    the historical disposal value, not the year-end market value — so unlike
    currently-held lots, they are added to total_ivafe_eur (and
    total_value_start_eur, when acquired before the year) but never to
    total_value_end_eur, which represents the portfolio's year-end value.
    """
    year_start = datetime.date(year, 1, 1)
    year_end = datetime.date(year, 12, 31)
    total_days = Decimal(366 if calendar.isleap(year) else 365)

    rows = []
    total_value_start_eur = Decimal("0")
    total_value_end_eur = Decimal("0")
    total_ivafe_eur = Decimal("0")

    for lot in lots:
        acquired = lot.date_acquired
        if acquired > year_end:
            continue

        value_end_usd = price_end_usd * lot.sellable_qty
        value_end_eur = value_end_usd * rate_end_eur_per_usd
        total_value_end_eur += value_end_eur

        if acquired < year_start:
            value_start_usd = price_start_usd * lot.sellable_qty
            value_start_eur = value_start_usd * rate_start_eur_per_usd
            total_value_start_eur += value_start_eur
        else:
            value_start_eur = None

        hold_from = max(acquired, year_start)
        days_held = (year_end - hold_from).days + 1
        ivafe_eur = value_end_eur * IVAFE_RATE * Decimal(days_held) / total_days
        total_ivafe_eur += ivafe_eur

        rows.append(
            {
                "lot": lot,
                "qty": lot.sellable_qty,
                "value_start_eur": value_start_eur,
                "value_end_eur": value_end_eur,
                "days_held": days_held,
                "ivafe_eur": ivafe_eur,
                "sold": False,
            }
        )

    for sold in sold_lots or []:
        acquired = sold.date_acquired
        disposal_date = sold.sale.sale_date
        if acquired > disposal_date:
            continue

        value_end_usd = sold.sale.sale_price_usd * sold.qty_sold
        value_end_eur = value_end_usd * sold.sale.eur_usd_rate

        if acquired < year_start:
            value_start_usd = price_start_usd * sold.qty_sold
            value_start_eur = value_start_usd * rate_start_eur_per_usd
            total_value_start_eur += value_start_eur
        else:
            value_start_eur = None

        hold_from = max(acquired, year_start)
        days_held = (disposal_date - hold_from).days + 1
        ivafe_eur = value_end_eur * IVAFE_RATE * Decimal(days_held) / total_days
        total_ivafe_eur += ivafe_eur

        rows.append(
            {
                "lot": sold,
                "qty": sold.qty_sold,
                "value_start_eur": value_start_eur,
                "value_end_eur": value_end_eur,
                "days_held": days_held,
                "ivafe_eur": ivafe_eur,
                "sold": True,
            }
        )

    return {
        "total_value_start_eur": total_value_start_eur,
        "total_value_end_eur": total_value_end_eur,
        "total_ivafe_eur": total_ivafe_eur,
        "rows": rows,
    }
