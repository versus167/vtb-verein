"""Rechnungs-Export im hmd-FBASC-Format (fbasc.hia) statt reinem Belegstapel.

Bis Schema v108 lieferte der Rechnungsexport ein Zip aus Belegen plus
`uebersicht.csv`; die Buchungszeile tippte jemand in der Fibu nach. Seit v109
rendert er – wie Kassenbuch und Sollstellungen – eine `fbasc.hia`: Eine
freigegebene Rechnung ist eine Verbindlichkeit, also Aufwand (Kategorie-Sachkonto)
im Soll gegen Kreditor im Haben. Seit dem 23.08.2026 liegt keine CSV mehr bei –
nur Altläufe (`format='zip'`) liefern sie beim Re-Download weiterhin.

Der Kreditor ist bei einer Erstattung das Personenkonto des Mitglieds
(ul_kreditor_konto_basis + Mitgliedsnummer), bei einem externen Aussteller der
Standard-Kreditor aus den Einstellungen des Rechnungs-Bereichs.

Zwei Ebenen:
  * Buchungszeile und Konten-Prüfung – ohne DB
  * Zip-Inhalt, Altläufe und Abbruch ohne Konten – gegen echtes PostgreSQL
"""
import io
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services import fibu_formatter  # noqa: E402
from app.services.rechnung_export_service import (  # noqa: E402
    FibuRechnungExportFehler, RechnungExportService,
)


# ========================================================== Buchungszeile (ohne DB)

def _einst(**kw):
    """Fibu-Einstellungen, wie der Export sie liest."""
    werte = dict(ul_kreditor_konto_basis=70000, rechnung_kreditor_konto="70999",
                 verein_kostenstelle=12, default_kostentraeger=1)
    werte.update(kw)
    return SimpleNamespace(**werte)


def _zeile(**kw):
    """Eine Zeile, wie `list_fbasc_offen` sie liefert."""
    z = {
        "id": 42, "betrag_cent": 4711, "rechnungsdatum": "2026-03-04",
        "rechnungsnummer": "RG-2026-88", "beschreibung": "Trikotsatz",
        "empfaenger_typ": "mitglied", "empfaenger_name": None, "empfaenger_iban": None,
        "freigegeben_am": "2026-03-20", "freigegeben_von": "kasse", "created_by": "trainer",
        "kategorie_name": "Sportmaterial", "kategorie_sachkonto": "4400",
        "kategorie_kostenstelle": None, "kategorie_kostentraeger": None,
        "abteilung_name": "Fußball", "abteilung_id": 3, "abteilung_kostenstelle": 30,
        "empfaenger_mitglied_id": 7, "mitgliedsnummer": 4711,
        "vorname": "Tim", "nachname": "Trainer", "strasse": "Weg 1",
        "plz": "09111", "ort": "Chemnitz", "land": "DE",
        "mitglied_iban": "DE02120300000000202051", "bic": "BYLADEM1001",
        "kontoinhaber": None, "email": "tim@example.org",
    }
    z.update(kw)
    return z


def _service():
    return RechnungExportService(rechnung_repo=None, anhang_repo=None, export_repo=None)


