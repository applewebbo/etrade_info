from decimal import Decimal

from django.db import models
from django.utils import timezone
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

    ctx = _portfolio_context() if Lot.objects.exists() else {"has_lots": False}
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

    return render(request, "import.html", {"count": Lot.objects.count()})


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


@app.route("/reset/")
def reset_view(request):
    from django.http import HttpResponse

    if request.method == "POST":
        Lot.objects.all().delete()
        response = HttpResponse()
        response["HX-Redirect"] = "/"
        return response


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] != "run":
        app.manage(sys.argv[1:])
    else:
        app.run()
