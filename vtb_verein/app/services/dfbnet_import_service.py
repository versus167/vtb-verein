"""DFBnet-Vereinsspielplan: Zuordnung, Vorschau und Übernahme (#95).

`dry_run` schreibt nichts und liefert je Zeile, was ein Lauf täte; `uebernehmen`
führt genau das aus. Beide teilen sich die Zuordnung, damit „Vorschau = Aktion"
gilt und nicht zwei Regelwerke auseinanderlaufen.

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

from app.db.termin_abweichung_repository import (
    FELD_ENTFALLEN,
    STATUS_UEBERNOMMEN,
    VALID_ENTSCHEIDUNGEN,
)

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
# Der erste „Typ" im Export ist der Platzbelag (Rasenplatz/Kunstrasenplatz), der
# zweite der Spieltyp – daher hier ohne, dort mit „#2" (s. _eindeutige_koepfe).
SPALTE_PLATZTYP = 'Typ'
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

# Was ein Lauf mit einer festgestellten Abweichung täte (je Feld):
WIRKUNG_UEBERNEHMEN = 'uebernehmen'      # nur die Quelle hat sich geändert
WIRKUNG_BLEIBT = 'bleibt'                # nur die App – bewusste Abweichung des Teams
WIRKUNG_ENTSCHEIDUNG = 'entscheidung'    # beide -> der Betreuer entscheidet


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
    platztyp: str = ''              # Belag laut Export, s. untergrund()
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
    abweichungen: list = field(default_factory=list)   # [{feld, app, dfbnet, wirkung}]
    hinweis: Optional[str] = None

    @property
    def braucht_entscheidung(self) -> bool:
        return any(a['wirkung'] == WIRKUNG_ENTSCHEIDUNG for a in self.abweichungen)


@dataclass
class ImportBericht:
    zeilen: int = 0
    befunde: list = field(default_factory=list)
    # [{name, mannschaftsart, anzahl}] – im Export vorhanden, in der App nicht zugeordnet
    unbekannte_teams: list = field(default_factory=list)
    # [{name, dfbnet_nr, strasse, plz, ort, untergrund, parallel_moeglich, anzahl}]
    neue_spielstaetten: list = field(default_factory=list)
    # Bekannte Plätze, deren Stammdaten vom Export abweichen:
    # [{id, name, dfbnet_nr, version, felder: [{feld, app, dfbnet}]}]
    abweichende_spielstaetten: list = field(default_factory=list)
    fehler: list = field(default_factory=list)         # Zeilen, die nicht lesbar waren

    @property
    def zusammenfassung(self) -> dict:
        z = Counter(b.einordnung for b in self.befunde)
        return {k: z.get(k, 0) for k in
                (NEU, AENDERUNG, UNVERAENDERT, PLATZBELEGUNG, FREMD)}

    @property
    def zeitraum(self) -> tuple[Optional[str], Optional[str]]:
        """Erster und letzter Spieltag der Datei als ISO-Datum, sonst (None, None).

        Das ist nicht bloß Anzeige-Beiwerk, sondern **das** Fenster, in dem
        :func:`_entfallene_melden` überhaupt nach fehlenden Spielen sucht — der
        DFBnet-Export liefert höchstens ein Quartal, „fehlt" kann also immer nur
        innerhalb dieser Grenzen etwas heißen. Beide lesen deshalb hier, damit die
        angezeigte Spanne genau die geprüfte ist.

        Gezählt werden alle Zeilen, auch Fremdspiele und Platzbelegungen: Es geht
        um den Zeitraum der *Datei*, nicht um den der eigenen Spiele.
        """
        tage = sorted(b.spiel.beginn[:10] for b in self.befunde if b.spiel.beginn)
        return (tage[0], tage[-1]) if tage else (None, None)


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


# Der Export hängt an jeden Belag „-platz"; in der App liest sich der kurze
# Begriff besser. Was nicht in der Liste steht (Hallenböden, Sonderformen), wird
# unverändert übernommen statt verschluckt.
_UNTERGRUND_KURZ = {
    'rasenplatz': 'Rasen',
    'kunstrasenplatz': 'Kunstrasen',
    'hartplatz': 'Hartplatz',
}


def untergrund(platztyp: str) -> Optional[str]:
    """Belag aus der Platztyp-Spalte des Exports, auf Anzeigeform gebracht."""
    wert = (platztyp or '').strip()
    if not wert:
        return None
    return _UNTERGRUND_KURZ.get(wert.lower(), wert)


# Stammdatenfelder, die der Export mitbringt. Der NAME ist bewusst nicht dabei:
# Wie der Verein seinen Platz nennt („Käfig"), ist seine Sache — das DFBnet
# schreibt dort seine eigene Bezeichnung.
_STAETTE_FELDER = ('strasse', 'plz', 'ort', 'untergrund', 'parallel_moeglich')


def _staette_soll(spiel) -> dict:
    """Stammdaten der Spielstätte, wie sie im Export stehen."""
    return {'strasse': spiel.strasse or None, 'plz': spiel.plz or None,
            'ort': spiel.ort or None, 'untergrund': untergrund(spiel.platztyp),
            'parallel_moeglich': spiel.parallel_moeglich}


def _staette_abweichungen(staette, spiel) -> list[dict]:
    """Felder, in denen der Platz vom Export abweicht.

    Leere Export-Werte zählen nicht: Fehlt im Spielplan die Hausnummer, ist das
    kein Grund, eine gepflegte Adresse zu löschen. Umgekehrt ist ein leeres Feld
    in der App der häufigste Fall — Bestandsplätze kennen den Belag noch nicht.
    """
    ist = {f: getattr(staette, f) for f in _STAETTE_FELDER}
    soll = _staette_soll(spiel)
    return [{'feld': f, 'app': ist[f], 'dfbnet': soll[f]}
            for f in _STAETTE_FELDER
            if soll[f] not in (None, '') and ist[f] != soll[f]]


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
            platztyp=feld(zeile, SPALTE_PLATZTYP),
            parallel_moeglich=_zahl(feld(zeile, SPALTE_PARALLEL)),
        ))
    return spiele, fehler


# ------------------------------------------------------------------- Dry-Run

def _beschreibung(s: Spiel) -> str:
    teile = [s.spieltyp, s.liga or s.staffel]
    if s.spieltag:
        teile.append(f'Sptg. {s.spieltag}')
    return ' · '.join(t for t in teile if t)


def _wirkung(stand: Optional[dict], feld: str, app_wert, dfbnet_wert) -> str:
    """Wer hat das Feld verändert – und was folgt daraus? (nur bei app != dfbnet)

    Vergleichsanker ist der zuletzt importierte Stand, nicht der App-Wert: Erst er
    trennt „das DFBnet hat verlegt" von „das Team hat bewusst etwas anderes
    eingetragen". Ohne Stand (Termin von Hand angelegt oder älter als Schema v83)
    lässt sich das nicht entscheiden — dann entscheidet ein Mensch.
    """
    if not stand:
        return WIRKUNG_ENTSCHEIDUNG
    alt = stand.get(feld)
    if alt == dfbnet_wert:
        return WIRKUNG_BLEIBT
    if alt == app_wert:
        return WIRKUNG_UEBERNEHMEN
    return WIRKUNG_ENTSCHEIDUNG


def dry_run(db, daten: bytes) -> ImportBericht:
    """Ordnet jede Zeile zu und meldet, was ein Lauf täte. Schreibt nichts."""
    spiele, fehler = parse_spielplan(daten)
    bericht = ImportBericht(zeilen=len(spiele), fehler=fehler)

    unbekannt: Counter = Counter()
    neue_staetten: dict = {}
    andere_staetten: dict = {}

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
                'untergrund': untergrund(s.platztyp),
                'parallel_moeglich': s.parallel_moeglich, 'anzahl': 0,
            })
            eintrag['anzahl'] += 1
        elif staette is not None and staette.platzhalter is None:
            # Bekannter Platz: Stammdaten gegen den Export halten. Geschrieben
            # wird nichts — der Bericht bietet die Übernahme je Platz an.
            abweichungen = _staette_abweichungen(staette, s)
            if abweichungen:
                andere_staetten[staette.id] = {
                    'id': staette.id, 'name': staette.name,
                    'dfbnet_nr': staette.dfbnet_nr, 'version': staette.version,
                    'felder': abweichungen,
                }

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
                {'feld': f, 'app': getattr(termin, f), 'dfbnet': neu_werte[f],
                 'wirkung': _wirkung(termin.extern_stand, f,
                                     getattr(termin, f), neu_werte[f])}
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
    bericht.abweichende_spielstaetten = sorted(
        andere_staetten.values(), key=lambda e: e['name'])
    return bericht


# ----------------------------------------------------------------- Übernahme

@dataclass
class UebernahmeErgebnis:
    angelegt: int = 0
    aktualisiert: int = 0
    stand_nachgetragen: int = 0
    uebersprungen: int = 0
    # Offene Fragen an den Betreuer (termin_abweichung), neu oder aufgefrischt
    abweichungen: int = 0
    entfallen: int = 0                                 # im Export nicht mehr enthalten
    konflikte: list = field(default_factory=list)      # [{termin_id, mannschaft, felder}]
    ohne_spielstaette: list = field(default_factory=list)   # [{spielkennung, name, nr}]
    spielstaetten_aktualisiert: int = 0
    # Mannschaften, deren Betreuer/ÜL eine Meldung über neue Fragen bekommen haben
    entscheidungen_gemeldet: int = 0
    bericht: Optional[ImportBericht] = None


def _neue_werte(befund: ZeilenBefund) -> dict:
    s = befund.spiel
    return {
        'beginn': s.beginn,
        'ort': s.ort_text,
        'heim_auswaerts': befund.heim_auswaerts,
        'gegner': s.gast if befund.heim_auswaerts == 'heim' else s.heim,
    }


def _plan(termin, werte: dict) -> tuple[dict, dict, dict]:
    """Feldweiser Abgleich: (ändern, nur Stand nachtragen, entscheiden lassen).

    Feldweise und nicht je Termin, damit eine strittige Platzverlegung nicht die
    unstrittige Zeitverlegung blockiert — und umgekehrt.
    """
    stand = termin.extern_stand
    aendern, nachtragen, entscheiden = {}, {}, {}
    for f in VERGLEICHSFELDER:
        neu, app = werte[f], getattr(termin, f)
        if not stand:
            # Ohne Basis wird nicht geraten: Was übereinstimmt, wird als Stand
            # festgehalten, alles andere legt der Betreuer fest.
            (nachtragen if app == neu else entscheiden)[f] = neu
            continue
        if stand.get(f) == neu:
            continue                       # Quelle unverändert -> in Ruhe lassen
        if app == neu:
            nachtragen[f] = neu            # App ist schon dort, nur der Stand hinkt
        elif app == stand.get(f):
            aendern[f] = neu               # nur die Quelle hat sich geändert
        else:
            entscheiden[f] = neu           # beide -> Abweichung
    return aendern, nachtragen, entscheiden


def _stand_mit_platz(stand: dict, staette) -> dict:
    """Schnappschuss um die Spielstätte hinter dem Ort-Text ergänzen.

    `ort` ist reiner Text; wer den Termin später auf den DFBnet-Stand ziehen will,
    bräuchte sonst raten, welcher Platz gemeint ist — und ein Ort ohne passende
    `spielstaette_id` macht die Platzbelegung falsch. Kein Vergleichsfeld, der
    Abgleich läuft weiter nur über VERGLEICHSFELDER; ältere Stände ohne den
    Schlüssel bleiben gültig.
    """
    if staette is None:
        return stand
    return {**stand, 'spielstaette_id': staette.id}


def _staetten_nachziehen(db, bericht: ImportBericht, *, actor: str) -> int:
    """Stammdaten bekannter Plätze auf den Export ziehen.

    Anders als beim Termin gibt es hier nichts zu entscheiden: Anschrift, Belag
    und Kapazität eines Platzes stehen im DFBnet, das ist die offizielle Quelle.
    Der NAME bleibt außen vor — wie der Verein seinen Platz nennt („Käfig"), ist
    seine Sache, und für die Zuordnung zählt ohnehin nur die DFBnet-Nummer.
    """
    geaendert = 0
    for eintrag in bericht.abweichende_spielstaetten:
        staette = db.spielstaetten.get(eintrag['id'])
        if staette is None:
            continue
        for f in eintrag['felder']:
            setattr(staette, f['feld'], f['dfbnet'])
        if db.spielstaetten.update(staette.id, staette, actor, staette.version):
            geaendert += 1
    return geaendert


def _melde_abweichungen(db, termin, entscheiden: dict, staette, *,
                        actor: str, neue: Optional[list] = None) -> int:
    """Offene Fragen festhalten – eine Zeile je Feld, idempotent je Lauf.

    Frisch aufgeworfene Fragen landen in `neue`; nur die lösen später eine
    Benachrichtigung aus (ein aufgefrischter Eintrag ist keine Neuigkeit).
    """
    for feld, wert in entscheiden.items():
        _, ist_neu = db.termin_abweichungen.melden(
            termin.id, feld, wert_app=getattr(termin, feld), wert_extern=wert,
            spielstaette_id=staette.id if (feld == 'ort' and staette) else None,
            erkannt_von=actor)
        if ist_neu and neue is not None:
            neue.append((termin.mannschaft_id, termin.id, feld))
    return len(entscheiden)


def _entfallene_melden(db, bericht: ImportBericht, ergebnis: UebernahmeErgebnis, *,
                       actor: str, neue: Optional[list] = None) -> None:
    """Spiele melden, die im Export nicht mehr auftauchen — ohne sie abzusagen.

    Der Export ist ein Zeitfenster-Auszug, kein Vollbestand: „fehlt" heißt nicht
    „abgesagt". Verglichen wird deshalb nur innerhalb des Datumsfensters der Datei
    und nur für Mannschaften, die darin überhaupt vorkommen — sonst meldete ein
    Teil-Export den halben Kalender als entfallen.
    """
    eigene = [b for b in bericht.befunde if b.mannschaft_id]
    if not eigene:
        return
    von, bis = bericht.zeitraum
    if von is None:
        return
    vorhanden = {(b.mannschaft_id, b.spiel.spielkennung) for b in eigene}

    # Wieder aufgetauchte Spiele: die alte Meldung ist damit erledigt.
    db.termin_abweichungen.entfallen_zuruecknehmen(
        [b.termin_id for b in eigene if b.termin_id], actor)

    teams = sorted({b.mannschaft_id for b in eigene})
    for termin in db.termine.list_importierte(teams, von, bis):
        if (termin.mannschaft_id, termin.extern_ref) in vorhanden:
            continue
        if db.termin_abweichungen.hat_unerledigte(termin.id, FELD_ENTFALLEN):
            continue    # schon gemeldet oder längst entschieden
        _, ist_neu = db.termin_abweichungen.melden(
            termin.id, FELD_ENTFALLEN, wert_app=termin.beginn, wert_extern=None,
            erkannt_von=actor)
        if ist_neu and neue is not None:
            neue.append((termin.mannschaft_id, termin.id, FELD_ENTFALLEN))
        ergebnis.entfallen += 1
        ergebnis.abweichungen += 1


def uebernehmen(db, daten: bytes, *, actor: str, benachrichtigen: bool = False,
                notify=None, notify_entscheidung=None) -> UebernahmeErgebnis:
    """Spielplan übernehmen — nach dem Drei-Wege-Abgleich, Feld für Feld.

    Verglichen wird nicht App gegen Datei, sondern jeweils gegen den zuletzt
    importierten Stand (`extern_stand`). Daraus die drei Fälle:

    * DFBnet geändert, App unberührt  -> übernehmen (und Kader benachrichtigen)
    * DFBnet geändert, App auch       -> NICHT anfassen, als Abweichung festhalten
    * nur die App geändert            -> nichts tun; das Team weicht bewusst ab

    Fehlt der Schnappschuss (Termin von Hand angelegt oder aus der Zeit vor v83),
    wird nur nachgetragen, was ohnehin übereinstimmt; der Rest wird zur Abweichung
    — ohne Basis lässt sich nicht sagen, wer etwas geändert hat, und Raten wäre
    hier teurer als Nachfragen.

    ``notify`` ist injizierbar, damit der Aufruf ohne Mailversand testbar bleibt.
    ``notify_entscheidung`` bekommt am Ende die frisch aufgeworfenen Fragen je
    Mannschaft — gerade der Fall „beide Seiten geändert" ändert am Termin ja
    nichts und bliebe sonst still, obwohl er als einziger eine Handlung braucht.
    """
    bericht = dry_run(db, daten)
    ergebnis = UebernahmeErgebnis(bericht=bericht)
    neue_fragen: list = []
    ergebnis.spielstaetten_aktualisiert = _staetten_nachziehen(db, bericht, actor=actor)

    for befund in bericht.befunde:
        if befund.einordnung not in (NEU, AENDERUNG, UNVERAENDERT):
            continue      # Platzbelegung/fremd schreibt diese Etappe noch nicht

        spiel = befund.spiel
        staette = (db.spielstaetten.get_by_dfbnet_nr(spiel.spielstaetten_nr)
                   if spiel.spielstaetten_nr else None)
        if staette is None:
            # Die Spielstätte ist Pflichtfeld am Termin – und Stammdaten legt der
            # Import bewusst nicht selbst an (Muster wie beim SPG-Import). Der
            # Bericht listet die fehlenden Plätze mitsamt Adresse zum Übernehmen.
            ergebnis.ohne_spielstaette.append({
                'spielkennung': spiel.spielkennung,
                'name': spiel.spielstaette,
                'dfbnet_nr': spiel.spielstaetten_nr,
            })
            if befund.einordnung == NEU:
                ergebnis.uebersprungen += 1
                continue
            # Bestehende Termine haben ihre Spielstätte längst; eine Zeitverlegung
            # lässt sich auch ohne die fehlenden Stammdaten nachziehen. Nur der Ort
            # bleibt liegen, bis der Platz angelegt ist.

        werte = _neue_werte(befund)

        if befund.einordnung == NEU:
            termin = db.termine.create_aus_import(
                befund.mannschaft_id, beginn=werte['beginn'], ort=werte['ort'],
                spielstaette_id=staette.id, gegner=werte['gegner'],
                heim_auswaerts=werte['heim_auswaerts'],
                beschreibung=_beschreibung(spiel), extern_ref=spiel.spielkennung,
                extern_stand=_stand_mit_platz(werte, staette), created_by=actor)
            ergebnis.angelegt += 1
            if benachrichtigen and notify:
                notify(termin, 'neu', None)
            continue

        termin = db.termine.get(befund.termin_id)
        if termin is None:                      # zwischenzeitlich gelöscht
            ergebnis.uebersprungen += 1
            continue

        aendern, nachtragen, entscheiden = _plan(termin, werte)
        if staette is None:
            # Ohne Stammdatum bliebe der Termin mit neuem Ort, aber altem Platz
            # zurück – der Belegungsplan zeigte die Verlegung dann nicht.
            aendern.pop('ort', None)

        if entscheiden:
            ergebnis.abweichungen += _melde_abweichungen(
                db, termin, entscheiden, staette, actor=actor, neue=neue_fragen)
            ergebnis.konflikte.append({
                'termin_id': termin.id, 'mannschaft': befund.mannschaft_name,
                'felder': sorted(entscheiden),
                'grund': ('kein Vergleichsstand aus einem früheren Import'
                          if not termin.extern_stand
                          else 'Termin wurde in der App geändert')})
        # Erledigte Fragen schließen: Was jetzt automatisch läuft oder ohnehin
        # übereinstimmt, muss niemand mehr entscheiden.
        db.termin_abweichungen.als_hinfaellig(
            termin.id, [f for f in VERGLEICHSFELDER if f not in entscheiden], actor)

        if not aendern and not nachtragen:
            continue

        stand_neu = _stand_mit_platz(
            {**(termin.extern_stand or {}), **aendern, **nachtragen}, staette)
        if not aendern:
            # Rein buchhalterisch: kein version-Bump, keine History-Zeile.
            db.termine.set_extern_stand(termin.id, stand_neu)
            ergebnis.stand_nachgetragen += 1
            continue

        vorher = termin
        if db.termine.update_aus_import(
                termin.id, werte=aendern, extern_stand=stand_neu,
                spielstaette_id=staette.id if 'ort' in aendern else None,
                updated_by=actor, expected_version=termin.version):
            ergebnis.aktualisiert += 1
            if benachrichtigen and notify:
                notify(db.termine.get(termin.id), 'geaendert', vorher)
        else:
            ergebnis.uebersprungen += 1

    _entfallene_melden(db, bericht, ergebnis, actor=actor, neue=neue_fragen)

    # Gebündelt je Mannschaft, nicht je Termin: Ein Lauf wirft schnell ein Dutzend
    # Fragen auf, und zwölf Einzelmeldungen liest niemand mehr.
    if notify_entscheidung and neue_fragen:
        je_mannschaft: dict[int, list] = {}
        for mannschaft_id, termin_id, feld in neue_fragen:
            je_mannschaft.setdefault(mannschaft_id, []).append((termin_id, feld))
        for mannschaft_id, fragen in je_mannschaft.items():
            notify_entscheidung(mannschaft_id, fragen)
        ergebnis.entscheidungen_gemeldet = len(je_mannschaft)

    return ergebnis


# ------------------------------------------------------- Abweichung entscheiden

def entscheiden(db, abweichung, entscheidung: str, *, actor: str,
                notify=None) -> bool:
    """Eine offene Abweichung entscheiden. False = Versionskonflikt.

    Beide Wege schreiben den Schnappschuss auf den DFBnet-Wert fort — auch das
    Verwerfen. Genau das macht die Entscheidung dauerhaft: Beim nächsten Lauf
    stimmt die Quelle mit dem Stand überein, die Frage wird nicht erneut gestellt,
    und die abweichende Angabe des Teams bleibt stehen.

    Reihenfolge ist Absicht: erst der Termin, dann die Abweichung. Scheitert der
    zweite Schritt (jemand war schneller), wurde höchstens derselbe Wert zweimal
    geschrieben; andersherum wäre die Frage als beantwortet markiert, ohne dass
    etwas passiert ist.
    """
    if entscheidung not in VALID_ENTSCHEIDUNGEN:
        raise ValueError(f"Unbekannte Entscheidung: {entscheidung}")
    termin = db.termine.get(abweichung.termin_id)
    if termin is None:
        return False

    uebernehmen_ = entscheidung == STATUS_UEBERNOMMEN
    vorher = termin

    if abweichung.feld == FELD_ENTFALLEN:
        # „Übernehmen" heißt hier: absagen – gelöscht wird ein Termin mit
        # Zu-/Absagen des Kaders nie automatisch.
        if uebernehmen_ and termin.status != 'abgesagt':
            db.termine.set_status(termin.id, 'abgesagt', actor, termin.version)
    else:
        stand_neu = {**(termin.extern_stand or {}),
                     abweichung.feld: abweichung.wert_extern}
        if abweichung.feld == 'ort' and abweichung.spielstaette_id:
            stand_neu['spielstaette_id'] = abweichung.spielstaette_id
        if uebernehmen_:
            db.termine.update_aus_import(
                termin.id, werte={abweichung.feld: abweichung.wert_extern},
                extern_stand=stand_neu,
                spielstaette_id=(abweichung.spielstaette_id
                                 if abweichung.feld == 'ort' else None),
                updated_by=actor, expected_version=termin.version)
        else:
            db.termine.set_extern_stand(termin.id, stand_neu)

    if not db.termin_abweichungen.entscheiden(
            abweichung.id, entscheidung, actor, abweichung.version):
        return False
    if notify and uebernehmen_:
        notify(db.termine.get(termin.id), vorher)
    return True
