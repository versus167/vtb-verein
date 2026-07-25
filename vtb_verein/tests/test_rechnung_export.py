"""Integrationstests des Rechnungs-Exports (Schema v78).

Der Export ist bewusst KEIN FBASC-Lauf, sondern ein Belegstapel für die Fibu:
ein flaches Zip mit den Belegdateien plus uebersicht.csv. Geprüft werden die
Delta-Semantik (jede Rechnung genau einmal), der Un-Export des jüngsten Laufs,
der Re-Download aus den gestempelten Zeilen und das Verhalten bei fehlender
Beleg-Datei auf dem Server.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import csv
import io
import os
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()
_UPLOADS = "/tmp/vtb-rechnung-export-uploads"


def _png_bytes() -> bytes:
    from PIL import Image
    puffer = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 120, 200)).save(puffer, format="PNG")
    return puffer.getvalue()


_PNG = _png_bytes()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path=_UPLOADS)
    yield d
    d.close()


# Sequenzen, die andere Testdateien per TRUNCATE ... RESTART IDENTITY zurücksetzen
# können, während die *_history-Zeilen stehen bleiben (sonst PK-Kollision im
# Audit-Trigger, je nach Testreihenfolge). Siehe test_rechnungen.py.
_SEQ_TABELLEN = ("users", "mitglied", "abteilung", "user_permissions",
                 "mitglied_abteilung")


def _resync_sequenzen(cur):
    for tabelle in _SEQ_TABELLEN:
        cur.execute(
            f"""
            SELECT setval(pg_get_serial_sequence('{tabelle}', 'id'), GREATEST(
                (SELECT COALESCE(MAX(id), 0) FROM {tabelle}),
                (SELECT COALESCE(MAX(id), 0) FROM {tabelle}_history),
                1))
            """
        )


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE rechnung_anhaenge, rechnung, rechnung_history, "
            "rechnung_exporte, rechnung_exporte_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM mitglied_abteilung WHERE created_by='xtest'")
        cur.execute("DELETE FROM user_permissions WHERE created_by='xtest'")
        cur.execute("DELETE FROM mitglied WHERE vorname='ExpTest'")
        cur.execute("DELETE FROM users WHERE username LIKE 'xtester%'")
        cur.execute("DELETE FROM abteilung WHERE name = 'X-Fussball'")
        for tabelle in ("user_permissions_history", "mitglied_abteilung_history",
                        "mitglied_history", "users_history", "abteilung_history"):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by='xtest'")
        _resync_sequenzen(cur)
    yield


# ---------------------------------------------------------------- Testdaten

def _setup(db):
    """Abteilung + Einreicher + Freigeber/Geschäftsstelle."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,kostenstelle,created_by,updated_by) "
                    "VALUES ('X-Fussball',77,'xtest','xtest') RETURNING id")
        abteilung = cur.fetchone()["id"]
    return abteilung, _user(db, "xtester_ein", ("rechnungen.einreichen",), abteilung), \
        _user(db, "xtester_gs", ("rechnungen.verwalten",), None)


def _user(db, username, perms, abteilung_id):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES (%s,%s,'x','mitglied',1,'xtest','xtest') RETURNING id",
            (username, f"{username}@example.invalid"))
        uid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
            "VALUES ('ExpTest',%s,'ueberweisung',%s,'xtest','xtest') RETURNING id",
            (username, uid))
        mid = cur.fetchone()["id"]
        for p in perms:
            cur.execute(
                "INSERT INTO user_permissions (user_id,permission,created_by,updated_by) "
                "VALUES (%s,%s,'xtest','xtest')", (uid, p))
        if abteilung_id is not None:
            cur.execute(
                "INSERT INTO mitglied_abteilung (mitglied_id,abteilung_id,status,von,created_by,updated_by) "
                "VALUES (%s,%s,'aktiv',%s,'xtest','xtest')", (mid, abteilung_id, LASTWEEK))
    return db.get_user_by_id(uid)


