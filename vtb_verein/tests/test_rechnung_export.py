"""Integrationstests des Rechnungs-Exports (Schema v78, FBASC seit v109).

Geprüft werden hier der Belegstapel und die Lauf-Mechanik: die Delta-Semantik
(jede Rechnung genau einmal), der Un-Export des jüngsten Laufs, der Re-Download
aus den gestempelten Zeilen, die Benennung der Belegdateien, `uebersicht.csv` und
das Verhalten bei fehlender Beleg-Datei auf dem Server.

Die Buchungszeilen der `fbasc.hia` selbst stehen in test_rechnung_fbasc_export.py.
Weil der Lauf ohne konfigurierte Konten abbricht, richtet `_setup` sie mit ein –
sonst käme man hier gar nicht erst bis zum Zip.

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

from app.services.rechnung_export_service import FibuRechnungExportFehler  # noqa: E402

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


def _aufraeumen(db):
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


@pytest.fixture(autouse=True)
def clean(db):
    # Vor UND nach dem Test aufräumen: Nur davor zu putzen lässt die Zeilen des
    # letzten Tests im geteilten Wegwerf-Postgres stehen. Vereinsweite Auswertungen
    # anderer Module zählen sie dann mit (die Statistik-KPIs in
    # test_gastspieler_integration fielen genau darüber, sobald die Suite ein
    # zweites Mal gegen dieselbe DB lief).
    _aufraeumen(db)
    yield
    _aufraeumen(db)


# ---------------------------------------------------------------- Testdaten

def _setup(db):
    """Abteilung + Einreicher + Freigeber/Geschäftsstelle – und die Fibu-Konten.

    Seit v109 rendert der Export eine `fbasc.hia` und verweigert den Lauf, solange
    Kreditor- oder Aufwandskonto fehlen. Die Konten gehören deshalb zum
    Grundaufbau jedes Export-Tests."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,kostenstelle,created_by,updated_by) "
                    "VALUES ('X-Fussball',77,'xtest','xtest') RETURNING id")
        abteilung = cur.fetchone()["id"]
    einreicher = _user(db, "xtester_ein", ("rechnungen.einreichen",), abteilung)
    gs = _user(db, "xtester_gs", ("rechnungen.verwalten",), None)
    _konten_setzen(db, gs)
    return abteilung, einreicher, gs


def _konten_setzen(db, gs):
    einst = db.fibu_einstellungen.get()
    einst.ul_kreditor_konto_basis = 70000
    einst.rechnung_kreditor_konto = "70999"
    db.fibu_einstellungen.update(einst, updated_by="xtest")
    for k in db.rechnungen.list_kategorien():
        if not k.sachkonto:
            db.rechnungen.kategorie_aktualisieren(
                k.id, gs, expected_version=k.version, sachkonto="4400")


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
                "INSERT INTO mitglied_abteilung (mitglied_id,abteilung_id,von,created_by,updated_by) "
                "VALUES (%s,%s,%s,'xtest','xtest')", (mid, abteilung_id, LASTWEEK))
    return db.get_user_by_id(uid)


def _freigegebene_rechnung(db, einreicher, gs, abteilung, *, belege=1, **felder):
    felder.setdefault("empfaenger_typ", "mitglied")   # Regelfall: Auslage erstatten
    felder.setdefault("betrag_cent", 1000)            # Pflicht beim Einreichen
    r = db.rechnungen.anlegen(
        einreicher, kategorie_id=db.rechnungen.list_kategorien()[0].id,
        abteilung_id=abteilung, **felder)
    for i in range(belege):
        db.rechnungen.add_anhang(r.id, einreicher, original_name=f"beleg{i}.png",
                                 mime_type="image/png", inhalt=_PNG)
    db.rechnungen.einreichen(r.id, einreicher)
    return db.rechnungen.freigeben(r.id, gs)


# Was im Zip neben den Belegen liegt: die Buchungsdatei für die Fibu und die
# Übersicht zum Mitlesen.
_METADATEIEN = {"fbasc.hia", "uebersicht.csv"}


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
    beleg = f"R{r.id} - Erstattung ExpTest xtester_ein - X-Fussball - " \
            f"Buerobedarf - Baelle - beleg0.jpg"     # PNG wird zu JPEG normalisiert
    assert sorted(namen) == [beleg, "fbasc.hia", "uebersicht.csv"]

    zeile = _uebersicht(zip_bytes)[0]
    assert zeile["Nr"] == f"R{r.id}"
    assert zeile["Belegdateien"] == beleg
    assert zeile["Betrag EUR"] == "12,50"                  # deutsches Dezimalkomma
    assert zeile["Rechnungsnummer"] == "RE-4711"
    assert zeile["Abteilung"] == "X-Fussball"
    assert zeile["Kostenstelle"] == "77"
    assert zeile["Freigegeben von"] == "xtester_gs"


