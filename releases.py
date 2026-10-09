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
        "date": date(2026, 10, 9),
        "notes": [
            "La vendita simulata può ora avere una data nel passato (cambio EUR/USD storico di Banca d'Italia) e l'importazione del file E*TRADE è più robusta: niente più blocchi su posizioni duplicate, e le stime che E*TRADE aggiorna vengono recepite invece di creare duplicati.",
            "La pagina IVAFE è diventata la pagina Tasse, con un riepilogo delle vendite dell'anno (quadro vendite) e un'anteprima provvisoria dell'anno in corso.",
            'Nuova importazione del file "Gains & Losses" di E*TRADE per registrare in blocco le vendite storiche con il cambio corretto per ogni data di vendita, e nuova pagina "Novità e aggiornamenti" con lo storico delle versioni.',
            "Aggiornamento grafico del sito (nuovo font, footer rivisto), passaggio del codice sorgente da Codeberg a GitHub, e un link che punta sempre all'ultima versione scaricabile dell'app.",
        ],
    },
]


def current_version(request: HttpRequest) -> dict:
    """Context processor: exposes the latest release version to every template."""
    return {"current_version": RELEASES[0]["version"] if RELEASES else None}
