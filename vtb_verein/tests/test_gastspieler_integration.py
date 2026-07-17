"""Integrationstests Personenart 'gastspieler' (#95 Teil 2, Schema v72).

Gastspieler (Gastspielgenehmigung) sind keine Vereinsmitglieder: eigener
mitglied-Datensatz mit art='gastspieler', OHNE Mitgliedsnummer, ausgeklammert
aus Beitragsregeln (auch Abteilungsregeln trotz mitglied_abteilung-Zuordnung),
Aufnahmegebühr-Vorschlägen und der Mitglieder-Statistik. Abteilungs-/Kader-
Zuordnung und damit der Termin-Gast-Kreis funktionieren wie bei Mitgliedern.

Prüft außerdem den Migrationspfad v71→v72 (Fresh == Migriert): Spalte wird
nachgezogen und der Audit-Trigger schreibt art in die History.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine (leere) Wegwerf-DB zeigt.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTYEAR = (date.today() - timedelta(days=365)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-gastspieler-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM gebuehr_forderung")
        cur.execute("DELETE FROM gebuehr")
        cur.execute("DELETE FROM mitglied_abteilung WHERE created_by='gasttest'")
        cur.execute("DELETE FROM mitglied WHERE created_by='gasttest'")
        cur.execute("DELETE FROM abteilung WHERE name LIKE 'GS-Abt%'")
    yield


def _make_abteilung(db, name="GS-Abt-Fussball"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                    "VALUES (%s,'gasttest','gasttest') RETURNING id", (name,))
        return cur.fetchone()['id']


def _make_mitglied(db, nachname, art="mitglied", eintritt=LASTYEAR,
                   geburtsdatum="1990-05-01", geschlecht="m"):
    from app.models.mitglied import Mitglied
    # Eintrittsdatum gibt es auch bei Gastspielern (Beginn der Gastspielgenehmigung)
    m = Mitglied(vorname="GS", nachname=nachname, art=art,
                 eintrittsdatum=eintritt,
                 geburtsdatum=geburtsdatum, geschlecht=geschlecht,
                 zahlungsart="lastschrift" if art == "mitglied" else "")
    return db.create_mitglied(m, created_by="gasttest")


def _add_abteilung(db, mitglied_id, abteilung_id, von=LASTYEAR):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id,abteilung_id,status,von,"
            "created_by,updated_by) VALUES (%s,%s,'aktiv',%s,'gasttest','gasttest')",
            (mitglied_id, abteilung_id, von))


# ------------------------------------------------------------ Stammdaten
def test_gastspieler_ohne_mitgliedsnummer(db):
    mitglied = _make_mitglied(db, "Stamm")
    gast = _make_mitglied(db, "Gastl", art="gastspieler")
    assert mitglied.mitgliedsnummer is not None
    assert gast.mitgliedsnummer is None
    assert db.get_mitglied(gast.id).art == "gastspieler"
    # zweiter Gastspieler kollidiert nicht (mehrere NULL-Nummern erlaubt)
    gast2 = _make_mitglied(db, "Gastl2", art="gastspieler")
    assert gast2.mitgliedsnummer is None


def test_art_wird_in_history_geschrieben(db):
    gast = _make_mitglied(db, "Gastl", art="gastspieler")
    gast.art = "mitglied"
    gast.mitgliedsnummer = db.get_next_mitgliedsnummer()
    gast.eintrittsdatum = LASTYEAR
    assert db.update_mitglied(gast, updated_by="gasttest")
    historie = db.get_mitglied_history(gast.id)
    assert [h["art"] for h in historie] == ["gastspieler", "mitglied"]


# ------------------------------------------------------------ Statistik
def test_statistik_zaehlt_gastspieler_nicht(db):
    abt = _make_abteilung(db)
    mitglied = _make_mitglied(db, "Stamm")
    gast = _make_mitglied(db, "Gastl", art="gastspieler", geschlecht="w")
    _add_abteilung(db, mitglied.id, abt)
    _add_abteilung(db, gast.id, abt)

    kpis = db.statistik.kpis()
    assert kpis["gesamt"] == 1
    assert kpis["aktiv"] == 1

    geschlechter = {g["geschlecht"]: g["anzahl"] for g in db.statistik.geschlechterverteilung()}
    assert geschlechter.get("w", 0) == 0 and geschlechter["m"] == 1

    alter = {a["gruppe"]: a["anzahl"] for a in db.statistik.altersstruktur()}
    assert sum(alter.values()) == 1

    uebersicht = {a["name"]: a["anzahl"] for a in db.statistik.abteilungsuebersicht()}
    assert uebersicht["GS-Abt-Fussball"] == 1


# ------------------------------------------------------------ Beiträge/Gebühren
def test_beitragsregeln_klammern_gastspieler_aus(db):
    from app.models.beitrag import Beitragsregel
    from app.services.beitrags_service import BeitragsService
    abt = _make_abteilung(db)
    mitglied = _make_mitglied(db, "Stamm")
    gast = _make_mitglied(db, "Gastl", art="gastspieler")
    _add_abteilung(db, mitglied.id, abt)
    _add_abteilung(db, gast.id, abt)

    service = BeitragsService(db)
    heute = date.today()
    q_start = date(heute.year, 1, 1)
    q_ende = date(heute.year, 12, 31)

    vereinsregel = Beitragsregel(name="Verein", abteilung_id=None,
                                 betrag_pro_monat=5.0, gueltig_ab="2000-01-01")
    ids = [m["id"] for m in service._betroffene_mitglieder(
        vereinsregel, heute.isoformat(), q_start, q_ende)]
    assert mitglied.id in ids and gast.id not in ids

    # Auch die Abteilungsregel greift nicht, obwohl der Gastspieler eine
    # mitglied_abteilung-Zuordnung hat (Gast-Kreis der Termine).
    abtregel = Beitragsregel(name="Abt", abteilung_id=abt,
                             betrag_pro_monat=3.0, gueltig_ab="2000-01-01")
    ids = [m["id"] for m in service._betroffene_mitglieder(
        abtregel, heute.isoformat(), q_start, q_ende)]
    assert mitglied.id in ids and gast.id not in ids


def test_keine_aufnahmegebuehr_fuer_gastspieler(db):
    from app.models.gebuehr import Gebuehr
    from app.services.gebuehren_service import GebuehrenService
    db.gebuehren.create(Gebuehr(name="Aufnahme", betrag=25.0, anlass="aufnahme",
                                gueltig_ab="2000-01-01"), created_by="gasttest")
    mitglied = _make_mitglied(db, "Stamm")
    gast = _make_mitglied(db, "Gastl", art="gastspieler")

    service = GebuehrenService(db)
    heute = date.today().isoformat()
    assert service.vorschlag_aufnahmegebuehren(mitglied.id, None, heute) != []
    assert service.vorschlag_aufnahmegebuehren(gast.id, None, heute) == []


# ------------------------------------------------------------ Personenliste
def test_personenliste_liefert_art(db):
    """Regression: list_personen baut eigenes SQL + Mitglied-Objekte von Hand –
    ohne art in der Spaltenliste fiele jeder Gastspieler auf den Dataclass-
    Default 'mitglied' zurück (Chip 'Vereinsmitglied', leerer Gastspieler-Filter)."""
    from types import SimpleNamespace
    from backend.api.personen import list_personen
    _make_mitglied(db, "Stamm")
    gast = _make_mitglied(db, "Gastl", art="gastspieler")

    admin = SimpleNamespace(role='admin', username='chef', id=1,
                            has_permission=lambda p: True,
                            allowed_abteilungen=lambda p: None)
    personen = list_personen(user=admin, db=db)
    arten = {p['mitglied']['id']: p['mitglied']['art']
             for p in personen if p['mitglied']}
    assert arten[gast.id] == 'gastspieler'
    assert 'mitglied' in arten.values()


# ------------------------------------------------------------ Migrationspfad
def test_migration_v71_zu_v72(db):
    """Fresh == Migriert: art-Spalte zurückbauen, Version auf 71 setzen und die
    Migration über einen frischen Connect laufen lassen – Spalte und Audit-
    Trigger (History mit art) müssen wieder da sein."""
    from app.db.datastore import VereinsDB
    with db.cursor() as cur:
        cur.execute("ALTER TABLE mitglied DROP COLUMN art")
        cur.execute("ALTER TABLE mitglied_history DROP COLUMN art")
        cur.execute("UPDATE schema_version SET version = 71 WHERE id = 1")

    d2 = VereinsDB(_URL, upload_path="/tmp/vtb-gastspieler-uploads")
    try:
        gast = _make_mitglied(db, "NachMigration", art="gastspieler")
        assert gast.mitgliedsnummer is None
        assert db.get_mitglied(gast.id).art == "gastspieler"
        historie = db.get_mitglied_history(gast.id)
        assert historie and historie[-1]["art"] == "gastspieler"
        with db.cursor() as cur:
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            assert cur.fetchone()["version"] >= 72
    finally:
        d2.close()
