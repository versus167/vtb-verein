"""Integrationstests für Einreichen & Freigeben von Rechnungen (Schema v78).

Deckt ab:
  * Status-Workflow entwurf → eingereicht → freigegeben/abgelehnt inkl. der
    verbotenen Übergänge (die Repository-WHERE-Klausel muss greifen, nicht nur
    eine Prüfung im Service).
  * Abteilungs-Scope der Freigabe: ein Abteilungsleiter Fußball darf Handball
    weder sehen noch entscheiden – auch wenn `has_permission` (lenient) sein
    Recht global bejaht.
  * Vereinsrechnungen (ohne Abteilung) nur für 'rechnungen.verwalten'.
  * Beleg-Pflicht beim Einreichen und Soft-Delete-Verhalten.
  * Abteilungs-Vorbelegung aus Mitgliedschaft und Funktion.
  * Erstattung an ein *anderes* Mitglied – nur für 'rechnungen.verwalten' (#134).

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB; VereinsDB legt das
Schema beim Connect an).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()
_UPLOADS = "/tmp/vtb-rechnung-uploads"


def _png_bytes() -> bytes:
    """Echtes PNG – der AnhangService lädt Bilder mit PIL und skaliert sie."""
    import io
    from PIL import Image
    puffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(puffer, format="PNG")
    return puffer.getvalue()


_PNG = _png_bytes()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path=_UPLOADS)
    yield d
    d.close()


# Tabellen, in die diese Tests schreiben und deren Sequenz von anderen Testdateien
# per TRUNCATE ... RESTART IDENTITY zurückgesetzt worden sein kann.
_SEQ_TABELLEN = ("users", "mitglied", "abteilung", "user_permissions",
                 "mitglied_abteilung", "mitglied_funktion")


def _resync_sequenzen(cur):
    """Sequenzen über den höchsten Wert in Live- UND History-Tabelle heben.

    Andere Testdateien truncaten diese Tabellen mit RESTART IDENTITY, lassen die
    *_history aber stehen. Ohne Resync vergibt die Sequenz eine ID erneut und der
    Audit-Trigger scheitert am History-PK (id, version) – abhängig davon, welche
    Testdatei vorher lief.
    """
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
        cur.execute("DELETE FROM mitglied_funktion WHERE created_by='rtest'")
        cur.execute("DELETE FROM mitglied_abteilung WHERE created_by='rtest'")
        cur.execute("DELETE FROM user_permissions WHERE created_by='rtest'")
        cur.execute("DELETE FROM mitglied WHERE vorname='RechTest'")
        cur.execute("DELETE FROM users WHERE username LIKE 'rtester%'")
        cur.execute("DELETE FROM abteilung WHERE name IN ('R-Fussball','R-Handball')")
        # Die Audit-Trigger haben zu den eben gelöschten Zeilen History geschrieben.
        # Bleibt sie liegen, kollidiert der nächste Lauf auf (id, version), sobald
        # eine Sequenz zurückgesetzt wurde.
        for tabelle in ("user_permissions_history", "mitglied_funktion_history",
                        "mitglied_abteilung_history", "mitglied_history",
                        "users_history", "abteilung_history"):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by='rtest'")
        _resync_sequenzen(cur)
    yield


# ---------------------------------------------------------------- Testdaten

def _abteilung(db, name):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,kostenstelle,created_by,updated_by) "
                    "VALUES (%s,42,'rtest','rtest') RETURNING id", (name,))
        return cur.fetchone()["id"]


def _user(db, username, *, perms=(), abteilung_perms=(), abteilungen=(), funktionen=()):
    """User + Mitglied, mit globalen Grants, abteilungs-scoped Grants,
    Abteilungs-Mitgliedschaften und Funktions-Zuordnungen."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES (%s,%s,'x','mitglied',1,'rtest','rtest') RETURNING id",
            (username, f"{username}@example.invalid"),
        )
        uid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
            "VALUES ('RechTest',%s,'ueberweisung',%s,'rtest','rtest') RETURNING id",
            (username, uid),
        )
        mid = cur.fetchone()["id"]
        for p in perms:
            cur.execute(
                "INSERT INTO user_permissions (user_id,permission,created_by,updated_by) "
                "VALUES (%s,%s,'rtest','rtest')", (uid, p))
        for p, aid in abteilung_perms:
            cur.execute(
                "INSERT INTO user_permissions (user_id,permission,abteilung_id,created_by,updated_by) "
                "VALUES (%s,%s,%s,'rtest','rtest')", (uid, p, aid))
        for aid in abteilungen:
            cur.execute(
                "INSERT INTO mitglied_abteilung (mitglied_id,abteilung_id,status,von,created_by,updated_by) "
                "VALUES (%s,%s,'aktiv',%s,'rtest','rtest')", (mid, aid, LASTWEEK))
        for fkey, aid in funktionen:
            cur.execute(
                "INSERT INTO mitglied_funktion (mitglied_id,abteilung_id,funktion,von,created_by,updated_by) "
                "VALUES (%s,%s,%s,%s,'rtest','rtest')", (mid, aid, fkey, LASTWEEK))
    return db.get_user_by_id(uid)


