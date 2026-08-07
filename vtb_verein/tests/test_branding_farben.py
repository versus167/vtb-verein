"""Vereinsfarben als CSS (backend/core/branding.py).

Zwei Env-Werte färben die Oberfläche einer Instanz (Ticket #131). Zwei Dinge
sind hier wirklich wichtig: dass nichts Ungeprüftes aus der Env in das
ausgelieferte Stylesheet gelangt, und dass der VTB-Standard pixelgleich bleibt —
die abgeleiteten Töne sind von Hand gemischt und dürfen sich nicht durch eine
Rechnung verschieben.
"""
import sys
from pathlib import Path

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from backend.core import branding  # noqa: E402


# ── Prüfung der Env-Werte ───────────────────────────────────────────────────

@pytest.mark.parametrize("unsinn", [
    "",
    None,
    "dunkelblau",
    "#12345",         # zu kurz
    "#1234567",       # zu lang
    "023a90",         # ohne Raute
    "#02 3a90",       # Leerzeichen
    "red; }",         # Ausbruchsversuch aus der Regel
    "#023a90; --q-primary: red",
    "</style><script>alert(1)</script>",
])
def test_unsinn_faellt_auf_den_standard_zurueck(unsinn):
    """Lieber die Standardfarbe als ein kaputtes (oder fremdes) Stylesheet."""
    assert branding.hexfarbe(unsinn, "#023a90") == "#023a90"


def test_grossschreibung_wird_vereinheitlicht():
    assert branding.hexfarbe("#AABBCC", "#023a90") == "#aabbcc"


def test_keine_env_kommt_ins_css_durch():
    """Auch als Ganzes: was nicht durch die Prüfung geht, steht nicht drin."""
    css = branding.farben_css("red; } body { display: none", "#feeb03")
    assert "display: none" not in css
    assert "--vtb-flaeche: #023a90;" in css


# ── Aufbau des Stylesheets ──────────────────────────────────────────────────

def test_standard_liefert_die_vtb_farben():
    css = branding.farben_css(None, None)
    assert "--vtb-flaeche: #023a90;" in css
    assert "--vtb-akzent: #feeb03;" in css
    # Kanalfassung für rgba(): ohne sie bleiben alle Tönungen ungefärbt
    assert "--vtb-flaeche-rgb: 2, 58, 144;" in css
    assert "--vtb-akzent-rgb: 254, 235, 3;" in css
    # Quasars eigene Primärfarbe wird mitgezogen (Kopfzeile, Buttons, Fokus)
    assert "--q-primary: #023a90;" in css


def test_standard_ohne_gerechnete_zwischentoene():
    """Beim VTB gelten die handgemischten Töne aus quasar.variables.scss.

    Fehlen die Properties, greift der SCSS-Rückfallwert — genau so bleibt der
    VTB-Look nach diesem Ticket unverändert.
    """
    css = branding.farben_css(None, None)
    assert "--vtb-flaeche-tief" not in css
    assert "--vtb-flaeche-hoch" not in css


def test_eigene_farben_bringen_gerechnete_zwischentoene():
    """Ein fremder Verein hat keine Handmischung — dort wird gerechnet."""
    css = branding.farben_css("#7a1120", "#e8d8b0")
    assert "--vtb-flaeche: #7a1120;" in css
    assert "--vtb-akzent: #e8d8b0;" in css
    assert "--vtb-flaeche-tief: #580c17;" in css   # 28 % Richtung Schwarz
    assert "--vtb-flaeche-tief-rgb: 88, 12, 23;" in css
    assert "--vtb-flaeche-hoch: #8d323f;" in css   # 14 % Richtung Weiß


def test_css_ist_eine_einzige_regel():
    """``html:root`` statt ``:root`` — sonst gewinnt Quasars eigener Block."""
    css = branding.farben_css("#7a1120", "#e8d8b0")
    assert css.count("{") == css.count("}") == 1
    assert css.strip().splitlines()[1].startswith("html:root {")


def test_mail_erbt_die_vereinsfarben(monkeypatch):
    """VTB_FARBE_* färbt auch die Mails — eine Stelle für beides."""
    from app.config.email_config import EmailConfig

    monkeypatch.setenv("VTB_FARBE_FLAECHE", "#7a1120")
    monkeypatch.setenv("VTB_FARBE_AKZENT", "#e8d8b0")
    monkeypatch.delenv("VTB_MAIL_FARBE_FLAECHE", raising=False)
    monkeypatch.delenv("VTB_MAIL_FARBE_AKZENT", raising=False)
    assert EmailConfig.get_mail_farbe_flaeche() == "#7a1120"
    assert EmailConfig.get_mail_farbe_akzent() == "#e8d8b0"


def test_mail_farbe_schlaegt_die_vereinsfarbe(monkeypatch):
    """Wer die Mail abweichend will, setzt zusätzlich VTB_MAIL_FARBE_*."""
    from app.config.email_config import EmailConfig

    monkeypatch.setenv("VTB_FARBE_FLAECHE", "#7a1120")
    monkeypatch.setenv("VTB_MAIL_FARBE_FLAECHE", "#101010")
    assert EmailConfig.get_mail_farbe_flaeche() == "#101010"
