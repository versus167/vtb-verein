"""Integrationstests der Teamkasse (#98, Schema v75) gegen echtes PostgreSQL.

Prüft die neuen Tabellen (History-Trigger, CHECK, partielle Unique-Indexe), die
Kader-Rechteableitung (aktiv am Stichtag, Rollen-Stufen), die Wart-ACL inkl.
Reaktivierung sowie die Ledger-Semantik des korrigierten Modells: Preis-Snapshot,
Mitglieds-Verkäufer als Nullsummen-Paar (konsum/verkauf), Zahlung als Paar,
Einkauf ans Team, automatischer Beitragslauf (Monatsfenster, Befreiung,
storniert = erlassen), Sammlungen/Events (#181: Teilnehmerkreis, Idempotenz,
Storno) und Team-Saldo = −Σ Mitgliedssalden.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine (leere) Wegwerf-DB zeigt –
VereinsDB legt das Schema beim Connect an (Muster wie test_termine_integration).
"""
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
MONAT = date.today().strftime('%Y-%m')


def _vormonat(monat: str) -> str:
    jahr, m = int(monat[:4]), int(monat[5:7])
    return f"{jahr - 1}-12" if m == 1 else f"{jahr:04d}-{m - 1:02d}"


def _naechster(monat: str) -> str:
    jahr, m = int(monat[:4]), int(monat[5:7])
    return f"{jahr + 1}-01" if m == 12 else f"{jahr:04d}-{m + 1:02d}"


NAECHSTER_MONAT = _naechster(MONAT)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-clubdeckel-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    def _wipe():
        with db.cursor() as cur:
            cur.execute(
                "TRUNCATE clubdeckel_buchung, clubdeckel_buchung_history, "
                "clubdeckel_artikel, clubdeckel_artikel_history, "
                "clubdeckel_gruppe, clubdeckel_gruppe_history, "
                "clubdeckel_beitrag_befreiung, clubdeckel_beitrag_befreiung_history, "
                "clubdeckel_event, clubdeckel_event_history, "
                "clubdeckel_event_opt_out, clubdeckel_event_opt_out_history, "
                "clubdeckel_berechtigung, clubdeckel_berechtigung_history, "
                "clubdeckel, clubdeckel_history, "
                # Termine hängen seit v97 an den Buchungen (#167). Das CASCADE
                # über mannschaft räumt zwar termine mit ab, nicht aber deren
                # History – die kollidierte sonst nach RESTART IDENTITY mit der
                # wiederverwendeten id.
                "termine, termine_history, "
                "mitglied_mannschaft, mitglied_mannschaft_history, "
                "mannschaft, mannschaft_history RESTART IDENTITY CASCADE"
            )
            cur.execute("DELETE FROM mitglied_history WHERE nachname='Deckeltest'")
            cur.execute("DELETE FROM mitglied WHERE nachname='Deckeltest'")
            cur.execute("DELETE FROM users WHERE username LIKE 'deckeltester%'")
            cur.execute("DELETE FROM abteilung WHERE name='Deckel-Abt'")
    _wipe()
    yield
    _wipe()


def _make_mannschaft(db, name="Erste"):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM abteilung WHERE name='Deckel-Abt' AND deleted_at IS NULL")
        row = cur.fetchone()
        if row:
            aid = row['id']
        else:
            cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                        "VALUES ('Deckel-Abt','t','t') RETURNING id")
            aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,%s,'2026/27','t','t') RETURNING id", (aid, name))
        return cur.fetchone()['id']


def _make_kader_user(db, mannschaft_id, rolle, vorname, von=LASTWEEK, bis=None):
    """User + Mitglied + Kader-Zuordnung; gibt (user_id, mitglied_id)."""
    username = f"deckeltester_{vorname.lower()}"
    with db.cursor() as cur:
        cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                    "VALUES (%s,%s,'x','mitglied',1,'t','t') RETURNING id",
                    (username, f"{username}@x.de"))
        uid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
                    "VALUES (%s,'Deckeltest','sonstiges',%s,'t','t') RETURNING id",
                    (vorname, uid))
        mid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,bis,created_by,updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,'t','t')", (mid, mannschaft_id, rolle, von, bis))
    return uid, mid


def _team_saldo(db, deckel_id):
    return -sum((s['saldo'] for s in db.clubdeckel_buchungen.salden(deckel_id)),
                Decimal('0'))


# ----------------------------------------------------------- Rechteableitung
def test_kader_stufen_und_stichtag(db):
    man = _make_mannschaft(db)
    spieler_uid, _ = _make_kader_user(db, man, 'spieler', 'Anna')
    ul_uid, _ = _make_kader_user(db, man, 'uebungsleiter', 'Bernd')
    betreuer_uid, _ = _make_kader_user(db, man, 'betreuer', 'Clara')
    ex_uid, _ = _make_kader_user(db, man, 'spieler', 'Doro', bis=YESTERDAY)
    zukunft_uid, _ = _make_kader_user(db, man, 'spieler', 'Emil', von=TOMORROW)

    assert db.clubdeckel.get_access_for_user(spieler_uid, man) == 'mitglied'
    assert db.clubdeckel.get_access_for_user(ul_uid, man) == 'verwalten'
    assert db.clubdeckel.get_access_for_user(betreuer_uid, man) == 'verwalten'
    assert db.clubdeckel.get_access_for_user(ex_uid, man) is None
    assert db.clubdeckel.get_access_for_user(zukunft_uid, man) is None
    assert db.clubdeckel.get_access_for_user(spieler_uid, man + 999) is None


def test_list_teams_for_user_mit_deckel_und_ohne(db):
    man1 = _make_mannschaft(db, "Erste")
    man2 = _make_mannschaft(db, "Zweite")
    uid, _ = _make_kader_user(db, man1, 'uebungsleiter', 'Anna')
    with db.cursor() as cur:
        cur.execute("SELECT id FROM mitglied WHERE user_id=%s", (uid,))
        mid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,created_by,updated_by) "
                    "VALUES (%s,%s,'spieler',%s,'t','t')", (mid, man2, LASTWEEK))
    db.clubdeckel.create(man1, "Teamkasse Erste", 't')

    teams = {t['mannschaft_id']: t for t in db.clubdeckel.list_teams_for_user(uid)}
    assert teams[man1]['zugriff'] == 'verwalten'
    assert teams[man1]['deckel']['name'] == 'Teamkasse Erste'
    assert teams[man2]['zugriff'] == 'mitglied'
    assert teams[man2]['deckel'] is None


# ------------------------------------------------------------- Schema/Unique
def test_ein_deckel_pro_mannschaft_und_neuanlage_nach_softdelete(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.clubdeckel.create(man, "Zweiter", 't')
    # Nach Soft-Delete ist die Mannschaft wieder frei (partieller Index)
    assert db.clubdeckel.mark_deleted(deckel.id, 't')
    neu = db.clubdeckel.create(man, "Neuer", 't')
    assert neu.id != deckel.id


def test_stammdaten_update_fuehrt_beitrag_ab(db):
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')

    # Beitrag setzen -> beitrag_ab = Folgemonat (nie im laufenden Monat)
    assert db.clubdeckel.update(deckel.id, "Teamkasse", 1, Decimal('5.00'),
                                mid, 'DE12', None, 'paypal.me/x', 't', deckel.version)
    d2 = db.clubdeckel.get(deckel.id)
    assert d2.beitrag == Decimal('5.00')
    assert d2.beitrag_ab == NAECHSTER_MONAT
    assert d2.zahlungsempfaenger_name == 'Anna Deckeltest'
    # Beitrag entfernen -> beitrag_ab leer
    assert db.clubdeckel.update(deckel.id, "Teamkasse", 1, None, None,
                                None, None, None, 't', d2.version)
    d3 = db.clubdeckel.get(deckel.id)
    assert d3.beitrag is None and d3.beitrag_ab is None
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM clubdeckel_history WHERE id=%s", (deckel.id,))
        assert cur.fetchone()['n'] == 3


def test_buchung_typ_check(db):
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_buchung (deckel_id,mitglied_id,typ,betrag,created_by,updated_by) "
                "VALUES (%s,%s,'quatsch',1,'t','t')", (deckel.id, mid))


# ----------------------------------------------------------------- Wart-ACL
def test_wart_setzen_revoken_reaktivieren(db):
    man = _make_mannschaft(db)
    uid, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')

    assert not db.clubdeckel_berechtigungen.ist_wart_user(deckel.id, uid)
    db.clubdeckel_berechtigungen.set_wart(deckel.id, mid, 't')
    assert db.clubdeckel_berechtigungen.ist_wart_user(deckel.id, uid)
    db.clubdeckel_berechtigungen.set_wart(deckel.id, mid, 't')  # idempotent

    assert db.clubdeckel_berechtigungen.revoke(deckel.id, mid, 't')
    assert not db.clubdeckel_berechtigungen.ist_wart(deckel.id, mid)

    # Erneut ernennen reaktiviert die Zeile statt (Unique!) neu einzufügen
    db.clubdeckel_berechtigungen.set_wart(deckel.id, mid, 't')
    assert db.clubdeckel_berechtigungen.ist_wart(deckel.id, mid)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM clubdeckel_berechtigung "
                    "WHERE deckel_id=%s AND mitglied_id=%s", (deckel.id, mid))
        assert cur.fetchone()['n'] == 1