def _mitglied_id(db, user) -> int:
    with db.cursor() as cur:
        cur.execute("SELECT id FROM mitglied WHERE user_id = %s", (user.id,))
        return cur.fetchone()["id"]


def _kategorie_id(db):
    return db.rechnungen.list_kategorien()[0].id


def _rechnung(db, user, abteilung_id=None, **felder):
    felder.setdefault("empfaenger_typ", "mitglied")   # Regelfall: Auslage erstatten
    felder.setdefault("betrag_cent", 1234)            # Pflicht beim Einreichen
    return db.rechnungen.anlegen(
        user, kategorie_id=_kategorie_id(db), abteilung_id=abteilung_id, **felder)


def _beleg(db, rechnung_id, user, name="beleg.png"):
    return db.rechnungen.add_anhang(
        rechnung_id, user, original_name=name, mime_type="image/png", inhalt=_PNG)


# ---------------------------------------------------------------- Workflow

def test_workflow_einreichen_freigeben(db):
    from app.models.rechnung import STATUS_EINGEREICHT, STATUS_FREIGEGEBEN

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_ein", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    leiter = _user(db, "rtester_al",
                   abteilung_perms=(("rechnungen.freigeben", fussball),))

    r = _rechnung(db, einreicher, fussball, beschreibung="Bälle")
    assert r.status == "entwurf"

    _beleg(db, r.id, einreicher)
    r = db.rechnungen.einreichen(r.id, einreicher)
    assert r.status == STATUS_EINGEREICHT
    assert r.eingereicht_von == "rtester_ein"

    r = db.rechnungen.freigeben(r.id, leiter)
    assert r.status == STATUS_FREIGEGEBEN
    assert r.freigegeben_von == "rtester_al"


def test_einreichen_ohne_beleg_scheitert(db):
    from app.services.rechnung_service import BelegFehltError

    einreicher = _user(db, "rtester_nobel", perms=("rechnungen.einreichen",))
    r = _rechnung(db, einreicher)
    with pytest.raises(BelegFehltError):
        db.rechnungen.einreichen(r.id, einreicher)
    assert db.rechnungen.get(r.id, einreicher).status == "entwurf"


def test_erstattung_setzt_einreicher_als_empfaenger(db):
    """Der Regelfall „ich habe ausgelegt" braucht keine Empfängereingabe – das
    Backend löst das Mitglied aus dem Einreicher auf, die IBAN kommt aus dem Stamm."""
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_erst", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    with db.cursor() as cur:
        cur.execute("UPDATE mitglied SET iban='DE02120300000000202051' "
                    "WHERE user_id=%s", (einreicher.id,))

    r = _rechnung(db, einreicher, fussball, empfaenger_typ="mitglied")
    assert r.empfaenger_mitglied_id is not None
    geladen = db.rechnungen.get(r.id, einreicher)
    assert geladen.empfaenger_mitglied_name == "RechTest rtester_erst"
    assert geladen.empfaenger_mitglied_iban == "DE02120300000000202051"