def _freigegebene_rechnung(db, einreicher, gs, abteilung, *, belege=1, **felder):
    r = db.rechnungen.anlegen(
        einreicher, kategorie_id=db.rechnungen.list_kategorien()[0].id,
        abteilung_id=abteilung, **felder)
    for i in range(belege):
        db.rechnungen.add_anhang(r.id, einreicher, original_name=f"beleg{i}.png",
                                 mime_type="image/png", inhalt=_PNG)
    db.rechnungen.einreichen(r.id, einreicher)
    return db.rechnungen.freigeben(r.id, gs)


def _entpacke(zip_bytes):
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    return zf, zf.namelist()


def _uebersicht(zip_bytes) -> list[dict]:
    zf, _ = _entpacke(zip_bytes)
    text = zf.read("uebersicht.csv").decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


# ------------------------------------------------------------------- Tests

def test_zip_enthaelt_belege_und_uebersicht(db):
    abteilung, einreicher, gs = _setup(db)
    r = _freigegebene_rechnung(db, einreicher, gs, abteilung,
                               betrag_cent=1250, rechnungsdatum="2026-07-01",
                               rechnungsnummer="RE-4711", beschreibung="Bälle")

    dateiname, zip_bytes = db.rechnung_export.exportieren(gs.username)
    assert dateiname == "rechnungen-export-1.zip"

    _, namen = _entpacke(zip_bytes)
    assert sorted(namen) == ["R1.jpg", "uebersicht.csv"]   # PNG wird zu JPEG normalisiert

    zeile = _uebersicht(zip_bytes)[0]
    assert zeile["Nr"] == f"R{r.id}"
    assert zeile["Belegdateien"] == "R1.jpg"
    assert zeile["Betrag EUR"] == "12,50"                  # deutsches Dezimalkomma
    assert zeile["Rechnungsnummer"] == "RE-4711"
    assert zeile["Abteilung"] == "X-Fussball"
    assert zeile["Kostenstelle"] == "77"
    assert zeile["Freigegeben von"] == "xtester_gs"


def test_mehrere_belege_bekommen_suffix(db):
    abteilung, einreicher, gs = _setup(db)
    _freigegebene_rechnung(db, einreicher, gs, abteilung, belege=3)

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    _, namen = _entpacke(zip_bytes)
    assert sorted(n for n in namen if n != "uebersicht.csv") == \
        ["R1-2.jpg", "R1-3.jpg", "R1.jpg"]
    assert _uebersicht(zip_bytes)[0]["Belegdateien"] == "R1.jpg R1-2.jpg R1-3.jpg"


def test_delta_zweiter_lauf_ohne_bereits_exportierte(db):
    abteilung, einreicher, gs = _setup(db)
    erste = _freigegebene_rechnung(db, einreicher, gs, abteilung)

    db.rechnung_export.exportieren(gs.username)
    assert db.rechnung_export.vorschau()["anzahl"] == 0

    zweite = _freigegebene_rechnung(db, einreicher, gs, abteilung)
    v = db.rechnung_export.vorschau()
    assert [r.id for r in v["rechnungen"]] == [zweite.id]

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    nummern = [z["Nr"] for z in _uebersicht(zip_bytes)]
    assert nummern == [f"R{zweite.id}"]
    assert f"R{erste.id}" not in nummern


def test_nur_freigegebene_werden_exportiert(db):
    abteilung, einreicher, gs = _setup(db)
    # eingereicht, aber noch nicht freigegeben
    r = db.rechnungen.anlegen(einreicher, kategorie_id=db.rechnungen.list_kategorien()[0].id,
                              abteilung_id=abteilung)
    db.rechnungen.add_anhang(r.id, einreicher, original_name="b.png",
                             mime_type="image/png", inhalt=_PNG)
    db.rechnungen.einreichen(r.id, einreicher)

    assert db.rechnung_export.vorschau()["anzahl"] == 0
    from app.services.rechnung_export_service import KeineRechnungenError
    with pytest.raises(KeineRechnungenError):
        db.rechnung_export.exportieren(gs.username)


