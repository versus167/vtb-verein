"""
Import des Zutrittslogs einer Fremdanlage (Schloss ohne TTLock-Anschluss).

Das Tor an der Einfahrt hängt an einer eigenen Anlage, wird aber mit denselben
Chips geöffnet. Ihr Export ist eine CSV mit vier Spalten:

    Unlock Account,Unlock Type, Lock Name,Unlock Time
    Chip8,Karte entsperren,Tor Einfahrt,2026-08-10 17:47:05

Der Import führt diese Zeilen in denselben `tuer_zutritt_log` wie die Cloud-Logs
(`quelle='extern'`), damit Auswertung und Anzeige nicht zwei Welten kennen müssen:
Schloss-Protokoll, Chip-Nutzung und „Mein Zugang" funktionieren unverändert.

Drei Eigenheiten gegenüber dem Cloud-Sync:
- **Kein recordId.** Dedupliziert wird über Schloss + Zeitpunkt + Konto; derselbe
  Export lässt sich deshalb gefahrlos erneut einlesen (auch überlappende Zeiträume).
- **Kein Personenbezug in der Quelle.** Das Konto ('Chip8', 'Marko1') wird über
  `SchluesselChip.externe_kennung` → Bezeichnung → Kartennummer auf einen Chip und
  darüber auf ein Mitglied aufgelöst. Was nicht trifft, steht im Bericht und wird
  nachgezogen, sobald jemand die Kennung am Chip pflegt (`resolve_extern_konto`).
- **Naive Ortszeit.** Die Anlage schreibt Ortszeit ohne Zeitzone; gespeichert wird
  wie überall UTC-ISO. In der doppelten Stunde der Zeitumstellung gilt die Sommerzeit
  (`fold=0`) — raten wäre hier schlimmer als eine Stunde Unschärfe einmal im Jahr.

`dry_run` und `uebernehmen` laufen durch dieselbe Auswertung: die Vorschau zeigt
exakt das, was der Lauf tun würde („Vorschau == Aktion").
"""
import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.models.schliessanlage import (
    TuerZutrittLog, extern_record_type, record_type_label,
)
from app.services.import_common import KODIERUNGEN, clean

logger = logging.getLogger(__name__)

# Zeitzone der Fremdanlage. Fest verdrahtet wie im ICS-Export – die Anlage steht
# auf dem Vereinsgelände, eine Konfigurationsschraube dafür wäre Ballast.
ZEITZONE = ZoneInfo("Europe/Berlin")

# Spaltennamen des Exports (normalisiert: klein, ohne Randleerzeichen). Mehrere
# Schreibweisen je Feld, weil die Anlage je nach Sprachwahl anders exportiert.
_SPALTEN_ALIASE: dict[str, tuple[str, ...]] = {
    'konto': ('unlock account', 'account', 'benutzer', 'benutzername', 'konto', 'user'),
    'typ': ('unlock type', 'type', 'typ', 'art'),
    'schloss': ('lock name', 'lock', 'schloss', 'schlossname', 'tür', 'tuer'),
    'zeit': ('unlock time', 'time', 'zeit', 'zeitpunkt', 'datum', 'date'),
}

# Zeitformate der Quelle. Das erste ist das beobachtete; die übrigen fangen die
# üblichen Varianten ab, damit ein Firmware-Update den Import nicht stilllegt.
_ZEIT_FORMATE = (
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
    '%Y/%m/%d %H:%M:%S', '%Y/%m/%d %H:%M',
    '%d.%m.%Y %H:%M:%S', '%d.%m.%Y %H:%M',
)

# Trenner-Kandidaten in der Reihenfolge, in der bei Gleichstand entschieden wird.
_TRENNER = (',', ';', '\t')

# So viele unlesbare Zeilen werden im Bericht namentlich genannt – der Rest nur gezählt.
_MAX_FEHLER = 20


class ImportFehler(ValueError):
    """Die Datei ist als Zutritts-Export nicht lesbar (Kodierung, Kopfzeile)."""


@dataclass
class Zeile:
    """Eine geparste Export-Zeile (Zeitpunkt bereits als UTC-ISO)."""
    konto: str
    typ: str
    schloss: str
    zeitpunkt: str
    roh: dict


@dataclass
class KontoBericht:
    """Ein Konto der Fremdanlage und worauf es zeigt."""
    konto: str
    anzahl: int
    chip_id: Optional[int] = None
    chip_bezeichnung: Optional[str] = None
    mitglied_id: Optional[int] = None
    # Wem der Chip gehört – Mitglied oder Benutzerkonto (Platzwart & Co. haben keinen
    # Mitgliedsdatensatz). Für den Bericht zählt der Name, nicht die Herkunft.
    inhaber_name: Optional[str] = None

    @property
    def zugeordnet(self) -> bool:
        return self.chip_id is not None


