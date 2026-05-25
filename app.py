from decimal import Decimal

from django.db import models
from nanodjango import Django

app = Django(
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "db.sqlite3",
        }
    },
    SECRET_KEY="local-dev-only-not-for-production",  # nosec B106
    ALLOWED_HOSTS=["localhost", "127.0.0.1"],
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


# ── helpers ──────────────────────────────────────────────────────────────────


def _portfolio_context():
    from prices import get_eur_usd_rate, get_stock_price_usd
    from tax_engine import calculate_sale_result

    lots = list(Lot.objects.all())
    price_usd = get_stock_price_usd()
    eur_usd = get_eur_usd_rate()
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
    }


# ── views ─────────────────────────────────────────────────────────────────────


@app.route("/")
def dashboard(request):
    from django.shortcuts import render

    ctx = _portfolio_context() if Lot.objects.exists() else {"has_lots": False}
    return render(request, "dashboard.html", ctx)


@app.route("/prices/")
def prices_fragment(request):
    """HTMX partial: refreshes the price header every 60s."""
    from django.shortcuts import render

    from prices import get_eur_usd_rate, get_stock_price_usd

    price_usd = get_stock_price_usd()
    eur_usd = get_eur_usd_rate()
    return render(
        request,
        "partials/price_header.html",
        {"price_usd": price_usd, "price_eur": price_usd / eur_usd, "eur_usd": eur_usd},
    )


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

        Lot.objects.all().delete()
        for data in parse_sellable_xlsx(tmp_path):
            Lot.objects.create(**data)

        return redirect("/")

    return render(request, "import.html", {"count": Lot.objects.count()})


@app.route("/simulate/")
def simulate(request):
    from django.shortcuts import render

    from prices import get_eur_usd_rate, get_stock_price_usd
    from tax_engine import calculate_sale_result

    lots = list(Lot.objects.all())
    price_usd = get_stock_price_usd()
    eur_usd = get_eur_usd_rate()

    if request.method == "POST":
        sale_price = Decimal(request.POST.get("sale_price", str(price_usd)))
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

    return render(
        request,
        "simulate.html",
        {"lots": lots, "price_usd": price_usd, "price_eur": price_usd / eur_usd},
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] != "run":
        app.manage(sys.argv[1:])
    else:
        app.run()
