import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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
                    "releases.current_version",
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
    grant_date = models.DateField(null=True, blank=True)
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
    sale_date = models.DateField(default=timezone.localdate)
    sale_price_usd = models.DecimalField(max_digits=10, decimal_places=5)
    eur_usd_rate = models.DecimalField(max_digits=10, decimal_places=6)
    gross_proceeds_usd = models.DecimalField(max_digits=14, decimal_places=5)
    net_gain_usd = models.DecimalField(max_digits=14, decimal_places=5)
    tax_usd = models.DecimalField(max_digits=14, decimal_places=5)
    order_number = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def gross_proceeds_eur(self):
        return self.gross_proceeds_usd / self.eur_usd_rate

    @property
    def tax_eur(self):
        return self.tax_usd / self.eur_usd_rate

    @property
    def net_gain_eur(self):
        return self.net_gain_usd / self.eur_usd_rate

    @property
    def total_qty(self):
        return sum(sl.qty_sold for sl in self.lots.all())


class SaleLot(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lots")
    original_lot_id = models.IntegerField(null=True, blank=True)
    symbol = models.CharField(max_length=10)
    plan_type = models.CharField(max_length=10)
    date_acquired = models.DateField()
    grant_date = models.DateField(null=True, blank=True)
    qty_sold = models.DecimalField(max_digits=10, decimal_places=4)
    cost_basis = models.DecimalField(max_digits=10, decimal_places=5)
    tax_status = models.CharField(max_length=20)
    gain_usd = models.DecimalField(max_digits=14, decimal_places=5)

    class Meta:
        ordering = ["date_acquired"]


# ── import logic ─────────────────────────────────────────────────────────────


def import_lots(lot_data: list[dict], mode: str = "overwrite") -> int:
    """Import lots from parsed data. Returns number of lots created (or updated)."""
    if mode == "overwrite":
        Lot.objects.all().delete()
        for data in lot_data:
            Lot.objects.create(**data)
        return len(lot_data)

    if mode == "update_grant":
        return _update_grant_dates(lot_data)

    created = 0
    for data in lot_data:
        key = {
            "symbol": data["symbol"],
            "plan_type": data["plan_type"],
            "date_acquired": data["date_acquired"],
        }
        matches = list(Lot.objects.filter(**key))
        if not matches:
            Lot.objects.create(
                **key,
                cost_basis=data["cost_basis"],
                sellable_qty=data["sellable_qty"],
                tax_status=data["tax_status"],
                grant_date=data.get("grant_date"),
            )
            created += 1
            continue
        if len(matches) == 1 and matches[0].cost_basis != data["cost_basis"]:
            matches[0].cost_basis = data["cost_basis"]
            matches[0].save()
    return created


def _update_grant_dates(lot_data: list[dict]) -> int:
    """Non-destructively fill grant_date on existing lots and sold lots.

    Matches rows by symbol+plan_type+date_acquired+cost_basis and sets grant_date
    only where still empty, preserving sellable_qty and all other data. Grant dates
    are also propagated from partially-sold lots to their historical SaleLot records.
    """
    updated = 0
    for data in lot_data:
        grant_date = data.get("grant_date")
        if grant_date is None:
            continue
        key = {
            "symbol": data["symbol"],
            "plan_type": data["plan_type"],
            "date_acquired": data["date_acquired"],
            "cost_basis": data["cost_basis"],
        }
        updated += Lot.objects.filter(**key, grant_date__isnull=True).update(grant_date=grant_date)
        SaleLot.objects.filter(**key, grant_date__isnull=True).update(grant_date=grant_date)

    for lot in Lot.objects.exclude(grant_date__isnull=True):
        SaleLot.objects.filter(original_lot_id=lot.pk, grant_date__isnull=True).update(
            grant_date=lot.grant_date
        )
    return updated


# ── backup / restore ─────────────────────────────────────────────────────────

BACKUP_VERSION = 1


class BackupError(ValueError):
    """Raised when a backup file cannot be restored."""


def _lot_to_dict(lot: "Lot") -> dict:
    return {
        "symbol": lot.symbol,
        "plan_type": lot.plan_type,
        "date_acquired": lot.date_acquired.isoformat(),
        "grant_date": lot.grant_date.isoformat() if lot.grant_date else None,
        "sellable_qty": str(lot.sellable_qty),
        "cost_basis": str(lot.cost_basis),
        "tax_status": lot.tax_status,
    }


def _sale_to_dict(sale: "Sale") -> dict:
    return {
        "created_at": sale.created_at.isoformat(),
        "sale_date": sale.sale_date.isoformat(),
        "sale_price_usd": str(sale.sale_price_usd),
        "eur_usd_rate": str(sale.eur_usd_rate),
        "gross_proceeds_usd": str(sale.gross_proceeds_usd),
        "net_gain_usd": str(sale.net_gain_usd),
        "tax_usd": str(sale.tax_usd),
        "lots": [
            {
                "original_lot_id": sl.original_lot_id,
                "symbol": sl.symbol,
                "plan_type": sl.plan_type,
                "date_acquired": sl.date_acquired.isoformat(),
                "grant_date": sl.grant_date.isoformat() if sl.grant_date else None,
                "qty_sold": str(sl.qty_sold),
                "cost_basis": str(sl.cost_basis),
                "tax_status": sl.tax_status,
                "gain_usd": str(sl.gain_usd),
            }
            for sl in sale.lots.all()
        ],
    }


def export_backup() -> dict:
    """Serialise the whole portfolio and sales history into a plain dict."""
    return {
        "version": BACKUP_VERSION,
        "exported_at": timezone.now().isoformat(),
        "lots": [_lot_to_dict(lot) for lot in Lot.objects.all()],
        "sales": [_sale_to_dict(sale) for sale in Sale.objects.all()],
    }


def _opt_date(value: str | None) -> "date | None":
    return date.fromisoformat(value) if value else None


def restore_backup(data: dict) -> None:
    """Replace all portfolio and sales data with the contents of a backup dict."""
    if not isinstance(data, dict) or data.get("version") != BACKUP_VERSION:
        raise BackupError("File di backup non valido o versione non supportata.")

    Lot.objects.all().delete()
    Sale.objects.all().delete()

    for lot in data.get("lots", []):
        Lot.objects.create(
            symbol=lot["symbol"],
            plan_type=lot["plan_type"],
            date_acquired=date.fromisoformat(lot["date_acquired"]),
            grant_date=_opt_date(lot.get("grant_date")),
            sellable_qty=Decimal(lot["sellable_qty"]),
            cost_basis=Decimal(lot["cost_basis"]),
            tax_status=lot["tax_status"],
        )

    for sale_data in data.get("sales", []):
        created_at = datetime.fromisoformat(sale_data["created_at"])
        sale = Sale.objects.create(
            sale_date=_opt_date(sale_data.get("sale_date")) or created_at.date(),
            sale_price_usd=Decimal(sale_data["sale_price_usd"]),
            eur_usd_rate=Decimal(sale_data["eur_usd_rate"]),
            gross_proceeds_usd=Decimal(sale_data["gross_proceeds_usd"]),
            net_gain_usd=Decimal(sale_data["net_gain_usd"]),
            tax_usd=Decimal(sale_data["tax_usd"]),
        )
        # created_at uses auto_now_add, so it must be restored via update().
        Sale.objects.filter(pk=sale.pk).update(created_at=created_at)
        for sl in sale_data.get("lots", []):
            SaleLot.objects.create(
                sale=sale,
                original_lot_id=sl["original_lot_id"],
                symbol=sl["symbol"],
                plan_type=sl["plan_type"],
                date_acquired=date.fromisoformat(sl["date_acquired"]),
                grant_date=_opt_date(sl.get("grant_date")),
                qty_sold=Decimal(sl["qty_sold"]),
                cost_basis=Decimal(sl["cost_basis"]),
                tax_status=sl["tax_status"],
                gain_usd=Decimal(sl["gain_usd"]),
            )


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_sale_date(raw: str | None) -> date:
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return timezone.localdate()


def _resolve_sale_rate(sale_date: date) -> "Decimal | None":
    """Live EUR/USD rate for today's sales, Banca d'Italia historical rate otherwise."""
    from bdi_rates import get_bdi_eur_usd_rate
    from prices import get_eur_usd_rate

    if sale_date >= timezone.localdate():
        return get_eur_usd_rate()
    return get_bdi_eur_usd_rate(sale_date)


def _execute_sale(
    selected: list, sale_price: Decimal, eur_usd: Decimal, sale_date: date | None = None
) -> "dict | None":
    from tax_engine import calculate_sale_result

    if not selected:
        return None

    result = calculate_sale_result(selected, sale_price, eur_usd)
    sale = Sale.objects.create(
        sale_date=sale_date or timezone.localdate(),
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
            grant_date=lot.grant_date,
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


def import_gains_losses(orders: list[dict], mode: str, year: int) -> int:
    """Batch-record historical sales from a parsed Gains & Losses export.

    Scoped to a single reference tax `year`. In "overwrite" mode, replaces all
    previously-imported (order_number-tagged) Sale/SaleLot records for that
    year, leaving manually-recorded sales untouched. In "incremental" mode,
    skips orders whose order_number is already recorded. Both modes are
    idempotent: re-running the same import yields the same end state.
    Does not touch Lot.sellable_qty.
    """
    from tax_engine import calculate_sale_result

    orders = [o for o in orders if o["sale_date"].year == year]

    if mode == "overwrite":
        Sale.objects.filter(sale_date__year=year, order_number__isnull=False).delete()
    else:
        existing = set(
            Sale.objects.filter(order_number__isnull=False).values_list("order_number", flat=True)
        )
        orders = [o for o in orders if o["order_number"] not in existing]

    created = 0
    for order in orders:
        eur_usd = _resolve_sale_rate(order["sale_date"])
        if eur_usd is None:
            continue

        lots_with_qty = [(SimpleNamespace(**t), t["qty"]) for t in order["tranches"]]
        result = calculate_sale_result(lots_with_qty, order["sale_price_usd"], eur_usd)
        sale = Sale.objects.create(
            sale_date=order["sale_date"],
            sale_price_usd=order["sale_price_usd"],
            eur_usd_rate=eur_usd,
            gross_proceeds_usd=result["gross_proceeds_usd"],
            net_gain_usd=result["net_gain_usd"],
            tax_usd=result["tax_usd"],
            order_number=order["order_number"],
        )
        for entry in result["per_lot"]:
            tranche = entry["lot"]
            SaleLot.objects.create(
                sale=sale,
                original_lot_id=None,
                symbol=tranche.symbol,
                plan_type=tranche.plan_type,
                date_acquired=tranche.date_acquired,
                grant_date=tranche.grant_date,
                qty_sold=entry["qty"],
                cost_basis=tranche.cost_basis,
                tax_status=tranche.tax_status,
                gain_usd=entry["gain_usd"],
            )
        created += 1
    return created


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


def _save_upload_to_tmp(f) -> str:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        for chunk in f.chunks():
            tmp.write(chunk)
        return tmp.name


@app.route("/import/")
def import_view(request):
    from django.shortcuts import redirect, render

    if request.method == "POST" and request.FILES.get("xlsx"):
        from xlsx_parser import parse_sellable_xlsx

        tmp_path = _save_upload_to_tmp(request.FILES["xlsx"])
        mode = request.POST.get("mode", "overwrite")
        import_lots(parse_sellable_xlsx(tmp_path), mode=mode)

        return redirect("/")

    if request.method == "POST" and request.FILES.get("gl_xlsx"):
        from gl_parser import parse_gains_losses_xlsx

        tmp_path = _save_upload_to_tmp(request.FILES["gl_xlsx"])
        mode = request.POST.get("gl_mode", "overwrite")
        year = _parse_tax_year(request.POST.get("year"), _gl_year_options(), _gl_default_year())
        import_gains_losses(parse_gains_losses_xlsx(tmp_path), mode=mode, year=year)

        return redirect(f"/tasse/?year={year}")

    return render(
        request,
        "import.html",
        {
            "count": Lot.objects.count(),
            "sales": list(Sale.objects.prefetch_related("lots").all()),
            "gl_years": _gl_year_options(),
            "gl_default_year": _gl_default_year(),
        },
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
        sale_date = _parse_sale_date(request.POST.get("sale_date"))
        sale_eur_usd = _resolve_sale_rate(sale_date)
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

        rate_unavailable = sale_eur_usd is None
        result = (
            calculate_sale_result(selected, sale_price, sale_eur_usd)
            if selected and not rate_unavailable
            else None
        )
        return render(
            request,
            "partials/sim_result.html",
            {
                "result": result,
                "sale_price": sale_price,
                "eur_usd": sale_eur_usd,
                "sale_date": sale_date,
                "rate_unavailable": rate_unavailable,
            },
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
            "sale_date": timezone.localdate(),
            "prices_stale": prices_stale,
            "prices_unavailable": prices_unavailable,
        },
    )


@app.route("/export/")
def export_view(request):
    from django.http import HttpResponse

    payload = json.dumps(export_backup(), indent=2, ensure_ascii=False)
    filename = f"etrade_backup_{timezone.localdate().isoformat()}.json"
    response = HttpResponse(payload, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@app.route("/restore/")
def restore_view(request):
    from django.shortcuts import redirect, render

    if request.method == "POST" and request.FILES.get("backup"):
        try:
            data = json.load(request.FILES["backup"])
            restore_backup(data)
        except (json.JSONDecodeError, BackupError, KeyError, TypeError):
            return render(request, "restore_error.html", status=400)
        return redirect("/")

    return redirect("/import/")


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

    sale_date = _parse_sale_date(request.POST.get("sale_date"))
    _execute_sale(selected, sale_price, eur_usd, sale_date)

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
                    grant_date=slot.grant_date,
                    sellable_qty=slot.qty_sold,
                    cost_basis=slot.cost_basis,
                    tax_status=slot.tax_status,
                )
        last_sale.delete()

    response = HttpResponse()
    response["HX-Redirect"] = "/import/"
    return response


def _tax_year_options(current_year: int) -> list[int]:
    """Contiguous years for which a tax computation can be requested.

    Spans from the earliest year with any Lot or Sale data up to the current,
    still in-progress year (shown as a provisional preview of next year's
    filing, assuming no further buys/sells).
    """
    last_complete_year = current_year - 1
    lot_years = Lot.objects.values_list("date_acquired__year", flat=True)
    sale_years = Sale.objects.values_list("sale_date__year", flat=True)
    relevant_years = {y for y in [*lot_years, *sale_years]}
    earliest = min(relevant_years) if relevant_years else last_complete_year
    return list(range(earliest, current_year + 1))


def _parse_tax_year(raw: str | None, available_years: list[int], default: int) -> int:
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return default
    return year if year in available_years else default


def _gl_year_options() -> list[int]:
    """Selectable tax years for the Gains & Losses import, independent of
    existing data (unlike _tax_year_options) since the first-ever import has
    none yet."""
    current_year = timezone.localdate().year
    return list(range(current_year - 6, current_year + 1))


def _gl_default_year() -> int:
    return timezone.localdate().year - 1


@app.route("/tasse/")
def tasse_view(request):
    import datetime

    import yfinance as yf
    from django.shortcuts import render

    from bdi_rates import get_bdi_eur_usd_rate
    from ivafe_engine import calculate_ivafe

    current_year = datetime.date.today().year
    default_year = current_year - 1
    available_years = _tax_year_options(current_year)
    year = _parse_tax_year(request.GET.get("year"), available_years, default_year)
    lots = list(Lot.objects.all())

    def _aapl_price(start: datetime.date, end: datetime.date, idx: int) -> Decimal | None:
        try:
            df = yf.download(
                "AAPL",
                start=start.isoformat(),
                end=end.isoformat(),
                auto_adjust=True,
                progress=False,
            )
            if df.empty:
                return None
            return Decimal(str(round(float(df["Close"].iloc[idx].item()), 4)))
        except Exception:
            return None

    is_in_progress_year = year == current_year

    price_start = _aapl_price(datetime.date(year, 1, 1), datetime.date(year, 1, 10), 0)
    rate_start = get_bdi_eur_usd_rate(datetime.date(year, 1, 10))
    if is_in_progress_year:
        from prices import get_eur_usd_rate, get_stock_price_usd

        price_end = get_stock_price_usd()
        rate_end = get_eur_usd_rate()
    else:
        price_end = _aapl_price(datetime.date(year, 12, 24), datetime.date(year, 12, 31), -1)
        rate_end = get_bdi_eur_usd_rate(datetime.date(year, 12, 31))

    data_available = all([price_start, price_end, rate_start, rate_end])

    sales = list(Sale.objects.filter(sale_date__year=year).order_by("sale_date"))
    sales_totals = (
        {
            "qty": sum(s.total_qty for s in sales),
            "gross_proceeds_eur": sum(s.gross_proceeds_eur for s in sales),
            "net_gain_eur": sum(s.net_gain_eur for s in sales),
            "tax_eur": sum(s.tax_eur for s in sales),
        }
        if sales
        else None
    )

    ctx = {
        "year": year,
        "available_years": available_years,
        "has_lots": bool(lots),
        "data_available": data_available,
        "is_in_progress_year": is_in_progress_year,
        "sales": sales,
        "sales_totals": sales_totals,
    }
    if data_available and lots:
        ivafe_data = calculate_ivafe(lots, price_start, price_end, rate_start, rate_end, year)
        rows = ivafe_data["rows"]
        full_rows = [r for r in rows if r["value_start_eur"] is not None]
        partial_rows = [r for r in rows if r["value_start_eur"] is None]
        for r in partial_rows:
            rate_acq = get_bdi_eur_usd_rate(r["lot"].date_acquired)
            r["value_start_eur"] = (
                r["lot"].cost_basis * r["lot"].sellable_qty * rate_acq if rate_acq else None
            )
        rw_full_year = (
            {
                "total_qty": sum(r["lot"].sellable_qty for r in full_rows),
                "value_start_eur": sum(r["value_start_eur"] for r in full_rows),
                "value_end_eur": sum(r["value_end_eur"] for r in full_rows),
                "days_held": 365,
                "ivafe_eur": sum(r["ivafe_eur"] for r in full_rows),
            }
            if full_rows
            else None
        )
        ctx.update(
            {
                "price_start": price_start,
                "price_end": price_end,
                "rate_start": rate_start,
                "rate_end": rate_end,
                "rw_full_year": rw_full_year,
                "rw_partial_rows": partial_rows,
                **ivafe_data,
            }
        )
    return render(request, "tasse.html", ctx)


@app.route("/novita/")
def releases_view(request):
    from django.shortcuts import render

    from releases import RELEASES

    return render(request, "releases.html", {"releases": RELEASES})


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