class TestKreditorZeile:
    def test_erstattung_laeuft_auf_das_personenkonto(self):
        p = _service()._fbasc_position(_zeile(), _einst(), "beleg.pdf")
        assert p.konto == 70000 + 4711
        assert p.kontenart == "K"
        assert p.soll_haben == "H"          # Verbindlichkeit entsteht
        assert p.gegenkonto == "4400"       # Aufwand aus der Kategorie
        assert p.betrag == pytest.approx(47.11)
        assert p.belegnummer == "R42"
        assert p.dokument == "beleg.pdf"

    def test_mitglied_bringt_seine_stammdaten_mit(self):
        p = _service()._fbasc_position(_zeile(), _einst(), None)
        assert (p.nachname, p.vorname) == ("Trainer", "Tim")
        assert p.iban == "DE02120300000000202051"
        assert p.ort == "Chemnitz"
        assert p.mailadresse == "tim@example.org"
        assert p.suchname == "4711"

    def test_externer_aussteller_laeuft_auf_den_sammelkreditor(self):
        z = _zeile(empfaenger_typ="extern", empfaenger_name="Sporthaus Meier GmbH",
                   empfaenger_iban="DE02500105170137075030", mitgliedsnummer=None,
                   vorname=None, nachname=None, strasse="Firmenweg 9", ort="Leipzig")
        p = _service()._fbasc_position(z, _einst(), None)
        assert p.konto == "70999"
        assert p.nachname == "Sporthaus Meier GmbH"
        assert p.vorname is None
        assert p.iban == "DE02500105170137075030"
        # Die Anschrift im Datensatz gehört dem Mitglied, nicht dem Aussteller –
        # ein externer Empfänger darf sie nicht geerbt bekommen.
        assert p.strasse is None and p.ort is None and p.mailadresse is None

    def test_externer_ohne_namen_bleibt_erkennbar(self):
        z = _zeile(empfaenger_typ="extern", empfaenger_name=None, mitgliedsnummer=None)
        p = _service()._fbasc_position(z, _einst(), None)
        assert p.nachname == "Unbekannter Aussteller"

    def test_mitglied_ohne_nummer_faellt_auf_den_sammelkreditor(self):
        """Ohne Mitgliedsnummer gibt es kein Personenkonto – die Zeile muss
        trotzdem auf ein gültiges Konto zeigen."""
        p = _service()._fbasc_position(_zeile(mitgliedsnummer=None), _einst(), None)
        assert p.konto == "70999"

    def test_iban_an_der_rechnung_schlaegt_den_mitgliedsstamm(self):
        p = _service()._fbasc_position(
            _zeile(empfaenger_iban="DE02100500000054540402"), _einst(), None)
        assert p.iban == "DE02100500000054540402"

    def test_abweichender_kontoinhaber_nur_wenn_er_abweicht(self):
        gleich = _service()._fbasc_position(_zeile(kontoinhaber="Tim Trainer"), _einst(), None)
        assert gleich.kontoinhaber is None
        anders = _service()._fbasc_position(_zeile(kontoinhaber="Erika Trainer"), _einst(), None)
        assert anders.kontoinhaber == "Erika Trainer"


class TestKostenstelleUndDatum:
    def test_kategorie_schlaegt_abteilung(self):
        p = _service()._fbasc_position(_zeile(kategorie_kostenstelle=99), _einst(), None)
        assert p.kostenstelle == 99

    def test_abteilung_schlaegt_verein(self):
        p = _service()._fbasc_position(_zeile(), _einst(), None)
        assert p.kostenstelle == 30

    def test_ohne_abteilung_greift_der_verein(self):
        p = _service()._fbasc_position(_zeile(abteilung_kostenstelle=None), _einst(), None)
        assert p.kostenstelle == 12

    def test_kostentraeger_aus_der_kategorie_sonst_default(self):
        assert _service()._fbasc_position(_zeile(), _einst(), None).kostentraeger == 1
        p = _service()._fbasc_position(_zeile(kategorie_kostentraeger=7), _einst(), None)
        assert p.kostentraeger == 7

    def test_belegdatum_ist_das_rechnungsdatum(self):
        p = _service()._fbasc_position(_zeile(), _einst(), None)
        assert p.belegdatum == "2026-03-04"
        assert p.faelligkeitsdatum == "2026-03-14"     # + 10 Nettotage

    def test_ohne_rechnungsdatum_zaehlt_die_freigabe(self):
        p = _service()._fbasc_position(_zeile(rechnungsdatum=None), _einst(), None)
        assert p.belegdatum == "2026-03-20"
        assert p.faelligkeitsdatum == "2026-03-30"

    def test_buchungstext_traegt_kategorie_notiz_nummer_und_person(self):
        p = _service()._fbasc_position(_zeile(), _einst(), None)
        assert p.buchungstext == "Sportmaterial – Trikotsatz – Rg. RG-2026-88 – Trainer, Tim"


