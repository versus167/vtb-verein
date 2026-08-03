"""Dry-Run des DFBnet-Spielplan-Imports gegen echtes PostgreSQL (#95, Etappe 2).

Prüft die Einordnung jeder Zeile — neu, Änderung, unverändert, Platzbelegung,
fremd — sowie die Vorschlagslisten für unbekannte Teams und noch fehlende
Spielstätten. Vereinsinterne Spiele ergeben bewusst ZWEI Befunde, einen je
Mannschaft, damit beide Kader zu-/absagen können. Es wird nichts geschrieben; der Test kontrolliert das
ausdrücklich.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` auf einer LEEREN Wegwerf-DB. Die
Spielplandatei wird synthetisch erzeugt (UTF-16LE, tabgetrennt) — echte Exporte
enthalten Schiedsrichternamen und gehören nicht ins Repo.
"""
import os
from contextlib import contextmanager

import pytest

from app.services import dfbnet_import_service as dfbnet

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_MARKE = 'dfbnettest'

_KOPF = [
    'Saison', 'Mannschaftsart', 'Staffel', 'Spielstätte', 'Spielstätten-Nr.',
    'Straße/Hausnr.', 'PLZ', 'Ort', 'Typ', 'Max. parallele Spiele',
    'Spieldatum', 'Uhrzeit', 'Sptg.', 'Spielkennung', 'Typ', 'Liga',
    'Heimmannschaft', 'Gastmannschaft', 'Spielleitung',
]


def _zeile(**kw):
    werte = {
        'Saison': '26/27', 'Mannschaftsart': 'Herren', 'Staffel': 'Kreisoberliga',
        'Spielstätte': 'Eigener Platz', 'Spielstätten-Nr.': '1000000001',
        'Straße/Hausnr.': 'Musterweg 1', 'PLZ': '09111', 'Ort': 'Musterstadt',
        'Max. parallele Spiele': '2', 'Spieldatum': '15.08.2026', 'Uhrzeit': '15:00',
        'Sptg.': '1', 'Spielkennung': '900000001', 'Liga': 'Kreisoberliga',
        'Heimmannschaft': 'Testteam DFBnet', 'Gastmannschaft': 'SV Fremd',
        'Spielleitung': 'Muster, Max',
    }
    platztyp = kw.pop('platztyp', 'Rasenplatz')
    spieltyp = kw.pop('spieltyp', 'Meisterschaft')
    werte.update(kw)
    spalten, typ_gesehen = [], 0
    for name in _KOPF:
        if name == 'Typ':
            typ_gesehen += 1
            spalten.append(platztyp if typ_gesehen == 1 else spieltyp)
        else:
            spalten.append(werte[name])
    return '\t'.join(spalten)


def _datei(*zeilen) -> bytes:
    return ('\r\n'.join(['\t'.join(_KOPF), *zeilen]) + '\r\n').encode('utf-16')


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-dfbnet-uploads")
    yield d
    d.close()


@contextmanager
def _cur(db):
    cur = db.conn.cursor()
    try:
        yield cur
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        raise
    finally:
        cur.close()


@pytest.fixture
def stammdaten(db):
    """Abteilung, zwei zugeordnete Mannschaften und ein eigener Platz."""
    with _cur(db) as cur:
        for tabelle in ('abteilung', 'mannschaft', 'termine', 'spielstaette'):
            cur.execute(
                f"""
                SELECT setval(pg_get_serial_sequence('{tabelle}', 'id'), GREATEST(
                    (SELECT COALESCE(MAX(id), 0) FROM {tabelle}),
                    (SELECT COALESCE(MAX(id), 0) FROM {tabelle}_history), 1))
                """
            )
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES ('DFBnet-Abt', %s, %s) RETURNING id", (_MARKE, _MARKE))
        abteilung_id = cur.fetchone()['id']
        cur.execute(
            "INSERT INTO mannschaft (abteilung_id, name, dfbnet_name, "
            "dfbnet_mannschaftsart, created_by, updated_by) "
            "VALUES (%s, 'Erste', 'Testteam DFBnet', 'Herren', %s, %s) RETURNING id",
            (abteilung_id, _MARKE, _MARKE))
        erste = cur.fetchone()['id']
        cur.execute(
            "INSERT INTO mannschaft (abteilung_id, name, dfbnet_name, "
            "dfbnet_mannschaftsart, created_by, updated_by) "
            "VALUES (%s, 'Zweite', 'Testteam DFBnet 2', 'Herren', %s, %s) RETURNING id",
            (abteilung_id, _MARKE, _MARKE))
        zweite = cur.fetchone()['id']
        cur.execute(
            "INSERT INTO spielstaette (name, dfbnet_nr, ist_eigen, created_by, updated_by) "
            "VALUES ('Eigener Platz', '1000000001', TRUE, %s, %s) RETURNING id",
            (_MARKE, _MARKE))
        platz = cur.fetchone()['id']
    yield {'abteilung': abteilung_id, 'erste': erste, 'zweite': zweite, 'platz': platz}
    with _cur(db) as cur:
        cur.execute("DELETE FROM termine_history WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM termine WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM mannschaft_dfbnet_alias_history WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM mannschaft_dfbnet_alias WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM mannschaft_history WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM mannschaft WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM spielstaette_history WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM spielstaette WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM abteilung WHERE created_by = %s", (_MARKE,))