def test_einreichen_ohne_empfaenger_scheitert(db):
    """Ohne Zahlungsempfänger kann niemand eine Zahlung freigeben."""
    from app.services.rechnung_service import EmpfaengerFehltError

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_ohne", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    r = _rechnung(db, einreicher, fussball, empfaenger_typ=None)
    _beleg(db, r.id, einreicher)
    with pytest.raises(EmpfaengerFehltError):
        db.rechnungen.einreichen(r.id, einreicher)


def test_einreichen_extern_braucht_keinen_namen(db):
    """Verlangt wird nur die Entscheidung. Name und Bankverbindung des
    Ausstellers stehen auf dem Beleg und werden (noch) nicht erfasst."""
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_extl", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    r = _rechnung(db, einreicher, fussball, empfaenger_typ="extern")
    _beleg(db, r.id, einreicher)

    eingereicht = db.rechnungen.einreichen(r.id, einreicher)
    assert eingereicht.status == "eingereicht"
    assert eingereicht.empfaenger_typ == "extern"


def test_externer_empfaenger_bleibt_ohne_mitglied(db):
    """Bei „an den Aussteller" darf kein Mitglied als Empfänger einwandern –
    sonst zeigte die Freigabe eine Erstattung an, die es nicht gibt."""
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_ext2", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    r = _rechnung(db, einreicher, fussball, empfaenger_typ="extern")
    assert r.empfaenger_mitglied_id is None

    # Die Felder bleiben für später erhalten – wer sie über die API mitgibt,
    # bekommt sie auch gespeichert.
    mit_namen = _rechnung(db, einreicher, fussball, empfaenger_typ="extern",
                          empfaenger_name="Getränke Meier",
                          empfaenger_iban="DE89370400440532013000")
    assert mit_namen.empfaenger_name == "Getränke Meier"


def test_verwaltung_reicht_fuer_anderes_mitglied_ein(db):
    """Ticket #134: Die Geschäftsstelle nimmt Belege auch für Mitglieder ohne
    App-Zugang an – dann geht das Geld an dieses Mitglied, nicht an den Erfasser."""
    fussball = _abteilung(db, "R-Fussball")
    gs = _user(db, "rtester_gs134", perms=("rechnungen.verwalten",))
    mitglied = _user(db, "rtester_fuer", perms=("rechnungen.einreichen",),
                     abteilungen=(fussball,))
    mid = _mitglied_id(db, mitglied)
    with db.cursor() as cur:
        cur.execute("UPDATE mitglied SET iban='DE02120300000000202051' WHERE id=%s", (mid,))

    r = _rechnung(db, gs, fussball, empfaenger_typ="mitglied",
                  empfaenger_mitglied_id=mid)
    assert r.empfaenger_mitglied_id == mid
    assert r.empfaenger_mitglied_name == "RechTest rtester_fuer"
    # Die Bankverbindung kommt aus dem Mitgliedsstamm des Empfängers,
    # nicht aus dem des Erfassers.
    assert r.empfaenger_mitglied_iban == "DE02120300000000202051"

    _beleg(db, r.id, gs)
    eingereicht = db.rechnungen.einreichen(r.id, gs)
    assert eingereicht.status == "eingereicht"
    # Erfasst hat die Geschäftsstelle – die Rechnung bleibt ihr Vorgang.
    assert eingereicht.ersteller_user_id == gs.id


def test_einreicher_darf_kein_fremdes_mitglied_eintragen(db):
    """Sonst wäre es der kurze Weg, eine fremde Bankverbindung an die eigene
    Rechnung zu hängen."""
    from app.services.rechnung_service import KeinZugriffError

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e134", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    anderer = _user(db, "rtester_a134", perms=("rechnungen.einreichen",))
    fremd = _mitglied_id(db, anderer)

    with pytest.raises(KeinZugriffError):
        _rechnung(db, einreicher, fussball, empfaenger_mitglied_id=fremd)

    # ... auch nicht nachträglich an einer bereits angelegten Rechnung
    r = _rechnung(db, einreicher, fussball)
    assert r.empfaenger_mitglied_id == _mitglied_id(db, einreicher)
    with pytest.raises(KeinZugriffError):
        db.rechnungen.aktualisieren(r.id, einreicher, expected_version=r.version,
                                    empfaenger_mitglied_id=fremd)