# ------------------------------------------------------------------- Ledger
def test_team_verkauf_preis_snapshot_und_team_saldo(db):
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                        Decimal('1.50'), 1, 0, 't')

    db.clubdeckel_buchungen.create_konsum(deckel.id, mid, bier.id, bier.name, 2,
                                          bier.preis, None, 't')
    # Preiserhöhung wirkt nur auf neue Buchungen (Snapshot im Betrag)
    assert db.clubdeckel_artikel.update(bier.id, gruppe.id, "Bier", Decimal('2.00'),
                                        1, 0, 't', bier.version)
    neu = db.clubdeckel_artikel.get(bier.id)
    db.clubdeckel_buchungen.create_konsum(deckel.id, mid, neu.id, neu.name, 1,
                                          neu.preis, None, 't')

    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mid) == Decimal('-5.00')
    # Team-Verkauf: Erlös liegt beim Team (= Gegensumme der Mitglieder)
    assert _team_saldo(db, deckel.id) == Decimal('5.00')


def test_mitglieds_verkaeufer_erzeugt_nullsummen_paar(db):
    man = _make_mannschaft(db)
    _, kaeufer = _make_kader_user(db, man, 'spieler', 'Anna')
    _, trompete = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Essen", trompete, 1, 0, 't')
    roster = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Roster",
                                          Decimal('2.50'), 1, 0, 't')

    b = db.clubdeckel_buchungen.create_konsum(
        deckel.id, kaeufer, roster.id, roster.name, 2, roster.preis,
        gruppe.verkaeufer_mitglied_id, 't')
    assert b.paar_ref is not None
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, kaeufer) == Decimal('-5.00')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, trompete) == Decimal('5.00')
    # Nullsumme: das Team ist an Mitglieds-Verkäufen nicht beteiligt
    assert _team_saldo(db, deckel.id) == Decimal('0')

    # Storno einer Paar-Zeile löscht beide (Verkäufer-Gutschrift fällt mit weg)
    assert db.clubdeckel_buchungen.storno(b.id, 't')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, trompete) == Decimal('0')


def test_bezeichnung_und_gegenkonto_bleiben_eingefroren(db):
    """Kernzusage: Bezeichnung UND Gegenkonto sind Snapshots auf der Buchungs-
    zeile — sie überleben Umbenennung und Soft-Delete des Artikels, weil
    list_for_deckel sie direkt aus der Zeile liest (kein Live-Katalog-JOIN)."""
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                        Decimal('1.50'), 1, 0, 't')
    db.clubdeckel_buchungen.create_konsum(deckel.id, mid, bier.id, bier.name, 2,
                                          bier.preis, None, 't')

    # Artikel umbenennen UND soft-löschen — die Altbuchung darf sich nicht ändern
    assert db.clubdeckel_artikel.update(bier.id, gruppe.id, "Pils", Decimal('9.99'),
                                        1, 0, 't', bier.version)
    assert db.clubdeckel_artikel.mark_deleted(bier.id, 't')

    (b,) = db.clubdeckel_buchungen.list_for_deckel(deckel.id)
    assert b.artikel_name == "Bier"          # nicht "Pils"
    assert b.gegen_name == "Team"
    assert b.betrag == Decimal('-3.00')      # 2 × 1,50, Preis eingefroren


def test_gegen_name_snapshot_je_buchungstyp(db):
    """Für jeden Buchungstyp wird das richtige Gegenkonto (Team bzw. der
    tatsächliche Mitgliedsname) eingefroren."""
    man = _make_mannschaft(db)
    _, a = _make_kader_user(db, man, 'spieler', 'Anna')
    _, brd = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gr = db.clubdeckel_gruppen.create(deckel.id, "Essen", brd, 1, 0, 't')
    roster = db.clubdeckel_artikel.create(deckel.id, gr.id, "Roster",
                                          Decimal('2.00'), 1, 0, 't')
    # Anna kauft über Verkäufer Bernd; danach Team-Einkauf, An-/Verkauf, Zahlung
    db.clubdeckel_buchungen.create_konsum(deckel.id, a, roster.id, roster.name, 1,
                                          roster.preis, brd, 't')
    db.clubdeckel_buchungen.create_einkauf(deckel.id, a, Decimal('5.00'), 'Kasten', 't')
    db.clubdeckel_buchungen.create_an_verkauf(deckel.id, a, None, False,
                                              Decimal('1.00'), None, 't')
    paar = db.clubdeckel_buchungen.create_an_verkauf(deckel.id, a, brd, False,
                                                     Decimal('1.00'), None, 't')
    db.clubdeckel_buchungen.create_zahlung(deckel.id, a, brd, Decimal('1.00'), None, 't')

    rows = db.clubdeckel_buchungen.list_for_deckel(deckel.id)

    def eine(**kw):
        treffer = [r for r in rows if all(getattr(r, k) == v for k, v in kw.items())]
        assert len(treffer) == 1, (kw, [(r.typ, r.mitglied_id, r.paar_ref,
                                         r.artikel_name, r.gegen_name) for r in rows])
        return treffer[0]

    # Mitglieds-Verkauf: Käufer sieht Verkäufer, Verkäufer sieht Käufer
    assert eine(typ='konsum', mitglied_id=a).gegen_name == 'Bernd Deckeltest'
    assert eine(typ='verkauf', artikel_name='Roster').gegen_name == 'Anna Deckeltest'
    # Team-Geschäfte tragen 'Team'
    assert eine(typ='einkauf', mitglied_id=a).gegen_name == 'Team'
    assert eine(typ='kauf', paar_ref=None).gegen_name == 'Team'
    # An-/Verkauf gegen Mitglied: Paar trägt beidseitig den Namen der Gegenseite
    assert eine(typ='kauf', paar_ref=paar).gegen_name == 'Bernd Deckeltest'
    assert eine(typ='verkauf', paar_ref=paar).gegen_name == 'Anna Deckeltest'
    # Zahlung: Zahler (+Betrag) sieht Empfänger, Empfänger (−Betrag) den Zahler
    zahl = [r for r in rows if r.typ == 'zahlung']
    zahler = next(r for r in zahl if r.betrag > 0)
    empf = next(r for r in zahl if r.betrag < 0)
    assert zahler.mitglied_id == a and zahler.gegen_name == 'Bernd Deckeltest'
    assert empf.mitglied_id == brd and empf.gegen_name == 'Anna Deckeltest'


def test_beispielkette_aus_dem_fachmodell(db):
    """Die Beispiele a)–d) aus der Modell-Abstimmung: Einkauf, Konsum, zwei
    Zahlungen — Salden A 20, B −10, C −20, Team 10."""
    man = _make_mannschaft(db)
    _, a = _make_kader_user(db, man, 'spieler', 'Anna')
    _, b = _make_kader_user(db, man, 'spieler', 'Bernd')
    _, c = _make_kader_user(db, man, 'spieler', 'Clara')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                        Decimal('2.00'), 1, 0, 't')

    # a) Team kauft von A einen Kasten (20 €) -> A +20, Team −20
    db.clubdeckel_buchungen.create_einkauf(deckel.id, a, Decimal('20.00'),
                                           'Kasten Bier', 't')
    assert _team_saldo(db, deckel.id) == Decimal('-20.00')
    # b) B kauft 15 Bier (30 €) -> B −30, Team +10
    db.clubdeckel_buchungen.create_konsum(deckel.id, b, bier.id, bier.name, 15,
                                          bier.preis, None, 't')
    assert _team_saldo(db, deckel.id) == Decimal('10.00')
    # c) B zahlt 20 € an C (Wart) -> B −10, C −20
    db.clubdeckel_buchungen.create_zahlung(deckel.id, b, c, Decimal('20.00'),
                                           None, 't')
    # d) B zahlt 10 € an A -> B 0, A +10... (Beispiel: nur Salden-Mechanik)
    salden = {s['mitglied_id']: s['saldo'] for s in db.clubdeckel_buchungen.salden(deckel.id)}
    assert salden[a] == Decimal('20.00')
    assert salden[b] == Decimal('-10.00')
    assert salden[c] == Decimal('-20.00')
    assert _team_saldo(db, deckel.id) == Decimal('10.00')

    db.clubdeckel_buchungen.create_zahlung(deckel.id, b, a, Decimal('10.00'), None, 't')
    salden = {s['mitglied_id']: s['saldo'] for s in db.clubdeckel_buchungen.salden(deckel.id)}
    assert salden[a] == Decimal('10.00')
    assert salden[b] == Decimal('0.00')
    assert _team_saldo(db, deckel.id) == Decimal('10.00')


def test_storno_und_restore_buchung(db):
    """#127: Storno = Soft-Delete (raus aus der Standard-Liste, Saldo zurück);
    mit_storniert zeigt die Zeile weiter, restore reaktiviert sie samt Saldo."""
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                        Decimal('1.50'), 1, 0, 't')
    b = db.clubdeckel_buchungen.create_konsum(deckel.id, mid, bier.id, bier.name, 2,
                                              bier.preis, None, 't')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mid) == Decimal('-3.00')

    assert db.clubdeckel_buchungen.storno(b.id, 't')
    assert db.clubdeckel_buchungen.list_for_deckel(deckel.id) == []
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mid) == Decimal('0')

    mit = db.clubdeckel_buchungen.list_for_deckel(deckel.id, mit_storniert=True)
    assert len(mit) == 1 and mit[0].deleted_at is not None

    assert db.clubdeckel_buchungen.restore(b.id, 't')
    (wieder,) = db.clubdeckel_buchungen.list_for_deckel(deckel.id)
    assert wieder.deleted_at is None
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mid) == Decimal('-3.00')
    # Nicht-stornierte Zeile lässt sich nicht „wiederherstellen"
    assert db.clubdeckel_buchungen.restore(b.id, 't') is False


def test_restore_paar_reaktiviert_beide_zeilen(db):
    """Restore einer Paar-Zeile stellt beide Zeilen wieder her (Nullsumme)."""
    man = _make_mannschaft(db)
    _, a = _make_kader_user(db, man, 'spieler', 'Anna')
    _, bernd = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    db.clubdeckel_buchungen.create_zahlung(deckel.id, a, bernd, Decimal('5.00'), None, 't')
    (row,) = [r for r in db.clubdeckel_buchungen.list_for_deckel(deckel.id)
              if r.mitglied_id == a]
    assert db.clubdeckel_buchungen.storno(row.id, 't')
    assert db.clubdeckel_buchungen.list_for_deckel(deckel.id) == []
    assert db.clubdeckel_buchungen.restore(row.id, 't')
    assert len(db.clubdeckel_buchungen.list_for_deckel(deckel.id)) == 2


