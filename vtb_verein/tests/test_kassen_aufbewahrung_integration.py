"""
Was mit Kassendaten über die Zeit passiert – gegen echtes PostgreSQL (#189).

Zwei Fehler dieser Art sind still, und beide werden hier abgesichert:

1. **Saldovortrag.** ``kassenbuchung_alter`` schiebt Buchungen nach zehn Jahren per
   Soft-Delete in den Papierkorb, ``get_bestand_cent`` summiert aber nur über AKTIVE
   Zeilen – der Kassenbestand wäre nach dem ersten Prune-Lauf um die Summe der
   archivierten Buchungen verrutscht, ohne Fehlermeldung und ohne dass irgendwo eine
   Buchung fehlt, die man vermissen würde.

2. **Storno-Kaskade.** Tor 4 des Prune fragt ``NOT EXISTS`` ohne ``deleted_at``-Filter.
   Ein Anhang, den beim Stornieren niemand mitnimmt, hält seine Buchung dauerhaft im
   Papierkorb fest – sie wird nie endgültig gelöscht, und auch das fällt niemandem auf.

Fakes würden beides durchgehen lassen: Es geht um das Zusammenspiel von UPDATE … FROM,
Audit-Triggern und dem realen Registry-Lauf.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --rm --name vtb-pg-eb -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=ebtest -e TZ=Europe/Berlin -p 55437:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55437/ebtest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_kassen_aufbewahrung_integration.py
"""
import os
import tempfile
from datetime import date

import pytest

from app.models.kasse import Kasse, Kassenbuchung
from app.services.kassenbuch_service import AnfangsbestandGesperrtError

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# Alt genug, dass die Zehn-Jahres-Frist in jedem Fall abgelaufen ist – unabhängig
# davon, wann der Test läuft.
ALT_1 = "2010-03-05"
ALT_2 = "2010-07-01"


@pytest.fixture(scope="module")
def uploads():
    with tempfile.TemporaryDirectory(prefix="vtb-eb-uploads-") as pfad:
        yield pfad


@pytest.fixture(scope="module")
def db(uploads):
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path=uploads)
    yield d
    d.close()


@pytest.fixture(scope="module")
def hochlader(db):
    """Wer den Anhang hochlädt – ``hochgeladen_von`` ist ein FK auf users.

    Ohne Mailadresse (Konto ohne Zugang): Der Test braucht keine, und ein
    wiederverwendeter Container liefe sonst in die Unique-Bremse.
    """
    return (db.users.get_by_username("ebkassenwart")
            or db.users.create("ebkassenwart", None, "x", "mitglied", created_by="TEST"))


@pytest.fixture
def svc(db):
    from app.services.prune_service import PruneService
    return PruneService(db)


@pytest.fixture(autouse=True)
def sauber(db):
    """Vor jedem Test alle Kassen-Daten weg – die Tests lassen echte Prune-Läufe los,
    Reste würden sich sonst gegenseitig in die Summen rechnen."""
    with db.cursor() as cur:
        cur.execute("TRUNCATE kassen, kassenbuchungen, kassen_zaehlungen, "
                    "kassenbuch_exporte, kassenbuchung_anhaenge, "
                    "kasse_berechtigungen CASCADE")
        cur.execute("DELETE FROM kassen_history")
        cur.execute("DELETE FROM kassenbuchungen_history")
    yield


def _kasse(db, anfangsbestand_cent=10000, name="Vortragskasse"):
    return db.kassen.create_kasse(
        Kasse(name=name, anfangsbestand_cent=anfangsbestand_cent), created_by="TEST")


def _buchung(db, kasse_id, datum, einnahme=0, ausgabe=0, text="Test"):
    """Direkt übers Repository: Der Service prüft das Datum gegen den erlaubten
    Bereich und ließe die zehn Jahre alten Belege dieses Tests nicht durch."""
    nr = db.kassenbuch._buchung.get_naechste_belegnummer(kasse_id)
    return db.kassenbuch._buchung.create_kassenbuchung(
        Kassenbuchung(kasse_id=kasse_id, buchungsdatum=datum, buchungstext=text,
                      kategorie="Sonstiges", einnahme_cent=einnahme,
                      ausgabe_cent=ausgabe, belegnummer=nr),
        created_by="TEST")