def test_verwaltung_bekommt_keinen_empfaenger_untergeschoben(db):
    """Wer wählen darf, bekommt nichts vorbelegt – auch sich selbst nicht.

    Ein übersehener Vorschlag hieße hier: Auszahlung an den Erfasser. Die Lücke
    fällt stattdessen beim Einreichen auf.
    """
    from app.services.rechnung_service import EmpfaengerFehltError

    fussball = _abteilung(db, "R-Fussball")
    gs = _user(db, "rtester_gs135", perms=("rechnungen.verwalten",))
    r = _rechnung(db, gs, fussball, empfaenger_typ="mitglied")
    assert r.empfaenger_mitglied_id is None          # Entwurf darf lückenhaft sein
    _beleg(db, r.id, gs)

    with pytest.raises(EmpfaengerFehltError):
        db.rechnungen.einreichen(r.id, gs)

    # Die eigene Auslage geht weiter – die Geschäftsstelle wählt sich selbst.
    eigenes = _mitglied_id(db, gs)
    r = db.rechnungen.aktualisieren(r.id, gs, expected_version=r.version,
                                    empfaenger_mitglied_id=eigenes)
    assert db.rechnungen.einreichen(r.id, gs).empfaenger_mitglied_id == eigenes


def test_unbekanntes_empfaengermitglied_wird_abgewiesen(db):
    fussball = _abteilung(db, "R-Fussball")
    gs = _user(db, "rtester_gs136", perms=("rechnungen.verwalten",))
    with pytest.raises(ValueError):
        _rechnung(db, gs, fussball, empfaenger_mitglied_id=99_999_999)


def test_empfaengerliste_nur_fuer_die_verwaltung(db):
    """Die Liste hängt am Verwaltungsrecht und soll kein zweiter Weg in den
    Personenstamm sein – darum schlank und für Einreicher gesperrt."""
    from app.services.rechnung_service import KeinZugriffError

    gs = _user(db, "rtester_gs137", perms=("rechnungen.verwalten",))
    einreicher = _user(db, "rtester_e137", perms=("rechnungen.einreichen",))
    mid = _mitglied_id(db, einreicher)
    with db.cursor() as cur:
        cur.execute("UPDATE mitglied SET iban='DE02120300000000202051' WHERE id=%s", (mid,))

    liste = db.rechnungen.empfaenger_mitglieder(gs)
    treffer = next(x for x in liste if x["id"] == mid)
    assert treffer["name"] == "RechTest rtester_e137"
    assert treffer["hat_iban"] is True
    # Ohne Bankverbindung kann die Geschäftsstelle nicht erstatten – das muss
    # sie vor der Auswahl sehen.
    assert any(x["hat_iban"] is False for x in liste)
    assert set(treffer) == {"id", "name", "mitgliedsnummer", "hat_iban"}

    with pytest.raises(KeinZugriffError):
        db.rechnungen.empfaenger_mitglieder(einreicher)


def test_einreichen_ohne_betrag_scheitert(db):
    """Der Freigeber entscheidet über eine Summe – die muss beim Einreichen dastehen.

    Der Entwurf selbst darf noch ohne Betrag existieren: erst der Statuswechsel
    verlangt ihn.
    """
    from app.services.rechnung_service import BetragFehltError

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_nobtr", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    r = _rechnung(db, einreicher, fussball, betrag_cent=None)
    assert r.status == "entwurf"                       # Anlegen bleibt erlaubt
    _beleg(db, r.id, einreicher)

    with pytest.raises(BetragFehltError):
        db.rechnungen.einreichen(r.id, einreicher)
    assert db.rechnungen.get(r.id, einreicher).status == "entwurf"

    r = db.rechnungen.aktualisieren(r.id, einreicher, expected_version=r.version,
                                    betrag_cent=4250)
    assert db.rechnungen.einreichen(r.id, einreicher).status == "eingereicht"


def test_betrag_null_oder_negativ_wird_abgewiesen(db):
    """0,00 € wäre der naheliegende Weg, die Betragspflicht zu umgehen."""
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_btr0", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    with pytest.raises(ValueError):
        _rechnung(db, einreicher, fussball, betrag_cent=0)
    with pytest.raises(ValueError):
        _rechnung(db, einreicher, fussball, betrag_cent=-500)

    r = _rechnung(db, einreicher, fussball)
    with pytest.raises(ValueError):
        db.rechnungen.aktualisieren(r.id, einreicher, expected_version=r.version,
                                    betrag_cent=0)


