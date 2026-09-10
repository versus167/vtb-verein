"""Welche Fläche welches Kamera-Werkzeug anbietet (#111 / #197).

Es gibt zwei, und sie sehen sich nur oberflächlich ähnlich:

* **Foto aufnehmen** (#111) hält fest, was im Sucher steht — eine kaputte Tür,
  ein Aushang. Ein Bild, aufrecht, ohne Nachbearbeitung.
* **Beleg scannen** (#197) sucht Belegkanten, entzerrt perspektivisch und baut
  ein mehrseitiges PDF. Das richtige Werkzeug für Papier, das falsche für die
  Tür: Es fände dort entweder keine Kanten oder schnitte etwas ab.

Daraus folgt die Aufteilung, und die ist eine Produktentscheidung, keine
technische — deshalb steht sie hier fest, statt in drei Vue-Dateien zu
verwittern:

    Rechnungen   Beleg               → Scanner
    Kasse        Beleg               → Scanner
    Tickets      Fehlermeldung       → Foto

Geprüft wird die Verdrahtung im Markup. Ein Vue-Testlauf existiert im Repo
nicht; das hier kostet nichts und schlägt an, wenn jemand die Props vertauscht
oder beim Aufräumen eine verliert.
"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_FRONTEND = _ROOT / "frontend/src"


def _panel_props(pfad: str) -> set[str]:
    """Die schaltenden Props am <AnhangPanel>/<anhang-panel> dieser Seite."""
    quelle = (_FRONTEND / pfad).read_text(encoding="utf-8")
    treffer = re.search(r"<(?:AnhangPanel|anhang-panel)\b(.*?)/>", quelle, re.S)
    assert treffer, f"Kein AnhangPanel in {pfad}"
    block = treffer.group(1)
    return {name for name in ("scannen", "foto")
            if re.search(rf"(?:^|\s){name}(?:\s|$)", block)}


@pytest.mark.parametrize("pfad,erwartet", [
    ("pages/RechnungenMeinePage.vue", {"scannen"}),
    ("pages/KassenbuchDetailPage.vue", {"scannen"}),
    ("pages/TicketsPage.vue", {"foto"}),
])
def test_jede_flaeche_bekommt_ihr_werkzeug(pfad, erwartet):
    assert _panel_props(pfad) == erwartet


def test_freigabe_ansicht_bekommt_keins():
    """Dort schaut man nur lesend drauf — ein Kamera-Knopf wäre eine Einladung
    ins Leere, denn hochladen darf man da ohnehin nicht."""
    assert _panel_props("pages/RechnungenFreigabePage.vue") == set()


def test_kamera_ablauf_steht_nur_an_einer_stelle():
    """getUserMedia zweimal zu schreiben, hieße die Fallstricke zweimal zu
    treffen — Autoplay-Policy, Spuren einzeln stoppen, Aufräumen beim Verlassen.

    Der Scanner zählt hier nicht mit: Er läuft als eigenständiges Dokument
    außerhalb der Vue-App (s. frontend/public/beleg-scanner.html) und hat seine
    eigene Kamerasteuerung, weil er ohne die App auskommen muss.
    """
    treffer = sorted(
        p.relative_to(_FRONTEND).as_posix()
        for p in _FRONTEND.rglob("*.*")
        if p.suffix in (".vue", ".js") and "getUserMedia" in p.read_text(encoding="utf-8")
    )
    # Die Composable hat den Ablauf; die Flächen prüfen höchstens noch, ob es
    # die Kamera überhaupt gibt (window.isSecureContext && …getUserMedia).
    assert "composables/useKamera.js" in treffer
    mit_stream = [
        p for p in treffer
        if "getUserMedia({" in (_FRONTEND / p).read_text(encoding="utf-8")
    ]
    assert mit_stream == ["composables/useKamera.js"], mit_stream
