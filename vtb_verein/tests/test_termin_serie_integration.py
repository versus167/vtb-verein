"""Integrationstests der Terminserien (#95, Schema v70) gegen echtes PostgreSQL.

Prüft Schema (termin_serie + History-Trigger + CHECK + FK auf termine.serie_id),
die rollierende Materialisierung (Anker-Wochentag, Horizont-/Ende-Kappung,
Wasserzeichen: keine Duplikate, keine Wiedergänger gelöschter Instanzen) und die
Serien-Update-Semantik (nur zukünftige unveränderte geplante Instanzen; Kürzen/
Verlängern des Endes) sowie das Serien-Löschen (Zukunft weg, Vergangenheit bleibt).

Läuft nur mit ``VTB_TEST_DATABASE_URL`` auf einer (leeren) Wegwerf-DB – VereinsDB legt
das Schema beim Connect an (Beispiel siehe test_termin_zusage_integration.py).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

HEUTE = date.today()
YESTERDAY = (HEUTE - timedelta(days=1)).isoformat()
TOMORROW = (HEUTE + timedelta(days=1)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-serie-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE termin_serie, termin_serie_history, "
            "termin_zusage, termin_zusage_history, termine, termine_history, "
            "mannschaft, mannschaft_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM mitglied WHERE vorname='Serie'")
        cur.execute("DELETE FROM abteilung WHERE name='Serie-Abt'")
    yield


def _make_mannschaft(db, name="Erste", abteilung="Serie-Abt"):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM abteilung WHERE name=%s AND deleted_at IS NULL", (abteilung,))
        row = cur.fetchone()
        aid = row['id'] if row else None
        if aid is None:
            cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                        "VALUES (%s,'t','t') RETURNING id", (abteilung,))
            aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,%s,'2026/27','t','t') RETURNING id", (aid, name))
        return cur.fetchone()['id']


def _make_serie(db, mannschaft_id, start=TOMORROW, ende=None, beginn_zeit="19:00", **kw):
    return db.termin_serien.create(
        mannschaft_id, kw.get('typ', 'training'), beginn_zeit, kw.get('ende_zeit'),
        kw.get('ort'), kw.get('treffpunkt'), kw.get('treffpunkt_zeit'),
        kw.get('beschreibung'), start, ende, 't',
    )


def _instanzen(db, serie_id, aktive_only=True):
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, beginn, ende, ort, status, deleted_at FROM termine "
            "WHERE serie_id=%s" + (" AND deleted_at IS NULL" if aktive_only else "") +
            " ORDER BY beginn",
            (serie_id,),
        )
        return cur.fetchall()


# --------------------------------------------------------------- Schema
def test_schema_fk_und_check(db):
    with db.cursor() as cur:
        cur.execute("SELECT conname FROM pg_constraint WHERE conname='fk_termine_serie'")
        assert cur.fetchone() is not None, "FK termine.serie_id -> termin_serie fehlt"
        # CHECK: keine Spiel-Serien
        mid = _make_mannschaft(db)
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO termin_serie (mannschaft_id,typ,beginn_zeit,start_datum,"
                "materialisiert_bis,created_by,updated_by) "
                "VALUES (%s,'spiel','19:00',%s,%s,'t','t')", (mid, TOMORROW, YESTERDAY))


def test_history_trigger(db):
    mid = _make_mannschaft(db)
    s = _make_serie(db, mid)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM termin_serie_history WHERE id=%s", (s.id,))
        assert cur.fetchone()['n'] == 1


# ----------------------------------------------------- Materialisierung
def test_materialisierung_wochentag_horizont_und_idempotenz(db):
    from app.db.termin_serie_repository import HORIZONT_TAGE
    mid = _make_mannschaft(db)
    s = _make_serie(db, mid, start=TOMORROW, ort="Halle 1")
    n = db.termin_serien.materialize_due([mid])
    inst = _instanzen(db, s.id)
    # wöchentlich ab morgen bis Horizont => 8 oder 9 Instanzen (56 Tage / 7)
    assert n == len(inst) and HORIZONT_TAGE // 7 <= n <= HORIZONT_TAGE // 7 + 1
    anker_wt = date.fromisoformat(TOMORROW).weekday()
    for r in inst:
        d = date.fromisoformat(r['beginn'][:10])
        assert d.weekday() == anker_wt and r['beginn'][11:] == "19:00" and r['ort'] == "Halle 1"
    # Idempotenz: zweiter Lauf erzeugt nichts
    assert db.termin_serien.materialize_due([mid]) == 0
    assert len(_instanzen(db, s.id)) == n


def test_materialisierung_ende_kappung(db):
    mid = _make_mannschaft(db)
    ende = (HEUTE + timedelta(days=15)).isoformat()
    s = _make_serie(db, mid, start=TOMORROW, ende=ende)
    db.termin_serien.materialize_due([mid])
    inst = _instanzen(db, s.id)
    assert 2 <= len(inst) <= 3
    assert all(r['beginn'][:10] <= ende for r in inst)


def test_geloeschte_instanz_wird_nicht_wiederbelebt(db):
    mid = _make_mannschaft(db)
    s = _make_serie(db, mid, start=TOMORROW)
    db.termin_serien.materialize_due([mid])
    erste = _instanzen(db, s.id)[0]
    db.termine.mark_deleted(erste['id'], 't')      # z. B. Feiertag
    vorher = len(_instanzen(db, s.id))
    assert db.termin_serien.materialize_due([mid]) == 0   # Wasserzeichen schützt
    assert len(_instanzen(db, s.id)) == vorher


# ------------------------------------------------------------ Update-Semantik
def test_update_wirkt_nur_auf_unveraenderte_zukuenftige_geplante(db):
    mid = _make_mannschaft(db)
    s = _make_serie(db, mid, start=TOMORROW, ort="Halle 1")
    db.termin_serien.materialize_due([mid])
    inst = _instanzen(db, s.id)
    individuell, abgesagt = inst[1], inst[2]
    # eine Instanz individuell verschieben, eine absagen
    t_ind = db.termine.get(individuell['id'])
    assert db.termine.update(t_ind.id, t_ind.typ, t_ind.beginn[:11] + "20:30", None,
                             "Ausweichhalle", None, None, None, None, None, 't', t_ind.version)
    t_abg = db.termine.get(abgesagt['id'])
    assert db.termine.set_status(t_abg.id, 'abgesagt', 't', t_abg.version)
    # eine vergangene unveränderte Instanz simulieren
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO termine (mannschaft_id,serie_id,typ,beginn,ort,created_by,updated_by) "
            "VALUES (%s,%s,'training',%s,'Halle 1','t','t') RETURNING id",
            (mid, s.id, f"{YESTERDAY}T19:00"))
        vergangen_id = cur.fetchone()['id']

    # Serie: 19:00->19:30, Halle 1->Halle 2
    assert db.termin_serien.update(s.id, 'training', "19:30", None, "Halle 2",
                                   None, None, None, None, 't2', s.version)
    for r in _instanzen(db, s.id):
        if r['id'] == individuell['id']:
            assert r['beginn'][11:] == "20:30" and r['ort'] == "Ausweichhalle"  # unberührt
        elif r['id'] == abgesagt['id']:
            assert r['beginn'][11:] == "19:00" and r['status'] == 'abgesagt'    # unberührt
        elif r['id'] == vergangen_id:
            assert r['beginn'][11:] == "19:00" and r['ort'] == "Halle 1"        # Vergangenheit
        else:
            assert r['beginn'][11:] == "19:30" and r['ort'] == "Halle 2"        # gewandert
    # Versionskonflikt: alter Stand darf nichts mehr ändern
    assert not db.termin_serien.update(s.id, 'training', "21:00", None, None,
                                       None, None, None, None, 't2', s.version)


def test_update_zusage_bleibt_erhalten(db):
    mid = _make_mannschaft(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,created_by,updated_by) "
                    "VALUES ('Serie','Tester','lastschrift','t','t') RETURNING id")
        mitglied_id = cur.fetchone()['id']
    s = _make_serie(db, mid, start=TOMORROW)
    db.termin_serien.materialize_due([mid])
    erste = _instanzen(db, s.id)[0]
    db.termin_zusagen.set_antwort(erste['id'], mitglied_id, 'zu', None, 't')

    assert db.termin_serien.update(s.id, 'training', "19:30", None, None,
                                   None, None, None, None, 't', s.version)
    neu = db.termine.get(erste['id'])
    assert neu.beginn.endswith("19:30")                                   # gewandert
    assert db.termin_zusagen.answer_for(mitglied_id, [erste['id']]) == {erste['id']: 'zu'}


def test_update_ende_kuerzen_und_wieder_verlaengern(db):
    mid = _make_mannschaft(db)
    s = _make_serie(db, mid, start=TOMORROW)
    db.termin_serien.materialize_due([mid])
    inst = _instanzen(db, s.id)
    assert len(inst) >= 6
    # individuelle Abweichung auf der letzten Instanz
    letzte = db.termine.get(inst[-1]['id'])
    db.termine.update(letzte.id, letzte.typ, letzte.beginn, None, "Sonderort",
                      None, None, None, None, None, 't', letzte.version)

    # Ende auf das Datum der 3. Instanz kürzen
    kurz_ende = inst[2]['beginn'][:10]
    s = db.termin_serien.get(s.id)
    assert db.termin_serien.update(s.id, 'training', "19:00", None, None,
                                   None, None, None, kurz_ende, 't', s.version)
    nach_kuerzung = _instanzen(db, s.id)
    # unveränderte hinter dem Ende weg, individuelle bleibt
    assert {r['id'] for r in nach_kuerzung} == {inst[0]['id'], inst[1]['id'],
                                                inst[2]['id'], letzte.id}
    assert db.termin_serien.get(s.id).materialisiert_bis == kurz_ende    # geklemmt

    # wieder verlängern (offenes Ende) -> Lücke wird nachmaterialisiert,
    # aber am Sonderort-Datum entsteht KEIN Duplikat
    s = db.termin_serien.get(s.id)
    assert db.termin_serien.update(s.id, 'training', "19:00", None, None,
                                   None, None, None, None, 't', s.version)
    assert db.termin_serien.materialize_due([mid]) > 0
    daten = [r['beginn'][:10] for r in _instanzen(db, s.id)]
    assert len(daten) == len(set(daten)), "Duplikat am Datum der individuellen Instanz"
    assert len(daten) >= len(inst)


# ------------------------------------------------------------------- löschen
def test_delete_serie_raeumt_zukunft_ab(db):
    mid = _make_mannschaft(db)
    s = _make_serie(db, mid, start=TOMORROW)
    db.termin_serien.materialize_due([mid])
    inst = _instanzen(db, s.id)
    # eine Instanz individuell ändern + eine absagen + eine vergangene anlegen
    t0 = db.termine.get(inst[0]['id'])
    db.termine.update(t0.id, t0.typ, t0.beginn, None, "Anders", None, None, None,
                      None, None, 't', t0.version)
    t1 = db.termine.get(inst[1]['id'])
    db.termine.set_status(t1.id, 'abgesagt', 't', t1.version)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO termine (mannschaft_id,serie_id,typ,beginn,created_by,updated_by) "
            "VALUES (%s,%s,'training',%s,'t','t') RETURNING id",
            (mid, s.id, f"{YESTERDAY}T19:00"))
        vergangen_id = cur.fetchone()['id']

    assert db.termin_serien.mark_deleted(s.id, 't')
    assert db.termin_serien.get(s.id) is None
    rest = _instanzen(db, s.id)
    assert [r['id'] for r in rest] == [vergangen_id]        # nur Vergangenheit bleibt
    assert db.termin_serien.materialize_due([mid]) == 0     # gelöschte Serie erzeugt nichts
    assert not db.termin_serien.mark_deleted(s.id, 't')     # idempotent: schon weg