def _termin_anlegen(db, mannschaft_id, platz_id, **kw):
    werte = {'beginn': '2026-08-15T15:00', 'extern_ref': '900000001',
             'ort': 'Eigener Platz, Musterweg 1, 09111 Musterstadt',
             'heim_auswaerts': 'heim', 'gegner': 'SV Fremd'}
    werte.update(kw)
    with _cur(db) as cur:
        cur.execute(
            """
            INSERT INTO termine (mannschaft_id, typ, beginn, ort, spielstaette_id,
                gegner, heim_auswaerts, extern_ref, created_by, updated_by)
            VALUES (%(m)s, 'spiel', %(beginn)s, %(ort)s, %(p)s, %(gegner)s,
                    %(heim_auswaerts)s, %(extern_ref)s, %(u)s, %(u)s)
            RETURNING id
            """,
            werte | {'m': mannschaft_id, 'p': platz_id, 'u': _MARKE},
        )
        return cur.fetchone()['id']


def test_neues_spiel_wird_als_neu_gemeldet(db, stammdaten):
    bericht = dfbnet.dry_run(db, _datei(_zeile()))
    assert bericht.zusammenfassung[dfbnet.NEU] == 1
    befund = bericht.befunde[0]
    assert befund.mannschaft_id == stammdaten['erste']
    assert befund.heim_auswaerts == 'heim'


def test_auswaertsspiel_dreht_das_heimrecht(db, stammdaten):
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{
        'Heimmannschaft': 'SV Fremd', 'Gastmannschaft': 'Testteam DFBnet'})))
    assert bericht.befunde[0].heim_auswaerts == 'auswaerts'


def test_bekanntes_spiel_ohne_abweichung_ist_unveraendert(db, stammdaten):
    _termin_anlegen(db, stammdaten['erste'], stammdaten['platz'])
    bericht = dfbnet.dry_run(db, _datei(_zeile()))
    assert bericht.zusammenfassung[dfbnet.UNVERAENDERT] == 1
    assert bericht.befunde[0].abweichungen == []


def test_verlegung_wird_als_abweichung_gemeldet(db, stammdaten):
    _termin_anlegen(db, stammdaten['erste'], stammdaten['platz'])
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{'Uhrzeit': '17:30'})))
    assert bericht.zusammenfassung[dfbnet.AENDERUNG] == 1
    abw = bericht.befunde[0].abweichungen
    assert [a['feld'] for a in abw] == ['beginn']
    assert abw[0]['app'] == '2026-08-15T15:00'
    assert abw[0]['dfbnet'] == '2026-08-15T17:30'


def test_fremdes_spiel_auf_eigenem_platz_ist_platzbelegung(db, stammdaten):
    """Der Vereinsspielplan ist auch ein Platzbelegungsplan."""
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{
        'Heimmannschaft': 'SV Fremd', 'Gastmannschaft': 'FC Anders',
        'Spielkennung': '900000002'})))
    assert bericht.zusammenfassung[dfbnet.PLATZBELEGUNG] == 1


def test_fremdes_spiel_auf_fremdem_platz_ist_irrelevant(db, stammdaten):
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{
        'Heimmannschaft': 'SV Fremd', 'Gastmannschaft': 'FC Anders',
        'Spielstätte': 'Fremder Platz', 'Spielstätten-Nr.': '2000000002',
        'Spielkennung': '900000003'})))
    assert bericht.zusammenfassung[dfbnet.FREMD] == 1