def test_list_for_deckel_volltextsuche(db):
    """#129: suche filtert case-insensitiv über Name, Typ, Artikel-/Gegen-
    Snapshot, Notiz und Beitragsmonat — kombinierbar mit mitglied_id."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    _, bernd = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                        Decimal('1.50'), 1, 0, 't')
    db.clubdeckel_buchungen.create_konsum(deckel.id, anna, bier.id, bier.name, 1,
                                          bier.preis, None, 't')
    db.clubdeckel_buchungen.create_einkauf(deckel.id, bernd, Decimal('20.00'),
                                           'Kasten Bier geliefert', 't')
    db.clubdeckel_buchungen.create_zahlung(deckel.id, anna, bernd,
                                           Decimal('5.00'), 'bar', 't')

    B = db.clubdeckel_buchungen
    # Artikel-Snapshot + Notiz, case-insensitiv
    assert {b.typ for b in B.list_for_deckel(deckel.id, suche='bIeR')} == \
        {'konsum', 'einkauf'}
    # Mitgliedsname trifft eigene Zeilen UND Zeilen mit ihm als Gegenkonto
    assert len(B.list_for_deckel(deckel.id, suche='Anna')) == 3
    # Typ + Notiz ('zahlung', 'bar'), kombinierbar mit mitglied_id
    assert {b.mitglied_id for b in B.list_for_deckel(deckel.id, suche='zahlung')} == \
        {anna, bernd}
    assert [b.mitglied_id for b in B.list_for_deckel(
        deckel.id, mitglied_id=anna, suche='bar')] == [anna]
    # kein Treffer
    assert B.list_for_deckel(deckel.id, suche='gibtsnicht') == []


def test_salden_sortiert_nach_saldo_desc(db):
    """#127: höchstes Guthaben zuerst, größte Schuld zuletzt."""
    man = _make_mannschaft(db)
    _, a = _make_kader_user(db, man, 'spieler', 'Anna')
    _, bernd = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    db.clubdeckel_buchungen.create_einkauf(deckel.id, a, Decimal('20.00'), None, 't')  # A +20
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                        Decimal('2.00'), 1, 0, 't')
    db.clubdeckel_buchungen.create_konsum(deckel.id, bernd, bier.id, bier.name, 5,
                                          bier.preis, None, 't')                       # B −10
    salden = db.clubdeckel_buchungen.salden(deckel.id)
    assert [s['mitglied_id'] for s in salden] == [a, bernd]
    assert salden[0]['saldo'] == Decimal('20.00')
    assert salden[1]['saldo'] == Decimal('-10.00')


def test_an_verkauf_team_und_mitglied_paar(db):
    man = _make_mannschaft(db)
    _, a = _make_kader_user(db, man, 'spieler', 'Anna')
    _, b = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')

    # Gegen Team: kauft von (Belastung) und verkauft an (Gutschrift) je Einzelzeile
    db.clubdeckel_buchungen.create_an_verkauf(deckel.id, a, None, False,
                                              Decimal('6.00'), 'Kauf vom Team', 't')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, a) == Decimal('-6.00')
    assert _team_saldo(db, deckel.id) == Decimal('6.00')
    db.clubdeckel_buchungen.create_an_verkauf(deckel.id, a, None, True,
                                              Decimal('4.00'), 'Verkauf ans Team', 't')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, a) == Decimal('-2.00')

    # Gegen Mitglied: Anna kauft von Bernd 3€ -> Anna -3, Bernd +3, Team unberührt
    team_vorher = _team_saldo(db, deckel.id)
    ref = db.clubdeckel_buchungen.create_an_verkauf(deckel.id, a, b, False,
                                                    Decimal('3.00'), 'privat', 't')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, a) == Decimal('-5.00')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, b) == Decimal('3.00')
    assert _team_saldo(db, deckel.id) == team_vorher  # Paar ist nullsummig

    # Paar-Storno über eine Zeile nimmt beide zurück
    with db.cursor() as cur:
        cur.execute("SELECT id FROM clubdeckel_buchung WHERE paar_ref=%s "
                    "AND deleted_at IS NULL LIMIT 1", (ref,))
        eine = cur.fetchone()['id']
    assert db.clubdeckel_buchungen.storno(eine, 't')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, b) == Decimal('0')


def test_an_verkauf_mit_wertdatum(db):
    man = _make_mannschaft(db)
    _, a = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    db.clubdeckel_buchungen.create_an_verkauf(deckel.id, a, None, False,
                                              Decimal('2.00'), None, 't',
                                              wert_datum='2026-01-15T12:00')
    with db.cursor() as cur:
        cur.execute("SELECT created_at FROM clubdeckel_buchung WHERE deckel_id=%s "
                    "AND mitglied_id=%s AND typ='kauf'", (deckel.id, a))
        created = cur.fetchone()['created_at']
    assert created.year == 2026 and created.month == 1 and created.day == 15


def test_zahlung_paar_storno(db):
    man = _make_mannschaft(db)
    _, a = _make_kader_user(db, man, 'spieler', 'Anna')
    _, b = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')

    ref = db.clubdeckel_buchungen.create_zahlung(deckel.id, a, b, Decimal('7.50'),
                                                 'bar', 't')
    with db.cursor() as cur:
        cur.execute("SELECT id FROM clubdeckel_buchung WHERE paar_ref=%s "
                    "AND deleted_at IS NULL LIMIT 1", (ref,))
        eine_zeile = cur.fetchone()['id']
    assert db.clubdeckel_buchungen.storno(eine_zeile, 't')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, a) == Decimal('0')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, b) == Decimal('0')
    # Storno einer bereits stornierten Buchung: kein zweites Mal
    assert not db.clubdeckel_buchungen.storno(eine_zeile, 't')


# ------------------------------------------------------------------ Beitrag
def test_beitragslauf_monatsfenster_befreiung_und_erlass(db):
    # Deterministische Kader-Fenster: alle seit dem Ersten des Vormonats aktiv,
    # Doro schied zum Vormonatsende aus (zahlt nur den Vormonat).
    erster_aktuell = date.today().replace(day=1)
    vormonat_letzter = (erster_aktuell - timedelta(days=1)).isoformat()
    vormonat_erster = (erster_aktuell - timedelta(days=1)).replace(day=1).isoformat()

    man = _make_mannschaft(db)
    _, aktiv1 = _make_kader_user(db, man, 'spieler', 'Anna', von=vormonat_erster)
    _, aktiv2 = _make_kader_user(db, man, 'spieler', 'Bernd', von=vormonat_erster)
    _, befreit = _make_kader_user(db, man, 'spieler', 'Clara', von=vormonat_erster)
    _, ex = _make_kader_user(db, man, 'spieler', 'Doro', von=vormonat_erster,
                             bis=vormonat_letzter)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    db.clubdeckel_befreiungen.set_befreiung(deckel.id, befreit, 't')

    vormonat = _vormonat(MONAT)
    n = db.clubdeckel_buchungen.buche_faellige_beitraege(
        deckel.id, man, Decimal('5.00'), vormonat)
    # Anna+Bernd je 2 Monate, Doro nur den Vormonat, Clara befreit
    assert n == 5
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, aktiv1) == Decimal('-10.00')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, ex) == Decimal('-5.00')
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, befreit) == Decimal('0')

    # Idempotent: zweiter Lauf bucht nichts nach
    assert db.clubdeckel_buchungen.buche_faellige_beitraege(
        deckel.id, man, Decimal('5.00'), vormonat) == 0

    # Storno eines Beitrags = erlassen; der nächste Lauf bucht NICHT nach
    with db.cursor() as cur:
        cur.execute("SELECT id FROM clubdeckel_buchung WHERE deckel_id=%s "
                    "AND mitglied_id=%s AND typ='beitrag' AND beitrag_monat=%s",
                    (deckel.id, aktiv2, MONAT))
        beitrag_id = cur.fetchone()['id']
    assert db.clubdeckel_buchungen.storno(beitrag_id, 't')
    assert db.clubdeckel_buchungen.buche_faellige_beitraege(
        deckel.id, man, Decimal('5.00'), vormonat) == 0
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, aktiv2) == Decimal('-5.00')


def test_sammellauf_nur_aktive_deckel_mit_beitrag(db):
    """run_beitragslauf (Sidecar): bucht für aktive Deckel mit Beitrag, lässt
    beitraglose und ausgeschaltete Deckel aus und ist idempotent."""
    from app.services.clubdeckel_beitrag_service import run_beitragslauf

    erster_aktuell = date.today().replace(day=1)
    vormonat_erster = (erster_aktuell - timedelta(days=1)).replace(day=1).isoformat()

    man1 = _make_mannschaft(db, name="Mit-Beitrag")
    _make_kader_user(db, man1, 'spieler', 'Anna', von=vormonat_erster)
    _make_kader_user(db, man1, 'spieler', 'Bernd', von=vormonat_erster)
    d1 = db.clubdeckel.create(man1, "T1", 't')
    assert db.clubdeckel.update(d1.id, d1.name, 1, Decimal('5.00'),
                                None, None, None, None, 't', d1.version)
    # Beitrag greift ab Folgemonat; für diesen Lauf den laufenden Monat fällig stellen
    with db.cursor() as cur:
        cur.execute("UPDATE clubdeckel SET beitrag_ab=%s WHERE id=%s", (MONAT, d1.id))

    man2 = _make_mannschaft(db, name="Ohne-Beitrag")
    d2 = db.clubdeckel.create(man2, "T2", 't')                       # aktiv, kein Beitrag

    man3 = _make_mannschaft(db, name="Aus")
    d3 = db.clubdeckel.create(man3, "T3", 't')
    assert db.clubdeckel.update(d3.id, d3.name, 0, Decimal('5.00'),  # Beitrag, aber aus
                                None, None, None, None, 't', d3.version)

    res = run_beitragslauf(db)
    assert res == {d1.id: 2}                                         # nur d1, 2 Mitglieder
    assert d2.id not in res and d3.id not in res
    # Idempotent: zweiter Lauf bucht nichts nach
    assert run_beitragslauf(db) == {d1.id: 0}


