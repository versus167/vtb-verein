"""Primär-Regel der Mitglied-Kontakte gegen echtes PostgreSQL.

Invariante (MitgliedKontaktRepository): Sobald aktive Kontakte eines Typs existieren,
ist genau einer davon primär. Geprüft werden Auto-Primär beim ersten Kontakt,
Primär-Wechsel, die Ablehnung von "verwaisenden" Updates/Deletes sowie das Nachrücken
beim Leeren des Einzelfelds (upsert_primaer).

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine (leere) Wegwerf-DB zeigt – VereinsDB
legt das Schema beim Connect an (Muster wie test_tresor_integration).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-kontakte-uploads")
    yield d
    d.close()


def _clean(db):
    with db.cursor() as cur:
        cur.execute("TRUNCATE mitglied_kontakt, mitglied_kontakt_history RESTART IDENTITY")
        cur.execute("DELETE FROM mitglied_history WHERE nachname = 'Kontakttest'")
        cur.execute("DELETE FROM mitglied WHERE nachname = 'Kontakttest'")


@pytest.fixture()
def mitglied_id(db):
    _clean(db)
    from app.models.mitglied import Mitglied
    m = db.create_mitglied(
        Mitglied(vorname="Karla", nachname="Kontakttest", mitgliedsnummer=90001),
        created_by="kontakttest",
    )
    yield m.id
    # Auch hinterher räumen: andere Integrationstests zählen Mitglieder global
    # (z. B. die Statistik-KPIs) und dürfen unser Test-Mitglied nicht sehen.
    _clean(db)


def test_erster_kontakt_wird_automatisch_primaer(db, mitglied_id):
    k = db.create_mitglied_kontakt(mitglied_id, 'telefon', '0711 1', None, False, 'kt')
    assert k.ist_primaer is True


def test_zweiter_kontakt_bleibt_sekundaer_und_primaer_wechsel(db, mitglied_id):
    k1 = db.create_mitglied_kontakt(mitglied_id, 'telefon', '0711 1', None, True, 'kt')
    k2 = db.create_mitglied_kontakt(mitglied_id, 'telefon', '0170 2', None, False, 'kt')
    assert k2.ist_primaer is False

    # k2 primär setzen → k1 verliert das Flag
    assert db.update_mitglied_kontakt(k2.id, 'telefon', k2.wert, None, True,
                                      updated_by='kt', expected_version=k2.version)
    werte = {k.wert: k.ist_primaer for k in db.list_mitglied_kontakte(mitglied_id)}
    assert werte == {'0711 1': False, '0170 2': True}


def test_primaer_flag_wegnehmen_mit_weiteren_kontakten_verboten(db, mitglied_id):
    from app.db.mitglied_kontakt_repository import KontaktPrimaerRegelError
    k1 = db.create_mitglied_kontakt(mitglied_id, 'telefon', '0711 1', None, True, 'kt')
    db.create_mitglied_kontakt(mitglied_id, 'telefon', '0170 2', None, False, 'kt')
    with pytest.raises(KontaktPrimaerRegelError):
        db.update_mitglied_kontakt(k1.id, 'telefon', k1.wert, None, False,
                                   updated_by='kt', expected_version=k1.version)


def test_typwechsel_des_primaeren_mit_weiteren_kontakten_verboten(db, mitglied_id):
    from app.db.mitglied_kontakt_repository import KontaktPrimaerRegelError
    k1 = db.create_mitglied_kontakt(mitglied_id, 'telefon', '0711 1', None, True, 'kt')
    db.create_mitglied_kontakt(mitglied_id, 'telefon', '0170 2', None, False, 'kt')
    with pytest.raises(KontaktPrimaerRegelError):
        db.update_mitglied_kontakt(k1.id, 'mobil', k1.wert, None, True,
                                   updated_by='kt', expected_version=k1.version)


def test_einziger_kontakt_kann_flag_nicht_verlieren(db, mitglied_id):
    k = db.create_mitglied_kontakt(mitglied_id, 'email', 'a@b.de', None, True, 'kt')
    assert db.update_mitglied_kontakt(k.id, 'email', 'neu@b.de', None, False,
                                      updated_by='kt', expected_version=k.version)
    (nach,) = db.list_mitglied_kontakte(mitglied_id)
    assert nach.wert == 'neu@b.de'
    assert nach.ist_primaer is True  # einziger Kontakt bleibt zwangsläufig primär


def test_primaeren_loeschen_mit_weiteren_verboten_dann_erlaubt(db, mitglied_id):
    from app.db.mitglied_kontakt_repository import KontaktPrimaerRegelError
    k1 = db.create_mitglied_kontakt(mitglied_id, 'telefon', '0711 1', None, True, 'kt')
    k2 = db.create_mitglied_kontakt(mitglied_id, 'telefon', '0170 2', None, False, 'kt')
    with pytest.raises(KontaktPrimaerRegelError):
        db.mark_mitglied_kontakt_deleted(k1.id, deleted_by='kt')

    # Sekundären löschen geht immer; danach ist der Primäre allein und löschbar
    assert db.mark_mitglied_kontakt_deleted(k2.id, deleted_by='kt')
    assert db.mark_mitglied_kontakt_deleted(k1.id, deleted_by='kt')
    assert db.list_mitglied_kontakte(mitglied_id) == []


def test_upsert_primaer_leeren_laesst_naechsten_nachruecken(db, mitglied_id):
    # Einzelfeld-Kompatibilität (Admin-Stammdaten): Feld leeren soft-löscht den
    # Primärkontakt; ein weiterer aktiver Kontakt des Typs rückt als primär nach.
    db.create_mitglied_kontakt(mitglied_id, 'telefon', '0711 1', None, True, 'kt')
    db.create_mitglied_kontakt(mitglied_id, 'telefon', '0170 2', None, False, 'kt')
    db.set_mitglied_primaer_kontakt(mitglied_id, 'telefon', '', 'kt')
    (verbleibt,) = db.list_mitglied_kontakte(mitglied_id)
    assert verbleibt.wert == '0170 2'
    assert verbleibt.ist_primaer is True