def test_vereinsinternes_spiel_ergibt_zwei_termine(db, stammdaten):
    """Beide Kader müssen zu-/absagen können – also je Mannschaft ein Termin.

    Möglich seit Schema v82: die Spielkennung ist je Mannschaft eindeutig.
    """
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{
        'Heimmannschaft': 'Testteam DFBnet', 'Gastmannschaft': 'Testteam DFBnet 2'})))
    assert bericht.zusammenfassung[dfbnet.NEU] == 2
    zuordnung = {(b.mannschaft_id, b.heim_auswaerts) for b in bericht.befunde}
    assert zuordnung == {(stammdaten['erste'], 'heim'), (stammdaten['zweite'], 'auswaerts')}
    assert all('Vereinsinternes Spiel' in b.hinweis for b in bericht.befunde)


def test_vereinsinternes_spiel_erkennt_den_bestehenden_termin_je_mannschaft(db, stammdaten):
    """Der Termin der einen Mannschaft darf den der anderen nicht verdecken."""
    _termin_anlegen(db, stammdaten['erste'], stammdaten['platz'],
                    gegner='Testteam DFBnet 2')
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{
        'Heimmannschaft': 'Testteam DFBnet', 'Gastmannschaft': 'Testteam DFBnet 2'})))
    nach_team = {b.mannschaft_id: b.einordnung for b in bericht.befunde}
    assert nach_team[stammdaten['erste']] == dfbnet.UNVERAENDERT
    assert nach_team[stammdaten['zweite']] == dfbnet.NEU


def test_falsche_mannschaftsart_trifft_nicht(db, stammdaten):
    """„Testteam DFBnet" als E-Junioren ist ein anderes Team als bei den Herren."""
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{'Mannschaftsart': 'E-Junioren'})))
    assert bericht.zusammenfassung[dfbnet.PLATZBELEGUNG] == 1   # eigener Platz, fremdes Team


def test_alias_findet_die_spielgemeinschaft(db, stammdaten):
    db.mannschaften.set_aliasse(stammdaten['erste'], ['Testteam DFBnet / SG Muster'], _MARKE)
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{
        'Heimmannschaft': 'Testteam DFBnet / SG Muster'})))
    assert bericht.zusammenfassung[dfbnet.NEU] == 1
    assert bericht.befunde[0].mannschaft_id == stammdaten['erste']


def test_unbekannte_teams_und_neue_spielstaetten_werden_vorgeschlagen(db, stammdaten):
    bericht = dfbnet.dry_run(db, _datei(_zeile(**{
        'Heimmannschaft': 'SV Unbekannt', 'Gastmannschaft': 'FC Unbekannt',
        'Spielstätte': 'Neuer Platz', 'Spielstätten-Nr.': '3000000003',
        'Spielkennung': '900000004'})))
    namen = {t['name'] for t in bericht.unbekannte_teams}
    assert namen == {'SV Unbekannt', 'FC Unbekannt'}
    assert len(bericht.neue_spielstaetten) == 1
    vorschlag = bericht.neue_spielstaetten[0]
    assert vorschlag['dfbnet_nr'] == '3000000003'
    assert vorschlag['parallel_moeglich'] == 2      # aus „Max. parallele Spiele"


def test_dry_run_schreibt_nichts(db, stammdaten):
    with _cur(db) as cur:
        cur.execute("SELECT count(*) AS n FROM termine")
        vorher = cur.fetchone()['n']
    dfbnet.dry_run(db, _datei(_zeile(), _zeile(**{'Spielkennung': '900000009'})))
    with _cur(db) as cur:
        cur.execute("SELECT count(*) AS n FROM termine")
        assert cur.fetchone()['n'] == vorher


# --------------------------------------------------------- Übernahme (Etappe 3)

def _stand(db, termin_id):
    with _cur(db) as cur:
        cur.execute("SELECT extern_stand FROM termine WHERE id = %s", (termin_id,))
        return cur.fetchone()['extern_stand']


def test_uebernahme_legt_das_spiel_an(db, stammdaten):
    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    assert (ergebnis.angelegt, ergebnis.aktualisiert) == (1, 0)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    assert termin is not None
    assert termin.typ == 'spiel'
    assert termin.beginn == '2026-08-15T15:00'
    assert termin.heim_auswaerts == 'heim'
    assert termin.gegner == 'SV Fremd'
    assert termin.spielstaette_id == stammdaten['platz']
    # Schnappschuss wird gleich mitgeschrieben – Basis des naechsten Abgleichs
    assert termin.extern_stand['beginn'] == '2026-08-15T15:00'


