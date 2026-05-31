import os
from decimal import Decimal
from pathlib import Path

from django.db import models
from django.utils import timezone
from nanodjango import Django

_db_path = Path(os.environ.get("ETRADE_DATA_DIR", ".")) / "db.sqlite3"

app = Django(
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(_db_path),
        }
    },
    SECRET_KEY=os.environ.get("ETRADE_SECRET_KEY", "local-dev-only-not-for-production"),  # nosec B106
    ALLOWED_HOSTS=["localhost", "127.0.0.1"],
    LANGUAGE_CODE="it",
    USE_L10N=True,
    TIME_ZONE="Europe/Rome",
    USE_TZ=True,
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django.contrib.staticfiles",
    ],
    STATIC_URL="/static/",
    STATICFILES_DIRS=["static"],
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": ["templates"],
            "APP_DIRS": False,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.request",
                ]
            },
        }
    ],
)


class Lot(models.Model):
    ESPP = "ESPP"
    RSU = "RSU"
    LONG_TERM = "Long Term"
    SHORT_TERM = "Short Term"

    symbol = models.CharField(max_length=10)
    plan_type = models.CharField(max_length=10, choices=[(ESPP, "ESPP"), (RSU, "RSU")])
    date_acquired = models.DateField()
    sellable_qty = models.DecimalField(max_digits=10, decimal_places=4)
    cost_basis = models.DecimalField(max_digits=10, decimal_places=5)
    tax_status = models.CharField(
        max_length=20, choices=[(LONG_TERM, "Long Term"), (SHORT_TERM, "Short Term")]
    )

    class Meta:
        ordering = ["date_acquired"]

    def __str__(self):
        return f"{self.symbol} {self.plan_type} {self.date_acquired}"


