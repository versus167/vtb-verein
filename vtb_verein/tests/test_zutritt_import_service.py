"""
Tests für den Import eines Fremd-Zutrittslogs (Schloss ohne TTLock-Anschluss).

Geprüft (ohne DB/Netz, Fakes für die drei Repos):
- Parser: Kopfzeile mit Leerzeichen, Trenner-Erkennung, cp1252, Ortszeit → UTC-ISO.
- Auflösung Konto → Chip über externe_kennung > Bezeichnung > Kartennummer.
- Vorschau schreibt nichts; der Lauf legt das Schloss an und ist idempotent.
- Nachzieh-Lauf ordnet früher importierte Zeilen einem neu gepflegten Chip zu.
"""
import pytest

from app.models.schliessanlage import (
    SchluesselChip, TuerSchloss, QUELLE_EXTERN, extern_record_type,
)
from app.services.zutritt_import_service import (
    ImportFehler, parse, run_import, zeitpunkt_zu_iso,
)

CSV = (
    "Unlock Account,Unlock Type, Lock Name,Unlock Time\n"
    "test1,Karte entsperren,Tor Einfahrt,2026-08-07 19:56:16\n"
    "Chip8,Karte entsperren,Tor Einfahrt,2026-08-10 17:47:05\n"
    "Volker1,Karte entsperren,Tor Einfahrt,2026-08-10 17:53:12\n"
).encode()


# --- Fakes ------------------------------------------------------------------
class FakeChipRepo:
    def __init__(self, chips=()):
        self.chips = list(chips)

    def find_active_by_externes_konto(self, konto):
        if not (konto or '').strip():
            return None
        norm = konto.strip().lower()
        for feld in ('externe_kennung', 'bezeichnung', 'kartennummer'):
            for c in self.chips:
                if (getattr(c, feld) or '').strip().lower() == norm:
                    return c
        return None


class FakeSchlossRepo:
    def __init__(self, schloesser=()):
        self.schloesser = list(schloesser)
        self.events = []
        self._next_id = 10

    def find_extern_by_name(self, name):
        return next((s for s in self.schloesser
                     if s.quelle == QUELLE_EXTERN
                     and (s.name or '').strip().lower() == name.strip().lower()), None)

    def create_extern(self, *, name, standort=None, notiz=None, by='SYSTEM'):
        s = TuerSchloss(id=self._next_id, name=name, quelle=QUELLE_EXTERN, notiz=notiz)
        self._next_id += 1
        self.schloesser.append(s)
        return s

    def update_letztes_event(self, schloss_id, *, letztes_event_at, letztes_event_type,
                             by='SYSTEM'):
        self.events.append((schloss_id, letztes_event_at, letztes_event_type))


class FakeLogRepo:
    def __init__(self):
        self.rows = []
        self.nachgezogen = []

    def extern_keys_for_schloss(self, schloss_id):
        return {(r.lock_date, r.extern_konto or '') for r in self.rows
                if r.schloss_id == schloss_id}

    def insert_extern_if_new(self, log):
        if (log.lock_date, log.extern_konto or '') in self.extern_keys_for_schloss(log.schloss_id):
            return False
        self.rows.append(log)
        return True

    def resolve_extern_konto(self, konto, *, chip_id, mitglied_id, user_id=None):
        treffer = [r for r in self.rows
                   if r.chip_id is None
                   and (r.extern_konto or '').strip().lower() == konto.strip().lower()]
        for r in treffer:
            r.chip_id, r.mitglied_id, r.user_id = chip_id, mitglied_id, user_id
        self.nachgezogen.append((konto, len(treffer)))
        return len(treffer)


class FakeDB:
    def __init__(self, chips=(), schloesser=()):
        self.schluessel_chips = FakeChipRepo(chips)
        self.tuer_schloesser = FakeSchlossRepo(schloesser)
        self.tuer_zutritt_logs = FakeLogRepo()


# --- Parser -----------------------------------------------------------------
def test_parse_liest_kopfzeile_mit_leerzeichen():
    zeilen, fehler = parse(CSV)
    assert fehler == []
    assert [z.konto for z in zeilen] == ['test1', 'Chip8', 'Volker1']
    assert all(z.schloss == 'Tor Einfahrt' for z in zeilen)


def test_parse_rechnet_ortszeit_in_utc_um():
    """Die Anlage schreibt Ortszeit ohne Zeitzone – gespeichert wird UTC wie überall."""
    zeilen, _ = parse(CSV)
    assert zeilen[0].zeitpunkt == '2026-08-07T17:56:16+00:00'      # Sommerzeit: -2 h
    assert zeitpunkt_zu_iso('2026-01-07 19:56:16') == '2026-01-07T18:56:16+00:00'   # Winter: -1 h


def test_parse_erkennt_semikolon_und_cp1252():
    daten = ("Unlock Account;Unlock Type;Lock Name;Unlock Time\n"
             "Tür-Chip;Karte entsperren;Tor;2026-08-10 17:47:05\n").encode('cp1252')
    zeilen, fehler = parse(daten)
    assert fehler == []
    assert zeilen[0].konto == 'Tür-Chip'


def test_parse_meldet_unlesbare_zeilen_statt_zu_raten():
    daten = (b"Unlock Account,Unlock Type, Lock Name,Unlock Time\n"
             b"a,Karte entsperren,Tor,irgendwann\n"
             b"b,Karte entsperren,Tor,2026-08-10 17:47:05\n")
    zeilen, fehler = parse(daten)
    assert len(zeilen) == 1 and fehler == ['Zeile 2: Zeitpunkt unlesbar']


