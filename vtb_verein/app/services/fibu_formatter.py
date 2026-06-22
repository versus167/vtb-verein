"""FBASC-Formatter (hmd.rewe): rendert FibuExportPosition-Listen zur Datei `fbasc.hia`.

Aufbau laut „Schnittstellenbeschreibung FBASC Format" (hmd, Stand 21.11.2025): Felder
00..70 (genutzt bis 48 + 59 Mailadresse + 70 abw. Kontoinhaber), Trennzeichen `;`,
Zeilenende CR+LF, leere Felder bleiben leer (`;;`), Betrag `n,nn` (Komma), Datum
`TT.MM.JJJJ`. Encoding UTF-8 (mit dem Nutzer abgestimmt). Beträge sind immer positiv –
das Vorzeichen steckt im S/H-Kennzeichen (Feld 03).
"""
from datetime import date
from typing import Optional

from app.models.fibu import FibuExportPosition

FBASC_DATEINAME = "fbasc.hia"
_FELD_ANZAHL = 71          # Felder 00..70 (59 Mailadresse, 70 abw. Kontoinhaber)
_SEP = ";"
_EOL = "\r\n"


def _datum(iso: Optional[str]) -> str:
    """ISO-Datum (YYYY-MM-DD…) → TT.MM.JJJJ; leer/ungültig → ''."""
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return ""


def _betrag(value: float) -> str:
    """Immer positiv, 2 Nachkommastellen, Komma als Dezimaltrenner."""
    return f"{abs(value):.2f}".replace(".", ",")


def _clean(value) -> str:
    """Feldwert säubern: kein Trennzeichen/Zeilenumbruch in einer Zelle."""
    if value is None:
        return ""
    return str(value).replace(_SEP, ",").replace("\r", " ").replace("\n", " ").strip()


def _land(value: Optional[str]) -> str:
    """FBASC-Länderkennung (max. 3 Zeichen); Fallback DE."""
    land = (value or "").strip()
    return land if 0 < len(land) <= 3 else "DE"


def felder(p: FibuExportPosition) -> list[str]:
    """Baut die 49 FBASC-Felder (Index = Feldnummer) für eine Position."""
    f = [""] * _FELD_ANZAHL
    f[0] = _clean(p.konto)              # Kontonummer (Debitor/Personenkonto)
    f[1] = _clean(p.gegenkonto)         # Gegenkonto (Erlös-Sachkonto)
    f[2] = _betrag(p.betrag)            # Betrag
    f[3] = p.soll_haben                 # S/H
    f[4] = _clean(p.belegnummer)        # Belegnummer (OPOS)
    f[6] = _clean(p.steuerschluessel)   # Steuerschlüssel (i.d.R. leer)
    if p.kostenstelle is not None:      # Kostenträger (08) nur mit Kostenstelle (07)
        f[7] = _clean(p.kostenstelle)
        if p.kostentraeger is not None:
            f[8] = _clean(p.kostentraeger)
    f[10] = _datum(p.belegdatum)        # Belegdatum
    f[11] = _datum(p.faelligkeitsdatum)  # Fälligkeitsdatum
    f[12] = _clean(p.buchungstext)      # Buchungstext
    f[17] = "E"                         # Währung EURO
    f[19] = "D"                         # Kontenart Debitor
    f[20] = _clean(p.suchname)          # Suchname (Adresscode)
    f[22] = _clean(p.nachname)          # Name
    f[24] = _clean(p.strasse)           # Straße
    f[25] = _clean(p.plz)               # PLZ
    f[26] = _clean(p.ort)               # Ort
    f[27] = _land(p.land)               # Land
    if p.lastschrifteinzug:
        f[36] = _clean(p.lastschrifteinzug)  # Lastschrifteinzug (1)
    f[40] = _clean(p.iban)              # IBAN
    f[41] = _clean(p.bic)              # BIC
    f[43] = _clean(p.vorname)           # Vorname (Erweiterung zu Feld 22)
    f[47] = _clean(p.mandatsref)        # Mandatsreferenznummer
    f[48] = _datum(p.mandatsdatum)      # Datum der Mandatsreferenz
    f[59] = _clean(p.mailadresse)       # Mailadresse Personenkonto
    f[70] = _clean(p.kontoinhaber)      # Abweichender Kontoinhaber (zur IBAN)
    return f


def render_zeile(p: FibuExportPosition) -> str:
    return _SEP.join(felder(p))


def render(positionen: list[FibuExportPosition]) -> bytes:
    """Rendert die komplette `fbasc.hia` (UTF-8, CR+LF je Satz)."""
    text = "".join(render_zeile(p) + _EOL for p in positionen)
    return text.encode("utf-8")
