"""
IBAN-Validierung nach ISO 13616 (Struktur) und ISO 7064 mod 97-10 (Prüfziffer).

Framework-agnostischer Kern (keine FastAPI-Abhängigkeit): wird vom HTTP-Adapter
`backend/core/validation.py` und dem Frontend-Pendant `frontend/src/utils/iban.js`
gespiegelt. Eine leere IBAN gilt als „nicht gesetzt" (None) und ist gültig – das
Feld ist optional (Zahlungsart kann bar/Überweisung sein).
"""
import re
from typing import Optional

# Offizielle IBAN-Längen je Land (SWIFT IBAN Registry). Kompakt gehalten:
# europäische SEPA-Länder + häufige Nachbarn. Unbekannte Länderkürzel werden
# nur generisch (Gesamtlänge 15–34) geprüft.
IBAN_LENGTHS: dict[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28,
    "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24,
    "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18,
    "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IS": 26,
    "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21,
    "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19,
    "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24, "PL": 28,
    "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SC": 31,
    "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TN": 24, "TR": 26, "UA": 29,
    "VA": 22, "VG": 24, "XK": 20,
}

# 2 Buchstaben (Land) + 2 Ziffern (Prüfziffer) + 11–30 alphanumerische BBAN-Stellen.
_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")


def normalize_iban(value: Optional[str]) -> Optional[str]:
    """Whitespace entfernen, Großbuchstaben; leer → None."""
    if value is None:
        return None
    cleaned = re.sub(r"\s+", "", value).upper()
    return cleaned or None


def _mod97(iban: str) -> int:
    """ISO 7064 mod 97-10: erste 4 Zeichen ans Ende, Buchstaben → Zahlen (A=10..Z=35)."""
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)  # 0-9 → sich selbst, A-Z → 10-35
    return int(digits) % 97


def is_valid_iban(value: Optional[str]) -> bool:
    """True, wenn die (normalisierte) IBAN Struktur, Länderlänge und Prüfziffer erfüllt."""
    iban = normalize_iban(value)
    if iban is None:
        return False
    if not _IBAN_RE.match(iban):
        return False
    if not (15 <= len(iban) <= 34):
        return False
    expected = IBAN_LENGTHS.get(iban[:2])
    if expected is not None and len(iban) != expected:
        return False
    return _mod97(iban) == 1


def validate_iban(value: Optional[str]) -> Optional[str]:
    """Normalisiert die IBAN und gibt sie kanonisch zurück.

    Leer/None → None (gültig, da optional). Ungültige IBAN → ValueError.
    """
    iban = normalize_iban(value)
    if iban is None:
        return None
    if not is_valid_iban(iban):
        raise ValueError("Ungültige IBAN – bitte Format und Prüfziffer prüfen.")
    return iban
