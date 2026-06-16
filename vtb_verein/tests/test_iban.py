"""
Tests für die IBAN-Validierung (ISO 13616 Struktur + ISO 7064 mod 97-10).
"""
import pytest

from app.services.iban import normalize_iban, is_valid_iban, validate_iban


# Offizielle Beispiel-IBANs (gültige Prüfziffer)
GUELTIGE = [
    "DE89370400440532013000",
    "AT611904300234573201",
    "CH9300762011623852957",
    "GB82WEST12345698765432",
    "FR1420041010050500013M02606",
    "NL91ABNA0417164300",
    "BE68539007547034",
]


@pytest.mark.parametrize("iban", GUELTIGE)
def test_gueltige_ibans(iban):
    assert is_valid_iban(iban) is True
    assert validate_iban(iban) == iban


def test_normalisierung_leerzeichen_und_kleinbuchstaben():
    eingabe = "de89 3704 0044 0532 0130 00"
    assert normalize_iban(eingabe) == "DE89370400440532013000"
    assert validate_iban(eingabe) == "DE89370400440532013000"


def test_leer_und_none_sind_gueltig():
    assert normalize_iban(None) is None
    assert normalize_iban("") is None
    assert normalize_iban("   ") is None
    assert validate_iban(None) is None
    assert validate_iban("") is None
    assert validate_iban("   ") is None
    # is_valid_iban prüft eine konkrete IBAN → leer ist keine gültige IBAN
    assert is_valid_iban("") is False
    assert is_valid_iban(None) is False


@pytest.mark.parametrize("iban", [
    "DE89370400440532013001",   # falsche Prüfziffer
    "DE0012345678901234567",    # falsche Länge für DE (DE=22)
    "DE89 3704 0044 0532",      # zu kurz
    "ZZ89370400440532013000",   # unbekanntes Land, Prüfziffer passt nicht
    "DE89-3704-0044",           # Sonderzeichen / zu kurz
    "1234567890",               # kein Ländercode
    "DEAB370400440532013000",   # Prüfziffer-Stellen keine Ziffern
])
def test_ungueltige_ibans_werden_abgelehnt(iban):
    assert is_valid_iban(iban) is False
    with pytest.raises(ValueError):
        validate_iban(iban)


def test_falsche_laenderlaenge_wird_erkannt():
    # mod-97 könnte zufällig passen, aber DE muss exakt 22 Stellen haben
    assert is_valid_iban("DE8937040044053201300000") is False