def test_zahlungsrichtung_in_der_uebersicht(db):
    """Die Buchhaltung muss sehen, wohin das Geld fließt.

    Erstattung → Einreicher samt IBAN aus dem Mitgliedsstamm; Aussteller →
    nur die Richtung, die Bankverbindung steht auf dem Beleg.
    """
    abteilung, einreicher, gs = _setup(db)
    with db.cursor() as cur:
        cur.execute("UPDATE mitglied SET iban='DE02120300000000202051' WHERE user_id=%s",
                    (einreicher.id,))

    _freigegebene_rechnung(db, einreicher, gs, abteilung, empfaenger_typ="mitglied")
    _freigegebene_rechnung(db, einreicher, gs, abteilung, empfaenger_typ="extern")

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    zeilen = _uebersicht(zip_bytes)
    assert zeilen[0]["Zahlung an"] == "Erstattung an Einreicher"
    assert zeilen[0]["Empfaenger"] == "ExpTest xtester_ein"
    assert zeilen[0]["IBAN"] == "DE02120300000000202051"     # aus dem Mitgliedsstamm
    assert zeilen[1]["Zahlung an"] == "Rechnungsaussteller"
    assert zeilen[1]["Empfaenger"] == ""                     # steht auf dem Beleg
    assert zeilen[1]["IBAN"] == ""


def test_mehrere_belege_behalten_ihren_namen(db):
    """Belege einer Rechnung unterscheiden sich über ihren Originalnamen."""
    abteilung, einreicher, gs = _setup(db)
    r = _freigegebene_rechnung(db, einreicher, gs, abteilung, belege=3)

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    _, namen = _entpacke(zip_bytes)
    belege = sorted(n for n in namen if n not in _METADATEIEN)
    assert [n.rsplit(" - ", 1)[-1] for n in belege] == \
        ["beleg0.jpg", "beleg1.jpg", "beleg2.jpg"]
    assert all(n.startswith(f"R{r.id} - ") for n in belege)
    assert _uebersicht(zip_bytes)[0]["Belegdateien"] == " | ".join(belege)


def test_gleicher_originalname_wird_durchgezaehlt(db):
    """Zwei Belege mit identischem Namen dürfen sich im Zip nicht überschreiben."""
    abteilung, einreicher, gs = _setup(db)
    r = db.rechnungen.anlegen(einreicher, kategorie_id=db.rechnungen.list_kategorien()[0].id,
                              abteilung_id=abteilung, empfaenger_typ="mitglied",
                              betrag_cent=1000)
    for _ in range(2):
        db.rechnungen.add_anhang(r.id, einreicher, original_name="scan.png",
                                 mime_type="image/png", inhalt=_PNG)
    db.rechnungen.einreichen(r.id, einreicher)
    db.rechnungen.freigeben(r.id, gs)

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    zf, namen = _entpacke(zip_bytes)
    belege = [n for n in namen if n not in _METADATEIEN]
    assert len(set(belege)) == 2
    assert sorted(n.rsplit(" - ", 1)[-1] for n in belege) == ["scan (2).jpg", "scan.jpg"]


def test_dateiname_traegt_die_erfassten_angaben(db):
    """Solange die Fibu die uebersicht.csv nicht mitliest, muss der Dateiname
    allein sagen, an wen gezahlt wird, aus welcher Abteilung und wofür."""
    abteilung, einreicher, gs = _setup(db)
    r = _freigegebene_rechnung(db, einreicher, gs, abteilung, empfaenger_typ="extern",
                               beschreibung="Trikots F-Jugend")

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    _, namen = _entpacke(zip_bytes)
    beleg = next(n for n in namen if n not in _METADATEIEN)
    # 'Bürobedarf' ist die erste Kategorie (alphabetisch) – der Umlaut wird
    # umschrieben, nicht weggeworfen.
    assert beleg == (f"R{r.id} - Zahlung Aussteller - X-Fussball - "
                     f"Buerobedarf - Trikots F-Jugend - beleg0.jpg")


def test_dateiname_bleibt_windowstauglich(db):
    """Umlaute werden umschrieben, Sonderzeichen fliegen raus – der Name muss
    sich unter Windows entpacken lassen."""
    abteilung, einreicher, gs = _setup(db)
    _freigegebene_rechnung(db, einreicher, gs, abteilung,
                           beschreibung='Bälle/Netze: "Sport" & mehr <hier>')

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    _, namen = _entpacke(zip_bytes)
    beleg = next(n for n in namen if n not in _METADATEIEN)
    assert beleg.isascii()
    assert not set(beleg) & set('\\/:*?"<>|')
    assert "Baelle Netze" in beleg
    # Der Trenner darf nur zwischen den Bestandteilen stehen.
    assert len(beleg.split(" - ")) == 6


