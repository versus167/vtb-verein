"""
Tests für die Prüfung des Aufbaus von E-Mail-Adressen (app/services/mailadresse.py).

Der Kern soll Tippfehler abfangen, ohne zulässige Adressen abzulehnen – beides ist
hier abgedeckt. Die Meldungstexte sind bewusst mitgetestet: Sie stehen wörtlich im
Frontend-Pendant (frontend/src/utils/email.js), und beide Seiten sollen dasselbe
sagen, wenn dieselbe Eingabe abgelehnt wird.
"""
import pytest

from app.services.mailadresse import (
    is_valid_mailadresse,
    normalize_mailadresse,
    pruefe_mailadresse,
    validate_mailadresse,
)


GUELTIGE = [
    "vorstand@vtbchemnitz.de",
    "a@b.de",
    "max.mustermann@sub.verein-chemnitz.de",
    "erika+termine@example.org",
    "o'brien@example.com",
    "kasse_2026@vtb.museum",
    "team-1@a-b.co.uk",
]

UNGUELTIGE = [
    "max.mustermannweb.de",     # @ vergessen – der häufigste Vertipper
    "max@web",                  # Endung fehlt
    "max@@web.de",              # zwei @
    "@web.de",                  # kein lokaler Teil
    "max@",                     # keine Domain
    "max mustermann@web.de",    # Leerzeichen
    "max@web..de",              # leeres Label
    "max@-web.de",              # Label beginnt mit Bindestrich
    "max@web.d",                # einbuchstabige Endung
    "max@web.1de",              # Endung nicht alphabetisch
    ".max@web.de",              # führender Punkt im lokalen Teil
    "max.@web.de",              # abschließender Punkt im lokalen Teil
    "max..mustermann@web.de",   # doppelter Punkt im lokalen Teil
]


@pytest.mark.parametrize("adresse", GUELTIGE)
def test_gueltige_adressen(adresse):
    assert is_valid_mailadresse(adresse) is True
    assert validate_mailadresse(adresse) == adresse


@pytest.mark.parametrize("adresse", UNGUELTIGE)
def test_ungueltige_adressen(adresse):
    assert is_valid_mailadresse(adresse) is False
    with pytest.raises(ValueError):
        validate_mailadresse(adresse)


def test_umgebender_whitespace_faellt_weg():
    assert normalize_mailadresse("  kasse@verein.de \n") == "kasse@verein.de"
    assert validate_mailadresse("  kasse@verein.de ") == "kasse@verein.de"


def test_grossschreibung_bleibt_stehen():
    """Kleinschreiben würde den Bestand verändern: Unique-Index und Magic-Link-Suche
    vergleichen die Adresse so, wie sie gespeichert wurde."""
    assert validate_mailadresse("Max.Mustermann@Web.de") == "Max.Mustermann@Web.de"


def test_leer_ist_erlaubt_solange_nicht_pflicht():
    """Konten ohne Zugang haben keine Adresse (Schema v96)."""
    assert validate_mailadresse(None) is None
    assert validate_mailadresse("") is None
    assert validate_mailadresse("   ") is None


def test_leer_mit_pflicht_wird_abgelehnt():
    with pytest.raises(ValueError, match="erforderlich"):
        validate_mailadresse("  ", pflicht=True)


def test_laengengrenzen():
    lokal = "a" * 64
    assert is_valid_mailadresse(f"{lokal}@verein.de") is True
    assert is_valid_mailadresse(f"{'a' * 65}@verein.de") is False
    # 254 Zeichen sind die Obergrenze des ganzen Pfades (RFC 5321). Die Domain
    # besteht aus lauter zulässigen Labels (je 60 Zeichen), damit wirklich die
    # Gesamtlänge greift und nicht die Label-Regel.
    zu_lang = lokal + "@" + ".".join(["b" * 60] * 4) + ".de"
    assert len(zu_lang) > 254
    assert is_valid_mailadresse(zu_lang) is False


def test_meldung_nennt_die_ursache():
    assert "genau ein @" in pruefe_mailadresse("max.mustermannweb.de")
    assert "Endung" in pruefe_mailadresse("max@web")
    assert "Leerzeichen" in pruefe_mailadresse("max mustermann@web.de")
    assert pruefe_mailadresse("max@web.de") is None
