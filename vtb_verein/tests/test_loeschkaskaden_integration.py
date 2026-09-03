"""
Löschkaskaden der Handpfade – gegen echtes PostgreSQL.

Ein Soft-Delete des Parents muss die Kinder mitnehmen, die ihn fachlich nicht
überleben können. Fehlt die Kaskade, bleibt ein AKTIVES Kind an einem GELÖSCHTEN
Parent hängen: Die Konsistenzprüfung meldet das als hängenden Verweis, und Tor 4
des Prune (``NOT EXISTS`` OHNE ``deleted_at``-Filter, also physische Existenz)
hält den Parent dauerhaft im Papierkorb fest, ohne dass irgendwo etwas auffiele.

Beide hier geprüften Beziehungen hatten genau diese Lücke: Die ArchiveRule bzw.
das PRUNE_REGISTRY führten das Kind längst mit, der von Hand ausgelöste Löschpfad
nicht. Gegenstück ist ``mark_kassenbuchung_deleted``, wo der Handpfad schon
nachgezogen war.

Mitgeprüft wird jeweils die Gegenrichtung – was NICHT mitgelöscht werden darf:
Ein Ticket überlebt seinen Bereich (der Vorgang bleibt, nur die Einsortierung
fällt weg), und eine bereits eingereichte Abrechnung lässt sich gar nicht löschen,
darf also auch ihre Stunden nicht anfassen.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --rm --name vtb-pg-kaskade -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=kaskade -e TZ=Europe/Berlin -p 55441:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55441/kaskade \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_loeschkaskaden_integration.py
"""
import os
import tempfile

import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    with tempfile.TemporaryDirectory(prefix="vtb-kaskade-uploads-") as pfad:
        d = VereinsDB(_URL, upload_path=pfad)
        yield d
        d.close()


@pytest.fixture(autouse=True)
def sauber(db):
    """Vor und nach jedem Test leer – die Konsistenzprüfung scannt den ganzen Bestand."""
    _leeren(db)
    yield
    _leeren(db)


def _leeren(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE mitglied, abteilung, ul_abrechnung, ul_stunde, "
            "tickets, ticket_bereiche, ticket_bereich_berechtigungen CASCADE"
        )
        for tabelle in ("mitglied", "ul_abrechnung", "ul_stunde", "tickets",
                        "ticket_bereiche", "ticket_bereich_berechtigungen"):
            cur.execute(f"DELETE FROM {tabelle}_history")
        cur.execute("DELETE FROM users WHERE username = 'kaskadentester'")


# --- Hilfen ------------------------------------------------------------------------
def _geloescht(db, tabelle, zeilen_id) -> bool:
    with db.cursor() as cur:
        cur.execute(f"SELECT deleted_at FROM {tabelle} WHERE id = %s", (zeilen_id,))
        zeile = cur.fetchone()
    assert zeile is not None, f"{tabelle}#{zeilen_id} wurde hart gelöscht"
    return zeile["deleted_at"] not in (None, "")


def _haengende_verweise(db, child_table, child_column) -> int:
    """Was die Konsistenzprüfung für genau diese Beziehung meldet.

    Bewusst je Beziehung statt über ``alles_konsistent``: Manche hängenden Verweise
    sind gewollt (ein Ticket überlebt seinen Bereich) und dürfen den Test nicht
    rot färben.
    """
    from app.services.konsistenz_service import KonsistenzService
    bericht = KonsistenzService(db).pruefung()
    return sum(b["verletzungen"] for b in bericht["befunde"]
               if b["child_table"] == child_table and b["child_column"] == child_column)


