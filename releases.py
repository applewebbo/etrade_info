"""Plain-language, per-release changelog shown on the /novita page.

Newest first. Append one entry per release. Keep the notes non-technical
Italian: 2-4 short bullet points a user would understand, condensed from the
actual changes — not the raw commit list.
"""

from datetime import date

from django.http import HttpRequest

RELEASES: list[dict] = [
    {
        "version": "2026.1",
        "date": date(2026, 10, 7),
        "notes": [
            "La vendita simulata può ora avere una data nel passato: in quel caso le tasse vengono calcolate con il cambio EUR/USD storico di Banca d'Italia, non con quello di oggi.",
            "Corretto un errore che poteva bloccare l'importazione del file E*TRADE quando nel portafoglio ci sono più posizioni acquistate nello stesso giorno allo stesso prezzo.",
            "L'importazione ora riconosce quando E*TRADE aggiorna una stima già presente (es. il costo di acquisto di una posizione ESPP) e la corregge, invece di creare una posizione duplicata.",
            "Introdotto un numero di versione per il sito, a partire da questa release.",
        ],
    },
]


def current_version(request: HttpRequest) -> dict:
    """Context processor: exposes the latest release version to every template."""
    return {"current_version": RELEASES[0]["version"] if RELEASES else None}
