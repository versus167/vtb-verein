"""
Integrationstest der Kassenzählung gegen echtes PostgreSQL.

Der Punkt dieses Moduls sind die **echten Spaltentypen**: `test_kassen_zaehlung.py`
arbeitet mit Fakes, und genau deshalb ist unbemerkt geblieben, dass `created_at` seit
der TIMESTAMPTZ-Normalisierung als `datetime` aus der DB kommt statt als Text. Der
PDF-Bau ist daran mit TypeError gescheitert; weil das Anhängen best-effort ist, wurde
der Fehler nur geloggt – die Zählung war gebucht, das Protokoll fehlte still.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --rm --name vtb-pg-zaehltest -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=zaehltest -e TZ=Europe/Berlin -p 55432:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/zaehltest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_kassen_zaehlung_integration.py
"""
import os
import tempfile
from datetime import datetime

import pytest

from app.models.kasse import Kasse, KassenKategorie
from app.services.kassenbuch_service import zaehlprotokoll_dateiname

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def uploads():
    with tempfile.TemporaryDirectory(prefix="vtb-zaehl-uploads-") as pfad:
        yield pfad


@pytest.fixture(scope="module")
def db(uploads):
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path=uploads)
    yield d
    d.close()


@pytest.fixture(scope="module")
def kassenwart(db):
    """Wer den Anhang hochlädt – `hochgeladen_von` ist ein FK auf users.

    Ohne Mailadresse (Konto ohne Zugang): Der Test braucht keine, und ein
    wiederverwendeter Container liefe sonst in die Unique-Bremse.
    """
    return (db.users.get_by_username("kassenwart")
            or db.users.create("kassenwart", None, "x", "mitglied", created_by="TEST"))


@pytest.fixture
def kasse(db):
    return db.kassen.create_kasse(
        Kasse(name="Imbisskasse", anfangsbestand_cent=12500), created_by="TEST"
    )


def _zaehlen(db, kasse, kassenwart, stueckelung, **kw):
    return db.kassenbuch.erstelle_zaehlung(
        kasse.id, stueckelung, created_by=kassenwart.username,
        user_id=kassenwart.id, is_admin=True, **kw,
    )


def test_created_at_kommt_als_datetime(db, kasse, kassenwart):
    """Die Annahme, auf der alles andere ruht – schlägt sie um, muss dieser Test rot werden."""
    z = _zaehlen(db, kasse, kassenwart, {"5000": 2, "200": 13})
    assert isinstance(z.created_at, datetime)


def test_zaehlprotokoll_haengt_an_der_buchung(db, kasse, kassenwart, uploads):
    z = _zaehlen(db, kasse, kassenwart, {"5000": 2, "200": 13})   # Ist 126 €, Soll 125 €

    assert z.differenz_cent == 100
    anhaenge = db.kassenbuch.get_anhaenge(z.buchung_id)
    assert [a.original_name for a in anhaenge] == [zaehlprotokoll_dateiname(z.id)]

    anhang = anhaenge[0]
    assert anhang.mime_type == "application/pdf"
    inhalt = (db.kassenbuch._anhang_service.upload_path / anhang.stored_name).read_bytes()
    assert inhalt.startswith(b"%PDF")
    assert anhang.dateigroesse == len(inhalt)


def test_kategorie_getriebene_zaehlung_haengt_das_protokoll_an(db, kasse, kassenwart):
    """Der Fall aus dem Kassenbuch: „Imbiss" löst die Zählung aus, die Zählung IST die Buchung."""
    db.kassen_kategorien.create(
        KassenKategorie(name="Einnahme Imbiss", kasse_id=kasse.id, loest_zaehlung_aus=True),
        created_by="TEST",
    )
    z = _zaehlen(db, kasse, kassenwart, {"5000": 6, "1000": 1},
                 kategorie="Einnahme Imbiss", buchungstext="Imbiss")

    buchung = db.kassenbuch._buchung.get_kassenbuchung(z.buchung_id)
    assert buchung.kategorie == "Einnahme Imbiss"
    assert db.kassenbuch.protokoll_anhang(z) is not None


def test_nachtragen_holt_ein_fehlendes_protokoll_nach(db, kasse, kassenwart):
    """Alter Bestand: Zählung ohne Protokoll (hier: ohne user_id gebucht)."""
    z = db.kassenbuch.erstelle_zaehlung(
        kasse.id, {"5000": 2}, created_by=kassenwart.username,
    )
    assert db.kassenbuch.protokoll_anhang(z) is None

    anhang = db.kassenbuch.protokoll_nachtragen(
        kasse.id, z.id, user_id=kassenwart.id, is_admin=True
    )
    assert anhang.original_name == zaehlprotokoll_dateiname(z.id)
    assert db.kassenbuch.protokoll_anhang(z).id == anhang.id

    # idempotent – ein zweiter Lauf legt nichts Neues an
    assert db.kassenbuch.protokoll_nachtragen(
        kasse.id, z.id, user_id=kassenwart.id, is_admin=True).id == anhang.id
    assert len(db.kassenbuch.get_anhaenge(z.buchung_id)) == 1


def test_nachtragen_gegen_fremde_kasse_wirft(db, kasse, kassenwart):
    z = _zaehlen(db, kasse, kassenwart, {"5000": 2})
    andere = db.kassen.create_kasse(Kasse(name="Zweitkasse"), created_by="TEST")
    with pytest.raises(KeyError):
        db.kassenbuch.protokoll_nachtragen(
            andere.id, z.id, user_id=kassenwart.id, is_admin=True)