def _heute():
    return date.today().isoformat()


def _altern(db, tage):
    """Lässt Zeit vergehen: alle Papierkorb- und History-Uhren der Kassendaten
    zurückdatieren. Die History muss mit, sonst hielte Tor 5 die Buchung fest."""
    with db.cursor() as cur:
        for tabelle in ("kassenbuchungen", "kassenbuchung_anhaenge", "kassen_zaehlungen"):
            cur.execute(f"UPDATE {tabelle} SET deleted_at = deleted_at - "
                        f"make_interval(days => %s) WHERE deleted_at IS NOT NULL", (tage,))
        cur.execute("UPDATE kassenbuchungen_history SET "
                    "created_at = created_at - make_interval(days => %s), "
                    "updated_at = updated_at - make_interval(days => %s), "
                    "deleted_at = deleted_at - make_interval(days => %s)",
                    (tage, tage, tage))


def _zaehle(db, sql_und_params):
    sql, params = sql_und_params
    with db.cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchone()["n"]


def _entity_ohne_mindestanzahl(name):
    """Die echte Registry-Entität mit keep_min=0.

    Tor 3 hält die zuletzt Gelöschten pauschal zurück und würde in Tests mit wenigen
    Zeilen jedes andere Tor überdecken – hier soll aber genau ein anderes Tor gemessen
    werden. Sonst bleibt die Entität unverändert, damit die Tests die echte Registry
    prüfen und nicht eine Nachbildung.
    """
    from app.services.prune_service import PRUNE_REGISTRY
    from dataclasses import replace
    return replace(next(e for e in PRUNE_REGISTRY if e.name == name), keep_min=0)


def _anhang_entity():
    return _entity_ohne_mindestanzahl("kassenbuchung_anhang")


