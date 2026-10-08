# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Local web app (single-user, no auth) for Italian equity tax simulation under **regime dichiarativo**. It ingests an E*TRADE "Sellable" XLSX export, fetches live AAPL and EUR/USD prices via yfinance, and shows portfolio value, unrealised gains, and estimated 26% tax liability. All monetary values are handled with `Decimal` to avoid float rounding errors.

## Commands

```bash
just install       # uv sync — create/update .venv
just run           # dev server on localhost
just migrate       # create DB tables (--run-syncdb, required first time)
just ftest         # run tests (use this, not pytest directly)
just ftest tests/test_tax_engine.py  # single test file
just cov           # full suite with 100% coverage gate
just lint          # pre-commit hooks on all files — run BEFORE git add
```

## Architecture

The app uses **nanodjango** — a single-file Django wrapper. All Django config, models, and views live in `app.py`. There is no `settings.py`, `urls.py`, or `wsgi.py`.

Key modules:

| File | Responsibility |
|------|---------------|
| `app.py` | Django setup via `nanodjango`, `Lot` model, all views |
| `prices.py` | In-process price cache (TTL=60s), yfinance wrapper, stale/direction tracking |
| `tax_engine.py` | Pure function: `calculate_sale_result(lots_with_qty, sale_price_usd, eur_usd_rate)` |
| `xlsx_parser.py` | Reads E*TRADE "Sellable" sheet, maps columns to `Lot` field dicts |
| `conftest.py` | Patches nanodjango so Django's syncdb picks up the `Lot` model in tests |

### Data flow

1. User uploads XLSX → `xlsx_parser.parse_sellable_xlsx` → `Lot` records in SQLite
2. `dashboard` view calls `_portfolio_context()` which calls `prices.py` and `tax_engine.py`
3. `/prices/` is an HTMX partial polled every 60 s to refresh the price header
4. `/simulate/` accepts POST with per-lot quantities and a custom sale price, returns `partials/sim_result.html`

### Frontend

Static assets are fully bundled (no CDN). Templates use **Pico CSS** + **HTMX** + **Alpine.js**, all served from `static/`. Custom styles go exclusively in `static/style.css` — never inline in templates.

### Testing patterns

- `tax_engine` tests instantiate `Lot` objects directly (unsaved) — no DB needed.
- `prices` tests pass a custom `fetcher` callable to `get_price()` instead of hitting yfinance, or use `monkeypatch` on `prices._now` to simulate TTL expiry.
- `conftest.py` is essential: without it, nanodjango's models are invisible to Django's test runner.

## Issue tracking

Issues are on GitHub. Use `just issue-*` commands (backed by `gh issue`) or `gh issue` directly.
