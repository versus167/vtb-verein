"""
Integrationstest der Zutritts-Auswertung (#161) gegen echtes PostgreSQL.

Hier zählt die SQL-Semantik, die Fakes nicht abbilden können: die Umrechnung des
UTC-Zeitstempels auf Ortszeit (davon hängen Stunde, Wochentag und „früheste Öffnung"
ab), die Positivliste der Öffnungs-Codes, die Auflösung „wer war es" über Mitglied →
Chip → Rohfeld sowie Zeitraum- und Abteilungs-Scope-Filter.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --name vtb-pg-auswertung -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=auswertung -p 55432:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/auswertung \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_zutritt_auswertung_integration.py
"""
import os

import pytest

from app.models.schliessanlage import SchluesselChip, TuerZutrittLog, QUELLE_EXTERN
from app.services import zutritt_auswertung_service as service

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-auswertung-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM tuer_zutritt_log")
        cur.execute("DELETE FROM tuer_schloss_status_log")
        cur.execute("DELETE FROM tuer_schloss_history")
        cur.execute("DELETE FROM tuer_schloss")
        cur.execute("DELETE FROM schluessel_chip_history")
        cur.execute("DELETE FROM schluessel_chip")
        # Eigene Testperson wieder wegräumen: andere Integrationstests zählen
        # Mitglieder und stolpern sonst über unsere Zeile.
        cur.execute("DELETE FROM mitglied WHERE vorname = 'AUS'")
    db.conn.commit()
    yield


def _schloss(db, name, **kw):
    return db.tuer_schloesser.create_extern(name=name, by="tester", **kw)


def _log(db, schloss, zeit_utc, *, record_type=7, erfolg=True, chip_id=None,
         mitglied_id=None, konto=None, methode=None):
    """Eine Log-Zeile mit UTC-Zeitstempel (so, wie Sync und Import sie schreiben)."""
    db.tuer_zutritt_logs.insert_extern_if_new(TuerZutrittLog(
        schloss_id=schloss.id, quelle=QUELLE_EXTERN, extern_konto=konto,
        record_type=record_type, methode=methode, erfolg=erfolg,
        chip_id=chip_id, mitglied_id=mitglied_id, lock_date=zeit_utc))


def test_ortszeit_bestimmt_stunde_wochentag_und_frueheste_oeffnung(db):
    """22:30 UTC im Sommer ist 00:30 Ortszeit am Folgetag – Stunde, Wochentag und
    „früheste Öffnung" müssen der Uhr an der Tür folgen, nicht der Datenbank."""
    tor = _schloss(db, "Tor")
    _log(db, tor, "2026-07-14T22:30:00+00:00", konto="a")   # Di 22:30 UTC → Mi 00:30
    _log(db, tor, "2026-07-15T04:12:00+00:00", konto="b")   # Mi 06:12 Ortszeit

    b = service.bericht(db, tage=0)
    stunden = {s['stunde']: s['anzahl'] for s in b['stunden'] if s['anzahl']}
    assert stunden == {0: 1, 6: 1}
    wochentage = {t['label']: t['anzahl'] for t in b['wochentage'] if t['anzahl']}
    assert wochentage == {'Mi': 2}
    frueh = next(a for a in b['auszeichnungen'] if a['schluessel'] == 'frueheste')
    assert frueh['wert'] == '00:30 Uhr' and frueh['detail'].startswith('15.07.2026')
    spaet = next(a for a in b['auszeichnungen'] if a['schluessel'] == 'spaeteste')
    assert spaet['wert'] == '06:12 Uhr'


def test_nur_oeffnungen_zaehlen(db):
    """Verriegeln, Türmagnet, Alarm und Fehlversuche gehören nicht in die Rangliste."""
    tor = _schloss(db, "Tor")
    _log(db, tor, "2026-07-01T08:00:00+00:00", record_type=7)            # IC-Karte
    _log(db, tor, "2026-07-01T09:00:00+00:00", record_type=8)            # Fingerprint
    _log(db, tor, "2026-07-01T10:00:00+00:00", record_type=35)           # Verriegelt
    _log(db, tor, "2026-07-01T11:00:00+00:00", record_type=31)           # Türmagnet auf
    _log(db, tor, "2026-07-01T12:00:00+00:00", record_type=44)           # Sabotage-Alarm
    _log(db, tor, "2026-07-01T13:00:00+00:00", record_type=4, erfolg=False)
    # Fremdanlage ohne erkannten Typ: zählt als Öffnung, Originaltext bleibt Label
    _log(db, tor, "2026-07-01T14:00:00+00:00", record_type=None, methode="Tor auf")

    b = service.bericht(db, tage=0)
    assert b['kennzahlen']['oeffnungen'] == 3
    assert b['kennzahlen']['ereignisse'] == 7
    assert b['kennzahlen']['fehlversuche'] == 1
    assert b['kennzahlen']['alarme'] == 1
    assert {m['label'] for m in b['methoden']} == {'IC-Karte', 'Fingerprint', 'Tor auf'}