class TestVortragBeimArchivieren:

    def test_bestand_bleibt_nach_dem_archivieren_gleich(self, db, svc):
        """Der eigentliche Punkt von #189."""
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        _buchung(db, k.id, ALT_2, ausgabe=2000)
        _buchung(db, k.id, _heute(), einnahme=700)
        vorher = db.kassen.get_bestand_cent(k.id)
        assert vorher == 10000 + 5000 - 2000 + 700

        svc.prune(dry_run=False)

        assert db.kassen.get_bestand_cent(k.id) == vorher

    def test_alte_buchungen_sind_wirklich_weg(self, db, svc):
        """Gegenprobe: Der Bestand stimmt nicht etwa, weil gar nichts archiviert wurde."""
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        _buchung(db, k.id, _heute(), einnahme=700)

        svc.prune(dry_run=False)

        aktiv = db.kassenbuch._buchung.list_kassenbuchungen(k.id, include_storniert=False)
        assert [b.buchungsdatum for b in aktiv] == [_heute()]

    def test_summe_landet_im_anfangsbestand(self, db, svc):
        k = _kasse(db, anfangsbestand_cent=10000)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        _buchung(db, k.id, ALT_2, ausgabe=2000)

        svc.prune(dry_run=False)

        assert db.kassen.get_kasse(k.id).anfangsbestand_cent == 13000

    def test_stichtag_ist_der_tag_nach_der_letzten_archivierten_buchung(self, db, svc):
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        _buchung(db, k.id, ALT_2, ausgabe=2000)
        _buchung(db, k.id, _heute(), einnahme=700)

        svc.prune(dry_run=False)

        assert db.kassen.get_kasse(k.id).anfangsbestand_ab == "2010-07-02"

    def test_kasse_ohne_faellige_buchungen_bleibt_unberuehrt(self, db, svc):
        k = _kasse(db, anfangsbestand_cent=4200, name="Junge Kasse")
        _buchung(db, k.id, _heute(), einnahme=700)

        svc.prune(dry_run=False)

        nachher = db.kassen.get_kasse(k.id)
        assert nachher.anfangsbestand_cent == 4200
        assert nachher.anfangsbestand_ab is None
        assert nachher.version == k.version      # kein Leerlauf-Bump

    def test_zweiter_lauf_zaehlt_nicht_doppelt(self, db, svc):
        """Rollierend: Beim zweiten Lauf sind die alten Zeilen schon archiviert und
        fallen aus der Summe – der Vortrag darf sie nicht erneut aufschlagen."""
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        _buchung(db, k.id, _heute(), einnahme=700)

        svc.prune(dry_run=False)
        nach_erstem = db.kassen.get_kasse(k.id).anfangsbestand_cent
        bestand = db.kassen.get_bestand_cent(k.id)
        svc.prune(dry_run=False)

        assert db.kassen.get_kasse(k.id).anfangsbestand_cent == nach_erstem
        assert db.kassen.get_bestand_cent(k.id) == bestand

    def test_mehrere_kassen_werden_getrennt_verrechnet(self, db, svc):
        """UPDATE … FROM über eine gruppierte Unterabfrage – ein fehlendes GROUP BY
        würde beiden Kassen die Gesamtsumme aufschlagen."""
        a = _kasse(db, anfangsbestand_cent=0, name="Kasse A")
        b = _kasse(db, anfangsbestand_cent=0, name="Kasse B")
        _buchung(db, a.id, ALT_1, einnahme=5000)
        _buchung(db, b.id, ALT_1, ausgabe=300)

        svc.prune(dry_run=False)

        assert db.kassen.get_kasse(a.id).anfangsbestand_cent == 5000
        assert db.kassen.get_kasse(b.id).anfangsbestand_cent == -300

    def test_verschiebung_steht_in_der_history(self, db, svc):
        """Ohne version-Bump gäbe es keine kassen_history-Zeile und niemand könnte
        später nachvollziehen, woher der neue Anfangsbestand kommt."""
        k = _kasse(db, anfangsbestand_cent=10000)
        _buchung(db, k.id, ALT_1, einnahme=5000)

        svc.prune(dry_run=False)

        with db.cursor() as cur:
            cur.execute("SELECT version, anfangsbestand_cent, anfangsbestand_ab, updated_by "
                        "FROM kassen_history WHERE id = %s ORDER BY version", (k.id,))
            zeilen = [dict(r) for r in cur.fetchall()]
        assert zeilen[0]["anfangsbestand_cent"] == 10000
        assert zeilen[-1]["anfangsbestand_cent"] == 15000
        assert zeilen[-1]["anfangsbestand_ab"] == "2010-03-06"
        assert zeilen[-1]["updated_by"] == "SYSTEM-PRUNE"

    def test_report_zeigt_den_vortrag_vorher_an(self, db, svc):
        """Vorschau = Aktion: Der Admin muss den Betrag sehen, bevor er auslöst."""
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        _buchung(db, k.id, ALT_2, ausgabe=2000)

        zeile = {e["name"]: e for e in svc.report()["entities"]}["kassenbuchung_alter"]

        assert zeile["vortrag_cent"] == 3000
        assert zeile["archivierbar"] == 2

    def test_report_veraendert_nichts(self, db, svc):
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)

        svc.report()

        assert db.kassen.get_kasse(k.id).anfangsbestand_cent == 10000
        assert db.kassen.get_bestand_cent(k.id) == 15000

    def test_lauf_meldet_den_vortrag_zurueck(self, db, svc):
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, ausgabe=1200)

        ergebnis = svc.prune(dry_run=False)

        zeile = {e["name"]: e for e in ergebnis["entities"]}["kassenbuchung_alter"]
        assert zeile["vortrag_cent"] == -1200
        assert zeile["archiviert"] == 1