def _abteilung(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES ('Kaskaden-Abteilung', 'TEST', 'TEST') RETURNING id")
        return cur.fetchone()["id"]


def _mitglied(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied (vorname, nachname, zahlungsart, created_by) "
                    "VALUES ('Uta', 'Übungsleiter', 'lastschrift', 'TEST') RETURNING id")
        return cur.fetchone()["id"]


def _abrechnung(db, status="entwurf", stunden=2):
    """Abrechnung mit `stunden` Einzelterminen."""
    mitglied_id, abteilung_id = _mitglied(db), _abteilung(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO ul_abrechnung (mitglied_id, abteilung_id, zeitraum_von, "
                    "zeitraum_bis, status, created_by, updated_by) "
                    "VALUES (%s, %s, '2026-01-01', '2026-01-31', %s, 'TEST', 'TEST') "
                    "RETURNING id", (mitglied_id, abteilung_id, status))
        abrechnung_id = cur.fetchone()["id"]
        stunden_ids = []
        for tag in range(1, stunden + 1):
            cur.execute("INSERT INTO ul_stunde (abrechnung_id, datum, stunden, "
                        "created_by, updated_by) "
                        "VALUES (%s, %s, 2.0, 'TEST', 'TEST') RETURNING id",
                        (abrechnung_id, f"2026-01-{tag:02d}"))
            stunden_ids.append(cur.fetchone()["id"])
    return abrechnung_id, stunden_ids


def _user(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO users (username, email, password_hash, role, active, "
                    "created_by, updated_by) "
                    "VALUES ('kaskadentester', 'kaskade@example.com', 'x', 'mitglied', 1, "
                    "'TEST', 'TEST') RETURNING id")
        return cur.fetchone()["id"]


# --- ÜL-Abrechnung -> Stunden ------------------------------------------------------
def test_abrechnung_loeschen_nimmt_ihre_stunden_mit(db):
    abrechnung_id, stunden_ids = _abrechnung(db)

    assert db.ul_abrechnungen.soft_delete(abrechnung_id, deleted_by="TEST") is True

    assert _geloescht(db, "ul_abrechnung", abrechnung_id)
    for stunde_id in stunden_ids:
        assert _geloescht(db, "ul_stunde", stunde_id), \
            f"ul_stunde#{stunde_id} blieb aktiv und hängt jetzt an einer gelöschten Abrechnung"
    assert _haengende_verweise(db, "ul_stunde", "abrechnung_id") == 0


def test_stunden_der_abrechnung_bekommen_history(db):
    """Der version-Bump ist Teil der Kaskade – sonst fehlt der Löschvorgang in der History."""
    abrechnung_id, stunden_ids = _abrechnung(db, stunden=1)
    db.ul_abrechnungen.soft_delete(abrechnung_id, deleted_by="TEST")

    with db.cursor() as cur:
        cur.execute("SELECT version FROM ul_stunde WHERE id = %s", (stunden_ids[0],))
        assert cur.fetchone()["version"] == 2
        cur.execute("SELECT COUNT(*) AS n FROM ul_stunde_history WHERE id = %s",
                    (stunden_ids[0],))
        assert cur.fetchone()["n"] >= 1


def test_eingereichte_abrechnung_bleibt_samt_stunden_unangetastet(db):
    """Nur Entwürfe sind löschbar – ein abgelehnter Versuch darf nichts halb erledigen."""
    abrechnung_id, stunden_ids = _abrechnung(db, status="eingereicht")

    assert db.ul_abrechnungen.soft_delete(abrechnung_id, deleted_by="TEST") is False

    assert not _geloescht(db, "ul_abrechnung", abrechnung_id)
    for stunde_id in stunden_ids:
        assert not _geloescht(db, "ul_stunde", stunde_id)


# --- Ticket-Bereich -> Bereichsrechte ----------------------------------------------
def test_bereich_loeschen_nimmt_die_rechte_mit_aber_nicht_die_tickets(db):
    from app.models.ticket import TicketBereich
    bereich = db.ticket_bereiche.create(TicketBereich(name="Kaskaden-Bereich"), "TEST")
    user_id = _user(db)
    db.ticket_bereich_berechtigungen.set_berechtigung(
        bereich.id, user_id, True, True, False, "TEST")
    with db.cursor() as cur:
        cur.execute("INSERT INTO tickets (titel, beschreibung, bereich_id, "
                    "created_by, updated_by) "
                    "VALUES ('Bleibt bestehen', 'Text', %s, 'TEST', 'TEST') RETURNING id",
                    (bereich.id,))
        ticket_id = cur.fetchone()["id"]

    assert db.ticket_bereiche.mark_deleted(bereich.id, deleted_by="TEST") is True

    assert _geloescht(db, "ticket_bereiche", bereich.id)
    assert db.ticket_bereich_berechtigungen.get_berechtigung(bereich.id, user_id) is None
    assert _haengende_verweise(db, "ticket_bereich_berechtigungen", "bereich_id") == 0

    # Gegenrichtung: Das Ticket ist der fachliche Vorgang und überlebt seinen Bereich.
    assert not _geloescht(db, "tickets", ticket_id)


def test_bereich_zweimal_loeschen_meldet_beim_zweiten_mal_false(db):
    from app.models.ticket import TicketBereich
    bereich = db.ticket_bereiche.create(TicketBereich(name="Doppelt"), "TEST")

    assert db.ticket_bereiche.mark_deleted(bereich.id, deleted_by="TEST") is True
    assert db.ticket_bereiche.mark_deleted(bereich.id, deleted_by="TEST") is False
