"""pain.008-Formatter: rendert einen SEPA-Einzugslauf als XML (SEPA-Basislastschrift).

Schema: pain.008.001.08 – seit November 2023 der Standard der Deutschen Kreditwirtschaft
für SEPA-Basislastschriften (CORE). Nur Standardbibliothek (xml.etree).

Zwei Eigenheiten, die das Format erzwingt:
- **Zeichensatz:** SEPA erlaubt nur einen eingeschränkten Latin-Zeichensatz. Umlaute und
  ß werden transliteriert (ä→ae, ß→ss), alles Unerlaubte fällt weg – sonst weist die Bank
  die Datei ab. Betrifft Namen und Verwendungszwecke.
- **Elementreihenfolge** ist Teil des XSD (sequence, nicht all): die Reihenfolge der
  Unterelemente unten ist verbindlich und darf nicht „aufgeräumt" werden.

Sequenztyp: durchgängig RCUR. Seit dem SEPA-Rulebook 2016 ist die Unterscheidung
FRST/RCUR nicht mehr erforderlich; RCUR für alle Einzüge erspart eine Mandats-Zustands-
verwaltung („war das schon mal eingezogen?").

Bündelung: Positionen desselben Mandats werden zu EINER Lastschrift zusammengefasst
(siehe ``gruppiere``). Die Bank berechnet Entgelte je eingereichter Lastschrift, und das
Mitglied sieht eine Buchung statt mehrerer. Über Mandate hinweg wird nie gebündelt.
"""
from datetime import date, datetime, timedelta
from typing import Optional
from xml.etree import ElementTree as ET

from app.models.sepa import SepaLauf, SepaPosition

NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
SEQUENZTYP = "RCUR"
LOCAL_INSTRUMENT = "CORE"

# Feldlängen laut Rulebook – wir schneiden ab, statt die Bank ablehnen zu lassen.
MAX_ID = 35
MAX_NAME = 70
MAX_VERWENDUNGSZWECK = 140

# SEPA-Zeichensatz: a-z A-Z 0-9 / - ? : ( ) . , ' + und Leerzeichen.
_ERLAUBT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-?:().,'+ ")
_UMSCHRIFT = {
    'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue', 'ß': 'ss',
    'é': 'e', 'è': 'e', 'ê': 'e', 'á': 'a', 'à': 'a', 'â': 'a', 'ç': 'c',
    'í': 'i', 'ì': 'i', 'ó': 'o', 'ò': 'o', 'ô': 'o', 'ú': 'u', 'ù': 'u', 'ñ': 'n',
    '&': '+', '"': "'", '_': '-',
}


def sepa_text(wert: Optional[str], max_len: int = MAX_NAME) -> str:
    """Text SEPA-konform machen: transliterieren, Unerlaubtes entfernen, kürzen.

    Whitespace (Tab/Umbruch) wird zuerst zu einem Leerzeichen – sonst würde ein
    mehrzeiliger Verwendungszweck beim Filtern zu einem Wort zusammenkleben.
    """
    if not wert:
        return ""
    entspannt = " ".join(str(wert).split())
    umgeschrieben = "".join(_UMSCHRIFT.get(z, z) for z in entspannt)
    gefiltert = "".join(z for z in umgeschrieben if z in _ERLAUBT)
    return " ".join(gefiltert.split())[:max_len]


def _betrag(cent: int) -> str:
    """Cent → '123.45' (Punkt als Dezimaltrenner, wie im Schema gefordert).

    Lastschriftbeträge sind immer positiv – ein negativer Wert käme aus einem Fehler
    und wird deshalb als Betrag ohne Vorzeichen ausgegeben (die Vorschau filtert ≤ 0
    ohnehin aus).
    """
    cent = abs(cent)
    return f"{cent // 100}.{cent % 100:02d}"


# --------------------------------------------------------------------------- #
# TARGET2-Kalender / Ausführungsdatum
# --------------------------------------------------------------------------- #

def _ostersonntag(jahr: int) -> date:
    """Ostersonntag nach der anonymen gregorianischen Osterformel."""
    a, b, c = jahr % 19, jahr // 100, jahr % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    monat = (h + l - 7 * m + 114) // 31
    tag = ((h + l - 7 * m + 114) % 31) + 1
    return date(jahr, monat, tag)


def ist_target2_tag(tag: date) -> bool:
    """TARGET2-Geschäftstag? Wochenende und die sechs TARGET2-Feiertage sind keine.

    TARGET2 schließt an Neujahr, Karfreitag, Ostermontag, 1. Mai sowie am 25./26.12.
    """
    if tag.weekday() >= 5:
        return False
    ostern = _ostersonntag(tag.year)
    feiertage = {
        date(tag.year, 1, 1),
        ostern - timedelta(days=2),   # Karfreitag
        ostern + timedelta(days=1),   # Ostermontag
        date(tag.year, 5, 1),
        date(tag.year, 12, 25),
        date(tag.year, 12, 26),
    }
    return tag not in feiertage