def test_beitrag_startet_erst_naechsten_monat(db):
    """Neu gesetzter Beitrag startet am Folgemonat; der laufende Monat bleibt
    unbelastet, bis der Erste des Folgemonats erreicht ist."""
    man = _make_mannschaft(db)
    erster_aktuell = date.today().replace(day=1)
    vormonat_erster = (erster_aktuell - timedelta(days=1)).replace(day=1).isoformat()
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna', von=vormonat_erster)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')

    assert db.clubdeckel.update(deckel.id, "Teamkasse", 1, Decimal('5.00'),
                                None, None, None, None, 't', deckel.version)
    d = db.clubdeckel.get(deckel.id)
    assert d.beitrag_ab == NAECHSTER_MONAT
    # Lazy-Lauf im laufenden Monat bucht nichts (Startmonat liegt in der Zukunft)
    assert db.clubdeckel_buchungen.buche_faellige_beitraege(
        deckel.id, man, d.beitrag, d.beitrag_ab) == 0
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mid) == Decimal('0')


def test_beitragsaenderung_schliesst_laufenden_monat_alt_ab(db):
    """Betragsänderung: der laufende Monat wird noch zum ALTEN Satz gebucht
    (Flush im API-Update), der neue Satz greift erst ab dem Folgemonat."""
    from types import SimpleNamespace
    from backend.api import clubdeckel as api

    erster_aktuell = date.today().replace(day=1)
    vormonat_erster = (erster_aktuell - timedelta(days=1)).replace(day=1).isoformat()
    admin = SimpleNamespace(id=1, username='admin', role='admin',
                            has_permission=lambda p: True)

    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna', von=vormonat_erster)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    assert db.clubdeckel.update(deckel.id, "Teamkasse", 1, Decimal('5.00'),
                                None, None, None, None, 't', deckel.version)
    # Beitrag läuft bereits: laufenden Monat zum alten Satz fällig stellen
    with db.cursor() as cur:
        cur.execute("UPDATE clubdeckel SET beitrag_ab=%s WHERE id=%s", (MONAT, deckel.id))
    d = db.clubdeckel.get(deckel.id)

    # Betrag über die API ändern (5,00 -> 8,00)
    api.update_deckel(
        deckel.id,
        api.DeckelUpdate(name="Teamkasse", aktiv=True, beitrag=8.0,
                         expected_version=d.version),
        admin, db)

    d2 = db.clubdeckel.get(deckel.id)
    assert d2.beitrag == Decimal('8.00')
    assert d2.beitrag_ab == NAECHSTER_MONAT
    # Genau eine Beitragszeile für den laufenden Monat, noch zum alten Satz
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mid) == Decimal('-5.00')
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM clubdeckel_buchung "
                    "WHERE deckel_id=%s AND typ='beitrag'", (deckel.id,))
        assert cur.fetchone()['n'] == 1
    # Folgemonat-Start: erneuter Lauf bucht im laufenden Monat nichts nach
    assert db.clubdeckel_buchungen.buche_faellige_beitraege(
        deckel.id, man, d2.beitrag, d2.beitrag_ab) == 0


def test_gruppe_loeschen_nur_ohne_artikel(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    artikel = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                           Decimal('1.50'), 1, 0, 't')
    assert db.clubdeckel_gruppen.has_active_artikel(gruppe.id)
    assert db.clubdeckel_artikel.mark_deleted(artikel.id, 't')
    assert not db.clubdeckel_gruppen.has_active_artikel(gruppe.id)
    assert db.clubdeckel_gruppen.mark_deleted(gruppe.id, 't')


def test_katalog_filtert_inaktive_gruppen(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    aktiv_g = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    inaktiv_g = db.clubdeckel_gruppen.create(deckel.id, "Essen", None, 0, 1, 't')
    db.clubdeckel_artikel.create(deckel.id, aktiv_g.id, "Bier", Decimal('1.50'), 1, 0, 't')
    db.clubdeckel_artikel.create(deckel.id, inaktiv_g.id, "Steak", Decimal('2.50'), 1, 0, 't')
    db.clubdeckel_artikel.create(deckel.id, None, "Wasser", Decimal('1.00'), 1, 0, 't')

    alle = db.clubdeckel_artikel.list_for_deckel(deckel.id)
    nur_aktive = db.clubdeckel_artikel.list_for_deckel(deckel.id, nur_aktive=True)
    assert {a['name'] for a in alle} == {'Bier', 'Steak', 'Wasser'}
    assert {a['name'] for a in nur_aktive} == {'Bier', 'Wasser'}


def test_konsum_striche_am_termin_und_letzte_konsum(db):
    """Die Strichliste am Tresen zählt den Konsum DIESES Termins (#167) — das
    frühere 24-Stunden-Fenster schnitt lange Abende auseinander und zog den
    Vortag mit hinein."""
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    spiel = _make_termin(db, man, _wandzeit(-30), _wandzeit(60), typ='spiel')
    frueher = _make_termin(db, man, _wandzeit(-3000))
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier", Decimal('1.50'), 1, 0, 't')
    wasser = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Wasser", Decimal('1.00'), 1, 0, 't')

    for _ in range(5):
        db.clubdeckel_buchungen.create_konsum(deckel.id, mid, bier.id, bier.name, 1,
                                              bier.preis, None, 't', termin_id=spiel)
    db.clubdeckel_buchungen.create_konsum(deckel.id, mid, wasser.id, wasser.name, 1,
                                          wasser.preis, None, 't', termin_id=spiel)
    # Ein Strich beim FRÜHEREN Termin darf nicht mitzählen, obwohl er zeitlich
    # gerade erst entstanden ist.
    db.clubdeckel_buchungen.create_konsum(deckel.id, mid, wasser.id, wasser.name, 3,
                                          wasser.preis, None, 't', termin_id=frueher)

    stats = db.clubdeckel_buchungen.konsum_fuer_termin(deckel.id, mid, spiel)
    assert stats['anzahl'][bier.id] == 5
    assert stats['anzahl'][wasser.id] == 1
    assert stats['summe'] == Decimal('8.50')  # 5×1,50 + 1×1,00, positiv

    # Undo: jüngsten Bier-Strich zurücknehmen -> Anzahl sinkt auf 4
    letzte = db.clubdeckel_buchungen.letzte_konsum_id(deckel.id, mid, bier.id)
    assert letzte is not None
    assert db.clubdeckel_buchungen.storno(letzte, 't')
    stats2 = db.clubdeckel_buchungen.konsum_fuer_termin(deckel.id, mid, spiel)
    assert stats2['anzahl'][bier.id] == 4

    # Der frühere Termin führt seine eigene Strichliste …
    assert db.clubdeckel_buchungen.konsum_fuer_termin(
        deckel.id, mid, frueher)['anzahl'] == {wasser.id: 3}
    # … und ohne Termin gibt es gar keine.
    assert db.clubdeckel_buchungen.konsum_fuer_termin(deckel.id, mid, None) == {
        'summe': Decimal('0'), 'anzahl': {}}


def test_get_kader_mitglied_id(db):
    man = _make_mannschaft(db)
    uid, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    assert db.clubdeckel.get_kader_mitglied_id(uid, man) == mid
    assert db.clubdeckel.get_kader_mitglied_id(uid, man + 999) is None


# ------------------------------------------------ Komplett-Löschen & Restore (#125)
def _loesch_ref(db, table, deckel_id):
    """Distinkte (gesetzte) loesch_ref-Werte gelöschter Zeilen einer Kind-/Deckel-
    Tabelle. NULL (= vorher einzeln storniert, nicht Teil des Batches) bleibt außen vor."""
    col = "id" if table == "clubdeckel" else "deckel_id"
    with db.cursor() as cur:
        cur.execute(f"SELECT DISTINCT loesch_ref FROM {table} "
                    f"WHERE {col}=%s AND deleted_at IS NOT NULL "
                    f"AND loesch_ref IS NOT NULL", (deckel_id,))
        return {r['loesch_ref'] for r in cur.fetchall()}


def test_loeschen_komplett_und_wiederherstellen(db):
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                        Decimal('1.50'), 1, 0, 't')
    db.clubdeckel_berechtigungen.set_wart(deckel.id, mid, 't')
    db.clubdeckel_befreiungen.set_befreiung(deckel.id, mid, 't')
    # Zwei Konsumbuchungen; die zweite wird VOR dem Löschen einzeln storniert.
    db.clubdeckel_buchungen.create_konsum(deckel.id, mid, bier.id, bier.name, 1,
                                          bier.preis, None, 't')
    b2 = db.clubdeckel_buchungen.create_konsum(deckel.id, mid, bier.id, bier.name, 3,
                                               bier.preis, None, 't')
    db.clubdeckel_buchungen.storno(b2.id, 't')

    salden_vorher = db.clubdeckel_buchungen.salden(deckel.id)
    saldo_vorher = db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mid)
    assert saldo_vorher == Decimal('-1.50')                 # nur die 1. Buchung aktiv

    # --- Komplett löschen (Kaskade als ein Batch) -------------------------------
    ref = db.clubdeckel.loesche_komplett(deckel.id, 'admin')
    assert ref is not None
    assert db.clubdeckel.get(deckel.id) is None             # aktiv nicht mehr sichtbar
    assert db.clubdeckel.get_by_mannschaft(man) is None
    weg = db.clubdeckel.get_geloescht(deckel.id)
    assert weg is not None and weg.name == "Teamkasse"
    # Alle Kinder + Deckel gelöscht und teilen dieselbe loesch_ref …
    for table in ("clubdeckel", "clubdeckel_buchung", "clubdeckel_artikel",
                  "clubdeckel_gruppe", "clubdeckel_berechtigung",
                  "clubdeckel_beitrag_befreiung"):
        assert _loesch_ref(db, table, deckel.id) == {ref}
    assert db.clubdeckel_buchungen.salden(deckel.id) == []
    assert db.clubdeckel_gruppen.list_for_deckel(deckel.id) == []
    assert db.clubdeckel_berechtigungen.list_for_deckel(deckel.id) == []
    # … der Vorab-Storno gehört NICHT zum Batch (keine loesch_ref).
    with db.cursor() as cur:
        cur.execute("SELECT loesch_ref FROM clubdeckel_buchung WHERE id=%s", (b2.id,))
        assert cur.fetchone()['loesch_ref'] is None

    # --- Wiederherstellen -------------------------------------------------------
    assert db.clubdeckel.restore(deckel.id, 'admin') == 'ok'
    d = db.clubdeckel.get(deckel.id)
    assert d is not None and d.aktiv == 1
    assert db.clubdeckel.get_by_mannschaft(man).id == deckel.id
    # Salden identisch zum Ausgangsstand; der Vorab-Storno bleibt gelöscht.
    assert db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mid) == saldo_vorher
    assert db.clubdeckel_buchungen.salden(deckel.id) == salden_vorher
    assert len(db.clubdeckel_gruppen.list_for_deckel(deckel.id)) == 1
    assert len(db.clubdeckel_berechtigungen.list_for_deckel(deckel.id)) == 1
    assert len(db.clubdeckel_befreiungen.list_for_deckel(deckel.id)) == 1
    with db.cursor() as cur:
        cur.execute("SELECT deleted_at FROM clubdeckel_buchung WHERE id=%s", (b2.id,))
        assert cur.fetchone()['deleted_at'] is not None      # Storno NICHT wiederbelebt
        # Nach dem Restore ist keine loesch_ref mehr gesetzt.
        cur.execute("SELECT count(*) AS n FROM clubdeckel_buchung "
                    "WHERE deckel_id=%s AND loesch_ref IS NOT NULL", (deckel.id,))
        assert cur.fetchone()['n'] == 0


