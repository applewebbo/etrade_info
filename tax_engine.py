from decimal import Decimal

TAX_RATE = Decimal("0.26")


def calculate_sale_result(
    lots_with_qty: list[tuple],
    sale_price_usd: Decimal,
    eur_usd_rate: Decimal,
) -> dict:
    """
    Calculate tax impact of selling selected lots at a given price.

    Regime dichiarativo: 26% on net gain (gains and losses offset each other).
    All values in USD; EUR equivalents computed at current eur_usd_rate.

    Args:
        lots_with_qty: list of (Lot, qty_to_sell) — zero-qty lots are ignored
        sale_price_usd: target sale price per share in USD
        eur_usd_rate: current EUR/USD exchange rate (e.g. Decimal("1.10"))

    Returns a dict with aggregate totals, per-lot breakdown, and EUR equivalents.
    """
    per_lot = []
    total_gain_usd = Decimal("0")
    total_gross_usd = Decimal("0")
    total_cost_usd = Decimal("0")

    for lot, qty in lots_with_qty:
        if qty == 0:
            continue
        gross = sale_price_usd * qty
        cost = lot.cost_basis * qty
        gain = gross - cost
        per_lot.append(
            {
                "lot": lot,
                "qty": qty,
                "gross_usd": gross,
                "cost_basis_usd": cost,
                "gain_usd": gain,
            }
        )
        total_gain_usd += gain
        total_gross_usd += gross
        total_cost_usd += cost

    tax_usd = max(Decimal("0"), total_gain_usd) * TAX_RATE

    def to_eur(usd: Decimal) -> Decimal:
        return usd / eur_usd_rate

    return {
        "gross_proceeds_usd": total_gross_usd,
        "gross_proceeds_eur": to_eur(total_gross_usd),
        "total_cost_basis_usd": total_cost_usd,
        "total_cost_basis_eur": to_eur(total_cost_usd),
        "net_gain_usd": total_gain_usd,
        "net_gain_eur": to_eur(total_gain_usd),
        "tax_usd": tax_usd,
        "tax_eur": to_eur(tax_usd),
        "net_after_tax_usd": total_gross_usd - tax_usd,
        "net_after_tax_eur": to_eur(total_gross_usd - tax_usd),
        "per_lot": per_lot,
    }
