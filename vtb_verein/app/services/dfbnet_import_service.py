"""DFBnet-Vereinsspielplan: Parser und Dry-Run-Bericht (#95, Etappe 3 des Plans).

Diese Stufe SCHREIBT NICHTS. Sie liest den Export, ordnet jede Zeile zu und liefert
einen Bericht, was ein späterer Lauf tun würde. Das Anlegen/Ändern folgt getrennt —
so lässt sich der Abgleich gefahrlos gegen echte Dateien prüfen.

Eigenheiten des Formats (alle drei kosten sonst Stunden):

* **UTF-16LE mit BOM, Tab-getrennt.** Nicht Semikolon, nicht UTF-8 — im Haus damit
  die dritte Kodierungsvariante nach SPG (cp1252) und LINEAR (UTF-8).
* **„Typ" kommt zweimal vor**: einmal als Platztyp (Rasenplatz), einmal als
  Spieltyp (Meisterschaft/Pokal/Freundschaftsspiel/Turnier). Ein DictReader
  behielte davon stillschweigend nur eine Spalte — deshalb werden Wiederholungen
  im Kopf durchnummeriert und positionsgetreu gelesen.
* **Nicht jede Zeile ist ein eigenes Spiel.** Der Vereinsspielplan enthält auch
  Partien fremder Vereine auf den eigenen Plätzen; er ist zugleich ein
  Platzbelegungsplan.

Die Schiedsrichter-Spalten (Namen, Ausweisnummern, Schirigebiet) werden bewusst
NICHT übernommen: Für den Kalender braucht sie niemand, und was nicht gespeichert
wird, muss auch nicht gelöscht werden.
"""
import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Spaltenköpfe, wie sie im Export stehen. Wiederholte Namen bekommen beim Einlesen
# ein "#2" angehängt (s. _eindeutige_koepfe) – daher hier „Typ#2" für den Spieltyp.
SPALTE_MANNSCHAFTSART = 'Mannschaftsart'
SPALTE_STAFFEL = 'Staffel'
SPALTE_SPIELSTAETTE = 'Spielstätte'
SPALTE_SPIELSTAETTEN_NR = 'Spielstätten-Nr.'
SPALTE_STRASSE = 'Straße/Hausnr.'
SPALTE_PLZ = 'PLZ'
SPALTE_ORT = 'Ort'
SPALTE_PARALLEL = 'Max. parallele Spiele'
SPALTE_DATUM = 'Spieldatum'
SPALTE_UHRZEIT = 'Uhrzeit'
SPALTE_SPIELTAG = 'Sptg.'
SPALTE_SPIELKENNUNG = 'Spielkennung'
SPALTE_SPIELTYP = 'Typ#2'
SPALTE_LIGA = 'Liga'
SPALTE_HEIM = 'Heimmannschaft'
SPALTE_GAST = 'Gastmannschaft'

# Einordnung einer Zeile im Bericht
NEU = 'neu'                       # eigenes Team, Spiel noch nicht im Kalender
AENDERUNG = 'aenderung'           # eigenes Team, Termin da, DFBnet weicht ab
UNVERAENDERT = 'unveraendert'     # eigenes Team, Termin da, alles gleich
PLATZBELEGUNG = 'platzbelegung'   # fremdes Spiel auf eigenem Platz
FREMD = 'fremd'                   # weder eigenes Team noch eigener Platz
# Ein „kein Team zugeordnet" gibt es bewusst NICHT als Einordnung: Ohne Zuordnung
# ist ein Team von außen nicht von einem fremden Verein zu unterscheiden. Welche
# Namen im Export vorkamen, trägt stattdessen `unbekannte_teams` im Bericht —
# das ist die Liste, an der die Zuordnung nachgepflegt wird.
# Ein vereinsinternes Spiel (beide Mannschaften sind eigene Teams) ist NICHT
# mehrdeutig, sondern ergibt ZWEI Befunde – je Mannschaft einen. Sonst könnte nur
# einer der beiden Kader zu-/absagen. Möglich seit Schema v82: die Spielkennung ist
# je Mannschaft eindeutig, nicht mehr vereinsweit.

# Felder, die beim Abgleich verglichen werden. Treffpunkt und Treffpunktzeit stehen
# bewusst NICHT dabei – die pflegt das Team, der Import fasst sie nie an.
VERGLEICHSFELDER = ('beginn', 'ort', 'heim_auswaerts', 'gegner')


@dataclass
class Spiel:
    """Eine gelesene Zeile, schon auf das Wesentliche eingedampft."""
    zeile: int
    spielkennung: str
    mannschaftsart: str
    staffel: str
    liga: str
    spieltyp: str
    spieltag: str
    beginn: Optional[str]           # 'YYYY-MM-DDTHH:MM' (lokale Wandzeit)
    heim: str
    gast: str
    spielstaette: str
    spielstaetten_nr: str
    strasse: str
    plz: str
    ort: str
    parallel_moeglich: int = 1

    @property
    def ort_text(self) -> str:
        """Anzeige-Ort für den Termin: Spielstätte + Adresse."""
        adresse = ' '.join(x for x in (self.plz, self.ort) if x)
        return ', '.join(x for x in (self.spielstaette, self.strasse, adresse) if x)