class TestKontenPruefung:
    def test_alles_gesetzt_ergibt_keine_fehler(self):
        s = _service()
        s._fibu_einstellungen = SimpleNamespace(get=lambda: _einst())
        assert s._konten_fehler([_zeile()]) == []

    def _fehler(self, zeilen, einst):
        s = _service()
        s._fibu_einstellungen = SimpleNamespace(get=lambda: einst)
        return s._konten_fehler(zeilen)

    def test_fehlendes_sachkonto_wird_je_kategorie_gemeldet(self):
        zeilen = [_zeile(id=1, kategorie_sachkonto=None),
                  _zeile(id=2, kategorie_sachkonto=None)]
        fehler = self._fehler(zeilen, _einst())
        # Eine Meldung, nicht zwei – die Ursache steckt in der Kategorie.
        assert fehler == ['Kategorie „Sportmaterial“ hat kein Sachkonto (Feld 01).']

    def test_fehlender_standard_kreditor_nur_bei_externen(self):
        einst = _einst(rechnung_kreditor_konto=None)
        assert self._fehler([_zeile()], einst) == []
        fehler = self._fehler([_zeile(empfaenger_typ="extern", mitgliedsnummer=None)], einst)
        assert any("Standard-Kreditor" in f for f in fehler)

    def test_fehlende_basis_nur_bei_mitgliedern(self):
        einst = _einst(ul_kreditor_konto_basis=None)
        assert self._fehler(
            [_zeile(empfaenger_typ="extern", mitgliedsnummer=None)], einst) == []
        assert any("ÜL-Kreditor-Konto-Basis" in f for f in self._fehler([_zeile()], einst))

    def test_rechnung_ohne_betrag_wird_gemeldet(self):
        fehler = self._fehler([_zeile(betrag_cent=None)], _einst())
        assert fehler == ["Rechnung #42: kein Betrag erfasst."]

    def test_ohne_zeilen_kein_fehler(self):
        assert self._fehler([], _einst(rechnung_kreditor_konto=None)) == []


class TestFormatter:
    def test_langer_firmenname_wird_auf_50_zeichen_gekappt(self):
        """Feld 22 fasst laut Schnittstellenbeschreibung 50 Zeichen."""
        z = _zeile(empfaenger_typ="extern", mitgliedsnummer=None,
                   empfaenger_name="Sportartikel Großhandel Sachsen und Thüringen GmbH & Co. KG")
        p = _service()._fbasc_position(z, _einst(), None)
        assert len(fibu_formatter.felder(p)[22]) == 50

    def test_zeile_traegt_die_kreditor_felder(self):
        f = fibu_formatter.felder(_service()._fbasc_position(_zeile(), _einst(), "b.pdf"))
        assert f[0] == "74711"          # Kreditor-Konto
        assert f[1] == "4400"           # Aufwand
        assert f[2] == "47,11"
        assert f[3] == "H"
        assert f[4] == "R42"
        assert f[7] == "30"             # Kostenstelle
        assert f[10] == "04.03.2026"    # Belegdatum
        assert f[19] == "K"
        assert f[39] == "b.pdf"


# ====================================================== Export (mit Postgres)

_URL = os.getenv("VTB_TEST_DATABASE_URL")
integration = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)")

_UPLOADS = "/tmp/vtb-rechnung-fbasc-uploads"


def _png() -> bytes:
    from PIL import Image
    puffer = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 90, 200)).save(puffer, format="PNG")
    return puffer.getvalue()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path=_UPLOADS)
    yield d
    d.close()