class TestAnfangsbestandSperre:

    def test_frisch_angelegt_ist_nicht_gesperrt(self, db):
        k = _kasse(db)
        _buchung(db, k.id, _heute(), einnahme=700)
        assert db.kassen.ist_anfangsbestand_gesperrt(k.id) is False

    def test_tippfehler_bleibt_korrigierbar(self, db):
        """Solange nichts abgerechnet ist, soll ein falsch erfasster Anfangsbestand
        nicht per Umbuchung geradegerückt werden müssen."""
        k = _kasse(db, anfangsbestand_cent=10000)
        k.anfangsbestand_cent = 12000
        assert db.kassenbuch.update_kasse(k, updated_by="TEST") is True
        assert db.kassen.get_kasse(k.id).anfangsbestand_cent == 12000

    def test_export_sperrt(self, db):
        k = _kasse(db)
        b = _buchung(db, k.id, _heute(), einnahme=700)
        with db.cursor() as cur:
            cur.execute("INSERT INTO kassenbuch_exporte (kasse_id, zeitraum_von, "
                        "zeitraum_bis, exportiert_von, dateiname, anzahl_buchungen, "
                        "created_by) VALUES (%s, %s, %s, 'TEST', 'x.csv', 1, 'TEST') "
                        "RETURNING id", (k.id, _heute(), _heute()))
            export_id = cur.fetchone()["id"]
            cur.execute("UPDATE kassenbuchungen SET exportiert_in_export_id = %s "
                        "WHERE id = %s", (export_id, b.id))

        assert db.kassen.ist_anfangsbestand_gesperrt(k.id) is True

    def test_stornierte_exportierte_buchung_sperrt_weiter(self, db):
        """Der Export ist raus – dass die Zeile später storniert wurde, holt ihn nicht
        zurück. Deshalb fragt die Sperre bewusst nicht nach deleted_at."""
        k = _kasse(db)
        b = _buchung(db, k.id, _heute(), einnahme=700)
        with db.cursor() as cur:
            cur.execute("INSERT INTO kassenbuch_exporte (kasse_id, zeitraum_von, "
                        "zeitraum_bis, exportiert_von, dateiname, anzahl_buchungen, "
                        "created_by) VALUES (%s, %s, %s, 'TEST', 'x.csv', 1, 'TEST') "
                        "RETURNING id", (k.id, _heute(), _heute()))
            export_id = cur.fetchone()["id"]
            cur.execute("UPDATE kassenbuchungen SET exportiert_in_export_id = %s, "
                        "deleted_at = CURRENT_TIMESTAMP, deleted_by = 'TEST' "
                        "WHERE id = %s", (export_id, b.id))

        assert db.kassen.ist_anfangsbestand_gesperrt(k.id) is True

    def test_vortrag_sperrt(self, db, svc):
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        svc.prune(dry_run=False)

        assert db.kassen.ist_anfangsbestand_gesperrt(k.id) is True

    def test_gesperrte_kasse_weist_die_aenderung_ab(self, db, svc):
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        svc.prune(dry_run=False)

        aktuell = db.kassen.get_kasse(k.id)
        aktuell.anfangsbestand_cent = 1
        with pytest.raises(AnfangsbestandGesperrtError):
            db.kassenbuch.update_kasse(aktuell, updated_by="TEST")

        assert db.kassen.get_kasse(k.id).anfangsbestand_cent == 15000

    def test_uebrige_stammdaten_bleiben_aenderbar(self, db, svc):
        """Gesperrt ist der Anfangsbestand, nicht die Kasse."""
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        svc.prune(dry_run=False)

        aktuell = db.kassen.get_kasse(k.id)
        aktuell.name = "Umbenannt"
        assert db.kassenbuch.update_kasse(aktuell, updated_by="TEST") is True
        assert db.kassen.get_kasse(k.id).name == "Umbenannt"


class TestKassenbericht:

    def test_bericht_weist_auf_archivierte_buchungen_hin(self, db, svc):
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        _buchung(db, k.id, _heute(), einnahme=700)
        svc.prune(dry_run=False)

        daten = db.kassenbuch.get_kassenbericht_daten(k.id, "2009-01-01", _heute())

        assert daten["archiviert_bis"] == "2010-03-05"

    def test_bericht_ohne_ueberlappung_ohne_hinweis(self, db, svc):
        k = _kasse(db)
        _buchung(db, k.id, ALT_1, einnahme=5000)
        _buchung(db, k.id, _heute(), einnahme=700)
        svc.prune(dry_run=False)

        heute = _heute()
        daten = db.kassenbuch.get_kassenbericht_daten(k.id, heute, heute)

        assert daten["archiviert_bis"] is None