def naechster_target2_tag(ab: date) -> date:
    """``ab`` selbst, wenn es ein TARGET2-Tag ist, sonst der nächste."""
    tag = ab
    while not ist_target2_tag(tag):
        tag += timedelta(days=1)
    return tag


def ausfuehrungsdatum(ab: date, vorlauftage: int) -> date:
    """Frühestes Ausführungsdatum: ``vorlauftage`` TARGET2-Tage nach ``ab``.

    Die Bank braucht für eine Basislastschrift mindestens einen Geschäftstag Vorlauf
    (D-1); der Verein stellt die Frist in den Fibu-Einstellungen ein.
    """
    tag = naechster_target2_tag(ab)
    for _ in range(max(0, vorlauftage)):
        tag = naechster_target2_tag(tag + timedelta(days=1))
    return tag


def message_id(erzeugt: datetime, lauf_id: Optional[int] = None) -> str:
    """MsgId: je Lauf eindeutig, ≤35 Zeichen, nur erlaubte Zeichen."""
    basis = f"VTB-{erzeugt.strftime('%Y%m%d-%H%M%S')}"
    if lauf_id is not None:
        basis = f"{basis}-{lauf_id}"
    return basis[:MAX_ID]


def end_to_end_id(mandatsref: str, ausfuehrungsdatum: str) -> str:
    """EndToEndId je Mandat und Lauf: ``<Mandatsreferenz>-<JJJJMMTT>``.

    Bis dahin war das die FBASC-Belegnummer (B<id>/G<id>). Das geht nicht mehr, seit
    mehrere Posten desselben Mandats zu EINER Lastschrift zusammengefasst werden – eine
    Lastschrift deckt dann mehrere Belege ab. Ein Rückläufer ist trotzdem zuzuordnen:
    die gespeicherten Positionen mit dieser EndToEndId nennen die betroffenen Posten.
    """
    datum = (ausfuehrungsdatum or "").replace("-", "")[:8]
    if not datum:
        return sepa_text(mandatsref, MAX_ID)
    return f"{sepa_text(mandatsref, MAX_ID - len(datum) - 1)}-{datum}"


def _gruppen_schluessel(p: SepaPosition) -> tuple:
    """Was eine Lastschrift ausmacht: dieselbe EndToEndId UND dasselbe Mandat/Konto.

    Die EndToEndId allein würde reichen (der Service vergibt sie je Mandat), das Konto
    steht aus Sicherheitsgründen mit im Schlüssel: bei fehlerhaften Stammdaten (zwei
    Mitglieder mit gleicher Mandatsreferenz) würde sonst von einem falschen Konto
    eingezogen. Getrennte Gruppen sind harmlos, ein falscher Debitor nicht.
    """
    return (p.end_to_end_id, p.mandatsref, p.mandatsdatum, p.iban, p.bic, p.kontoinhaber)


def gruppiere(positionen: list[SepaPosition]) -> list[list[SepaPosition]]:
    """Positionen zu Lastschriften bündeln – gleiches Mandat = eine Lastschrift.

    Entgelte fallen je eingereichter Lastschrift an, nicht je Datei; zwei Beiträge
    desselben Mitglieds werden deshalb zusammen eingezogen. Ältere Läufe, deren
    Positionen noch je eine eigene EndToEndId (Belegnummer) tragen, bleiben dabei
    unverändert einzeln – ein Re-Download liefert weiterhin dieselbe Datei.
    """
    gruppen: dict[tuple, list[SepaPosition]] = {}
    for p in positionen:
        gruppen.setdefault(_gruppen_schluessel(p), []).append(p)
    return list(gruppen.values())   # dict behält die Einfügereihenfolge


def _verwendungszweck(gruppe: list[SepaPosition]) -> str:
    """Verwendungszwecke der zusammengefassten Posten zu einem Feld verbinden.

    Passen nicht alle in die 140 Zeichen, werden so viele genannt wie hineinpassen und
    der Rest mit „u.w." angedeutet – verständlicher als ein mitten im Wort
    abgeschnittener letzter Posten.
    """
    teile = [t for t in (sepa_text(p.verwendungszweck, MAX_VERWENDUNGSZWECK)
                         for p in gruppe if p.verwendungszweck) if t]
    if not teile:
        return ""
    text = ", ".join(teile)
    if len(text) <= MAX_VERWENDUNGSZWECK:
        return text

    rest = " u.w."
    passend: list[str] = []
    for t in teile:
        if len(", ".join(passend + [t])) + len(rest) > MAX_VERWENDUNGSZWECK:
            break
        passend.append(t)
    return ", ".join(passend) + rest if passend else text[:MAX_VERWENDUNGSZWECK]


# --------------------------------------------------------------------------- #
# XML
# --------------------------------------------------------------------------- #