def test_parse_wirft_bei_fremder_kopfzeile():
    with pytest.raises(ImportFehler, match="Kopfzeile"):
        parse(b"Vorname,Nachname\nMax,Muster\n")


def test_unlock_type_wird_auf_recordtype_abgebildet():
    assert extern_record_type('Karte entsperren') == 7
    assert extern_record_type('Fingerabdruck entsperren') == 8
    assert extern_record_type('Irgendwas Neues') is None


# --- Vorschau / Lauf ---------------------------------------------------------
def test_vorschau_schreibt_nichts():
    db = FakeDB()
    bericht = run_import(db, CSV, commit=False)
    assert bericht.zeilen == 3 and bericht.neu == 3
    assert db.tuer_zutritt_logs.rows == []
    assert db.tuer_schloesser.schloesser == []
    assert bericht.schloesser[0].neu_angelegt is True      # „würde angelegt"


def test_lauf_legt_externes_schloss_an_und_importiert():
    db = FakeDB()
    bericht = run_import(db, CSV, commit=True, actor='tester')
    schloss = db.tuer_schloesser.schloesser[0]
    assert schloss.quelle == QUELLE_EXTERN and schloss.ttlock_lock_id is None
    assert len(db.tuer_zutritt_logs.rows) == 3
    assert bericht.neu == 3 and bericht.doppelt == 0
    # Status-Snapshot zeigt auf den jüngsten Vorgang
    assert db.tuer_schloesser.events == [(10, '2026-08-10T15:53:12+00:00', 7)]


def test_erneuter_lauf_ist_idempotent():
    db = FakeDB()
    run_import(db, CSV, commit=True)
    zweiter = run_import(db, CSV, commit=True)
    assert zweiter.neu == 0 and zweiter.doppelt == 3
    assert len(db.tuer_zutritt_logs.rows) == 3
    # Kein zweiter Status-Schreib – sonst History-Leerrauschen ohne neue Daten
    assert len(db.tuer_schloesser.events) == 1


def test_konto_wird_ueber_kennung_bezeichnung_und_nummer_aufgeloest():
    db = FakeDB(chips=[
        SchluesselChip(id=1, kartennummer='111', bezeichnung='Chip8'),
        SchluesselChip(id=2, kartennummer='222', bezeichnung='Karte rot',
                       externe_kennung='Volker1', mitglied_id=7,
                       mitglied_vorname='Max', mitglied_nachname='Muster'),
    ])
    bericht = run_import(db, CSV, commit=True)
    zuordnung = {r.extern_konto: (r.chip_id, r.mitglied_id)
                 for r in db.tuer_zutritt_logs.rows}
    assert zuordnung == {'test1': (None, None), 'Chip8': (1, None), 'Volker1': (2, 7)}
    assert bericht.ohne_zuordnung == 1
    konten = {k.konto: k for k in bericht.schloesser[0].konten}
    assert konten['Volker1'].inhaber_name == 'Max Muster'
    assert konten['test1'].zugeordnet is False


def test_bericht_nennt_auch_inhaber_ohne_mitgliedsdatensatz():
    """Chips laufen auch auf Benutzerkonten (Platzwart & Co.) – der Bericht darf sie
    dann nicht als „niemandem zugeordnet" ausweisen."""
    db = FakeDB(chips=[
        SchluesselChip(id=1, kartennummer='111', bezeichnung='Chip8',
                       user_id=9, user_username='platzwart'),
    ])
    bericht = run_import(db, CSV, commit=True)
    konten = {k.konto: k for k in bericht.schloesser[0].konten}
    assert konten['Chip8'].inhaber_name == 'platzwart'
    assert konten['Chip8'].mitglied_id is None


def test_gepflegte_kennung_schlaegt_gleichnamige_bezeichnung():
    """Wer die Kennung explizit pflegt, gewinnt gegen einen Namensgleichklang."""
    db = FakeDB(chips=[
        SchluesselChip(id=1, kartennummer='111', bezeichnung='Volker1'),
        SchluesselChip(id=2, kartennummer='222', externe_kennung='Volker1'),
    ])
    run_import(db, CSV, commit=True)
    treffer = next(r for r in db.tuer_zutritt_logs.rows if r.extern_konto == 'Volker1')
    assert treffer.chip_id == 2


def test_spaeter_gepflegte_kennung_zieht_alte_zeilen_nach():
    db = FakeDB()
    run_import(db, CSV, commit=True)
    assert all(r.chip_id is None for r in db.tuer_zutritt_logs.rows)

    db.schluessel_chips.chips.append(
        SchluesselChip(id=5, kartennummer='999', externe_kennung='test1', mitglied_id=3))
    bericht = run_import(db, CSV, commit=True)

    assert bericht.nachgezogen == 1          # die test1-Zeile aus dem ersten Lauf
    assert all(r.chip_id == 5 for r in db.tuer_zutritt_logs.rows
               if r.extern_konto == 'test1')


def test_mehrere_schloesser_in_einer_datei():
    daten = (b"Unlock Account,Unlock Type, Lock Name,Unlock Time\n"
             b"a,Karte entsperren,Tor Einfahrt,2026-08-10 17:47:05\n"
             b"b,Karte entsperren,Tor Hinten,2026-08-10 17:48:05\n")
    db = FakeDB()
    bericht = run_import(db, daten, commit=True)
    assert [s.name for s in bericht.schloesser] == ['Tor Einfahrt', 'Tor Hinten']
    assert len(db.tuer_schloesser.schloesser) == 2