@pytest.fixture(autouse=True)
def sauber(request):
    # `db` erst anfordern, wenn es eine DB gibt – sonst baute diese Fixture auch
    # für die DB-freien Tests oben eine Verbindung auf (und scheiterte daran).
    if not _URL:
        yield
        return
    db = request.getfixturevalue("db")

    def aufraeumen():
        with db.cursor() as cur:
            cur.execute("TRUNCATE rechnung_anhaenge, rechnung, rechnung_history, "
                        "rechnung_exporte, rechnung_exporte_history "
                        "RESTART IDENTITY CASCADE")
            cur.execute("DELETE FROM mitglied WHERE vorname='FbascTest'")
            cur.execute("DELETE FROM mitglied_history WHERE vorname='FbascTest'")
            cur.execute("DELETE FROM users WHERE username LIKE 'fbasctester%'")
            cur.execute("DELETE FROM users_history WHERE username LIKE 'fbasctester%'")
            cur.execute("DELETE FROM abteilung WHERE name = 'F-Fussball'")
            cur.execute("DELETE FROM abteilung_history WHERE name = 'F-Fussball'")
            for t in ("users", "mitglied", "abteilung"):
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{t}','id'), GREATEST("
                    f"(SELECT COALESCE(MAX(id),0) FROM {t}),"
                    f"(SELECT COALESCE(MAX(id),0) FROM {t}_history), 1))")

    aufraeumen()
    yield
    aufraeumen()


@pytest.fixture()
def welt(db):
    """Konten gesetzt, eine freigegebene Rechnung mit Beleg."""
    db.fibu_einstellungen.update(
        _fibu_werte(db, ul_kreditor_konto_basis=70000, rechnung_kreditor_konto="70999"),
        updated_by="fbasctest")
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,kostenstelle,created_by,updated_by) "
                    "VALUES ('F-Fussball',30,'fbasctest','fbasctest') RETURNING id")
        abt = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
            "VALUES ('fbasctester','fbasc@example.invalid','x','admin',1,'fbasctest','fbasctest') "
            "RETURNING id")
        uid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO mitglied (vorname,nachname,mitgliedsnummer,zahlungsart,user_id,"
            "iban,strasse,plz,ort,created_by,updated_by) "
            "VALUES ('FbascTest','Trainer',4711,'ueberweisung',%s,"
            "'DE02120300000000202051','Weg 1','09111','Chemnitz','fbasctest','fbasctest') "
            "RETURNING id", (uid,))
        mid = cur.fetchone()["id"]
    user = db.get_user_by_id(uid)
    kategorie = db.rechnungen.list_kategorien()[0]
    db.rechnungen.kategorie_aktualisieren(
        kategorie.id, user, expected_version=kategorie.version, sachkonto="4400")
    return SimpleNamespace(user=user, mitglied_id=mid, abteilung_id=abt,
                           kategorie_id=kategorie.id)


def _fibu_werte(db, **kw):
    e = db.fibu_einstellungen.get()
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def _freigegebene_rechnung(db, welt, *, belege=1, **felder):
    felder.setdefault("empfaenger_typ", "mitglied")
    felder.setdefault("betrag_cent", 4711)
    felder.setdefault("empfaenger_mitglied_id", welt.mitglied_id)
    r = db.rechnungen.anlegen(welt.user, kategorie_id=welt.kategorie_id,
                              abteilung_id=welt.abteilung_id, **felder)
    for i in range(belege):
        db.rechnungen.add_anhang(r.id, welt.user, original_name=f"beleg{i + 1}.png",
                                 mime_type="image/png", inhalt=_png())
    db.rechnungen.einreichen(r.id, welt.user)
    db.rechnungen.freigeben(r.id, welt.user)
    return db.rechnungen.get(r.id, welt.user)