@dataclass
class SchlossBericht:
    """Was der Import je Schloss ('Lock Name') vorfindet bzw. tut."""
    name: str
    schloss_id: Optional[int] = None
    neu_angelegt: bool = False       # Vorschau: „würde angelegt"
    zeilen: int = 0
    neu: int = 0
    doppelt: int = 0                 # schon vorhanden (oder Dublette in der Datei)
    von: Optional[str] = None
    bis: Optional[str] = None
    konten: list[KontoBericht] = field(default_factory=list)


@dataclass
class ImportBericht:
    commit: bool = False
    zeilen: int = 0
    neu: int = 0
    doppelt: int = 0
    ohne_zuordnung: int = 0          # Zeilen, deren Konto keinen Chip trifft
    nachgezogen: int = 0             # früher importierte Zeilen, jetzt zugeordnet
    schloesser: list[SchlossBericht] = field(default_factory=list)
    fehler: list[str] = field(default_factory=list)
    fehler_gesamt: int = 0

    @property
    def zusammenfassung(self) -> str:
        teile = [f"{self.zeilen} Zeilen gelesen", f"{self.neu} neu",
                 f"{self.doppelt} bereits vorhanden"]
        if self.ohne_zuordnung:
            teile.append(f"{self.ohne_zuordnung} ohne Chip-Zuordnung")
        if self.fehler_gesamt:
            teile.append(f"{self.fehler_gesamt} unlesbar")
        return ", ".join(teile)


# --- Parsen ------------------------------------------------------------------
def _dekodieren(daten: bytes) -> str:
    for kodierung in KODIERUNGEN:
        try:
            return daten.decode(kodierung)
        except UnicodeDecodeError:
            continue
    raise ImportFehler("Datei ist in keiner erwarteten Kodierung lesbar "
                       "(UTF-8 oder Windows-1252)")


def _trenner(kopfzeile: str) -> str:
    """Häufigsten Trenner der Kopfzeile wählen – Sniffer-Ersatz ohne Heuristik-Risiko."""
    return max(_TRENNER, key=kopfzeile.count)


def _spalten_zuordnen(kopf: list[str]) -> dict[str, str]:
    """Kopfzeile → {feld: Spaltenname}. Wirft, wenn ein Pflichtfeld fehlt."""
    normalisiert = {(name or '').strip().lower(): name for name in kopf}
    zuordnung: dict[str, str] = {}
    for feld, aliase in _SPALTEN_ALIASE.items():
        for alias in aliase:
            if alias in normalisiert:
                zuordnung[feld] = normalisiert[alias]
                break
    fehlend = [f for f in _SPALTEN_ALIASE if f not in zuordnung]
    if fehlend:
        raise ImportFehler(
            "Kopfzeile passt nicht zu einem Zutritts-Export – es fehlen: "
            + ", ".join(_SPALTEN_ALIASE[f][0] for f in fehlend)
            + f" (gefunden: {', '.join(k for k in kopf if k)})"
        )
    return zuordnung


def zeitpunkt_zu_iso(text: str) -> Optional[str]:
    """Ortszeit der Anlage → UTC-ISO (wie die Cloud-Logs). None, wenn unlesbar."""
    text = clean(text)
    if not text:
        return None
    zeit: Optional[datetime] = None
    for fmt in _ZEIT_FORMATE:
        try:
            zeit = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if zeit is None:
        try:
            zeit = datetime.fromisoformat(text)
        except ValueError:
            return None
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=ZEITZONE)
    return zeit.astimezone(timezone.utc).isoformat()


def parse(daten: bytes) -> tuple[list[Zeile], list[str]]:
    """Export einlesen. Gibt gelesene Zeilen und die Meldungen zu unlesbaren zurück."""
    text = _dekodieren(daten)
    erste_zeile = text.splitlines()[0] if text.strip() else ''
    if not erste_zeile:
        raise ImportFehler("Datei ist leer")
    leser = csv.DictReader(io.StringIO(text), delimiter=_trenner(erste_zeile))
    spalten = _spalten_zuordnen(list(leser.fieldnames or []))

    zeilen: list[Zeile] = []
    fehler: list[str] = []
    for nr, roh in enumerate(leser, start=2):          # 1 = Kopfzeile
        konto = clean(roh.get(spalten['konto']))
        schloss = clean(roh.get(spalten['schloss']))
        zeitpunkt = zeitpunkt_zu_iso(roh.get(spalten['zeit']) or '')
        if not schloss or not zeitpunkt:
            grund = "kein Schloss" if not schloss else "Zeitpunkt unlesbar"
            fehler.append(f"Zeile {nr}: {grund}")
            continue
        zeilen.append(Zeile(
            konto=konto, typ=clean(roh.get(spalten['typ'])), schloss=schloss,
            zeitpunkt=zeitpunkt, roh={k: v for k, v in roh.items() if k},
        ))
    return zeilen, fehler