class TestStornoKaskade:
    """Beim Stornieren müssen Beleg und Zählung mit in den Papierkorb – sonst hält
    Tor 4 die Buchung dort für immer fest."""

    def _anhang(self, db, buchung_id, hochlader, name="beleg.pdf"):
        return db.kassenbuch.add_anhang(
            buchung_id=buchung_id, original_name=name, mime_type="application/pdf",
            inhalt=b"%PDF-1.4 Testbeleg", hochgeladen_von=hochlader.id)

    def test_storno_nimmt_den_beleg_mit(self, db, hochlader):
        k = _kasse(db)
        b = _buchung(db, k.id, _heute(), einnahme=700)
        a = self._anhang(db, b.id, hochlader)

        db.kassenbuch._buchung.mark_kassenbuchung_deleted(b.id, deleted_by="TEST")

        with db.cursor() as cur:
            cur.execute("SELECT deleted_at, deleted_by FROM kassenbuchung_anhaenge "
                        "WHERE id = %s", (a.id,))
            zeile = cur.fetchone()
        assert zeile["deleted_at"] is not None
        assert zeile["deleted_by"] == "TEST"

    def test_kette_laeuft_bis_zur_buchung_durch(self, db, hochlader):
        """Der eigentliche Punkt: Ohne Kaskade landet der Anhang nie im Papierkorb, wird
        damit nie Prune-Kandidat – und Tor 4 hielte die stornierte Buchung für immer
        fest. Geprüft wird die ganze Kette (keep_min=0 blendet Tor 3 aus)."""
        from app.services.prune_service import build_original_candidate_count_sql
        k = _kasse(db)
        b = _buchung(db, k.id, _heute(), einnahme=700)
        self._anhang(db, b.id, hochlader)
        db.kassenbuch._buchung.mark_kassenbuchung_deleted(b.id, deleted_by="TEST")
        _altern(db, 400)

        anhang = build_original_candidate_count_sql(
            _anhang_entity(), 90, 0, 365, parent_hold_days=365)
        buchung = build_original_candidate_count_sql(
            _entity_ohne_mindestanzahl("kassenbuchung"), 90, 0, 365)

        assert _zaehle(db, anhang) == 1      # ohne Kaskade: 0, weil nie im Papierkorb
        assert _zaehle(db, buchung) == 0     # Tor 4 – der Anhang liegt noch da

        with db.cursor() as cur:             # einen Lauf später ist er weg
            cur.execute("DELETE FROM kassenbuchung_anhaenge WHERE buchung_id = %s", (b.id,))
        assert _zaehle(db, buchung) == 1

    def test_storno_nimmt_die_zaehlung_mit(self, db):
        """Die Zählung hängt an ihrer Differenzbuchung und stirbt mit ihr."""
        k = _kasse(db)
        b = _buchung(db, k.id, _heute(), einnahme=700, text="Zählung")
        with db.cursor() as cur:
            cur.execute("INSERT INTO kassen_zaehlungen (kasse_id, buchung_id, ist_cent, "
                        "soll_cent, differenz_cent, created_by, updated_by) "
                        "VALUES (%s, %s, 700, 700, 0, 'TEST', 'TEST') RETURNING id",
                        (k.id, b.id))
            zid = cur.fetchone()["id"]

        db.kassenbuch._buchung.mark_kassenbuchung_deleted(b.id, deleted_by="TEST")

        with db.cursor() as cur:
            cur.execute("SELECT deleted_at, version FROM kassen_zaehlungen WHERE id = %s",
                        (zid,))
            zeile = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS n FROM kassen_zaehlungen_history WHERE id = %s",
                        (zid,))
            history = cur.fetchone()["n"]
        assert zeile["deleted_at"] is not None
        assert zeile["version"] == 2          # Bump, sonst schriebe der Trigger nichts
        assert history == 2                   # Anlage + Soft-Delete

    def test_ausloesende_buchung_bleibt_verschont(self, db):
        """Sie ist nur der Anlass der Zählung, nicht ihr Träger – ihr Storno darf das
        Zählprotokoll nicht mitreißen."""
        k = _kasse(db)
        traeger = _buchung(db, k.id, _heute(), einnahme=700, text="Differenz")
        anlass = _buchung(db, k.id, _heute(), einnahme=100, text="Anlass")
        with db.cursor() as cur:
            cur.execute("INSERT INTO kassen_zaehlungen (kasse_id, buchung_id, "
                        "ausloesende_buchung_id, ist_cent, soll_cent, differenz_cent, "
                        "created_by, updated_by) VALUES (%s, %s, %s, 800, 800, 0, "
                        "'TEST', 'TEST') RETURNING id", (k.id, traeger.id, anlass.id))
            zid = cur.fetchone()["id"]

        db.kassenbuch._buchung.mark_kassenbuchung_deleted(anlass.id, deleted_by="TEST")

        with db.cursor() as cur:
            cur.execute("SELECT deleted_at FROM kassen_zaehlungen WHERE id = %s", (zid,))
            assert cur.fetchone()["deleted_at"] is None

    def test_zweites_storno_meldet_false(self, db, hochlader):
        """Die Kaskade darf die Idempotenz nicht kaputtmachen."""
        k = _kasse(db)
        b = _buchung(db, k.id, _heute(), einnahme=700)
        self._anhang(db, b.id, hochlader)

        assert db.kassenbuch._buchung.mark_kassenbuchung_deleted(b.id, "TEST") is True
        assert db.kassenbuch._buchung.mark_kassenbuchung_deleted(b.id, "TEST") is False