def test_freigeben_aus_entwurf_scheitert(db):
    """Der Übergang scheitert an der WHERE-Klausel, nicht erst an einer
    Service-Prüfung – sonst wäre er im Wettlauf zweier Freigeber offen.

    Bewusst direkt am Repository: über den Service käme ein Entwurf gar nicht
    erst bis hierher (fremde Entwürfe sind unsichtbar, siehe
    test_freigabe_sicht_zeigt_keine_fremden_entwuerfe).
    """
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e2", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    r = _rechnung(db, einreicher, fussball)

    assert db.rechnung_repository.freigeben(r.id, freigegeben_von="wer_auch_immer") is False
    assert db.rechnungen.get(r.id, einreicher).status == "entwurf"


def test_doppelte_freigabe_scheitert(db):
    from app.services.rechnung_service import FalscherStatusError

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e3", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    leiter = _user(db, "rtester_al3",
                   abteilung_perms=(("rechnungen.freigeben", fussball),))
    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)
    db.rechnungen.freigeben(r.id, leiter)
    with pytest.raises(FalscherStatusError):
        db.rechnungen.freigeben(r.id, leiter)


def test_ablehnen_mit_grund_und_zuruecksetzen(db):
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e4", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    leiter = _user(db, "rtester_al4",
                   abteilung_perms=(("rechnungen.freigeben", fussball),))
    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)

    r = db.rechnungen.ablehnen(r.id, leiter, "Beleg unleserlich")
    assert r.status == "abgelehnt"
    assert r.abgelehnt_grund == "Beleg unleserlich"

    # Abgelehnt → zurück in den Entwurf, damit der Einreicher nacharbeiten kann.
    r = db.rechnungen.zuruecksetzen(r.id, leiter)
    assert r.status == "entwurf"
    assert r.abgelehnt_grund is None


def test_zuruecksetzen_nach_freigabe_geht_auf_eingereicht(db):
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e5", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    leiter = _user(db, "rtester_al5",
                   abteilung_perms=(("rechnungen.freigeben", fussball),))
    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)
    db.rechnungen.freigeben(r.id, leiter)

    r = db.rechnungen.zuruecksetzen(r.id, leiter)
    assert r.status == "eingereicht"
    assert r.freigegeben_am is None
    assert r.eingereicht_am is not None      # Einreichung bleibt bestehen


def test_ablehnen_nach_versehentlicher_freigabe(db):
    """Eine versehentliche Freigabe muss sich in einem Schritt korrigieren lassen.

    Die Freigabe-Spuren verschwinden dabei – „abgelehnt, freigegeben von X" wäre
    ein Widerspruch. In der History steht der Vorgang weiter.
    """
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e5b", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    leiter = _user(db, "rtester_al5b",
                   abteilung_perms=(("rechnungen.freigeben", fussball),))
    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)
    r = db.rechnungen.freigeben(r.id, leiter)
    assert r.freigegeben_von == "rtester_al5b"

    r = db.rechnungen.ablehnen(r.id, leiter, "doch nicht, falscher Beleg")
    assert r.status == "abgelehnt"
    assert r.abgelehnt_grund == "doch nicht, falscher Beleg"
    assert r.freigegeben_am is None and r.freigegeben_von is None

    verlauf = [h["status"] for h in db.rechnung_repository.get_history(r.id)]
    assert "freigegeben" in verlauf


# ------------------------------------------------------------ Abteilungs-Scope