def _kind(eltern: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    el = ET.SubElement(eltern, tag)
    if text is not None:
        el.text = text
    return el


def _finanzinstitut(eltern: ET.Element, tag: str, bic: Optional[str]) -> None:
    """FinInstnId-Block: BIC, wenn bekannt – sonst der IBAN-only-Platzhalter."""
    fin = _kind(_kind(eltern, tag), "FinInstnId")
    if bic:
        _kind(fin, "BICFI", sepa_text(bic, MAX_ID))
    else:
        _kind(_kind(fin, "Othr"), "Id", "NOTPROVIDED")


def render(lauf: SepaLauf, erzeugt_am: Optional[datetime] = None) -> bytes:
    """Rendert den Lauf als pain.008.001.08-XML (UTF-8, mit XML-Deklaration)."""
    if not lauf.positionen:
        raise ValueError("SEPA-Lauf ohne Positionen kann nicht gerendert werden.")
    erzeugt_am = erzeugt_am or datetime.now()
    # NbOfTxs zählt Lastschriften, nicht Posten: mehrere Posten desselben Mandats
    # sind EINE Lastschrift (siehe gruppiere). CtrlSum bleibt die Gesamtsumme.
    gruppen = gruppiere(lauf.positionen)
    anzahl = str(len(gruppen))
    summe = _betrag(sum(p.betrag_cent for p in lauf.positionen))

    ET.register_namespace("", NAMESPACE)
    document = ET.Element(f"{{{NAMESPACE}}}Document")
    initiation = _kind(document, "CstmrDrctDbtInitn")

    kopf = _kind(initiation, "GrpHdr")
    _kind(kopf, "MsgId", lauf.message_id[:MAX_ID])
    _kind(kopf, "CreDtTm", erzeugt_am.replace(microsecond=0).isoformat())
    _kind(kopf, "NbOfTxs", anzahl)
    _kind(kopf, "CtrlSum", summe)
    _kind(_kind(kopf, "InitgPty"), "Nm", sepa_text(lauf.glaeubiger_name))

    zahlung = _kind(initiation, "PmtInf")
    _kind(zahlung, "PmtInfId", lauf.message_id[:MAX_ID])
    _kind(zahlung, "PmtMtd", "DD")
    _kind(zahlung, "BtchBookg", "true")
    _kind(zahlung, "NbOfTxs", anzahl)
    _kind(zahlung, "CtrlSum", summe)
    typ = _kind(zahlung, "PmtTpInf")
    _kind(_kind(typ, "SvcLvl"), "Cd", "SEPA")
    _kind(_kind(typ, "LclInstrm"), "Cd", LOCAL_INSTRUMENT)
    _kind(typ, "SeqTp", lauf.sequenztyp or SEQUENZTYP)
    _kind(zahlung, "ReqdColltnDt", lauf.ausfuehrungsdatum)
    _kind(_kind(zahlung, "Cdtr"), "Nm", sepa_text(lauf.glaeubiger_name))
    _kind(_kind(_kind(zahlung, "CdtrAcct"), "Id"), "IBAN",
          sepa_text(lauf.glaeubiger_iban, MAX_ID))
    _finanzinstitut(zahlung, "CdtrAgt", lauf.glaeubiger_bic)
    _kind(zahlung, "ChrgBr", "SLEV")
    andere = _kind(_kind(_kind(_kind(zahlung, "CdtrSchmeId"), "Id"), "PrvtId"), "Othr")
    _kind(andere, "Id", sepa_text(lauf.glaeubiger_id, MAX_ID))
    _kind(_kind(andere, "SchmeNm"), "Prtry", "SEPA")

    for gruppe in gruppen:
        kopf = gruppe[0]                  # Mandat/Konto sind je Gruppe identisch
        posten = _kind(zahlung, "DrctDbtTxInf")
        _kind(_kind(posten, "PmtId"), "EndToEndId", sepa_text(kopf.end_to_end_id, MAX_ID))
        betrag = _kind(posten, "InstdAmt", _betrag(sum(p.betrag_cent for p in gruppe)))
        betrag.set("Ccy", "EUR")
        mandat = _kind(_kind(posten, "DrctDbtTx"), "MndtRltdInf")
        _kind(mandat, "MndtId", sepa_text(kopf.mandatsref, MAX_ID))
        _kind(mandat, "DtOfSgntr", kopf.mandatsdatum)
        _finanzinstitut(posten, "DbtrAgt", kopf.bic)
        _kind(_kind(posten, "Dbtr"), "Nm", sepa_text(kopf.kontoinhaber))
        _kind(_kind(_kind(posten, "DbtrAcct"), "Id"), "IBAN", sepa_text(kopf.iban, MAX_ID))
        zweck = _verwendungszweck(gruppe)
        if zweck:
            _kind(_kind(posten, "RmtInf"), "Ustrd", sepa_text(zweck, MAX_VERWENDUNGSZWECK))

    ET.indent(document, space="  ")
    return ET.tostring(document, encoding="utf-8", xml_declaration=True)