def test_loeschen_idempotent_und_papierkorb(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    assert db.clubdeckel.loesche_komplett(deckel.id, 'admin') is not None
    assert db.clubdeckel.loesche_komplett(deckel.id, 'admin') is None   # schon weg
    eintraege = {e['id']: e for e in db.clubdeckel.list_geloescht()}
    assert deckel.id in eintraege
    assert eintraege[deckel.id]['mannschaft_hat_aktiven'] is False


def test_restore_konflikt_wenn_neuer_deckel(db):
    man = _make_mannschaft(db)
    alt = db.clubdeckel.create(man, "Alt", 't')
    db.clubdeckel.loesche_komplett(alt.id, 'admin')
    neu = db.clubdeckel.create(man, "Neu", 't')          # frischer aktiver Deckel
    assert neu.id != alt.id
    assert db.clubdeckel.restore(alt.id, 'admin') == 'conflict'
    # Der Papierkorb markiert den Konflikt für die UI.
    eintrag = next(e for e in db.clubdeckel.list_geloescht() if e['id'] == alt.id)
    assert eintrag['mannschaft_hat_aktiven'] is True


def test_restore_unbekannt(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    assert db.clubdeckel.restore(deckel.id, 'admin') == 'not_found'   # aktiv, nicht gelöscht
    assert db.clubdeckel.restore(deckel.id + 999, 'admin') == 'not_found'


def test_loesch_ref_spalten_existieren(db):
    """Fresh-Schema-Pfad: loesch_ref liegt auf allen 8 Live-Tabellen — der
    komplette Soft-Delete einer Teamkasse läuft als ein Batch über diese Spalte,
    eine neue Kindtabelle ohne sie fiele stillschweigend aus dem Batch."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE column_name='loesch_ref' AND table_name LIKE 'clubdeckel%'")
        tabellen = {r['table_name'] for r in cur.fetchall()}
    assert tabellen == {"clubdeckel", "clubdeckel_buchung", "clubdeckel_artikel",
                        "clubdeckel_gruppe", "clubdeckel_berechtigung",
                        "clubdeckel_beitrag_befreiung",
                        "clubdeckel_event", "clubdeckel_event_opt_out"}


# ------------------------------------------- Termin-Bezug & Matrix (#167, v98)
def _make_termin(db, mannschaft_id, beginn, ende=None, typ='training',
                 status='geplant'):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM spielstaette WHERE deleted_at IS NULL "
                    "ORDER BY id LIMIT 1")
        spielstaette_id = cur.fetchone()['id']
        cur.execute(
            "INSERT INTO termine (mannschaft_id,typ,beginn,ende,spielstaette_id,"
            " status,created_by,updated_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,'t','t') RETURNING id",
            (mannschaft_id, typ, beginn, ende, spielstaette_id, status))
        return cur.fetchone()['id']


def _wandzeit(minuten_offset: int) -> str:
    """Lokale Wandzeit relativ zu jetzt – dieselbe Zeitbasis wie termine.beginn."""
    return (datetime.now() + timedelta(minutes=minuten_offset)).strftime('%Y-%m-%dT%H:%M')


def test_get_laufenden_findet_termin_im_fenster(db):
    man = _make_mannschaft(db)
    laeuft = _make_termin(db, man, _wandzeit(-30), _wandzeit(60))

    gefunden = db.termine.get_laufenden(man)
    assert gefunden is not None and gefunden.id == laeuft


def test_get_laufenden_greift_schon_im_vorlauf(db):
    """Getränke werden beim Aufbau geholt — eine Stunde vor Anpfiff zählt schon."""
    man = _make_mannschaft(db)
    gleich = _make_termin(db, man, _wandzeit(30), _wandzeit(120))
    assert db.termine.get_laufenden(man).id == gleich


def test_get_laufenden_ignoriert_termine_vor_ihrem_vorlauf(db):
    man = _make_mannschaft(db)
    _make_termin(db, man, _wandzeit(61), _wandzeit(120))   # Vorlauf noch nicht erreicht

    assert db.termine.get_laufenden(man) is None


def test_get_laufenden_gilt_nach_dem_ende_weiter(db):
    """Kernregel: Ein Termin bleibt zuständig, bis der nächste seinen Vorlauf
    erreicht — auch lange nach dem Abpfiff. Das dritte Bier gehört zum Spiel."""
    man = _make_mannschaft(db)
    vorbei = _make_termin(db, man, _wandzeit(-600), _wandzeit(-500))

    assert db.termine.get_laufenden(man).id == vorbei


def test_get_laufenden_ohne_ende_gilt_ebenfalls_weiter(db):
    """Ein fehlendes `ende` ändert nichts — das Ende zählt für die Zuordnung nie."""
    man = _make_mannschaft(db)
    offen = _make_termin(db, man, _wandzeit(-500), None, typ='sonstiges')

    assert db.termine.get_laufenden(man).id == offen


def test_get_laufenden_wechselt_mit_dem_vorlauf_des_naechsten(db):
    """Die Ablösung: Solange der Vorlauf des Spiels nicht begonnen hat, gilt das
    Training; danach das Spiel — auch wenn das Training noch läuft."""
    man = _make_mannschaft(db)
    training = _make_termin(db, man, _wandzeit(-100), _wandzeit(60), typ='training')
    spiel = _make_termin(db, man, _wandzeit(61), _wandzeit(180), typ='spiel')
    assert db.termine.get_laufenden(man).id == training

    with db.cursor() as cur:
        cur.execute("UPDATE termine SET beginn = %s WHERE id = %s",
                    (_wandzeit(59), spiel))
    assert db.termine.get_laufenden(man).id == spiel


def test_get_laufenden_abgesagter_loest_den_vorherigen_nicht_ab(db):
    """Ein abgesagter Termin ist nicht zuständig UND beendet den vorherigen nicht
    — sonst fiele der Abend in ein Loch, an dem nichts stattgefunden hat."""
    man = _make_mannschaft(db)
    training = _make_termin(db, man, _wandzeit(-200), _wandzeit(-100), typ='training')
    _make_termin(db, man, _wandzeit(-30), _wandzeit(60), status='abgesagt')

    assert db.termine.get_laufenden(man).id == training


def test_get_laufenden_trennt_die_mannschaften(db):
    erste = _make_mannschaft(db, "Erste")
    zweite = _make_mannschaft(db, "Zweite")
    _make_termin(db, erste, _wandzeit(-30), _wandzeit(60))

    assert db.termine.get_laufenden(zweite) is None


def test_konsum_paar_traegt_denselben_termin(db):
    """Käufer- und Verkäufer-Zeile eines Mitglieds-Verkaufs gehören zum selben
    Termin – sonst fehlte die Gegenzeile in der Termin-Auswertung."""
    man = _make_mannschaft(db)
    _, kaeufer = _make_kader_user(db, man, 'spieler', 'Anna')
    _, verkaeufer = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    termin = _make_termin(db, man, _wandzeit(-30), _wandzeit(60))

    db.clubdeckel_buchungen.create_konsum(
        deckel.id, kaeufer, None, 'Roster', 1, Decimal('2.50'), verkaeufer, 't',
        termin_id=termin)

    with db.cursor() as cur:
        cur.execute("SELECT typ, termin_id FROM clubdeckel_buchung "
                    "WHERE deckel_id = %s ORDER BY typ", (deckel.id,))
        zeilen = [(r['typ'], r['termin_id']) for r in cur.fetchall()]
    assert zeilen == [('konsum', termin), ('verkauf', termin)]


def _matrix_aufbau(db):
    """Deckel mit zwei Mitgliedern, zwei Artikeln und einem Termin."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    _, bernd = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    bier = db.clubdeckel_artikel.create(deckel.id, None, 'Bier', Decimal('1.50'), 1, 0, 't')
    wasser = db.clubdeckel_artikel.create(deckel.id, None, 'Wasser', Decimal('1.00'), 1, 0, 't')
    termin = _make_termin(db, man, _wandzeit(-30), _wandzeit(60))
    return man, deckel, anna, bernd, bier, wasser, termin


def test_matrix_zaehlt_zellen_und_randsummen(db):
    man, deckel, anna, bernd, bier, wasser, termin = _matrix_aufbau(db)
    for _ in range(3):
        db.clubdeckel_buchungen.create_konsum(
            deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
            termin_id=termin)
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, bernd, wasser.id, 'Wasser', 2, Decimal('1.00'), None, 't',
        termin_id=termin)

    m = db.clubdeckel_buchungen.matrix(deckel.id, termin_id=termin)

    assert m['zellen'][f"{anna}:{bier.id}"] == {"anzahl": 3, "betrag": Decimal('4.50')}
    assert m['zellen'][f"{bernd}:{wasser.id}"] == {"anzahl": 2, "betrag": Decimal('2.00')}
    assert m['je_artikel'][bier.id]['anzahl'] == 3
    assert m['je_artikel'][wasser.id]['betrag'] == Decimal('2.00')
    assert m['gesamt'] == Decimal('6.50')


def test_matrix_zaehlt_nur_konsum_und_ignoriert_storniertes(db):
    """Die Gegenzeile 'verkauf' und Zahlungen sind kein Tresenverbrauch; ein
    zurückgenommener Strich verschwindet aus dem Gitter."""
    man, deckel, anna, bernd, bier, _, termin = _matrix_aufbau(db)
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), bernd, 't',
        termin_id=termin)
    weg = db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
        termin_id=termin)
    db.clubdeckel_buchungen.create_zahlung(
        deckel.id, anna, bernd, Decimal('5.00'), None, 't')
    db.clubdeckel_buchungen.storno(weg.id, 't')

    m = db.clubdeckel_buchungen.matrix(deckel.id, termin_id=termin)

    assert m['gesamt'] == Decimal('1.50')
    assert [e['mitglied_id'] for e in m['je_mitglied']] == [anna]