def test_langer_dateiname_wird_gekappt(db):
    """Windows scheitert beim Entpacken an zu langen Pfaden – der Name bleibt
    begrenzt und endet nicht auf einem angeschnittenen Trenner."""
    abteilung, einreicher, gs = _setup(db)
    _freigegebene_rechnung(db, einreicher, gs, abteilung, beschreibung="Bandenwerbung " * 20)

    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    _, namen = _entpacke(zip_bytes)
    beleg = next(n for n in namen if n != "uebersicht.csv")
    assert len(beleg) <= 160
    assert not beleg.rsplit(".", 1)[0].endswith((" ", "-", "."))


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
                              abteilung_id=abteilung, empfaenger_typ="mitglied",
                              betrag_cent=1000)
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
    """Mit dem Export ist Schluss – bis dahin bleibt alles korrigierbar."""
    from app.services.rechnung_service import RechnungGesperrtError

    abteilung, einreicher, gs = _setup(db)
    r = _freigegebene_rechnung(db, einreicher, gs, abteilung)
    db.rechnung_export.exportieren(gs.username)

    with pytest.raises(RechnungGesperrtError):
        db.rechnungen.zuruecksetzen(r.id, gs)
    with pytest.raises(RechnungGesperrtError):
        db.rechnungen.loeschen(r.id, gs)
    with pytest.raises(RechnungGesperrtError):
        db.rechnungen.ablehnen(r.id, gs, "zu spät")

    # Nach dem Un-Export greift die Korrektur wieder.
    db.rechnung_export.zuruecknehmen(db.rechnung_export.list_exporte()[0].id, gs.username)
    assert db.rechnungen.ablehnen(r.id, gs, "doch falsch").status == "abgelehnt"


def test_status_exportiert_ist_ein_eigener_filter(db):
    """'exportiert' steht nicht in der Spalte, verhält sich für die Oberfläche
    aber wie ein Status: die Rechnung erscheint danach nur noch dort."""
    abteilung, einreicher, gs = _setup(db)
    exportiert = _freigegebene_rechnung(db, einreicher, gs, abteilung)
    db.rechnung_export.exportieren(gs.username)
    offen = _freigegebene_rechnung(db, einreicher, gs, abteilung)

    assert [r.id for r in db.rechnungen.list_alle(gs, "exportiert")] == [exportiert.id]
    assert [r.id for r in db.rechnungen.list_alle(gs, "freigegeben")] == [offen.id]
    assert [r.id for r in db.rechnungen.list_meine(einreicher, "exportiert")] == [exportiert.id]
    assert sorted(r.id for r in db.rechnungen.list_zur_freigabe(gs)) == \
        [exportiert.id, offen.id]                       # ohne Filter weiter beides

    # Un-Export dreht die Zuordnung zurück – kein zweiter Zustand, der driften kann.
    db.rechnung_export.zuruecknehmen(db.rechnung_export.list_exporte()[0].id, gs.username)
    assert db.rechnungen.list_alle(gs, "exportiert") == []
    assert sorted(r.id for r in db.rechnungen.list_alle(gs, "freigegeben")) == \
        sorted([exportiert.id, offen.id])


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
    # Kein Beleg, aber ein Lauf: Buchungszeile und Übersicht entstehen trotzdem.
    assert sorted(namen) == ["fbasc.hia", "uebersicht.csv"]
    assert _uebersicht(zip_bytes)[0]["Belegdateien"] == ""


def test_summe_und_anzahl_im_header(db):
    abteilung, einreicher, gs = _setup(db)
    _freigegebene_rechnung(db, einreicher, gs, abteilung, betrag_cent=1000)
    _freigegebene_rechnung(db, einreicher, gs, abteilung, betrag_cent=2550)

    db.rechnung_export.exportieren(gs.username)
    export = db.rechnung_export.list_exporte()[0]
    assert export.anzahl_rechnungen == 2
    assert export.summe_cent == 3550


def test_rechnung_ohne_betrag_haelt_den_lauf_an(db):
    """Ohne Betrag gibt es keine Buchung – der Lauf bricht ab und nennt die Rechnung.

    Bis v108 lief der Export durch und ließ die Betragsspalte der Übersicht leer;
    die Buchungszeile tippte ohnehin jemand von Hand. Mit der `fbasc.hia` geht das
    nicht mehr: Eine Zeile über 0,00 € wäre eine sinnlose Buchung, und die Rechnung
    trüge danach den Export-Stempel, ohne je bezahlt worden zu sein. Der Betrag
    lässt sich nachtragen – von genau der Stelle, die auch exportiert.
    """
    abteilung, einreicher, gs = _setup(db)
    ohne = _freigegebene_rechnung(db, einreicher, gs, abteilung, betrag_cent=700)
    db.rechnungen.aktualisieren(ohne.id, gs, expected_version=ohne.version,
                                betrag_cent=None)
    _freigegebene_rechnung(db, einreicher, gs, abteilung, betrag_cent=500)

    with pytest.raises(FibuRechnungExportFehler) as exc:
        db.rechnung_export.exportieren(gs.username)
    assert exc.value.fehler == [f"Rechnung #{ohne.id}: kein Betrag erfasst."]
    # Nichts gestempelt: nach dem Nachtragen läuft derselbe Delta-Lauf durch.
    assert db.rechnung_export.list_exporte() == []

    db.rechnungen.aktualisieren(ohne.id, gs,
                                expected_version=db.rechnungen.get(ohne.id, gs).version,
                                betrag_cent=700)
    _, zip_bytes = db.rechnung_export.exportieren(gs.username)
    assert [z["Betrag EUR"] for z in _uebersicht(zip_bytes)] == ["7,00", "5,00"]
    assert db.rechnung_export.list_exporte()[0].summe_cent == 1200
