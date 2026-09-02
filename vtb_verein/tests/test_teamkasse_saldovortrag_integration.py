"""
Wie das Teamkassen-Ledger altert – gegen echtes PostgreSQL (#187).

Das Ledger kennt keinen Periodenabschluss: Der Saldo eines Mitglieds ist
``SUM(betrag)`` über seine AKTIVEN Zeilen. Alte Buchungen einfach zu archivieren
verschöbe den Saldo um deren Summe – lautlos, ohne Fehlermeldung und ohne dass
irgendwo eine Buchung fehlte, die man vermissen würde. Genau deshalb war
``clubdeckel_buchung`` die einzige Bewegungstabelle ohne Alters-Regel, und genau
deshalb konnte ein Mitglied, das je in einer Teamkasse gebucht hat, über Tor 4 des
Prune (``NOT EXISTS`` ohne ``deleted_at``-Filter) nie endgültig gelöscht werden.

Geprüft wird beides: dass der Saldovortrag die Salden nicht verschiebt – und dass
der Löschpfad am Ende wirklich bis zum Mitglied durchläuft.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --rm --name vtb-pg-cd -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=cdtest -e TZ=Europe/Berlin -p 55433:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55433/cdtest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_teamkasse_saldovortrag_integration.py
"""
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# Die Frist steht auf fünf Jahren; ALT liegt sicher davor, JUNG sicher dahinter.
ALT_TAGE = 6 * 365
JUNG_TAGE = 30