def test_matrix_trennt_termine_und_zeitraeume(db):
    man, deckel, anna, _, bier, _, termin = _matrix_aufbau(db)
    anderer = _make_termin(db, man, _wandzeit(-2000), _wandzeit(-1900))
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
        termin_id=termin)
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 4, Decimal('1.50'), None, 't',
        termin_id=anderer)

    assert db.clubdeckel_buchungen.matrix(deckel.id, termin_id=termin)['gesamt'] \
        == Decimal('1.50')
    assert db.clubdeckel_buchungen.matrix(deckel.id, termin_id=anderer)['gesamt'] \
        == Decimal('6.00')
    # Ohne Termin-Filter zählt das Zeitfenster – beide Buchungen sind eben erst
    # entstanden, also stecken beide drin.
    assert db.clubdeckel_buchungen.matrix(deckel.id)['gesamt'] == Decimal('7.50')


def test_letzte_konsum_id_trifft_nur_den_gewaehlten_termin(db):
    """Das „−" der Matrix darf nicht den Strich eines anderen Abends erwischen."""
    man, deckel, anna, _, bier, _, termin = _matrix_aufbau(db)
    anderer = _make_termin(db, man, _wandzeit(-2000), _wandzeit(-1900))
    alt = db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
        termin_id=anderer)
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
        termin_id=termin)

    treffer = db.clubdeckel_buchungen.letzte_konsum_id(
        deckel.id, anna, bier.id, termin_id=anderer)
    assert treffer == alt.id


def test_buchungsliste_filtert_auf_termin_und_liefert_label(db):
    man, deckel, anna, _, bier, _, termin = _matrix_aufbau(db)
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
        termin_id=termin)
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't')

    gefiltert = db.clubdeckel_buchungen.list_for_deckel(deckel.id, termin_id=termin)
    assert len(gefiltert) == 1
    assert gefiltert[0].termin_id == termin
    assert gefiltert[0].termin_label.startswith('Training ')
    assert len(db.clubdeckel_buchungen.list_for_deckel(deckel.id)) == 2


def test_matrix_behaelt_spalte_fuer_abgeschalteten_artikel(db):
    """Summen müssen aufgehen: Ein deaktivierter Artikel mit Umsatz im Ausschnitt
    behält seine Spalte, sonst fehlte er in der Aufschlüsselung, steckte aber in
    der Gesamtsumme."""
    man, deckel, anna, _, bier, _, termin = _matrix_aufbau(db)
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 2, Decimal('1.50'), None, 't',
        termin_id=termin)
    db.clubdeckel_artikel.update(bier.id, None, 'Bier', Decimal('1.50'), 0, 0,
                                 't', bier.version)

    ids = [a['id'] for a in db.clubdeckel_artikel.list_fuer_ids(deckel.id, [bier.id])]
    assert ids == [bier.id]

    m = db.clubdeckel_buchungen.matrix(deckel.id, termin_id=termin)
    assert m['je_artikel'][bier.id]['anzahl'] == 2
    assert m['gesamt'] == Decimal('3.00')


def test_list_fuer_ids_findet_auch_geloeschte_artikel(db):
    """Auch ein soft-gelöschter Artikel muss auffindbar bleiben — die Zahlen von
    damals ändern sich nicht, weil jemand den Katalog aufgeräumt hat."""
    man, deckel, _, _, bier, _, _ = _matrix_aufbau(db)
    db.clubdeckel_artikel.mark_deleted(bier.id, 't')

    treffer = db.clubdeckel_artikel.list_fuer_ids(deckel.id, [bier.id])
    assert [a['id'] for a in treffer] == [bier.id]
    assert db.clubdeckel_artikel.list_fuer_ids(deckel.id, []) == []


# --------------------------- Sortiments-Stände je Gruppe (#167, v100) -----------
def test_neue_gruppe_ist_ihre_erste_generation(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, 'Kasse', 't')

    g = db.clubdeckel_gruppen.create(deckel.id, 'Getränke', None, 1, 0, 't')

    assert g.stamm_id == g.id           # zeigt auf sich selbst
    assert g.gilt_ab_termin_id is None  # gilt von Anfang an


def test_stand_gilt_ab_seinem_spieltag(db):
    """Kernregel: Ein Stand ab Spieltag B gilt für B und alles danach; für den
    früheren Spieltag A bleibt der alte Stand — samt Verkäufer und Preisen."""
    man = _make_mannschaft(db)
    _, trompete = _make_kader_user(db, man, 'spieler', 'Trompete')
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    frueher = _make_termin(db, man, _wandzeit(-3000))
    spaeter = _make_termin(db, man, _wandzeit(-100))
    g = db.clubdeckel_gruppen.create(deckel.id, 'Getränke', None, 1, 0, 't')
    db.clubdeckel_artikel.create(deckel.id, g.id, 'Bier', Decimal('1.50'), 1, 0, 't')

    db.clubdeckel_gruppen.neue_generation(
        g.id, spaeter, 'Getränke', trompete, 1, 0, 't')

    alt = db.clubdeckel_gruppen.list_stand(deckel.id, frueher)
    neu = db.clubdeckel_gruppen.list_stand(deckel.id, spaeter)
    assert [x.verkaeufer_mitglied_id for x in alt] == [None]
    assert [x.verkaeufer_mitglied_id for x in neu] == [trompete]
    # Je Stamm genau ein Stand — nicht beide Generationen nebeneinander.
    assert len(alt) == 1 and len(neu) == 1


def test_neue_generation_kopiert_die_artikel(db):
    """Die Artikel gehören zum Stand — ohne Kopie stünde die neue Generation
    vor einem leeren Regal."""
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    spaeter = _make_termin(db, man, _wandzeit(-100))
    g = db.clubdeckel_gruppen.create(deckel.id, 'Getränke', None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, g.id, 'Bier', Decimal('1.50'), 1, 0, 't')

    neue_id, abbildung = db.clubdeckel_gruppen.neue_generation(
        g.id, spaeter, 'Getränke', None, 1, 0, 't')

    kopien = db.clubdeckel_artikel.list_fuer_gruppen([neue_id])
    assert [(k['name'], k['preis']) for k in kopien] == [('Bier', Decimal('1.50'))]
    assert abbildung[bier.id] == kopien[0]['id']     # alt → neu abgebildet
    assert kopien[0]['id'] != bier.id                # eigene Zeile, kein Verweis


def test_zweite_aenderung_am_selben_spieltag_bleibt_ein_stand(db):
    """Sonst sammelte jedes Nachjustieren am selben Abend eine Generation an."""
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    spieltag = _make_termin(db, man, _wandzeit(-100))
    g = db.clubdeckel_gruppen.create(deckel.id, 'Getränke', None, 1, 0, 't')

    erste, _ = db.clubdeckel_gruppen.neue_generation(
        g.id, spieltag, 'Getränke', None, 1, 0, 't')
    zweite, _ = db.clubdeckel_gruppen.neue_generation(
        g.id, spieltag, 'Kaltgetränke', None, 1, 0, 't')

    assert erste == zweite
    staende = db.clubdeckel_gruppen.list_generationen(g.id)
    assert len(staende) == 2                          # Basis + dieser Spieltag
    assert staende[0]['name'] == 'Kaltgetränke'       # überschrieben, nicht ergänzt