def test_zweiter_lauf_ohne_aenderung_tut_nichts(db, stammdaten):
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    zweiter = dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    assert (zweiter.angelegt, zweiter.aktualisiert, zweiter.uebersprungen) == (0, 0, 0)


def test_verlegung_wird_uebernommen_wenn_die_app_unberuehrt_ist(db, stammdaten):
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    assert ergebnis.aktualisiert == 1
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    assert termin.beginn == '2026-08-15T17:30'
    assert termin.extern_stand['beginn'] == '2026-08-15T17:30'   # Stand zieht mit


def test_vom_team_geaenderter_termin_wird_nicht_ueberschrieben(db, stammdaten):
    """Der Kern des Drei-Wege-Abgleichs: DFBnet und App haben beide geaendert."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    db.termine.update(termin.id, 'spiel', '2026-08-15T16:00', None, termin.ort,
                      None, None, termin.gegner, termin.heim_auswaerts, None,
                      'trainer', termin.version, spielstaette_id=termin.spielstaette_id)

    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    assert ergebnis.aktualisiert == 0
    assert len(ergebnis.konflikte) == 1
    assert ergebnis.konflikte[0]['grund'] == 'Termin wurde in der App geändert'
    # Die Aenderung des Teams bleibt stehen
    assert db.termine.get(termin.id).beginn == '2026-08-15T16:00'


def test_nur_die_app_hat_geaendert_bleibt_unangetastet(db, stammdaten):
    """DFBnet unveraendert: kein erneutes Nachfragen, kein Ueberschreiben."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    db.termine.update(termin.id, 'spiel', '2026-08-15T16:00', None, termin.ort,
                      None, None, termin.gegner, termin.heim_auswaerts, None,
                      'trainer', termin.version, spielstaette_id=termin.spielstaette_id)

    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    assert (ergebnis.aktualisiert, ergebnis.konflikte) == (0, [])
    assert db.termine.get(termin.id).beginn == '2026-08-15T16:00'


def test_termin_ohne_schnappschuss_wird_nur_nachgetragen(db, stammdaten):
    """Von Hand angelegter Termin: ohne Basis wird nichts ueberschrieben."""
    termin_id = _termin_anlegen(db, stammdaten['erste'], stammdaten['platz'])
    assert _stand(db, termin_id) is None

    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    assert ergebnis.stand_nachgetragen == 1
    assert _stand(db, termin_id)['beginn'] == '2026-08-15T15:00'


def test_ohne_schnappschuss_und_mit_abweichung_wird_gemeldet_statt_geschrieben(db, stammdaten):
    termin_id = _termin_anlegen(db, stammdaten['erste'], stammdaten['platz'])
    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    assert ergebnis.aktualisiert == 0
    assert ergebnis.konflikte[0]['grund'] == 'kein Vergleichsstand aus einem früheren Import'
    assert db.termine.get(termin_id).beginn == '2026-08-15T15:00'


def test_fehlende_spielstaette_wird_uebersprungen_und_gemeldet(db, stammdaten):
    """Stammdaten legt der Import nicht selbst an – die Spielstaette ist Pflichtfeld."""
    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{
        'Spielstätte': 'Unbekannter Platz', 'Spielstätten-Nr.': '4000000004',
        'Spielkennung': '900000005'})), actor=_MARKE)
    assert ergebnis.angelegt == 0
    assert ergebnis.uebersprungen == 1
    assert ergebnis.ohne_spielstaette[0]['dfbnet_nr'] == '4000000004'


def test_vereinsinternes_spiel_legt_zwei_termine_an(db, stammdaten):
    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{
        'Heimmannschaft': 'Testteam DFBnet',
        'Gastmannschaft': 'Testteam DFBnet 2'})), actor=_MARKE)
    assert ergebnis.angelegt == 2
    erste = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    zweite = db.termine.get_by_extern_ref('900000001', stammdaten['zweite'])
    assert (erste.heim_auswaerts, zweite.heim_auswaerts) == ('heim', 'auswaerts')
    assert (erste.gegner, zweite.gegner) == ('Testteam DFBnet 2', 'Testteam DFBnet')


def test_benachrichtigung_nur_mit_flag(db, stammdaten):
    gerufen = []
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE,
                       notify=lambda t, a, v: gerufen.append(a))
    assert gerufen == []          # ohne benachrichtigen=True schweigt der Lauf

    dfbnet.uebernehmen(db, _datei(_zeile(**{'Spielkennung': '900000007'})),
                       actor=_MARKE, benachrichtigen=True,
                       notify=lambda t, a, v: gerufen.append(a))
    assert gerufen == ['neu']