# --- Import ------------------------------------------------------------------
def _inhaber_name(chip) -> Optional[str]:
    """Wem der Chip gehört: Mitglied, sonst Benutzerkonto, sonst niemandem."""
    if chip is None:
        return None
    if chip.mitglied_id is not None:
        name = f"{chip.mitglied_vorname or ''} {chip.mitglied_nachname or ''}".strip()
        return name or f"Mitglied #{chip.mitglied_id}"
    if chip.user_id is not None:
        return chip.user_username or f"Benutzer #{chip.user_id}"
    return None


def _log_zeile(z: Zeile, schloss_id: int, chip) -> TuerZutrittLog:
    record_type = extern_record_type(z.typ)
    return TuerZutrittLog(
        schloss_id=schloss_id,
        extern_konto=z.konto or None,
        record_type=record_type,
        # Originaltext der Anlage, wenn wir ihn nicht auf einen recordType abbilden
        # können – lieber die fremde Bezeichnung zeigen als ein nichtssagendes '-'.
        methode=record_type_label(record_type) if record_type else (z.typ or None),
        erfolg=True,                 # der Export listet ausschließlich Öffnungen
        key_name=z.konto or None,    # Anzeige-Rückfall, solange kein Chip zugeordnet ist
        chip_id=chip.id if chip else None,
        mitglied_id=chip.mitglied_id if chip else None,
        lock_date=z.zeitpunkt,
        raw=z.roh,
    )


def run_import(db, daten: bytes, *, commit: bool = False,
               actor: str = 'SYSTEM') -> ImportBericht:
    """Fremd-Export einlesen; ohne `commit` reine Vorschau (schreibt nichts)."""
    zeilen, fehler = parse(daten)
    bericht = ImportBericht(commit=commit, zeilen=len(zeilen),
                            fehler=fehler[:_MAX_FEHLER], fehler_gesamt=len(fehler))

    # Konto → Chip einmal je Konto auflösen (der Export wiederholt sie tausendfach).
    chips: dict[str, object] = {}
    for konto in {z.konto for z in zeilen if z.konto}:
        chips[konto] = db.schluessel_chips.find_active_by_externes_konto(konto)

    for schloss_name in dict.fromkeys(z.schloss for z in zeilen):   # Reihenfolge der Datei
        gruppe = [z for z in zeilen if z.schloss == schloss_name]
        schloss = db.tuer_schloesser.find_extern_by_name(schloss_name)
        sb = SchlossBericht(
            name=schloss_name,
            schloss_id=schloss.id if schloss else None,
            neu_angelegt=schloss is None,
            zeilen=len(gruppe),
            von=min(z.zeitpunkt for z in gruppe),
            bis=max(z.zeitpunkt for z in gruppe),
        )
        if schloss is None and commit:
            schloss = db.tuer_schloesser.create_extern(
                name=schloss_name,
                notiz="Automatisch angelegt beim Import eines Fremd-Logs "
                      "(nicht in der TTLock-Cloud).",
                by=actor,
            )
            sb.schloss_id = schloss.id

        bekannt = (db.tuer_zutritt_logs.extern_keys_for_schloss(schloss.id)
                   if schloss else set())
        je_konto: dict[str, int] = {}
        for z in gruppe:
            je_konto[z.konto] = je_konto.get(z.konto, 0) + 1
            schluessel = (z.zeitpunkt, z.konto or '')
            if schluessel in bekannt:
                sb.doppelt += 1
                continue
            bekannt.add(schluessel)          # Dubletten innerhalb der Datei mitzählen
            sb.neu += 1
            chip = chips.get(z.konto)
            if chip is None:
                bericht.ohne_zuordnung += 1
            if commit:
                db.tuer_zutritt_logs.insert_extern_if_new(
                    _log_zeile(z, schloss.id, chip))

        sb.konten = sorted(
            (KontoBericht(
                konto=konto, anzahl=anzahl,
                chip_id=chips[konto].id if chips.get(konto) else None,
                chip_bezeichnung=chips[konto].bezeichnung if chips.get(konto) else None,
                mitglied_id=(chips[konto].mitglied_id if chips.get(konto) else None),
                inhaber_name=_inhaber_name(chips.get(konto)),
            ) for konto, anzahl in je_konto.items()),
            key=lambda k: (-k.anzahl, k.konto.lower()),
        )
        bericht.schloesser.append(sb)
        bericht.neu += sb.neu
        bericht.doppelt += sb.doppelt

        if commit and sb.neu:
            juengste = max(z.zeitpunkt for z in gruppe)
            db.tuer_schloesser.update_letztes_event(
                schloss.id, letztes_event_at=juengste,
                letztes_event_type=extern_record_type(
                    next(z.typ for z in gruppe if z.zeitpunkt == juengste)),
                by=actor,
            )

    if commit:
        # Zeilen aus früheren Läufen nachziehen, deren Konto inzwischen einen Chip hat.
        for konto, chip in chips.items():
            if chip is not None:
                bericht.nachgezogen += db.tuer_zutritt_logs.resolve_extern_konto(
                    konto, chip_id=chip.id, mitglied_id=chip.mitglied_id)
        logger.info("Fremd-Log-Import: %s", bericht.zusammenfassung)
    return bericht