def test_stand_ohne_passende_generation_faellt_auf_die_basis(db):
    """Ein Termin VOR der ersten datierten Generation sieht den Basisstand."""
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    frueh = _make_termin(db, man, _wandzeit(-5000))
    spaet = _make_termin(db, man, _wandzeit(-100))
    g = db.clubdeckel_gruppen.create(deckel.id, 'Getränke', None, 1, 0, 't')
    db.clubdeckel_gruppen.neue_generation(g.id, spaet, 'Neu', None, 1, 0, 't')

    assert [x.name for x in db.clubdeckel_gruppen.list_stand(deckel.id, frueh)] == ['Getränke']
    assert [x.name for x in db.clubdeckel_gruppen.list_stand(deckel.id, spaet)] == ['Neu']


def test_kuenftiger_stand_gilt_heute_noch_nicht(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    kuenftig = _make_termin(db, man, _wandzeit(5000))
    g = db.clubdeckel_gruppen.create(deckel.id, 'Getränke', None, 1, 0, 't')
    db.clubdeckel_gruppen.neue_generation(g.id, kuenftig, 'Später', None, 1, 0, 't')

    assert [x.name for x in db.clubdeckel_gruppen.list_stand(deckel.id)] == ['Getränke']
    assert [x.name for x in db.clubdeckel_gruppen.list_stand(deckel.id, kuenftig)] == ['Später']


def test_artikel_folgen_dem_stand_mit_preis_und_verkaeufer(db):
    """Der Prüfstein des ganzen Umbaus: Preis, Bezeichnung UND Verkäufer kommen
    aus derselben Generation."""
    man = _make_mannschaft(db)
    _, trompete = _make_kader_user(db, man, 'spieler', 'Trompete')
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    spaeter = _make_termin(db, man, _wandzeit(-100))
    g = db.clubdeckel_gruppen.create(deckel.id, 'Getränke', None, 1, 0, 't')
    db.clubdeckel_artikel.create(deckel.id, g.id, 'Bier', Decimal('1.50'), 1, 0, 't')

    neue_id, abbildung = db.clubdeckel_gruppen.neue_generation(
        g.id, spaeter, 'Getränke', trompete, 1, 0, 't')
    kopie = list(abbildung.values())[0]
    db.clubdeckel_artikel.update(kopie, neue_id, 'Bier 0,5', Decimal('2.00'), 1, 0,
                                 't', db.clubdeckel_artikel.get(kopie).version)

    alt = db.clubdeckel_artikel.list_fuer_gruppen(
        [x.id for x in db.clubdeckel_gruppen.list_stand(deckel.id, None,
                                                        jetzt='2020-01-01T00:00')])
    neu = db.clubdeckel_artikel.list_fuer_gruppen(
        [x.id for x in db.clubdeckel_gruppen.list_stand(deckel.id, spaeter)])
    assert [(a['name'], a['preis'], a['verkaeufer_mitglied_id']) for a in alt] == \
        [('Bier', Decimal('1.50'), None)]
    assert [(a['name'], a['preis'], a['verkaeufer_mitglied_id']) for a in neu] == \
        [('Bier 0,5', Decimal('2.00'), trompete)]


def test_neue_generation_kopiert_den_wart_artikel_als_solchen(db):
    """„Wäsche" gehört zum Stand wie Preis und Bezeichnung: Die Kopie darf nicht
    plötzlich am Tresen stehen."""
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    spaeter = _make_termin(db, man, _wandzeit(-100))
    g = db.clubdeckel_gruppen.create(deckel.id, 'Service', None, 1, 0, 't')
    db.clubdeckel_artikel.create(deckel.id, g.id, 'Wäsche', Decimal('3.00'), 1, 0,
                                 't', nur_wart=1)

    neue_id, _ = db.clubdeckel_gruppen.neue_generation(
        g.id, spaeter, 'Service', None, 1, 0, 't')

    kopien = db.clubdeckel_artikel.list_fuer_gruppen([neue_id])
    assert [(k['name'], k['nur_wart']) for k in kopien] == [('Wäsche', 1)]


# ----------------- Nächster Termin: Vorgabe des Katalogs (#167, v100) ----------
def test_naechster_ist_das_ereignis_am_abend_nicht_das_alte_training(db):
    """Der Prüfstein: Morgens am Spieltag pflegt man die Karte fürs Spiel am
    Abend — get_laufenden zeigt dann noch aufs alte Training."""
    man = _make_mannschaft(db)
    training = _make_termin(db, man, _wandzeit(-6000), _wandzeit(-5900), typ='training')
    spiel = _make_termin(db, man, _wandzeit(600), _wandzeit(720), typ='spiel')

    assert db.termine.get_laufenden(man).id == training     # für Buchungen
    assert db.termine.get_naechsten(man).id == spiel        # für die Speisekarte


def test_naechster_bleibt_waehrend_des_termins_stehen(db):
    man = _make_mannschaft(db)
    laeuft = _make_termin(db, man, _wandzeit(-30), _wandzeit(60))
    _make_termin(db, man, _wandzeit(3000), _wandzeit(3100))

    assert db.termine.get_naechsten(man).id == laeuft


def test_naechster_rueckt_nach_dem_ende_weiter(db):
    man = _make_mannschaft(db)
    _make_termin(db, man, _wandzeit(-300), _wandzeit(-200))
    danach = _make_termin(db, man, _wandzeit(3000), _wandzeit(3100))

    assert db.termine.get_naechsten(man).id == danach


def test_naechster_ohne_ende_zaehlt_ueber_den_beginn(db):
    man = _make_mannschaft(db)
    _make_termin(db, man, _wandzeit(-300), None, typ='sonstiges')
    kuenftig = _make_termin(db, man, _wandzeit(300), None, typ='sonstiges')

    assert db.termine.get_naechsten(man).id == kuenftig


def test_naechster_ignoriert_abgesagte_und_liefert_sonst_nichts(db):
    man = _make_mannschaft(db)
    _make_termin(db, man, _wandzeit(300), _wandzeit(400), status='abgesagt')
    _make_termin(db, man, _wandzeit(-3000), _wandzeit(-2900))

    assert db.termine.get_naechsten(man) is None


# ------------- Bestehende Buchungen auf einen neuen Stand umstellen (#167) ----
def _uebernahme_aufbau(db):
    """Deckel mit Gruppe, Bier zu 1,50 und drei Strichen bei einem Spiel."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    _, bernd = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    spiel = _make_termin(db, man, _wandzeit(-30), _wandzeit(60), typ='spiel')
    g = db.clubdeckel_gruppen.create(deckel.id, 'Getränke', None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, g.id, 'Bier', Decimal('1.50'), 1, 0, 't')
    for mid in (anna, anna, bernd):
        db.clubdeckel_buchungen.create_konsum(
            deckel.id, mid, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
            termin_id=spiel)
    return man, deckel, g, bier, spiel, anna, bernd


def test_zaehlt_gebuchtes_des_termins(db):
    _, deckel, _, _, spiel, _, _ = _uebernahme_aufbau(db)

    stand = db.clubdeckel_buchungen.zaehle_konsum_fuer_termin(deckel.id, spiel)

    assert stand['anzahl'] == 3 and stand['betrag'] == Decimal('4.50')


def test_konsum_je_artikel_liefert_nur_den_termin(db):
    man, deckel, g, bier, spiel, anna, _ = _uebernahme_aufbau(db)
    # Ein Strich bei einem ANDEREN Termin darf nicht mitkommen.
    anderer = _make_termin(db, man, _wandzeit(-3000))
    db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
        termin_id=anderer)

    treffer = db.clubdeckel_buchungen.konsum_je_artikel(deckel.id, spiel, [bier.id])

    assert len(treffer) == 3
    assert {t['artikel_id'] for t in treffer} == {bier.id}


def test_konsum_je_artikel_ignoriert_stornierte_und_fremde_artikel(db):
    _, deckel, g, bier, spiel, anna, _ = _uebernahme_aufbau(db)
    weg = db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('1.50'), None, 't',
        termin_id=spiel)
    db.clubdeckel_buchungen.storno(weg.id, 't')

    assert len(db.clubdeckel_buchungen.konsum_je_artikel(
        deckel.id, spiel, [bier.id])) == 3
    assert db.clubdeckel_buchungen.konsum_je_artikel(deckel.id, spiel, []) == []


def test_ersatzbuchung_behaelt_die_uhrzeit(db):
    """Beim Umstellen darf der Strich in der Tagesansicht nicht nach vorn
    rutschen — sonst stünde er plötzlich nach dem Abpfiff."""
    _, deckel, g, bier, spiel, anna, _ = _uebernahme_aufbau(db)
    alt = db.clubdeckel_buchungen.konsum_je_artikel(deckel.id, spiel, [bier.id])[0]

    neu = db.clubdeckel_buchungen.create_konsum(
        deckel.id, anna, bier.id, 'Bier', 1, Decimal('2.00'), None, 't',
        termin_id=spiel, wert_datum=str(alt['created_at']))

    assert str(neu.created_at) == str(alt['created_at'])


# ------------------------------------------------------------ Sammlungen (#181)
def _saldo(db, deckel_id, mitglied_id):
    return db.clubdeckel_buchungen.saldo_for_mitglied(deckel_id, mitglied_id)


def test_event_bucht_kader_ohne_jubilar_und_ohne_opt_out(db):
    """Der Teilnehmerkreis: aktiver Kader minus der, für den gesammelt wird,
    minus die generellen Opt-outs. Das Geld landet beim Club."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    _, bernd = _make_kader_user(db, man, 'spieler', 'Bernd')
    _, klaus = _make_kader_user(db, man, 'spieler', 'Klaus')      # der Jubilar
    _, dora = _make_kader_user(db, man, 'spieler', 'Dora')        # macht nie mit
    _, ex = _make_kader_user(db, man, 'spieler', 'Emil', bis=YESTERDAY)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    db.clubdeckel_events.set_opt_out(deckel.id, dora, 't')

    event = db.clubdeckel_events.create(deckel.id, "60. Geburtstag Klaus",
                                        Decimal('5.00'), klaus, 't')
    gebucht = db.clubdeckel_buchungen.buche_event(
        deckel.id, man, event.id, event.name, event.betrag,
        event.fuer_mitglied_id, 't')

    assert gebucht == 2                       # nur Anna und Bernd
    assert _saldo(db, deckel.id, anna) == Decimal('-5.00')
    assert _saldo(db, deckel.id, bernd) == Decimal('-5.00')
    assert _saldo(db, deckel.id, klaus) == Decimal('0')
    assert _saldo(db, deckel.id, dora) == Decimal('0')
    assert _saldo(db, deckel.id, ex) == Decimal('0')
    assert _team_saldo(db, deckel.id) == Decimal('10.00')


def test_event_ohne_jubilar_bucht_den_ganzen_kader(db):
    """fuer_mitglied_id NULL nimmt niemanden aus — `IS DISTINCT FROM NULL`
    darf nicht versehentlich alle herausfiltern."""
    man = _make_mannschaft(db)
    _make_kader_user(db, man, 'spieler', 'Anna')
    _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    event = db.clubdeckel_events.create(deckel.id, "Kasten für den Kühlschrank",
                                        Decimal('3.00'), None, 't')

    assert db.clubdeckel_buchungen.buche_event(
        deckel.id, man, event.id, event.name, event.betrag, None, 't') == 2


def test_event_zweimal_buchen_holt_nur_nachzuegler(db):
    """Idempotenz: Der zweite Klick belastet niemanden doppelt, holt aber den
    ins Boot, dessen Opt-out inzwischen weg ist."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    _, dora = _make_kader_user(db, man, 'spieler', 'Dora')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    db.clubdeckel_events.set_opt_out(deckel.id, dora, 't')
    event = db.clubdeckel_events.create(deckel.id, "Geschenk", Decimal('5.00'),
                                        None, 't')

    def buchen():
        return db.clubdeckel_buchungen.buche_event(
            deckel.id, man, event.id, event.name, event.betrag, None, 't')

    assert buchen() == 1
    assert buchen() == 0                      # nichts Neues
    db.clubdeckel_events.revoke_opt_out(deckel.id, dora, 't')
    assert buchen() == 1                      # jetzt zahlt Dora mit
    assert _saldo(db, deckel.id, anna) == Decimal('-5.00')
    assert _saldo(db, deckel.id, dora) == Decimal('-5.00')


def test_event_storno_nimmt_alle_zeilen_zurueck_und_erlaubt_neubuchung(db):
    """Anders als beim Beitrag heißt Storno hier nicht „erlassen": Nach dem
    Zurücknehmen darf dieselbe Sammlung korrigiert und neu gebucht werden."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    event = db.clubdeckel_events.create(deckel.id, "Geschenk", Decimal('5.00'),
                                        None, 't')
    db.clubdeckel_buchungen.buche_event(deckel.id, man, event.id, event.name,
                                        event.betrag, None, 't')

    assert db.clubdeckel_buchungen.storno_event(deckel.id, event.id, 't') == 2
    assert _saldo(db, deckel.id, anna) == Decimal('0')
    assert _team_saldo(db, deckel.id) == Decimal('0')

    # Korrigierter Betrag, erneut buchen
    db.clubdeckel_events.update(event.id, "Geschenk", Decimal('2.00'), None, 't',
                                event.version)
    neu = db.clubdeckel_events.get(event.id)
    assert db.clubdeckel_buchungen.buche_event(
        deckel.id, man, neu.id, neu.name, neu.betrag, None, 't') == 2
    assert _saldo(db, deckel.id, anna) == Decimal('-2.00')


