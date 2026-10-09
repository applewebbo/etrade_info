# Etrade Portfolio

A local, single-user web app for simulating Italian equity tax
(**regime dichiarativo**) on an E*TRADE stock plan. It ingests an
E*TRADE "Sellable" XLSX export, fetches live AAPL and EUR/USD prices,
and shows portfolio value, unrealised gains, estimated 26% capital
gains tax, and IVAFE.

## Download

[**Download the latest version**](https://github.com/applewebbo/etrade_info/releases/latest/download/EtradePortfolio.zip)
— this link always points to the newest release's zip, no need to
browse releases or branches. (See the [Releases page](https://github.com/applewebbo/etrade_info/releases)
for release notes and older versions.)

## Requirements

- macOS (any recent version)
- Internet access on first launch and for live prices

## First launch

1. Unzip and move the "Etrade Portfolio" folder wherever you like (e.g. Documents)
2. Double-click `start.command`

   If macOS blocks it ("unidentified developer"), unblock it **once**:

   - macOS Sequoia (15) or newer (e.g. Tahoe 26): System Settings →
     Privacy & Security → scroll to the "Security" section → "Open
     Anyway" → confirm. Then double-click `start.command` again.
   - Older macOS (up to Sonoma 14): right-click `start.command` →
     Open → Open.

   This is only needed on the very first launch. On first run the
   script also installs `uv` and the app's dependencies (~1-2 min);
   later launches are much faster.

3. The browser opens automatically at `http://127.0.0.1:8000`
4. Go to Settings → Import portfolio and upload the
   `ByStatus_expanded.xlsx` file exported from E*TRADE

## Later launches

Double-click `start.command` — the browser opens after ~2 seconds.

## Data storage

Portfolio data is stored in `~/.etrade_info/db.sqlite3` (a hidden
folder in your home directory) and is never touched by app updates.

## Updating

Replace the contents of the "Etrade Portfolio" folder with the new
version. Your data stays intact.

## Uninstalling

Double-click `uninstall.command` to remove data and the virtual
environment, then delete the "Etrade Portfolio" folder manually.

---

A full user guide is planned; this README covers the basics to get
started.
