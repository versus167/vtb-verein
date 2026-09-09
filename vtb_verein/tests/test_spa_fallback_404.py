"""Der SPA-Fallback beantwortet Datei-Anfragen mit 404, nicht mit der index.html.

Anlass: In den Container-Logs tauchten reihenweise Zeilen wie
``GET //wp-includes/wlwmanifest.xml HTTP/1.1" 200`` auf. Ein WordPress-Scanner
klapperte bekannte Pfade ab und bekam auf jeden einzelnen ein 200 — weil der
Fallback für alles Unbekannte die ``index.html`` auslieferte. Angreifbar war
daran nichts (es gibt kein WordPress), aber jeder Treffer sah für den Scanner
nach Fund aus, und die App schob dabei jedes Mal die volle index.html raus.

Nachtrag: Dieselben Logs zeigten kurz darauf einen zweiten Scanner, der die
Regel unterlief. ``GET /.aws/credentials`` und ``GET /.git/config`` haben keinen
Punkt im *letzten* Segment und galten damit als Route — 200 mit der index.html,
für den Scanner also ein Fund. Punkt-Segmente sind deshalb ebenfalls
Datei-Anfragen.

Getestet wird die Entscheidung selbst, nicht die Route: Die entsteht nur, wenn
``frontend_dist/`` existiert — also erst nach dem Frontend-Build im Image.
"""
import sys
from pathlib import Path

import pytest

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.main import sieht_wie_datei_aus  # noqa: E402


@pytest.mark.parametrize("pfad", [
    "/wp-includes/wlwmanifest.xml",   # führender Slash: so kommt //… hier an
    "wp-includes/wlwmanifest.xml",
    "blog/wp-includes/wlwmanifest.xml",
    "xmlrpc.php",
    ".env",
    "config.json.bak",
])
def test_datei_anfragen_werden_erkannt(pfad):
    assert sieht_wie_datei_aus(pfad) is True


@pytest.mark.parametrize("pfad", [
    ".git/config",            # kein Punkt im letzten Segment …
    ".aws/credentials",
    ".stripe/",               # … und hier ist das letzte Segment sogar leer
    "/.git/config",
    ".ssh/id_rsa",
    "backend/.env.bak",
    ".well-known/acme-challenge/xyz",
])
def test_punkt_segmente_sind_ebenfalls_datei_anfragen(pfad):
    """Punktdateien und -verzeichnisse sind nie Routen der SPA.

    ``.well-known`` steht bewusst mit in der Liste: Ein Challenge-File, das es
    im Build wirklich gibt, liefert der Fallback vorher aus — diese Prüfung
    greift erst danach und macht aus dem Nicht-Vorhandenen ein ehrliches 404.
    """
    assert sieht_wie_datei_aus(pfad) is True


@pytest.mark.parametrize("pfad", [
    "",                     # Wurzel
    "personen",
    "kassenbuch/12",
    "users/7/permissions",
    "auth/magic-link",
    "irgendwas/das/es/nicht/gibt",   # unbekannte Route: SPA zeigt ihren 404
    "termine/2026-09-09",            # Datum in der Route: Punkt-frei, bleibt Route
])
def test_routen_der_spa_bleiben_bei_der_index(pfad):
    assert sieht_wie_datei_aus(pfad) is False


def test_alle_router_pfade_sind_keine_datei_anfragen():
    """Gegenprobe am echten Router: kein Pfad dort hat einen Punkt.

    Bricht dieser Test, wurde eine Route mit Punkt im letzten Segment ergänzt —
    dann liefe sie in den 404 und die Regel oben müsste sie ausnehmen.
    """
    router = (_ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    pfade = [
        zeile.split("path:", 1)[1].strip().strip(",").strip("'\"")
        for zeile in router.splitlines() if "path:" in zeile
    ]
    assert pfade, "Keine Routen gefunden — Parser oder Datei geändert?"
    # `/:catchAll(.*)*` ist der clientseitige 404 der SPA und matcht per
    # Definition alles — der greift ohnehin nur, wenn der Server die index.html
    # ausliefert. Platzhalter-Segmente (`:id`) sind hier ebenso wenig gemeint.
    literale = [p for p in pfade if ":" not in p]
    treffer = [p for p in literale if sieht_wie_datei_aus(p.lstrip("/"))]
    assert treffer == [], f"Route(n) mit Punkt im letzten Segment: {treffer}"