@dataclass
class ZeilenBefund:
    spiel: Spiel
    einordnung: str
    mannschaft_id: Optional[int] = None
    mannschaft_name: Optional[str] = None
    heim_auswaerts: Optional[str] = None
    termin_id: Optional[int] = None
    abweichungen: list = field(default_factory=list)   # [{feld, app, dfbnet}]
    hinweis: Optional[str] = None


@dataclass
class ImportBericht:
    zeilen: int = 0
    befunde: list = field(default_factory=list)
    # [{name, mannschaftsart, anzahl}] – im Export vorhanden, in der App nicht zugeordnet
    unbekannte_teams: list = field(default_factory=list)
    # [{name, dfbnet_nr, strasse, plz, ort, parallel_moeglich, anzahl}] – Vorschläge
    neue_spielstaetten: list = field(default_factory=list)
    fehler: list = field(default_factory=list)         # Zeilen, die nicht lesbar waren

    @property
    def zusammenfassung(self) -> dict:
        z = Counter(b.einordnung for b in self.befunde)
        return {k: z.get(k, 0) for k in
                (NEU, AENDERUNG, UNVERAENDERT, PLATZBELEGUNG, FREMD)}


# --------------------------------------------------------------------- Parser

def dekodieren(daten: bytes) -> str:
    """Text aus den Rohbytes – Kodierung wird probiert, nicht geraten.

    Der DFBnet-Export ist UTF-16LE mit BOM; die anderen Varianten stehen dahinter,
    damit eine per Hand umgespeicherte Datei nicht am Parser scheitert.
    """
    if daten[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return daten.decode('utf-16')
    for kodierung in ('utf-8-sig', 'utf-8', 'cp1252'):
        try:
            return daten.decode(kodierung)
        except UnicodeDecodeError:
            continue
    raise ValueError('Kodierung der Datei nicht erkannt')


def _eindeutige_koepfe(kopf: list[str]) -> list[str]:
    """Wiederholte Spaltennamen durchnummerieren: „Typ", „Typ#2", …

    Der Export führt „Typ" zweimal (Platztyp und Spieltyp). Ohne diese Auflösung
    verlöre ein namensbasierter Zugriff stillschweigend eine der beiden Spalten.
    """
    gesehen: Counter = Counter()
    ergebnis = []
    for name in kopf:
        name = (name or '').strip()
        gesehen[name] += 1
        ergebnis.append(name if gesehen[name] == 1 else f'{name}#{gesehen[name]}')
    return ergebnis


def _wandzeit(datum: str, uhrzeit: str) -> Optional[str]:
    """'06.08.2026' + '19:00' -> '2026-08-06T19:00'."""
    datum, uhrzeit = (datum or '').strip(), (uhrzeit or '').strip()
    if not datum or not uhrzeit:
        return None
    try:
        tag = datetime.strptime(datum, '%d.%m.%Y').date()
        datetime.strptime(uhrzeit, '%H:%M')
    except ValueError:
        return None
    return f'{tag.isoformat()}T{uhrzeit}'


def _zahl(wert: str, standard: int = 1) -> int:
    try:
        return max(1, int((wert or '').strip()))
    except ValueError:
        return standard


def parse_spielplan(daten: bytes) -> tuple[list[Spiel], list[str]]:
    """Liest den Export. Gibt (Spiele, Fehlermeldungen) zurück.

    Unlesbare Zeilen brechen den Lauf nicht ab, sondern landen als Meldung im
    Bericht – ein Tippfehler in einer Zeile soll nicht den ganzen Spielplan kosten.
    """
    text = dekodieren(daten)
    zeilen = list(csv.reader(text.splitlines(), delimiter='\t'))
    if not zeilen:
        return [], ['Datei ist leer']

    koepfe = _eindeutige_koepfe(zeilen[0])
    idx = {name: i for i, name in enumerate(koepfe)}
    fehlend = [s for s in (SPALTE_SPIELKENNUNG, SPALTE_HEIM, SPALTE_GAST, SPALTE_DATUM)
               if s not in idx]
    if fehlend:
        return [], [f'Spalten fehlen: {", ".join(fehlend)}']

    def feld(zeile: list[str], name: str) -> str:
        i = idx.get(name)
        return (zeile[i].strip() if i is not None and i < len(zeile) else '')

    spiele, fehler = [], []
    for nr, zeile in enumerate(zeilen[1:], start=2):
        if not any((z or '').strip() for z in zeile):
            continue
        kennung = feld(zeile, SPALTE_SPIELKENNUNG)
        if not kennung:
            fehler.append(f'Zeile {nr}: ohne Spielkennung, übersprungen')
            continue
        beginn = _wandzeit(feld(zeile, SPALTE_DATUM), feld(zeile, SPALTE_UHRZEIT))
        if beginn is None:
            fehler.append(f'Zeile {nr}: Datum/Uhrzeit unlesbar, übersprungen')
            continue
        spiele.append(Spiel(
            zeile=nr,
            spielkennung=kennung,
            mannschaftsart=feld(zeile, SPALTE_MANNSCHAFTSART),
            staffel=feld(zeile, SPALTE_STAFFEL),
            liga=feld(zeile, SPALTE_LIGA),
            spieltyp=feld(zeile, SPALTE_SPIELTYP),
            spieltag=feld(zeile, SPALTE_SPIELTAG),
            beginn=beginn,
            heim=feld(zeile, SPALTE_HEIM),
            gast=feld(zeile, SPALTE_GAST),
            spielstaette=feld(zeile, SPALTE_SPIELSTAETTE),
            spielstaetten_nr=feld(zeile, SPALTE_SPIELSTAETTEN_NR),
            strasse=feld(zeile, SPALTE_STRASSE),
            plz=feld(zeile, SPALTE_PLZ),
            ort=feld(zeile, SPALTE_ORT),
            parallel_moeglich=_zahl(feld(zeile, SPALTE_PARALLEL)),
        ))
    return spiele, fehler


# ------------------------------------------------------------------- Dry-Run

def _beschreibung(s: Spiel) -> str:
    teile = [s.spieltyp, s.liga or s.staffel]
    if s.spieltag:
        teile.append(f'Sptg. {s.spieltag}')
    return ' · '.join(t for t in teile if t)


def dry_run(db, daten: bytes) -> ImportBericht:
    """Ordnet jede Zeile zu und meldet, was ein Lauf täte. Schreibt nichts."""
    spiele, fehler = parse_spielplan(daten)
    bericht = ImportBericht(zeilen=len(spiele), fehler=fehler)

    unbekannt: Counter = Counter()
    neue_staetten: dict = {}

    for s in spiele:
        heim_team = db.mannschaften.find_by_dfbnet(s.heim, s.mannschaftsart) if s.heim else None
        gast_team = db.mannschaften.find_by_dfbnet(s.gast, s.mannschaftsart) if s.gast else None
        staette = (db.spielstaetten.get_by_dfbnet_nr(s.spielstaetten_nr)
                   if s.spielstaetten_nr else None)

        # Spielstätten, die es noch nicht als Stammdatum gibt, zum Anlegen vorschlagen
        if staette is None and s.spielstaetten_nr:
            eintrag = neue_staetten.setdefault(s.spielstaetten_nr, {
                'name': s.spielstaette, 'dfbnet_nr': s.spielstaetten_nr,
                'strasse': s.strasse, 'plz': s.plz, 'ort': s.ort,
                'parallel_moeglich': s.parallel_moeglich, 'anzahl': 0,
            })
            eintrag['anzahl'] += 1

        if heim_team is None and gast_team is None:
            # Kein eigenes Team. Eigener Platz? Dann Platzbelegung, sonst irrelevant.
            if staette is not None and staette.ist_eigen:
                bericht.befunde.append(ZeilenBefund(spiel=s, einordnung=PLATZBELEGUNG))
            else:
                bericht.befunde.append(ZeilenBefund(spiel=s, einordnung=FREMD))
            for name in (s.heim, s.gast):
                if name:
                    unbekannt[(name, s.mannschaftsart)] += 1
            continue

        # Je eigenem Team ein Befund: Bei einem vereinsinternen Spiel sind das zwei,
        # damit beide Kader den Termin bekommen und zusagen können.
        intern = heim_team is not None and gast_team is not None
        for team, heim_auswaerts in ((heim_team, 'heim'), (gast_team, 'auswaerts')):
            if team is None:
                continue
            gegner = s.gast if heim_auswaerts == 'heim' else s.heim
            hinweis = 'Vereinsinternes Spiel – Termin für beide Mannschaften' if intern else None
            termin = db.termine.get_by_extern_ref(s.spielkennung, team.id)
            if termin is None:
                bericht.befunde.append(ZeilenBefund(
                    spiel=s, einordnung=NEU, mannschaft_id=team.id,
                    mannschaft_name=team.name, heim_auswaerts=heim_auswaerts,
                    hinweis=hinweis))
                continue

            neu_werte = {'beginn': s.beginn, 'ort': s.ort_text,
                         'heim_auswaerts': heim_auswaerts, 'gegner': gegner}
            abweichungen = [
                {'feld': f, 'app': getattr(termin, f), 'dfbnet': neu_werte[f]}
                for f in VERGLEICHSFELDER if getattr(termin, f) != neu_werte[f]
            ]
            bericht.befunde.append(ZeilenBefund(
                spiel=s, einordnung=AENDERUNG if abweichungen else UNVERAENDERT,
                mannschaft_id=team.id, mannschaft_name=team.name,
                heim_auswaerts=heim_auswaerts, termin_id=termin.id,
                abweichungen=abweichungen, hinweis=hinweis))

    bericht.unbekannte_teams = [
        {'name': name, 'mannschaftsart': art, 'anzahl': anzahl}
        for (name, art), anzahl in sorted(unbekannt.items(), key=lambda x: -x[1])
    ]
    bericht.neue_spielstaetten = sorted(
        neue_staetten.values(), key=lambda e: (-e['anzahl'], e['name']))
    return bericht