def test_event_buchung_haelt_namen_als_schnappschuss(db):
    """Der Anlass steht als Notiz an der Buchung — die History bleibt lesbar,
    auch wenn die Sammlung später umbenannt oder geprunt wird."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    event = db.clubdeckel_events.create(deckel.id, "60. Geburtstag Klaus",
                                        Decimal('5.00'), None, 't')
    db.clubdeckel_buchungen.buche_event(deckel.id, man, event.id, event.name,
                                        event.betrag, None, 't')

    buchung = db.clubdeckel_buchungen.list_for_deckel(deckel.id, mitglied_id=anna)[0]
    assert buchung.typ == 'event'
    assert buchung.event_id == event.id
    assert buchung.notiz == "60. Geburtstag Klaus"
    assert buchung.gegen_name == 'Team'
    # Und sie ist über die Volltextsuche der History auffindbar (#129).
    assert db.clubdeckel_buchungen.list_for_deckel(deckel.id, suche='Geburtstag')


def test_event_liste_zeigt_buchungsstand(db):
    man = _make_mannschaft(db)
    _make_kader_user(db, man, 'spieler', 'Anna')
    _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    event = db.clubdeckel_events.create(deckel.id, "Geschenk", Decimal('5.00'),
                                        None, 't')

    offen = db.clubdeckel_events.list_for_deckel(deckel.id)[0]
    assert (offen.gebucht_anzahl, offen.gebucht_summe) == (0, Decimal('0'))

    db.clubdeckel_buchungen.buche_event(deckel.id, man, event.id, event.name,
                                        event.betrag, None, 't')
    gebucht = db.clubdeckel_events.list_for_deckel(deckel.id)[0]
    assert gebucht.gebucht_anzahl == 2
    assert gebucht.gebucht_summe == Decimal('10.00')   # positiv, nicht −10
    assert gebucht.gebucht_am is not None


def test_event_liste_loest_jubilar_namen_auf(db):
    man = _make_mannschaft(db)
    _, klaus = _make_kader_user(db, man, 'spieler', 'Klaus')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    db.clubdeckel_events.create(deckel.id, "Geschenk", Decimal('5.00'), klaus, 't')

    assert db.clubdeckel_events.list_for_deckel(deckel.id)[0].fuer_name == 'Klaus Deckeltest'


def test_event_opt_out_ist_reaktivierbar_und_einmalig(db):
    """Muster der Beitragsbefreiung: eine Zeile je (Deckel, Mitglied), erneutes
    Setzen reaktiviert sie, statt eine zweite anzulegen."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')

    db.clubdeckel_events.set_opt_out(deckel.id, anna, 't')
    db.clubdeckel_events.set_opt_out(deckel.id, anna, 't')     # idempotent
    assert len(db.clubdeckel_events.list_opt_outs(deckel.id)) == 1

    assert db.clubdeckel_events.revoke_opt_out(deckel.id, anna, 't') is True
    assert db.clubdeckel_events.list_opt_outs(deckel.id) == []
    assert db.clubdeckel_events.revoke_opt_out(deckel.id, anna, 't') is False

    db.clubdeckel_events.set_opt_out(deckel.id, anna, 't')     # reaktiviert
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM clubdeckel_event_opt_out "
                    "WHERE deckel_id=%s AND mitglied_id=%s", (deckel.id, anna))
        assert cur.fetchone()['n'] == 1


def test_event_doppelbuchung_wird_hart_verhindert(db):
    """Der partielle Unique-Index ist die letzte Verteidigungslinie, falls zwei
    Warte gleichzeitig auf „Buchen" tippen."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    event = db.clubdeckel_events.create(deckel.id, "Geschenk", Decimal('5.00'),
                                        None, 't')
    db.clubdeckel_buchungen.buche_event(deckel.id, man, event.id, event.name,
                                        event.betrag, None, 't')
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_buchung (deckel_id, mitglied_id, typ, "
                "betrag, event_id, created_by, updated_by) "
                "VALUES (%s,%s,'event',-5.00,%s,'t','t')",
                (deckel.id, anna, event.id))


def test_event_schreibt_history_und_soft_delete(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    event = db.clubdeckel_events.create(deckel.id, "Geschenk", Decimal('5.00'),
                                        None, 't')
    db.clubdeckel_events.update(event.id, "Geschenk XL", Decimal('7.00'), None,
                                't2', event.version)
    assert db.clubdeckel_events.mark_deleted(event.id, 't3') is True
    assert db.clubdeckel_events.get(event.id) is None

    with db.cursor() as cur:
        cur.execute("SELECT version, name, betrag FROM clubdeckel_event_history "
                    "WHERE id=%s ORDER BY version", (event.id,))
        stufen = [(r['version'], r['name'], r['betrag']) for r in cur.fetchall()]
    assert stufen == [(1, 'Geschenk', Decimal('5.00')),
                      (2, 'Geschenk XL', Decimal('7.00')),
                      (3, 'Geschenk XL', Decimal('7.00'))]


def test_deckel_softdelete_nimmt_sammlungen_mit(db):
    """Der komplette Soft-Delete der Teamkasse ist ein Batch über loesch_ref —
    neue Kindtabellen müssen mit, sonst blieben sie aktiv zurück."""
    man = _make_mannschaft(db)
    _, anna = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamkasse", 't')
    db.clubdeckel_events.create(deckel.id, "Geschenk", Decimal('5.00'), None, 't')
    db.clubdeckel_events.set_opt_out(deckel.id, anna, 't')

    db.clubdeckel.loesche_komplett(deckel.id, 't')
    assert db.clubdeckel_events.list_for_deckel(deckel.id) == []
    assert db.clubdeckel_events.list_opt_outs(deckel.id) == []

    assert db.clubdeckel.restore(deckel.id, 't') == 'ok'
    assert len(db.clubdeckel_events.list_for_deckel(deckel.id)) == 1
    assert len(db.clubdeckel_events.list_opt_outs(deckel.id)) == 1
