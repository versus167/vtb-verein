"""Der Beleg-Scanner hängt an keiner Fachlichkeit mehr (Ticket #197).

Anlass: Der Endpunkt lag als ``/api/rechnungen/beleg-scan`` im Rechnungs-Router
und verlangte ``rechnungen.einreichen``. Damit war der Scanner faktisch nur für
Rechnungsbelege benutzbar — wer ein Ticket schreiben oder eine Kassenbuchung
belegen wollte, wäre auf ein 403 gelaufen, obwohl er denselben Beleg gleich
danach ganz regulär als Datei hätte hochladen dürfen.

Jetzt liegt er unter ``/api/scan/beleg-pdf`` und verlangt nur die Anmeldung.
Das gibt nichts preis: Der Endpunkt liest nichts, legt nichts ab und gibt nur
zurück, was der Aufrufer selbst geschickt hat. Die Rechteprüfung sitzt dort, wo
das PDF danach abgelegt wird — im Ticket-, Rechnungs- oder Kassenbuch-Upload.

Getestet wird die Verdrahtung (Pfad, Abhängigkeiten, kein Fach-Recht), nicht
der PDF-Bau — der steht in test_scan_pdf_service.py.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.main import app  # noqa: E402


def _route(pfad):
    for r in app.routes:
        if getattr(r, "path", None) == pfad:
            return r
    return None


def test_endpunkt_liegt_neutral():
    """Der Pfad ist die halbe Aussage: /api/scan/ statt /api/rechnungen/."""
    assert _route("/api/scan/beleg-pdf") is not None


def test_alter_rechnungs_pfad_ist_weg():
    """Kein zweiter Eingang, der die alte Rechteprüfung weiterschleppt.

    Der Scanner ist neu und hat außerhalb der App keine Aufrufer, deshalb wird
    der alte Pfad ersatzlos entfernt statt überzugangsweise mitgeführt.
    """
    assert _route("/api/rechnungen/beleg-scan") is None


def test_kein_fachliches_recht_im_quelltext():
    """Die eigentliche Aussage dieses Umbaus.

    Wer ein Ticket schreiben darf, muss den Scanner benutzen dürfen, ohne
    Rechnungen einreichen zu können. Ein `has_permission`-Aufruf im Scan-Modul
    wäre ein Rückfall in genau das Problem — er stünde vor einem Endpunkt, der
    gar keine Vereinsdaten anfasst.
    """
    quelle = (_ROOT / "backend/api/scan.py").read_text(encoding="utf-8")
    assert "has_permission" not in quelle
    assert "RECHNUNGEN_EINREICHEN" not in quelle


def test_anmeldung_ist_trotzdem_noetig():
    """Offen für alle Angemeldeten heißt nicht offen für alle.

    ``CurrentUser`` ist die Anmelde-Abhängigkeit; ohne sie stünde ein Endpunkt
    im Netz, der für jeden Fremden PDFs baut.
    """
    quelle = (_ROOT / "backend/api/scan.py").read_text(encoding="utf-8")
    assert "CurrentUser" in quelle


def test_scanner_dokument_zeigt_auf_den_neuen_pfad():
    """Das Scanner-Dokument läuft nicht durch den Vue-Build, ein Umbenennen
    fällt dort also nicht beim Kompilieren auf — nur hier."""
    js = (_ROOT / "frontend/public/vendor/beleg-scan.js").read_text(encoding="utf-8")
    assert "'/api/scan/beleg-pdf'" in js
    assert "/api/rechnungen/beleg-scan" not in js