def test_wer_wird_ueber_mitglied_chip_und_rohfeld_aufgeloest(db):
    tor = _schloss(db, "Tor")
    with db.conn.cursor() as cur:
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,created_by,updated_by) "
                    "VALUES ('AUS','Tester','lastschrift','t','t') RETURNING id")
        mid = cur.fetchone()['id']
    db.conn.commit()
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4711", bezeichnung="karte1", mitglied_id=mid), "t")
    pool = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4712", bezeichnung="TestChip blau"), "t")

    _log(db, tor, "2026-07-01T08:00:00+00:00", chip_id=chip.id, mitglied_id=mid)
    _log(db, tor, "2026-07-02T08:00:00+00:00", chip_id=pool.id)          # Chip ohne Person
    _log(db, tor, "2026-07-03T08:00:00+00:00", konto="Gastkonto")        # nur Rohfeld
    _log(db, tor, "2026-07-04T08:00:00+00:00")                           # niemand zuordenbar

    b = service.bericht(db, tage=0)
    assert [(p['wer'], p['anzahl']) for p in b['personen']] == [
        ('AUS Tester', 1), ('Gastkonto', 1), ('TestChip blau', 1)]
    # Die nicht zuordenbare Zeile zählt bei den Öffnungen mit, aber bei niemandem
    assert b['kennzahlen']['oeffnungen'] == 4
    assert b['kennzahlen']['akteure'] == 3


def test_rangliste_und_vielfalt_ueber_mehrere_schloesser(db):
    kueche, tor = _schloss(db, "Küche"), _schloss(db, "Tor")
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="1", bezeichnung="karte1"), "t")
    for tag in range(1, 6):
        _log(db, kueche, f"2026-07-0{tag}T08:00:00+00:00", chip_id=chip.id)
    _log(db, tor, "2026-07-01T09:00:00+00:00", chip_id=chip.id)

    b = service.bericht(db, tage=0)
    assert [(s['name'], s['anzahl']) for s in b['schloesser']] == [('Küche', 5), ('Tor', 1)]
    assert b['schloesser'][0]['anteil'] == round(5 / 6, 4)
    vielfalt = next(a for a in b['auszeichnungen'] if a['schluessel'] == 'vielfalt')
    assert vielfalt['wer'] == 'karte1' and vielfalt['wert'] == '2 Türen'
    serie = next(a for a in b['auszeichnungen'] if a['schluessel'] == 'serie')
    assert serie['wert'] == '5 Tage'


def test_abteilungs_scope_beschraenkt_die_auswertung(db):
    kueche, tor = _schloss(db, "Küche"), _schloss(db, "Tor")
    _log(db, kueche, "2026-07-01T08:00:00+00:00", konto="a")
    _log(db, tor, "2026-07-01T09:00:00+00:00", konto="b")

    b = service.bericht(db, tage=0, schloss_ids={tor.id})
    assert b['kennzahlen']['oeffnungen'] == 1
    assert [s['name'] for s in b['schloesser']] == ['Tor']
    # Leerer Scope (Recht ohne passende Abteilung) darf nicht alles zeigen
    assert service.bericht(db, tage=0, schloss_ids=set())['kennzahlen']['oeffnungen'] == 0


def test_zeitraum_schneidet_alte_zeilen_ab(db):
    from datetime import datetime, timedelta, timezone
    tor = _schloss(db, "Tor")
    jetzt = datetime.now(timezone.utc)
    _log(db, tor, (jetzt - timedelta(days=5)).isoformat(), konto="neu")
    _log(db, tor, (jetzt - timedelta(days=200)).isoformat(), konto="alt")

    assert service.bericht(db, tage=30)['kennzahlen']['oeffnungen'] == 1
    assert service.bericht(db, tage=365)['kennzahlen']['oeffnungen'] == 2
    assert service.bericht(db, tage=0)['kennzahlen']['oeffnungen'] == 2