def test_fremde_abteilung_darf_nicht_freigeben(db):
    """Kern der Freigabe-Logik: der Scope wird STRICT geprüft.

    Der Handball-Leiter scheitert schon an der Sichtbarkeit – wer eine Rechnung
    nicht sehen darf, soll sie auch nicht entscheiden können. Beide Fehler
    liefern der API ein 403.
    """
    from app.services.rechnung_service import KeinZugriffError

    fussball = _abteilung(db, "R-Fussball")
    handball = _abteilung(db, "R-Handball")
    einreicher = _user(db, "rtester_e6", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    hb_leiter = _user(db, "rtester_hb",
                      abteilung_perms=(("rechnungen.freigeben", handball),))

    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)

    # lenient hätte er das Recht – für DIESE Abteilung aber nicht
    assert hb_leiter.has_permission("rechnungen.freigeben")
    assert not db.rechnungen.darf_freigeben(hb_leiter, fussball)
    with pytest.raises(KeinZugriffError):
        db.rechnungen.freigeben(r.id, hb_leiter)


def test_fremde_abteilung_sieht_rechnung_nicht(db):
    fussball = _abteilung(db, "R-Fussball")
    handball = _abteilung(db, "R-Handball")
    einreicher = _user(db, "rtester_e7", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    hb_leiter = _user(db, "rtester_hb2",
                      abteilung_perms=(("rechnungen.freigeben", handball),))
    fb_leiter = _user(db, "rtester_fb2",
                      abteilung_perms=(("rechnungen.freigeben", fussball),))

    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)

    assert [x.id for x in db.rechnungen.list_zur_freigabe(hb_leiter)] == []
    assert [x.id for x in db.rechnungen.list_zur_freigabe(fb_leiter)] == [r.id]


def test_freigabe_sicht_zeigt_keine_fremden_entwuerfe(db):
    """Bis zum Einreichen ist die Rechnung die Werkbank des Einreichers."""
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e12", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    leiter = _user(db, "rtester_al8",
                   abteilung_perms=(("rechnungen.freigeben", fussball),))
    gs = _user(db, "rtester_gs3", perms=("rechnungen.verwalten",))

    entwurf = _rechnung(db, einreicher, fussball)
    eingereicht = _rechnung(db, einreicher, fussball)
    _beleg(db, eingereicht.id, einreicher)
    db.rechnungen.einreichen(eingereicht.id, einreicher)

    # ohne Statusfilter („Alle") darf der Entwurf nicht auftauchen
    for user in (leiter, gs):
        ids = [x.id for x in db.rechnungen.list_zur_freigabe(user)]
        assert entwurf.id not in ids
        assert eingereicht.id in ids

    # explizit nach Entwürfen zu filtern liefert nichts
    assert db.rechnungen.list_zur_freigabe(leiter, "entwurf") == []
    # der Einreicher sieht seinen Entwurf weiterhin unter „Meine Rechnungen"
    assert entwurf.id in [x.id for x in db.rechnungen.list_meine(einreicher)]

    # ... und auch der Direktzugriff auf die Detail-URL bleibt zu, sonst wäre
    # das Ausblenden in der Liste nur Kosmetik
    from app.services.rechnung_service import KeinZugriffError
    with pytest.raises(KeinZugriffError):
        db.rechnungen.get(entwurf.id, leiter)
    assert db.rechnungen.get(eingereicht.id, leiter).id == eingereicht.id
    # die Geschäftsstelle behält den vollen Blick (Domänen-Verwaltung)
    assert db.rechnungen.get(entwurf.id, gs).id == entwurf.id


def test_vereinsrechnung_nur_fuer_verwaltung(db):
    """Ohne Abteilung greift kein Abteilungs-Scope – nur die Geschäftsstelle."""
    from app.services.rechnung_service import KeinZugriffError

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e8", perms=("rechnungen.einreichen",))
    fb_leiter = _user(db, "rtester_fb3",
                      abteilung_perms=(("rechnungen.freigeben", fussball),))
    verwaltung = _user(db, "rtester_gs", perms=("rechnungen.verwalten",))

    r = _rechnung(db, einreicher, None)          # Vereinsrechnung
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)

    assert not db.rechnungen.darf_freigeben(fb_leiter, None)
    with pytest.raises(KeinZugriffError):
        db.rechnungen.freigeben(r.id, fb_leiter)

    assert db.rechnungen.freigeben(r.id, verwaltung).status == "freigegeben"


def test_einreicher_sieht_eigene_rechnung_immer(db):
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e9", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    r = _rechnung(db, einreicher, fussball)
    assert [x.id for x in db.rechnungen.list_meine(einreicher)] == [r.id]
    assert db.rechnungen.get(r.id, einreicher).id == r.id


