#!/bin/bash
# Avvia Etrade Portfolio — doppio clic per lanciare l'app

set -e
cd "$(dirname "$0")"

# ── 1. Verifica/installa uv ────────────────────────────────────────────────────
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv &>/dev/null; then
    echo "uv non trovato — installazione in corso..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "uv $(uv --version) trovato."

# ── 2. Directory dati utente (sopravvive agli aggiornamenti) ──────────────────
export ETRADE_DATA_DIR="$HOME/.etrade_info"
mkdir -p "$ETRADE_DATA_DIR"

# Genera secret key univoca al primo avvio; non sovrascrivere agli aggiornamenti
SECRET_KEY_FILE="$ETRADE_DATA_DIR/secret_key"
if [ ! -f "$SECRET_KEY_FILE" ]; then
    python3 -c "import secrets; print(secrets.token_hex(50))" > "$SECRET_KEY_FILE"
    chmod 600 "$SECRET_KEY_FILE"
    echo "✓ Secret key generata."
fi
export ETRADE_SECRET_KEY
ETRADE_SECRET_KEY="$(cat "$SECRET_KEY_FILE")"

# ── 3. Libera la porta 8000 se occupata da un'istanza precedente ──────────────
if lsof -ti :8000 &>/dev/null; then
    echo "Chiusura istanza precedente sulla porta 8000..."
    lsof -ti :8000 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# ── 4. Crea/aggiorna l'ambiente virtuale ──────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "Prima configurazione: installazione dipendenze (può richiedere 1-2 minuti)..."
    uv sync
else
    uv sync --quiet
fi

# ── 5. Migrazioni database (idempotente) ──────────────────────────────────────
uv run python app.py migrate --run-syncdb 2>/dev/null || true

# ── 6. Apri il browser dopo 2 secondi ────────────────────────────────────────
(sleep 2 && open http://127.0.0.1:8000) &

# ── 7. Avvia il server ────────────────────────────────────────────────────────
echo ""
echo "✓ App in esecuzione su http://127.0.0.1:8000"
echo "  Dati in: $ETRADE_DATA_DIR"
echo "  Per chiudere: Cmd+C in questa finestra"
echo ""
uv run python app.py runserver