# Alles, was ein kompletter Teamkassen-Löschbatch anfasst, plus mitglied – die
# Tabellen, deren Uhren der Ketten-Test vorstellen muss.
KETTEN_TABELLEN = (
    "clubdeckel_buchung", "clubdeckel_artikel", "clubdeckel_gruppe",
    "clubdeckel_berechtigung", "clubdeckel_beitrag_befreiung",
    "clubdeckel_event", "clubdeckel_event_opt_out", "clubdeckel",
    "mitglied_mannschaft", "mitglied",
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-vortrag-uploads")
    yield d
    d.close()


@pytest.fixture
def svc(db):
    from app.services.prune_service import PruneService
    return PruneService(db)


def _leeren(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE clubdeckel_buchung, clubdeckel_artikel, clubdeckel_gruppe, "
            "clubdeckel_berechtigung, clubdeckel_beitrag_befreiung, "
            "clubdeckel_event, clubdeckel_event_opt_out, clubdeckel, "
            "mitglied, mitglied_mannschaft, mannschaft, abteilung, termine CASCADE"
        )
        for tabelle in ("clubdeckel_buchung", "clubdeckel_artikel", "clubdeckel_gruppe",
                        "clubdeckel_berechtigung", "clubdeckel_beitrag_befreiung",
                        "clubdeckel_event", "clubdeckel_event_opt_out", "clubdeckel",
                        "mitglied", "mitglied_mannschaft", "mannschaft", "termine"):
            cur.execute(f"DELETE FROM {tabelle}_history")


@pytest.fixture(autouse=True)
def sauber(db):
    """Vor UND nach jedem Test: Die Tests lassen echte Prune-Läufe los, und ein
    liegengelassenes Mitglied verfälscht beim nächsten Lauf im selben Container die
    Statistik-Tests anderer Module (die zählen über den ganzen Bestand)."""
    _leeren(db)
    yield
    _leeren(db)


@pytest.fixture
def ohne_mindestanzahl(db):
    """Tor 3 (``keep_min``) hält die zuletzt Gelöschten pauschal zurück und würde in
    Tests mit einer Handvoll Zeilen jedes andere Tor überdecken."""
    for name in ("clubdeckel_buchung", "clubdeckel_artikel", "clubdeckel_gruppe",
                 "clubdeckel_berechtigung", "clubdeckel_beitrag_befreiung",
                 "clubdeckel_event", "clubdeckel_event_opt_out", "clubdeckel",
                 "mitglied", "mitglied_abteilung", "mitglied_kontakt",
                 "mitglied_funktion", "mitglied_mannschaft"):
        db.prune_einstellungen.upsert(name, 90, 0, 365, updated_by="TEST")
    yield


# --- Anlegen -----------------------------------------------------------------------
def _deckel(db, aktiv=1, name="Vortragskasse"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES ('Vortrag-Abt', 'TEST', 'TEST') RETURNING id")
        aid = cur.fetchone()["id"]
        cur.execute("INSERT INTO mannschaft (abteilung_id, name, saison, created_by, "
                    "updated_by) VALUES (%s, 'Erste', '2026/27', 'TEST', 'TEST') "
                    "RETURNING id", (aid,))
        man = cur.fetchone()["id"]
        cur.execute("INSERT INTO clubdeckel (mannschaft_id, name, aktiv, created_by, "
                    "updated_by) VALUES (%s, %s, %s, 'TEST', 'TEST') RETURNING id",
                    (man, name, aktiv))
        return cur.fetchone()["id"]


def _mitglied(db, vorname="Anna", austritt=None):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied (vorname, nachname, zahlungsart, "
                    "austrittsdatum, created_by, updated_by) "
                    "VALUES (%s, 'Vortragstest', 'sonstiges', %s, 'TEST', 'TEST') "
                    "RETURNING id", (vorname, austritt or ""))
        return cur.fetchone()["id"]


def _buchung(db, deckel_id, mitglied_id, betrag, tage_alt, typ="einkauf",
             paar_ref=None):
    """Eine Ledger-Zeile mit frei gewähltem Buchungszeitpunkt.

    Direktes SQL statt der create_*-Methoden: Nur so lässt sich ``created_at``
    beliebig weit zurückdatieren, und genau daran hängt die Fälligkeit."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO clubdeckel_buchung (deckel_id, mitglied_id, typ, betrag, "
            "paar_ref, created_at, created_by, updated_by) "
            "VALUES (%s, %s, %s, %s, %s, now() - make_interval(days => %s), "
            "'TEST', 'TEST') RETURNING id",
            (deckel_id, mitglied_id, typ, Decimal(str(betrag)), paar_ref, tage_alt),
        )
        return cur.fetchone()["id"]


# --- Abfragen ----------------------------------------------------------------------
def _saldo(db, deckel_id, mitglied_id) -> Decimal:
    return db.clubdeckel_buchungen.saldo_for_mitglied(deckel_id, mitglied_id)


def _team_saldo(db, deckel_id) -> Decimal:
    return -sum((s["saldo"] for s in db.clubdeckel_buchungen.salden(deckel_id)),
                Decimal("0"))


def _zeilen(db, deckel_id, mitglied_id=None, typ=None, aktiv=True) -> int:
    sql = ("SELECT COUNT(*) AS n FROM clubdeckel_buchung WHERE deckel_id = %s"
           + (" AND deleted_at IS NULL" if aktiv else ""))
    params = [deckel_id]
    if mitglied_id is not None:
        sql += " AND mitglied_id = %s"
        params.append(mitglied_id)
    if typ is not None:
        sql += " AND typ = %s"
        params.append(typ)
    with db.cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchone()["n"]


def _existiert(db, tabelle, zeilen_id) -> bool:
    with db.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {tabelle} WHERE id = %s", (zeilen_id,))
        return cur.fetchone() is not None


def _altern(db, tage):
    """Papierkorb- und History-Uhren der ganzen Kette zurückdatieren – ohne die
    History hielte Tor 5 jede Zeile fest."""
    with db.cursor() as cur:
        for tabelle in KETTEN_TABELLEN:
            cur.execute(f"UPDATE {tabelle} SET deleted_at = deleted_at - "
                        f"make_interval(days => %s) WHERE deleted_at IS NOT NULL",
                        (tage,))
            cur.execute(f"UPDATE {tabelle}_history SET "
                        "created_at = created_at - make_interval(days => %s), "
                        "updated_at = updated_at - make_interval(days => %s), "
                        "deleted_at = deleted_at - make_interval(days => %s)",
                        (tage, tage, tage))


class TestSaldovortrag:

    def test_saldo_bleibt_nach_dem_vortrag_gleich(self, db, svc):
        """Der eigentliche Punkt von #187."""
        d = _deckel(db)
        m = _mitglied(db)
        _buchung(db, d, m, -12.50, ALT_TAGE)
        _buchung(db, d, m, 30.00, ALT_TAGE, typ="zahlung")
        _buchung(db, d, m, -5.00, JUNG_TAGE)
        vorher = _saldo(db, d, m)
        assert vorher == Decimal("12.50")

        svc.prune(dry_run=False)

        assert _saldo(db, d, m) == vorher

    def test_alte_buchungen_sind_wirklich_weg(self, db, svc):
        """Gegenprobe: Der Saldo stimmt nicht etwa, weil gar nichts passiert ist."""
        d = _deckel(db)
        m = _mitglied(db)
        _buchung(db, d, m, -12.50, ALT_TAGE)
        _buchung(db, d, m, 30.00, ALT_TAGE, typ="zahlung")
        _buchung(db, d, m, -5.00, JUNG_TAGE)

        svc.prune(dry_run=False)

        # Übrig: die junge Buchung + genau eine Vortragszeile.
        assert _zeilen(db, d, m) == 2
        assert _zeilen(db, d, m, typ="vortrag") == 1

    def test_junge_buchung_bleibt_unangetastet(self, db, svc):
        d = _deckel(db)
        m = _mitglied(db)
        jung = _buchung(db, d, m, -5.00, JUNG_TAGE)
        _buchung(db, d, m, -1.00, ALT_TAGE)

        svc.prune(dry_run=False)

        with db.cursor() as cur:
            cur.execute("SELECT deleted_at, vortrag_ref FROM clubdeckel_buchung "
                        "WHERE id = %s", (jung,))
            zeile = cur.fetchone()
        assert zeile["deleted_at"] is None and zeile["vortrag_ref"] is None

    def test_rollierend_bleibt_es_bei_einer_vortragszeile(self, db, svc):
        """Die Invariante, ohne die der Vortrag seinen Zweck verfehlte: Entstünde je
        Lauf eine weitere Zeile, wüchse die Menge wieder unbegrenzt – nur langsamer."""
        d = _deckel(db)
        m = _mitglied(db)
        _buchung(db, d, m, -10.00, ALT_TAGE)
        svc.prune(dry_run=False)

        _buchung(db, d, m, -7.00, ALT_TAGE + 1)   # eine weitere alte Zeile taucht auf
        svc.prune(dry_run=False)

        assert _zeilen(db, d, m, typ="vortrag") == 1
        assert _saldo(db, d, m) == Decimal("-17.00")

    def test_leerlauf_ruehrt_die_vortragszeile_nicht_an(self, db, svc):
        """Ein Lauf ohne fällige Zeilen darf die vorhandene Vortragszeile nicht
        anfassen – sonst schriebe jeder Lauf eine inhaltsgleiche History-Zeile und
        der Audit-Trail bestünde bald nur noch aus Rauschen."""
        d = _deckel(db)
        m = _mitglied(db)
        _buchung(db, d, m, -10.00, ALT_TAGE)
        svc.prune(dry_run=False)
        with db.cursor() as cur:
            cur.execute("SELECT id, version FROM clubdeckel_buchung "
                        "WHERE deckel_id = %s AND typ = 'vortrag'", (d,))
            vorher = dict(cur.fetchone())

        svc.prune(dry_run=False)
        svc.prune(dry_run=False)

        with db.cursor() as cur:
            cur.execute("SELECT id, version FROM clubdeckel_buchung "
                        "WHERE deckel_id = %s AND typ = 'vortrag'", (d,))
            nachher = dict(cur.fetchone())
        assert nachher == vorher

    def test_summe_null_laesst_kein_mitglied_zurueck(self, db, svc):
        """Wer abgerechnet hat, verschwindet restlos aus dem Ledger. Bliebe eine
        Vortragszeile über 0,00 € stehen, hielte sie ihr Mitglied über Tor 4 weiter
        fest – der eigentliche Grund für den ganzen Mechanismus wäre verfehlt."""
        d = _deckel(db)
        m = _mitglied(db)
        _buchung(db, d, m, -20.00, ALT_TAGE)
        _buchung(db, d, m, 20.00, ALT_TAGE, typ="zahlung")

        svc.prune(dry_run=False)

        assert _zeilen(db, d, m) == 0
        assert _saldo(db, d, m) == Decimal("0")

    def test_ausgeglichener_vortrag_verschwindet_wieder(self, db, svc):
        """Dasselbe eine Runde später: Erst trägt der Lauf einen Schuldenstand vor,
        dann zahlt das Mitglied – der nächste Abschluss räumt die Zeile ab."""
        d = _deckel(db)
        m = _mitglied(db)
        _buchung(db, d, m, -20.00, ALT_TAGE)
        svc.prune(dry_run=False)
        assert _zeilen(db, d, m, typ="vortrag") == 1

        _buchung(db, d, m, 20.00, ALT_TAGE, typ="zahlung")
        svc.prune(dry_run=False)

        assert _zeilen(db, d, m) == 0

    def test_team_saldo_bleibt_richtig(self, db, svc):
        """Der Team-Saldo ist die negierte Summe aller Mitgliedssalden. Weil sich die
        Vorträge beider Seiten eines Nullsummen-Paars gegenseitig aufheben, bleibt er
        auch nach dem Abschluss richtig."""
        d = _deckel(db)
        a = _mitglied(db, "Anna")
        b = _mitglied(db, "Bernd")
        ref = uuid.uuid4().hex
        _buchung(db, d, a, 15.00, ALT_TAGE, typ="zahlung", paar_ref=ref)
        _buchung(db, d, b, -15.00, ALT_TAGE, typ="zahlung", paar_ref=ref)
        _buchung(db, d, a, -40.00, ALT_TAGE)          # Konsum gegen das Team
        vorher = _team_saldo(db, d)
        assert vorher == Decimal("40.00")

        svc.prune(dry_run=False)

        assert _team_saldo(db, d) == vorher
        assert _saldo(db, d, a) == Decimal("-25.00")
        assert _saldo(db, d, b) == Decimal("-15.00")

    def test_vorschau_nennt_dieselbe_zahl_wie_der_lauf(self, db, svc):
        """„Vorschau = Aktion" – der Admin sieht vorher, wie viele Zeilen er verliert."""
        d = _deckel(db)
        m = _mitglied(db)
        for _ in range(3):
            _buchung(db, d, m, -1.00, ALT_TAGE)
        _buchung(db, d, m, -1.00, JUNG_TAGE)

        vorschau = {e["name"]: e
                    for e in svc.report()["entities"]}["clubdeckel_vortrag"]
        assert vorschau["archivierbar"] == 3
        assert vorschau["loeschbar"] == 0

        lauf = {e["name"]: e
                for e in svc.prune(dry_run=False)["entities"]}["clubdeckel_vortrag"]
        assert lauf["archiviert"] == 3


class TestVortragIstNichtUmkehrbar:
    """Der Vortrag ersetzt Zeilen durch ihre Summe. Beide Enden dieser Ersetzung
    müssen gegen die normalen Storno-Wege gesperrt sein, sonst zählt derselbe Betrag
    doppelt oder fällt ersatzlos aus dem Saldo."""

    def _mit_vortrag(self, db, svc):
        d = _deckel(db)
        m = _mitglied(db)
        alt = _buchung(db, d, m, -10.00, ALT_TAGE)
        svc.prune(dry_run=False)
        with db.cursor() as cur:
            cur.execute("SELECT id FROM clubdeckel_buchung "
                        "WHERE deckel_id = %s AND typ = 'vortrag'", (d,))
            vortrag = cur.fetchone()["id"]
        return d, m, alt, vortrag

    def test_zusammengefasste_zeile_kommt_nicht_zurueck(self, db, svc):
        """Ihr Betrag steckt bereits in der Vortragszeile – ein Wiederherstellen
        rechnete ihn ein zweites Mal in den Saldo."""
        d, m, alt, _ = self._mit_vortrag(db, svc)

        assert db.clubdeckel_buchungen.restore(alt, "TEST") is False
        assert _saldo(db, d, m) == Decimal("-10.00")

    def test_vortragszeile_laesst_sich_nicht_stornieren(self, db, svc):
        """Sie trägt die Summe längst entfernter Buchungen; ein Storno nähme diesen
        Betrag ersatzlos aus dem Saldo."""
        d, m, _, vortrag = self._mit_vortrag(db, svc)

        assert db.clubdeckel_buchungen.storno(vortrag, "TEST") is False
        assert _saldo(db, d, m) == Decimal("-10.00")

    def test_zusammengefasste_zeilen_gelten_nicht_als_storniert(self, db, svc):
        """In der History-Ansicht („Stornierte anzeigen") haben sie nichts verloren:
        Sie sind nicht storniert, sondern aufgegangen. Als Storno angezeigt wären sie
        eine Lüge – und der Wiederherstellen-Knopf daneben ein leeres Versprechen."""
        d, m, _, _ = self._mit_vortrag(db, svc)

        alle = db.clubdeckel_buchungen.list_for_deckel(d, mit_storniert=True)

        assert [b.typ for b in alle] == ["vortrag"]

    def test_normales_storno_bleibt_umkehrbar(self, db, svc):
        """Gegenprobe: Die Sperre trifft nur den Abschluss, nicht das Tagesgeschäft."""
        d = _deckel(db)
        m = _mitglied(db)
        b = _buchung(db, d, m, -3.00, JUNG_TAGE)

        assert db.clubdeckel_buchungen.storno(b, "TEST") is True
        assert db.clubdeckel_buchungen.restore(b, "TEST") is True
        assert _saldo(db, d, m) == Decimal("-3.00")


class TestToteTeamkasse:

    def test_deaktivierte_teamkasse_altert_als_batch(self, db, svc):
        """Der Batch mit gemeinsamer `loesch_ref` ist der Grund, warum die Teamkasse
        keine ArchiveRule bekommt: Nur so holt der Admin-Papierkorb sie vollständig
        zurück."""
        d = _deckel(db, aktiv=0)
        m = _mitglied(db)
        _buchung(db, d, m, -10.00, ALT_TAGE)
        with db.cursor() as cur:      # Deaktivieren liegt lange zurück
            cur.execute("UPDATE clubdeckel SET updated_at = now() - "
                        "make_interval(days => %s) WHERE id = %s", (ALT_TAGE, d))

        svc.prune(dry_run=False)

        with db.cursor() as cur:
            cur.execute("SELECT deleted_at, loesch_ref FROM clubdeckel WHERE id = %s",
                        (d,))
            zeile = cur.fetchone()
        assert zeile["deleted_at"] is not None
        assert zeile["loesch_ref"] is not None
        assert _zeilen(db, d) == 0                       # keine aktive Buchung mehr
        assert db.clubdeckel.restore(d, "TEST") == "ok"  # und vollständig umkehrbar
        assert _saldo(db, d, m) == Decimal("-10.00")

    def test_aktive_teamkasse_altert_nie(self, db, svc):
        """Auch wenn seit Jahren nichts gebucht wurde: Die Winterpause einer
        Mannschaft ist kein Grund, ihren Deckel abzuräumen."""
        d = _deckel(db, aktiv=1)
        m = _mitglied(db)
        _buchung(db, d, m, -10.00, ALT_TAGE)
        with db.cursor() as cur:
            cur.execute("UPDATE clubdeckel SET updated_at = now() - "
                        "make_interval(days => %s) WHERE id = %s", (ALT_TAGE, d))

        svc.prune(dry_run=False)

        with db.cursor() as cur:
            cur.execute("SELECT deleted_at FROM clubdeckel WHERE id = %s", (d,))
            assert cur.fetchone()["deleted_at"] is None

    def test_junge_buchung_haelt_die_teamkasse_am_leben(self, db, svc):
        """Die Uhr läuft ab dem SPÄTEREN von Deaktivieren und letzter Buchung."""
        d = _deckel(db, aktiv=0)
        m = _mitglied(db)
        _buchung(db, d, m, -10.00, JUNG_TAGE)
        with db.cursor() as cur:
            cur.execute("UPDATE clubdeckel SET updated_at = now() - "
                        "make_interval(days => %s) WHERE id = %s", (ALT_TAGE, d))

        svc.prune(dry_run=False)

        with db.cursor() as cur:
            cur.execute("SELECT deleted_at FROM clubdeckel WHERE id = %s", (d,))
            assert cur.fetchone()["deleted_at"] is None

    def test_vortragszeile_startet_die_uhr_nicht_neu(self, db, svc):
        """Vortragszeilen entstehen maschinell und tragen das Datum ihres Laufs.
        Zählten sie als Aktivität, hielte sich jede tote Teamkasse selbst am Leben –
        der Abschlusslauf würde die Uhr bei jedem Durchgang neu starten."""
        d = _deckel(db, aktiv=0)
        m = _mitglied(db)
        _buchung(db, d, m, -10.00, ALT_TAGE)
        with db.cursor() as cur:
            cur.execute("UPDATE clubdeckel SET updated_at = now() - "
                        "make_interval(days => %s) WHERE id = %s", (ALT_TAGE, d))
            # Vortragszeile von heute, ohne dass der Deckel deshalb lebt
            cur.execute(
                "INSERT INTO clubdeckel_buchung (deckel_id, mitglied_id, typ, betrag, "
                "created_by, updated_by) VALUES (%s, %s, 'vortrag', -10, 'T', 'T')",
                (d, m))

        stichtag = (date.today() - timedelta(days=5 * 365)).isoformat()
        assert db.clubdeckel.faellige_deckel_ids(stichtag) == [d]


class TestKetteLaeuftBisZumMitgliedDurch:
    """Der eigentliche Zweck von #187 – geprüft wird nicht der Vortrag, sondern sein
    Ergebnis: dass ein ausgeschiedenes Mitglied das System am Ende verlässt."""

    def test_mitglied_mit_teamkassen_vergangenheit_wird_geloescht(
            self, db, svc, ohne_mindestanzahl):
        d = _deckel(db, aktiv=0)
        m = _mitglied(db, austritt="2010-05-01")
        _buchung(db, d, m, -10.00, ALT_TAGE)
        _buchung(db, d, m, 10.00, ALT_TAGE, typ="zahlung")
        with db.cursor() as cur:
            # Der Deckel zahlt an dieses Mitglied aus – auch diese Referenz muss sich
            # auflösen, sonst hält sie das Mitglied in Tor 4 fest.
            cur.execute("UPDATE clubdeckel SET updated_at = now() - "
                        "make_interval(days => %s), zahlungsempfaenger_mitglied_id = %s "
                        "WHERE id = %s", (ALT_TAGE, m, d))

        svc.prune(dry_run=False)          # 1) Abschluss + Archivieren
        assert _existiert(db, "mitglied", m), "erst der Papierkorb, dann das Löschen"

        for _ in range(6):                # 2) die Kette Blatt → Wurzel abräumen
            _altern(db, 400)
            svc.prune(dry_run=False)
            if not _existiert(db, "mitglied", m):
                break

        assert not _existiert(db, "mitglied", m)
        assert not _existiert(db, "clubdeckel", d)

    def test_ohne_teamkasse_haengt_das_mitglied_nicht_fest(self, db, svc,
                                                           ohne_mindestanzahl):
        """Gegenprobe: Ein ausgeschiedenes Mitglied ohne Teamkassen-Vergangenheit war
        auch vorher schon löschbar – der Test oben misst also wirklich diese Kette."""
        m = _mitglied(db, austritt="2010-05-01")

        svc.prune(dry_run=False)
        _altern(db, 400)
        svc.prune(dry_run=False)

        assert not _existiert(db, "mitglied", m)
