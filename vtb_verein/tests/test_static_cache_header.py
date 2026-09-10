"""Cache-Regel für statische Dateien unter /vendor/ (Ticket #197).

Anlass: Der Beleg-Scanner brachte opencv.js mit — 10,9 MB, die sonst jedes
Handy bei jedem Aufruf neu zöge. Dagegen steht ein Jahr `immutable`. Der erste
Anlauf hängte das an das ganze Verzeichnis, und darin liegt neben der fremden
Bibliothek auch *eigener* Code: beleg-scan.js, scan-detect.js, beleg-scan.css.
Der ändert sich mit jedem Fix, wird aber von beleg-scanner.html ohne `?v=`
eingebunden — unveränderlich ausgeliefert hätte ein Scanner-Fix bestehende
Browser ein Jahr lang nicht erreicht, ohne Rückfrage, ohne Handhabe.

Diese Tests halten die Trennung fest: zugekauft und nie bearbeitet → ein Jahr;
alles andere → Pflicht-Rückfrage.

Getestet wird die Entscheidung selbst, nicht die Route: Die entsteht nur, wenn
``frontend_dist/`` existiert — also erst nach dem Frontend-Build im Image
(gleiche Bauart wie test_spa_fallback_404.py).
"""
import sys
from pathlib import Path

import pytest

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.main import _cache_header  # noqa: E402


def _cc(pfad):
    return _cache_header(pfad).get("Cache-Control", "")


@pytest.mark.parametrize("pfad", [
    "vendor/opencv.js",
    "vendor/material-icons.woff2",
])
def test_zugekauftes_bleibt_ein_jahr(pfad):
    """Der Grund für die ganze Übung: 10,9 MB nicht bei jedem Aufruf."""
    cc = _cc(pfad)
    assert "max-age=31536000" in cc
    assert "immutable" in cc


@pytest.mark.parametrize("pfad", [
    "vendor/beleg-scan.js",
    "vendor/scan-detect.js",
    "vendor/beleg-scan.css",
])
def test_eigener_code_wird_nachgefragt(pfad):
    """Die eigentliche Aussage: Ein Fix am Scanner muss ankommen können.

    Ohne diese Ausnahme läge zwischen einem Deploy und dem Browser eines
    Nutzers ein Jahr — und niemand könnte etwas dagegen tun, denn `immutable`
    unterdrückt auch die Rückfrage.
    """
    cc = _cc(pfad)
    assert "immutable" not in cc
    assert "must-revalidate" in cc


def test_ausserhalb_von_vendor_gilt_keine_regel():
    """Der Rest der App wird von dieser Regel gar nicht angefasst.

    Quasar hängt seinen Bauteilen ohnehin einen Inhalts-Hash an den Namen; die
    index.html darf gerade nicht lange liegen bleiben.
    """
    for pfad in ("index.html", "beleg-scanner.html", "icons/favicon.ico"):
        assert _cache_header(pfad) == {}, pfad


def test_neue_datei_unter_vendor_ist_nicht_versehentlich_unveraenderlich():
    """Voreinstellung ist die sichere Seite.

    Wer künftig etwas unter /vendor/ ablegt, bekommt die Rückfrage — nicht ein
    Jahr Stillstand. Unveränderlich wird eine Datei nur, wenn sie jemand
    ausdrücklich in `_VENDOR_IMMUTABLE` einträgt.
    """
    assert "immutable" not in _cc("vendor/irgendwas-neues.js")