def test_un_export_gibt_rechnungen_wieder_frei(db):
    abteilung, einreicher, gs = _setup(db)
    r = _freigegebene_rechnung(db, einreicher, gs, abteilung)
    db.rechnung_export.exportieren(gs.username)

    export = db.rechnung_export.list_exporte()[0]
    ergebnis = db.rechnung_export.zuruecknehmen(export.id, gs.username)
    assert ergebnis["rechnungen_wieder_offen"] == 1

    assert [x.id for x in db.rechnung_export.vorschau()["rechnungen"]] == [r.id]
    assert db.rechnung_export.list_exporte() == []          # Header soft-deleted
    assert db.rechnungen.get(r.id, gs).exportiert_in_export_id is None


def test_un_export_nur_juengster_lauf(db):
    from app.services.rechnung_export_service import NichtJuengsterLaufError

    abteilung, einreicher, gs = _setup(db)
    _freigegebene_rechnung(db, einreicher, gs, abteilung)
    db.rechnung_export.exportieren(gs.username)
    erster = db.rechnung_export.list_exporte()[0]

    _freigegebene_rechnung(db, einreicher, gs, abteilung)
    db.rechnung_export.exportieren(gs.username)

    with pytest.raises(NichtJuengsterLaufError):
        db.rechnung_export.zuruecknehmen(erster.id, gs.username)


def test_re_download_liefert_denselben_inhalt(db):
    abteilung, einreicher, gs = _setup(db)
    _freigegebene_rechnung(db, einreicher, gs, abteilung, betrag_cent=999)
    dateiname, original = db.rechnung_export.exportieren(gs.username)

    export = db.rechnung_export.list_exporte()[0]
    name2, erneut = db.rechnung_export.re_download(export.id)

    assert name2 == dateiname
    assert _uebersicht(erneut) == _uebersicht(original)
    assert sorted(_entpacke(erneut)[1]) == sorted(_entpacke(original)[1])


def test_exportierte_rechnung_ist_gesperrt(db):
    from app.services.rechnung_service import RechnungGesperrtError

    abteilung, einreicher, gs = _setup(db)
    r = _freigegebene_rechnung(db, einreicher, gs, abteilung)
    db.rechnung_export.exportieren(gs.username)

    with pytest.raises(RechnungGesperrtError):
        db.rechnungen.zuruecksetzen(r.id, gs)
    with pytest.raises(RechnungGesperrtError):
        db.rechnungen.loeschen(r.id, gs)


def test_fehlende_belegdatei_bricht_lauf_nicht_ab(db):
    """Eine verlorene Datei darf den Export nicht kippen – die Vorschau warnt vorher."""
    abteilung, einreicher, gs = _setup(db)
    r = _freigegebene_rechnung(db, einreicher, gs, abteilung)
    anhang = db.rechnungen.list_anhaenge(r.id, gs)[0]
    (Path(_UPLOADS) / anhang.stored_name).unlink()

    hinweise = db.rechnung_export.vorschau()["hinweise"]
    assert any("fehlt auf dem Server" in h for h in hinweise)

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    _, namen = _entpacke(zip_bytes)
    assert namen == ["uebersicht.csv"]                      # kein Beleg, aber ein Lauf
    assert _uebersicht(zip_bytes)[0]["Belegdateien"] == ""


def test_summe_und_anzahl_im_header(db):
    abteilung, einreicher, gs = _setup(db)
    _freigegebene_rechnung(db, einreicher, gs, abteilung, betrag_cent=1000)
    _freigegebene_rechnung(db, einreicher, gs, abteilung, betrag_cent=2550)

    db.rechnung_export.exportieren(gs.username)
    export = db.rechnung_export.list_exporte()[0]
    assert export.anzahl_rechnungen == 2
    assert export.summe_cent == 3550


def test_rechnung_ohne_betrag_stoert_summe_nicht(db):
    """Betrag ist optional – die Fibu trägt ihn nach."""
    abteilung, einreicher, gs = _setup(db)
    _freigegebene_rechnung(db, einreicher, gs, abteilung)               # ohne Betrag
    _freigegebene_rechnung(db, einreicher, gs, abteilung, betrag_cent=500)

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    betraege = [z["Betrag EUR"] for z in _uebersicht(zip_bytes)]
    assert betraege == ["", "5,00"]
    assert db.rechnung_export.list_exporte()[0].summe_cent == 500
