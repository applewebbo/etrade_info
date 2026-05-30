#!/bin/bash
# Disinstalla Etrade Portfolio — rimuove dati e ambiente virtuale

cd "$(dirname "$0")"

echo "=== Disinstallazione Etrade Portfolio ==="
echo ""

# ── Rimozione database e dati utente ─────────────────────────────────────────
DATA_DIR="$HOME/.etrade_info"
if [ -d "$DATA_DIR" ]; then
    read -r -p "Eliminare i dati del portfolio in $DATA_DIR? [s/N] " risposta
    if [[ "$risposta" =~ ^[Ss]$ ]]; then
        rm -rf "$DATA_DIR"
        echo "✓ Dati eliminati."
    else
        echo "  Dati mantenuti."
    fi
else
    echo "  Nessun dato trovato in $DATA_DIR."
fi

# ── Rimozione ambiente virtuale ───────────────────────────────────────────────
if [ -d ".venv" ]; then
    read -r -p "Eliminare l'ambiente virtuale (.venv)? [s/N] " risposta
    if [[ "$risposta" =~ ^[Ss]$ ]]; then
        rm -rf .venv
        echo "✓ Ambiente virtuale eliminato."
    else
        echo "  Ambiente virtuale mantenuto."
    fi
fi

echo ""
echo "Disinstallazione completata."
echo "Puoi eliminare manualmente la cartella dell'app."
echo ""
read -r -p "Premi Invio per chiudere..." _
