"""Integrationstests des Teamtresors (#98, Schema v75) gegen echtes PostgreSQL.

Prüft die neuen Tabellen (History-Trigger, CHECK, partielle Unique-Indexe), die
Kader-Rechteableitung (aktiv am Stichtag, Rollen-Stufen), die Wart-ACL inkl.
Reaktivierung sowie die Ledger-Semantik des korrigierten Modells: Preis-Snapshot,
Mitglieds-Verkäufer als Nullsummen-Paar (konsum/verkauf), Zahlung als Paar,
Einkauf ans Team, automatischer Beitragslauf (Monatsfenster, Befreiung,
storniert = erlassen) und Team-Saldo = −Σ Mitgliedssalden.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine (leere) Wegwerf-DB zeigt –
VereinsDB legt das Schema beim Connect an (Muster wie test_termine_integration).
"""
import os
import sys
from datetime import date, timedelta
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
                "clubdeckel_berechtigung, clubdeckel_berechtigung_history, "
                "clubdeckel, clubdeckel_history, "
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
    db.clubdeckel.create(man1, "Teamtresor Erste", 't')

    teams = {t['mannschaft_id']: t for t in db.clubdeckel.list_teams_for_user(uid)}
    assert teams[man1]['zugriff'] == 'verwalten'
    assert teams[man1]['deckel']['name'] == 'Teamtresor Erste'
    assert teams[man2]['zugriff'] == 'mitglied'
    assert teams[man2]['deckel'] is None


# ------------------------------------------------------------- Schema/Unique
def test_ein_deckel_pro_mannschaft_und_neuanlage_nach_softdelete(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.clubdeckel.create(man, "Zweiter", 't')
    # Nach Soft-Delete ist die Mannschaft wieder frei (partieller Index)
    assert db.clubdeckel.mark_deleted(deckel.id, 't')
    neu = db.clubdeckel.create(man, "Neuer", 't')
    assert neu.id != deckel.id


def test_stammdaten_update_fuehrt_beitrag_ab(db):
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')

    # Beitrag setzen -> beitrag_ab = laufender Monat
    assert db.clubdeckel.update(deckel.id, "Teamtresor", 1, Decimal('5.00'),
                                mid, 'DE12', None, 'paypal.me/x', 't', deckel.version)
    d2 = db.clubdeckel.get(deckel.id)
    assert d2.beitrag == Decimal('5.00')
    assert d2.beitrag_ab == MONAT
    assert d2.zahlungsempfaenger_name == 'Anna Deckeltest'
    # Beitrag entfernen -> beitrag_ab leer
    assert db.clubdeckel.update(deckel.id, "Teamtresor", 1, None, None,
                                None, None, None, 't', d2.version)
    d3 = db.clubdeckel.get(deckel.id)
    assert d3.beitrag is None and d3.beitrag_ab is None
    with db.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM clubdeckel_history WHERE id=%s", (deckel.id,))
        assert cur.fetchone()['n'] == 3


def test_buchung_typ_check(db):
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_buchung (deckel_id,mitglied_id,typ,betrag,created_by,updated_by) "
                "VALUES (%s,%s,'quatsch',1,'t','t')", (deckel.id, mid))


# ----------------------------------------------------------------- Wart-ACL
def test_wart_setzen_revoken_reaktivieren(db):
    man = _make_mannschaft(db)
    uid, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')

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
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
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
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
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
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
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
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
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
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
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


def test_an_verkauf_team_und_mitglied_paar(db):
    man = _make_mannschaft(db)
    _, a = _make_kader_user(db, man, 'spieler', 'Anna')
    _, b = _make_kader_user(db, man, 'spieler', 'Bernd')
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')

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
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
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
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')

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
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
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


def test_gruppe_loeschen_nur_ohne_artikel(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    artikel = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier",
                                           Decimal('1.50'), 1, 0, 't')
    assert db.clubdeckel_gruppen.has_active_artikel(gruppe.id)
    assert db.clubdeckel_artikel.mark_deleted(artikel.id, 't')
    assert not db.clubdeckel_gruppen.has_active_artikel(gruppe.id)
    assert db.clubdeckel_gruppen.mark_deleted(gruppe.id, 't')


def test_katalog_filtert_inaktive_gruppen(db):
    man = _make_mannschaft(db)
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
    aktiv_g = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    inaktiv_g = db.clubdeckel_gruppen.create(deckel.id, "Essen", None, 0, 1, 't')
    db.clubdeckel_artikel.create(deckel.id, aktiv_g.id, "Bier", Decimal('1.50'), 1, 0, 't')
    db.clubdeckel_artikel.create(deckel.id, inaktiv_g.id, "Steak", Decimal('2.50'), 1, 0, 't')
    db.clubdeckel_artikel.create(deckel.id, None, "Wasser", Decimal('1.00'), 1, 0, 't')

    alle = db.clubdeckel_artikel.list_for_deckel(deckel.id)
    nur_aktive = db.clubdeckel_artikel.list_for_deckel(deckel.id, nur_aktive=True)
    assert {a['name'] for a in alle} == {'Bier', 'Steak', 'Wasser'}
    assert {a['name'] for a in nur_aktive} == {'Bier', 'Wasser'}


def test_konsum_24h_striche_und_letzte_konsum(db):
    man = _make_mannschaft(db)
    _, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    deckel = db.clubdeckel.create(man, "Teamtresor", 't')
    gruppe = db.clubdeckel_gruppen.create(deckel.id, "Getränke", None, 1, 0, 't')
    bier = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Bier", Decimal('1.50'), 1, 0, 't')
    wasser = db.clubdeckel_artikel.create(deckel.id, gruppe.id, "Wasser", Decimal('1.00'), 1, 0, 't')

    for _ in range(5):
        db.clubdeckel_buchungen.create_konsum(deckel.id, mid, bier.id, bier.name, 1,
                                              bier.preis, None, 't')
    db.clubdeckel_buchungen.create_konsum(deckel.id, mid, wasser.id, wasser.name, 1,
                                          wasser.preis, None, 't')

    stats = db.clubdeckel_buchungen.konsum_24h(deckel.id, mid)
    assert stats['anzahl'][bier.id] == 5
    assert stats['anzahl'][wasser.id] == 1
    assert stats['summe'] == Decimal('8.50')  # 5×1,50 + 1×1,00, positiv

    # Undo: jüngsten Bier-Strich zurücknehmen -> Anzahl sinkt auf 4
    letzte = db.clubdeckel_buchungen.letzte_konsum_id(deckel.id, mid, bier.id)
    assert letzte is not None
    assert db.clubdeckel_buchungen.storno(letzte, 't')
    stats2 = db.clubdeckel_buchungen.konsum_24h(deckel.id, mid)
    assert stats2['anzahl'][bier.id] == 4
    # Buchung außerhalb des 24h-Fensters zählt nicht mit
    with db.cursor() as cur:
        cur.execute("UPDATE clubdeckel_buchung SET created_at = now() - interval '2 days' "
                    "WHERE deckel_id=%s AND artikel_id=%s AND deleted_at IS NULL",
                    (deckel.id, wasser.id))
    assert wasser.id not in db.clubdeckel_buchungen.konsum_24h(deckel.id, mid)['anzahl']


def test_get_kader_mitglied_id(db):
    man = _make_mannschaft(db)
    uid, mid = _make_kader_user(db, man, 'spieler', 'Anna')
    assert db.clubdeckel.get_kader_mitglied_id(uid, man) == mid
    assert db.clubdeckel.get_kader_mitglied_id(uid, man + 999) is None