class Sale(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    sale_price_usd = models.DecimalField(max_digits=10, decimal_places=5)
    eur_usd_rate = models.DecimalField(max_digits=10, decimal_places=6)
    gross_proceeds_usd = models.DecimalField(max_digits=14, decimal_places=5)
    net_gain_usd = models.DecimalField(max_digits=14, decimal_places=5)
    tax_usd = models.DecimalField(max_digits=14, decimal_places=5)

    class Meta:
        ordering = ["-created_at"]

    @property
    def gross_proceeds_eur(self):
        return self.gross_proceeds_usd / self.eur_usd_rate

    @property
    def tax_eur(self):
        return self.tax_usd / self.eur_usd_rate

    @property
    def total_qty(self):
        return sum(sl.qty_sold for sl in self.lots.all())


class SaleLot(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lots")
    original_lot_id = models.IntegerField()
    symbol = models.CharField(max_length=10)
    plan_type = models.CharField(max_length=10)
    date_acquired = models.DateField()
    qty_sold = models.DecimalField(max_digits=10, decimal_places=4)
    cost_basis = models.DecimalField(max_digits=10, decimal_places=5)
    tax_status = models.CharField(max_length=20)
    gain_usd = models.DecimalField(max_digits=14, decimal_places=5)

    class Meta:
        ordering = ["date_acquired"]


# ── import logic ─────────────────────────────────────────────────────────────


def import_lots(lot_data: list[dict], mode: str = "overwrite") -> int:
    """Import lots from parsed data. Returns number of lots created."""
    if mode == "overwrite":
        Lot.objects.all().delete()
        for data in lot_data:
            Lot.objects.create(**data)
        return len(lot_data)

    created = 0
    for data in lot_data:
        _, was_created = Lot.objects.get_or_create(
            symbol=data["symbol"],
            plan_type=data["plan_type"],
            date_acquired=data["date_acquired"],
            cost_basis=data["cost_basis"],
            defaults={"sellable_qty": data["sellable_qty"], "tax_status": data["tax_status"]},
        )
        if was_created:
            created += 1
    return created


# ── helpers ──────────────────────────────────────────────────────────────────


def _execute_sale(selected: list, sale_price: Decimal, eur_usd: Decimal) -> "dict | None":
    from tax_engine import calculate_sale_result

    if not selected:
        return None

    result = calculate_sale_result(selected, sale_price, eur_usd)
    sale = Sale.objects.create(
        sale_price_usd=sale_price,
        eur_usd_rate=eur_usd,
        gross_proceeds_usd=result["gross_proceeds_usd"],
        net_gain_usd=result["net_gain_usd"],
        tax_usd=result["tax_usd"],
    )
    updated_lots = []
    deleted_lot_pks = []
    for entry in result["per_lot"]:
        lot = entry["lot"]
        SaleLot.objects.create(
            sale=sale,
            original_lot_id=lot.pk,
            symbol=lot.symbol,
            plan_type=lot.plan_type,
            date_acquired=lot.date_acquired,
            qty_sold=entry["qty"],
            cost_basis=lot.cost_basis,
            tax_status=lot.tax_status,
            gain_usd=entry["gain_usd"],
        )
        if entry["qty"] >= lot.sellable_qty:
            deleted_lot_pks.append(lot.pk)
            lot.delete()
        else:
            lot.sellable_qty -= entry["qty"]
            lot.save()
            updated_lots.append(lot)
    return {"sale": sale, "updated_lots": updated_lots, "deleted_lot_pks": deleted_lot_pks}


def _portfolio_context():
    from prices import get_eur_usd_rate, get_price_direction, get_stock_price_usd, is_price_stale
    from tax_engine import calculate_sale_result

    lots = list(Lot.objects.all())
    price_usd = get_stock_price_usd()
    eur_usd = get_eur_usd_rate()
    prices_stale = is_price_stale("AAPL") or is_price_stale("EURUSD=X")
    prices_unavailable = price_usd is None or eur_usd is None

    if prices_unavailable:
        return {
            "has_lots": bool(lots),
            "prices_unavailable": True,
            "prices_stale": False,
            "price_direction": "neutral",
            "last_updated": timezone.localtime().strftime("%H:%M:%S"),
        }

    price_eur = price_usd / eur_usd
    rows = []
    total_value_usd = Decimal("0")
    total_tax_usd = Decimal("0")

    for lot in lots:
        value_usd = price_usd * lot.sellable_qty
        result = calculate_sale_result([(lot, lot.sellable_qty)], price_usd, eur_usd)
        gain_usd = result["net_gain_usd"]
        tax_usd = result["tax_usd"]
        gain_pct = (
            (gain_usd / result["total_cost_basis_usd"] * 100)
            if result["total_cost_basis_usd"]
            else Decimal("0")
        )
        rows.append(
            {
                "lot": lot,
                "value_usd": value_usd,
                "value_eur": value_usd / eur_usd,
                "gain_usd": gain_usd,
                "gain_eur": gain_usd / eur_usd,
                "gain_pct": gain_pct,
                "tax_usd": tax_usd,
                "tax_eur": tax_usd / eur_usd,
            }
        )
        total_value_usd += value_usd
        total_tax_usd += tax_usd

    # Summaries by plan type
    def _summary(plan):
        subset = [r for r in rows if r["lot"].plan_type == plan]
        return {
            "qty": sum(r["lot"].sellable_qty for r in subset),
            "value_eur": sum(r["value_eur"] for r in subset),
            "tax_eur": sum(r["tax_eur"] for r in subset),
        }

    return {
        "price_usd": price_usd,
        "price_eur": price_eur,
        "eur_usd": eur_usd,
        "total_value_usd": total_value_usd,
        "total_value_eur": total_value_usd / eur_usd,
        "total_tax_usd": total_tax_usd,
        "total_tax_eur": total_tax_usd / eur_usd,
        "rows": rows,
        "espp": _summary("ESPP"),
        "rsu": _summary("RSU"),
        "has_lots": bool(lots),
        "prices_stale": prices_stale,
        "prices_unavailable": False,
        "price_direction": get_price_direction("AAPL"),
        "last_updated": timezone.localtime().strftime("%H:%M:%S"),
    }


# ── views ─────────────────────────────────────────────────────────────────────


@app.route("/")
def dashboard(request):
    from django.shortcuts import render

    has_lots = Lot.objects.exists()
    sales = list(Sale.objects.prefetch_related("lots").all()[:10])
    ctx = _portfolio_context() if has_lots else {"has_lots": False}
    ctx["sales"] = sales
    return render(request, "dashboard.html", ctx)


@app.route("/prices/")
def prices_fragment(request):
    """HTMX partial: refreshes the price header every 60s."""
    from django.shortcuts import render

    from prices import get_eur_usd_rate, get_price_direction, get_stock_price_usd, is_price_stale

    price_usd = get_stock_price_usd()
    eur_usd = get_eur_usd_rate()
    prices_stale = is_price_stale("AAPL") or is_price_stale("EURUSD=X")
    prices_unavailable = price_usd is None or eur_usd is None
    ctx = {
        "prices_stale": prices_stale,
        "prices_unavailable": prices_unavailable,
        "price_direction": get_price_direction("AAPL"),
        "last_updated": timezone.localtime().strftime("%H:%M:%S"),
    }
    if not prices_unavailable:
        ctx.update({"price_usd": price_usd, "price_eur": price_usd / eur_usd, "eur_usd": eur_usd})
    return render(request, "partials/price_header.html", ctx)


@app.route("/import/")
def import_view(request):
    from django.shortcuts import redirect, render

    if request.method == "POST" and request.FILES.get("xlsx"):
        import tempfile

        from xlsx_parser import parse_sellable_xlsx

        f = request.FILES["xlsx"]
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            for chunk in f.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        mode = request.POST.get("mode", "overwrite")
        import_lots(parse_sellable_xlsx(tmp_path), mode=mode)

        return redirect("/")

    return render(
        request,
        "import.html",
        {"count": Lot.objects.count(), "sales": list(Sale.objects.prefetch_related("lots").all())},
    )


@app.route("/simulate/")
def simulate(request):
    from django.shortcuts import render

    from prices import get_eur_usd_rate, get_stock_price_usd, is_price_stale
    from tax_engine import calculate_sale_result

    lots = list(Lot.objects.all())
    plan_groups = [
        ("ESPP", [lot for lot in lots if lot.plan_type == Lot.ESPP], "card-espp"),
        ("RSU", [lot for lot in lots if lot.plan_type == Lot.RSU], "card-rsu"),
    ]
    price_usd = get_stock_price_usd()
    eur_usd = get_eur_usd_rate()
    prices_stale = is_price_stale("AAPL") or is_price_stale("EURUSD=X")
    prices_unavailable = price_usd is None or eur_usd is None

    if request.method == "POST":
        default_price = str(price_usd) if price_usd is not None else "0"
        sale_price = Decimal(request.POST.get("sale_price", default_price))
        selected = []
        for lot in lots:
            key = f"qty_{lot.pk}"
            raw = request.POST.get(key, "0").strip()
            try:
                qty = Decimal(raw)
            except Exception:
                qty = Decimal("0")
            if qty > 0:
                selected.append((lot, qty))

        result = calculate_sale_result(selected, sale_price, eur_usd) if selected else None
        return render(
            request,
            "partials/sim_result.html",
            {"result": result, "sale_price": sale_price, "eur_usd": eur_usd},
        )

    price_eur = (price_usd / eur_usd) if not prices_unavailable else None
    return render(
        request,
        "simulate.html",
        {
            "lots": lots,
            "plan_groups": plan_groups,
            "price_usd": price_usd,
            "price_eur": price_eur,
            "eur_usd": eur_usd,
            "prices_stale": prices_stale,
            "prices_unavailable": prices_unavailable,
        },
    )


@app.route("/export/")
def export_view(request):
    import io

    import pandas as pd
    from django.http import HttpResponse

    lots = list(Lot.objects.all())
    rows = [
        {
            "Record Type": "Detail",
            "Symbol": lot.symbol,
            "Plan Type": "Rest. Stock" if lot.plan_type == Lot.RSU else lot.plan_type,
            "Date Acquired": lot.date_acquired.strftime("%m/%d/%Y"),
            "Sellable Qty.": float(lot.sellable_qty),
            "Est. Cost Basis (per share):": float(lot.cost_basis),
            "Tax Status.1": lot.tax_status,
        }
        for lot in lots
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "Record Type",
            "Symbol",
            "Plan Type",
            "Date Acquired",
            "Sellable Qty.",
            "Est. Cost Basis (per share):",
            "Tax Status.1",
        ],
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sellable", index=False)
    buf.seek(0)

    response = HttpResponse(
        buf.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="portfolio_export.xlsx"'
    return response


@app.route("/reset/")
def reset_view(request):
    from django.http import HttpResponse

    if request.method == "POST":
        Lot.objects.all().delete()
        response = HttpResponse()
        response["HX-Redirect"] = "/"
        return response


@app.route("/sell/")
def sell_view(request):
    from django.shortcuts import redirect, render

    if request.method != "POST":
        return redirect("/simulate/")

    try:
        sale_price = Decimal(request.POST.get("sale_price", "0"))
        eur_usd = Decimal(request.POST.get("eur_usd", "0"))
    except Exception:
        return redirect("/simulate/")

    if sale_price <= 0 or eur_usd <= 0:
        return redirect("/simulate/")

    lots = list(Lot.objects.all())
    selected = []
    for lot in lots:
        raw = request.POST.get(f"qty_{lot.pk}", "0").strip()
        try:
            qty = Decimal(raw)
        except Exception:
            qty = Decimal("0")
        if qty > 0:
            selected.append((lot, qty))

    _execute_sale(selected, sale_price, eur_usd)

    response = render(request, "partials/sell_success.html", {})
    response["HX-Trigger"] = "saleComplete"
    return response


@app.route("/sell/undo/")
def sell_undo_view(request):
    from django.http import HttpResponse
    from django.shortcuts import redirect

    if request.method != "POST":
        return redirect("/import/")

    last_sale = Sale.objects.first()
    if last_sale:
        for slot in last_sale.lots.all():
            try:
                lot = Lot.objects.get(pk=slot.original_lot_id)
                lot.sellable_qty += slot.qty_sold
                lot.save()
            except Lot.DoesNotExist:
                Lot.objects.create(
                    symbol=slot.symbol,
                    plan_type=slot.plan_type,
                    date_acquired=slot.date_acquired,
                    sellable_qty=slot.qty_sold,
                    cost_basis=slot.cost_basis,
                    tax_status=slot.tax_status,
                )
        last_sale.delete()

    response = HttpResponse()
    response["HX-Redirect"] = "/import/"
    return response


@app.route("/simulate/lots/")
def simulate_lots(request):
    from django.shortcuts import render

    from prices import get_stock_price_usd

    lots = list(Lot.objects.all())
    plan_groups = [
        ("ESPP", [lot for lot in lots if lot.plan_type == Lot.ESPP], "card-espp"),
        ("RSU", [lot for lot in lots if lot.plan_type == Lot.RSU], "card-rsu"),
    ]
    price_usd = get_stock_price_usd()
    return render(
        request, "partials/lot_tables.html", {"plan_groups": plan_groups, "price_usd": price_usd}
    )


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) > 1 and sys.argv[1] != "run":
        app.manage(sys.argv[1:])
    else:
        app.run()