def test_fremder_ohne_rechte_sieht_nichts(db):
    from app.services.rechnung_service import KeinZugriffError

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_e10", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    fremder = _user(db, "rtester_frem", perms=("rechnungen.einreichen",))
    r = _rechnung(db, einreicher, fussball)
    with pytest.raises(KeinZugriffError):
        db.rechnungen.get(r.id, fremder)


def test_einreichen_in_fremde_abteilung_scheitert(db):
    """Sonst könnte man die Rechnung an ihrem eigentlichen Freigeber vorbeischieben."""
    from app.services.rechnung_service import KeinZugriffError

    fussball = _abteilung(db, "R-Fussball")
    handball = _abteilung(db, "R-Handball")
    einreicher = _user(db, "rtester_e11", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    with pytest.raises(KeinZugriffError):
        _rechnung(db, einreicher, handball)


# ------------------------------------------------------- Abteilungs-Vorbelegung

def test_abteilungen_aus_mitgliedschaft_und_funktion(db):
    fussball = _abteilung(db, "R-Fussball")
    handball = _abteilung(db, "R-Handball")
    user = _user(db, "rtester_vor", perms=("rechnungen.einreichen",),
                 abteilungen=(fussball,),
                 funktionen=(("abteilungsleiter", handball),))
    ids = {a["id"] for a in db.rechnungen.abteilungen_fuer_user(user)}
    assert ids == {fussball, handball}


def test_abteilungen_leer_ohne_zuordnung(db):
    user = _user(db, "rtester_leer", perms=("rechnungen.einreichen",))
    assert db.rechnungen.abteilungen_fuer_user(user) == []


def test_verwaltung_darf_jede_abteilung(db):
    fussball = _abteilung(db, "R-Fussball")
    handball = _abteilung(db, "R-Handball")
    gs = _user(db, "rtester_gs2", perms=("rechnungen.verwalten",))
    ids = {a["id"] for a in db.rechnungen.abteilungen_fuer_user(gs)}
    assert {fussball, handball} <= ids


# ------------------------------------------------------------------- Löschen

def test_loeschen_nur_im_entwurf(db):
    from app.services.rechnung_service import FalscherStatusError

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_del", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)

    with pytest.raises(FalscherStatusError):
        db.rechnungen.loeschen(r.id, einreicher)

    # Zurück in den Entwurf → löschbar (Soft-Delete, Zeile bleibt bestehen)
    leiter = _user(db, "rtester_al6",
                   abteilung_perms=(("rechnungen.freigeben", fussball),))
    db.rechnungen.ablehnen(r.id, leiter, "nö")
    db.rechnungen.zuruecksetzen(r.id, leiter)
    db.rechnungen.loeschen(r.id, einreicher)

    assert db.rechnungen.list_meine(einreicher) == []
    with db.cursor() as cur:
        cur.execute("SELECT deleted_at FROM rechnung WHERE id=%s", (r.id,))
        assert cur.fetchone()["deleted_at"] is not None     # soft, nicht hart


def test_beleg_upload_nur_im_entwurf(db):
    from app.services.rechnung_service import KeinZugriffError

    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_bel", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)
    with pytest.raises(KeinZugriffError):
        _beleg(db, r.id, einreicher, name="zweiter.png")


def test_history_wird_geschrieben(db):
    """Jeder version-Bump landet per Audit-Trigger in rechnung_history."""
    fussball = _abteilung(db, "R-Fussball")
    einreicher = _user(db, "rtester_hist", perms=("rechnungen.einreichen",),
                       abteilungen=(fussball,))
    leiter = _user(db, "rtester_al7",
                   abteilung_perms=(("rechnungen.freigeben", fussball),))
    r = _rechnung(db, einreicher, fussball)
    _beleg(db, r.id, einreicher)
    db.rechnungen.einreichen(r.id, einreicher)
    db.rechnungen.freigeben(r.id, leiter)

    verlauf = db.rechnung_repository.get_history(r.id)
    assert [h["status"] for h in verlauf] == ["freigegeben", "eingereicht", "entwurf"]