def _entpacke(zip_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def _hia_zeilen(dateien: dict) -> list[list[str]]:
    text = dateien["fbasc.hia"].decode("utf-8")
    return [z.split(";") for z in text.split("\r\n") if z]


@integration
class TestExportInhalt:
    def test_zip_enthaelt_hia_und_beleg(self, db, welt):
        """Buchungsdatei und Belege – und nichts weiter: Was früher in der
        `uebersicht.csv` stand, steht in der Buchungszeile."""
        _freigegebene_rechnung(db, welt)
        _, zip_bytes = db.rechnung_export.exportieren("fbasctest")
        namen = _entpacke(zip_bytes).keys()
        assert "fbasc.hia" in namen
        assert "uebersicht.csv" not in namen
        assert any(n.startswith("R1 - ") for n in namen)

    def test_buchungszeile_stimmt(self, db, welt):
        _freigegebene_rechnung(db, welt, rechnungsdatum="2026-03-04")
        _, zip_bytes = db.rechnung_export.exportieren("fbasctest")
        (zeile,) = _hia_zeilen(_entpacke(zip_bytes))
        assert zeile[0] == "74711"        # Kreditor = Basis + Mitgliedsnummer
        assert zeile[1] == "4400"         # Aufwandskonto der Kategorie
        assert zeile[2] == "47,11"
        assert zeile[3] == "H"
        assert zeile[4] == "R1"
        assert zeile[10] == "04.03.2026"
        assert zeile[19] == "K"
        assert zeile[39].startswith("R1 - ")   # Beleg in Feld 39

    def test_zweiter_beleg_bekommt_eine_null_zeile(self, db, welt):
        _freigegebene_rechnung(db, welt, belege=2)
        _, zip_bytes = db.rechnung_export.exportieren("fbasctest")
        zeilen = _hia_zeilen(_entpacke(zip_bytes))
        assert len(zeilen) == 2
        assert zeilen[1][2] == "0,00"
        # Gleiche Konten wie die Hauptzeile, nur ein anderes Dokument.
        assert zeilen[1][0] == zeilen[0][0] and zeilen[1][1] == zeilen[0][1]
        assert zeilen[1][39] != zeilen[0][39]

    def test_lauf_wird_als_fbasc_gefuehrt(self, db, welt):
        _freigegebene_rechnung(db, welt)
        db.rechnung_export.exportieren("fbasctest")
        assert db.rechnung_export.list_exporte()[0].format == "fbasc"

    def test_re_download_liefert_dieselbe_datei(self, db, welt):
        _freigegebene_rechnung(db, welt)
        _, erst = db.rechnung_export.exportieren("fbasctest")
        export_id = db.rechnung_export.list_exporte()[0].id
        _, nochmal = db.rechnung_export.re_download(export_id)
        assert _hia_zeilen(_entpacke(nochmal)) == _hia_zeilen(_entpacke(erst))


@integration
class TestAltlaeufe:
    def test_alter_lauf_bleibt_ohne_hia(self, db, welt):
        """Ein vor v109 übergebener Lauf muss beim erneuten Download liefern, was
        er damals lieferte – und nicht nachträglich eine Buchungsdatei erfinden."""
        _freigegebene_rechnung(db, welt)
        db.rechnung_export.exportieren("fbasctest")
        export_id = db.rechnung_export.list_exporte()[0].id
        with db.cursor() as cur:
            cur.execute("UPDATE rechnung_exporte SET format='zip' WHERE id=%s", (export_id,))
        _, zip_bytes = db.rechnung_export.re_download(export_id)
        namen = _entpacke(zip_bytes).keys()
        assert "fbasc.hia" not in namen
        # Dort war die CSV die einzige Lesehilfe – sie bleibt dem Altlauf erhalten.
        assert "uebersicht.csv" in namen


@integration
class TestBereichsEinstellung:
    """Der Standard-Kreditor wird im Rechnungs-Bereich gepflegt, nicht auf der
    Fibu-Seite – wer Rechnungen verwaltet, hat nicht zwingend Fibu-Export-Recht."""

    def test_speichern_und_lesen(self, db, welt):
        from backend.api.rechnungen import (
            RechnungEinstellungenUpdate, einstellungen, einstellungen_speichern,
        )
        einstellungen_speichern(
            RechnungEinstellungenUpdate(rechnung_kreditor_konto=" 70123 "),
            welt.user, db)
        # Getrimmt gespeichert – eine Kontonummer mit Rand ist keine andere Nummer.
        assert einstellungen(welt.user, db) == {"rechnung_kreditor_konto": "70123"}

    def test_leeren_setzt_zurueck(self, db, welt):
        from backend.api.rechnungen import (
            RechnungEinstellungenUpdate, einstellungen, einstellungen_speichern,
        )
        einstellungen_speichern(
            RechnungEinstellungenUpdate(rechnung_kreditor_konto=""), welt.user, db)
        assert einstellungen(welt.user, db)["rechnung_kreditor_konto"] is None

    def test_andere_konten_bleiben_unberuehrt(self, db, welt):
        """Regression: Beim Speichern eines Bereichs darf kein fremdes Konto
        verloren gehen – beide Formulare setzen auf dem Bestand auf."""
        from backend.api.rechnungen import (
            RechnungEinstellungenUpdate, einstellungen_speichern,
        )
        vorher = db.fibu_einstellungen.get()
        einstellungen_speichern(
            RechnungEinstellungenUpdate(rechnung_kreditor_konto="70123"), welt.user, db)
        nachher = db.fibu_einstellungen.get()
        assert nachher.ul_kreditor_konto_basis == vorher.ul_kreditor_konto_basis
        assert nachher.debitor_konto_basis == vorher.debitor_konto_basis
        assert nachher.verein_kostenstelle == vorher.verein_kostenstelle

    def test_fibu_formular_laesst_den_standard_kreditor_stehen(self, db, welt):
        """Das Fibu-Formular kennt das Feld nicht mehr; ein Speichern dort darf es
        nicht auf NULL ziehen."""
        from backend.api.fibu import EinstellungenUpdate, update_einstellungen
        from backend.api.rechnungen import (
            RechnungEinstellungenUpdate, einstellungen, einstellungen_speichern,
        )
        einstellungen_speichern(
            RechnungEinstellungenUpdate(rechnung_kreditor_konto="70123"), welt.user, db)
        update_einstellungen(
            EinstellungenUpdate(debitor_konto_basis=200000, ul_kreditor_konto_basis=70000),
            welt.user, db)
        assert einstellungen(welt.user, db)["rechnung_kreditor_konto"] == "70123"


@integration
class TestAbbruchOhneKonten:
    def test_ohne_standard_kreditor_bricht_der_lauf_ab(self, db, welt):
        db.fibu_einstellungen.update(
            _fibu_werte(db, rechnung_kreditor_konto=None), updated_by="fbasctest")
        _freigegebene_rechnung(db, welt, empfaenger_typ="extern",
                               empfaenger_mitglied_id=None, empfaenger_name="Sporthaus")
        with pytest.raises(FibuRechnungExportFehler) as exc:
            db.rechnung_export.exportieren("fbasctest")
        assert any("Standard-Kreditor" in f for f in exc.value.fehler)

    def test_abgebrochener_lauf_stempelt_nichts(self, db, welt):
        db.fibu_einstellungen.update(
            _fibu_werte(db, rechnung_kreditor_konto=None), updated_by="fbasctest")
        _freigegebene_rechnung(db, welt, empfaenger_typ="extern",
                               empfaenger_mitglied_id=None, empfaenger_name="Sporthaus")
        with pytest.raises(FibuRechnungExportFehler):
            db.rechnung_export.exportieren("fbasctest")
        # Weder Lauf noch Stempel – sonst müsste man erst zurücknehmen, um es
        # nach dem Setzen des Kontos erneut zu versuchen.
        assert db.rechnung_export.list_exporte() == []
        assert db.rechnung_export.vorschau()["anzahl"] == 1

    def test_vorschau_nennt_die_fehlenden_konten(self, db, welt):
        db.fibu_einstellungen.update(
            _fibu_werte(db, rechnung_kreditor_konto=None), updated_by="fbasctest")
        _freigegebene_rechnung(db, welt, empfaenger_typ="extern",
                               empfaenger_mitglied_id=None, empfaenger_name="Sporthaus")
        assert any("Standard-Kreditor" in f
                   for f in db.rechnung_export.vorschau()["fehler"])