class TestBelegLebensdauer:
    """Tor 6: Der Beleg darf nicht lange vor der Buchung endgültig verschwinden."""

    def test_beleg_wartet_auf_seine_buchung(self, db, hochlader, svc):
        """Nach 100 Tagen ist die eigene Frist des Anhangs (90 T) abgelaufen, das
        History-Fenster der Buchung (365 T) nicht – ohne Tor 6 wäre der Beleg hier
        schon weg, während die Buchung noch neun Monate im Papierkorb liegt."""
        from app.services.prune_service import build_original_candidate_count_sql
        entity = _anhang_entity()
        k = _kasse(db)
        b = _buchung(db, k.id, _heute(), einnahme=700)
        db.kassenbuch.add_anhang(buchung_id=b.id, original_name="beleg.pdf",
                                 mime_type="application/pdf", inhalt=b"%PDF x",
                                 hochgeladen_von=hochlader.id)
        db.kassenbuch._buchung.mark_kassenbuchung_deleted(b.id, deleted_by="TEST")

        _altern(db, 100)
        assert _zaehle(db, build_original_candidate_count_sql(entity, 90, 0, 365, parent_hold_days=365)) == 0

        _altern(db, 300)          # zusammen 400 Tage – jetzt sind beide Fenster durch
        assert _zaehle(db, build_original_candidate_count_sql(entity, 90, 0, 365, parent_hold_days=365)) == 1

    def test_eigenstaendig_geloeschter_beleg_wartet_nicht(self, db, hochlader):
        """Ein versehentlich hochgeladenes Dokument an einer AKTIVEN Buchung soll nach
        der kurzen Frist verschwinden und nicht ein Jahr liegen bleiben."""
        from app.services.prune_service import build_original_candidate_count_sql
        entity = _anhang_entity()
        k = _kasse(db)
        b = _buchung(db, k.id, _heute(), einnahme=700)
        a = db.kassenbuch.add_anhang(buchung_id=b.id, original_name="falsch.pdf",
                                     mime_type="application/pdf", inhalt=b"%PDF x",
                                     hochgeladen_von=hochlader.id)
        db.kassenbuch.mark_anhang_deleted(a.id, deleted_by="TEST")

        _altern(db, 100)          # Buchung bleibt aktiv, nur der Anhang ist im Papierkorb

        assert _zaehle(db, build_original_candidate_count_sql(entity, 90, 0, 365, parent_hold_days=365)) == 1

    def test_hold_tage_folgen_der_konfiguration(self, db, svc):
        """Wer die Frist der Buchung verkürzt, verkürzt die Wartezeit des Belegs mit –
        sonst liefen die beiden wieder auseinander."""
        from app.services.prune_service import PRUNE_REGISTRY
        entity = next(e for e in PRUNE_REGISTRY if e.name == "kassenbuchung_anhang")
        cfg = svc.effective_config()
        assert svc._parent_hold_days(entity, cfg) == cfg["kassenbuchung"]["history_retention_days"]

        db.prune_einstellungen.upsert("kassenbuchung", 30, 10, 45, updated_by="TEST")
        try:
            assert svc._parent_hold_days(entity, svc.effective_config()) == 45
        finally:
            db.prune_einstellungen.delete("kassenbuchung", deleted_by="TEST")
