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
from datetime import date, timedelta

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
        # Abweichungen zeigen per FK auf termine – zuerst weg, sonst scheitert das
        # Aufräumen und der nächste Test läuft in die Unique-Verletzung.
        cur.execute("DELETE FROM termin_abweichung_history WHERE created_by = %s", (_MARKE,))
        cur.execute("DELETE FROM termin_abweichung WHERE created_by = %s", (_MARKE,))
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


def test_bekannter_platz_ohne_belag_wird_gemeldet(db, stammdaten):
    """Der häufigste Fall: Der Platz steht längst in den Stammdaten, kennt aber
    den Untergrund nicht — er wurde vor dieser Angabe angelegt."""
    bericht = dfbnet.dry_run(db, _datei(_zeile(platztyp='Kunstrasenplatz')))

    assert [p['name'] for p in bericht.abweichende_spielstaetten] == ['Eigener Platz']
    felder = {f['feld']: (f['app'], f['dfbnet'])
              for f in bericht.abweichende_spielstaetten[0]['felder']}
    assert felder['untergrund'] == (None, 'Kunstrasen')
    # Die Adresse steht in der Testvorgabe nicht am Platz -> ebenfalls gemeldet
    assert felder['strasse'] == (None, 'Musterweg 1')
    assert bericht.neue_spielstaetten == []      # der Platz ist ja bekannt


def test_uebereinstimmende_stammdaten_werden_nicht_gemeldet(db, stammdaten):
    with _cur(db) as cur:
        cur.execute("UPDATE spielstaette SET strasse='Musterweg 1', plz='09111', "
                    "ort='Musterstadt', untergrund='Rasen', parallel_moeglich=2 "
                    "WHERE id=%s", (stammdaten['platz'],))

    bericht = dfbnet.dry_run(db, _datei(_zeile(platztyp='Rasenplatz')))
    assert bericht.abweichende_spielstaetten == []


def test_leeres_exportfeld_loescht_keine_gepflegten_daten(db, stammdaten):
    """Fehlt im Export die Angabe, ist das kein Grund, die App zu leeren."""
    with _cur(db) as cur:
        cur.execute("UPDATE spielstaette SET strasse='Musterweg 1', plz='09111', "
                    "ort='Musterstadt', untergrund='Rasen', parallel_moeglich=2 "
                    "WHERE id=%s", (stammdaten['platz'],))

    bericht = dfbnet.dry_run(db, _datei(_zeile(platztyp='')))
    assert bericht.abweichende_spielstaetten == []


def test_platzhalter_werden_nie_gemeldet(db, stammdaten):
    """„Kein Vereinsgelände" ist kein Ort, sondern eine Antwort auf das
    Pflichtfeld — Stammdaten hat er keine."""
    with _cur(db) as cur:
        cur.execute("UPDATE spielstaette SET dfbnet_nr='1000000001' "
                    "WHERE id=%s", (stammdaten['platz'],))
        cur.execute("UPDATE spielstaette SET dfbnet_nr=NULL WHERE platzhalter IS NOT NULL")

    bericht = dfbnet.dry_run(db, _datei(_zeile()))
    assert all(p['name'] != 'Kein Vereinsgelände'
               for p in bericht.abweichende_spielstaetten)


def test_lauf_zieht_die_stammdaten_nach(db, stammdaten):
    """Beim Übernehmen wandern Anschrift, Belag und Kapazität in die Stammdaten —
    das DFBnet ist dafür die offizielle Quelle, da gibt es nichts zu entscheiden."""
    ergebnis = dfbnet.uebernehmen(
        db, _datei(_zeile(platztyp='Kunstrasenplatz')), actor=_MARKE)
    assert ergebnis.spielstaetten_aktualisiert == 1

    platz = db.spielstaetten.get(stammdaten['platz'])
    assert platz.untergrund == 'Kunstrasen'
    assert (platz.strasse, platz.plz, platz.ort) == ('Musterweg 1', '09111', 'Musterstadt')
    assert platz.parallel_moeglich == 2
    assert platz.name == 'Eigener Platz'          # der Name bleibt unangetastet

    # Zweiter Lauf: nichts mehr nachzuziehen
    zweiter = dfbnet.uebernehmen(db, _datei(_zeile(platztyp='Kunstrasenplatz')), actor=_MARKE)
    assert zweiter.spielstaetten_aktualisiert == 0
    assert zweiter.bericht.abweichende_spielstaetten == []


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


# ------------------------------------------------------- Abweichungen (Etappe 4)

def _verlegen(db, termin, beginn):
    """Verlegung durch das Team – wie über das Formular, also mit version-Bump."""
    db.termine.update(termin.id, 'spiel', beginn, None, termin.ort, None, None,
                      termin.gegner, termin.heim_auswaerts, None, 'trainer',
                      termin.version, spielstaette_id=termin.spielstaette_id)


def _offene(db, termin_id):
    return db.termin_abweichungen.list_for_termin(termin_id, nur_offen=True)


def test_konflikt_wird_als_abweichung_festgehalten(db, stammdaten):
    """Der Kern von Etappe 4: Der Lauf entscheidet nicht, er fragt."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')

    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    assert ergebnis.abweichungen == 1

    offen = _offene(db, termin.id)
    assert len(offen) == 1
    assert (offen[0].feld, offen[0].status) == ('beginn', 'offen')
    assert offen[0].wert_app == '2026-08-15T16:00'      # was das Team eingetragen hat
    assert offen[0].wert_extern == '2026-08-15T17:30'   # was das DFBnet sagt


def test_zweiter_lauf_frischt_die_abweichung_auf_statt_zu_doppeln(db, stammdaten):
    """Ein wöchentlicher Import darf den Betreuer nicht mit Dubletten zuschütten."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '18:00'})), actor=_MARKE)

    offen = _offene(db, termin.id)
    assert len(offen) == 1
    assert offen[0].wert_extern == '2026-08-15T18:00'   # der neue Vorschlag
    assert offen[0].version == 2                        # aufgefrischt, nicht neu


def test_schnappschuss_fuehrt_die_spielstaette_mit(db, stammdaten):
    """`ort` ist bloßer Text – ohne die Platz-ID ließe sich der Termin später nicht
    auf den DFBnet-Stand ziehen, ohne die Belegung zu verfälschen."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])

    assert _stand(db, termin.id)['spielstaette_id'] == stammdaten['platz']
    # und der Abgleich läuft weiter nur über die Vergleichsfelder
    assert dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE).aktualisiert == 0


def test_auffrischen_hinterlaesst_die_alte_fassung_in_der_history(db, stammdaten):
    """Der überholte Vorschlag verschwindet aus der offenen Zeile, nicht aus der Welt:
    Wer später prüft, worüber vorige Woche gefragt wurde, findet es in der History."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    abw_id = _offene(db, termin.id)[0].id
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '18:00'})), actor=_MARKE)

    with _cur(db) as cur:
        cur.execute("SELECT version, wert_extern FROM termin_abweichung_history "
                    "WHERE id = %s ORDER BY version", (abw_id,))
        historie = [(r['version'], r['wert_extern']) for r in cur.fetchall()]
    # Die History führt jede Fassung, die aktuelle eingeschlossen: Version 1 hält
    # den überholten Vorschlag fest, Version 2 den, über den jetzt zu entscheiden ist.
    assert historie == [(1, '2026-08-15T17:30'), (2, '2026-08-15T18:00')]
    assert _offene(db, termin.id)[0].wert_extern == '2026-08-15T18:00'


def test_neuer_stand_nach_entscheidung_fragt_erneut(db, stammdaten):
    """Eine getroffene Entscheidung gilt für den Wert, über den entschieden wurde –
    nicht für alle künftigen. Meldet das DFBnet danach einen dritten Stand, entsteht
    neben der entschiedenen Zeile eine neue offene (der Unique-Index greift nur für
    'offen'); die alte Entscheidung bleibt als Beleg stehen."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    assert dfbnet.entscheiden(db, _offene(db, termin.id)[0], 'verworfen',
                              actor='betreuer') is True

    # Das DFBnet verlegt erneut – jetzt auf 19:00
    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '19:00'})), actor=_MARKE)
    assert ergebnis.abweichungen == 1

    offen = _offene(db, termin.id)
    assert len(offen) == 1
    assert offen[0].wert_extern == '2026-08-15T19:00'
    assert offen[0].wert_app == '2026-08-15T16:00'      # die Wahl des Teams steht noch
    # Zwei Zeilen zum Feld: die verworfene von damals und die neue Frage
    alle = db.termin_abweichungen.list_for_termin(termin.id)
    assert sorted(a.status for a in alle) == ['offen', 'verworfen']
    assert db.termine.get(termin.id).beginn == '2026-08-15T16:00'


def test_uebernehmen_schreibt_den_termin_und_beendet_die_frage(db, stammdaten):
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)

    abw = _offene(db, termin.id)[0]
    assert dfbnet.entscheiden(db, abw, 'uebernommen', actor='betreuer') is True

    assert db.termine.get(termin.id).beginn == '2026-08-15T17:30'
    assert _stand(db, termin.id)['beginn'] == '2026-08-15T17:30'
    assert _offene(db, termin.id) == []

    # Und der nächste Lauf fragt nicht erneut
    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    assert (ergebnis.abweichungen, ergebnis.aktualisiert) == (0, 0)


def test_verwerfen_laesst_den_termin_stehen_und_fragt_nie_wieder(db, stammdaten):
    """Auch das Verwerfen schreibt den Stand fort – sonst käme die Frage zurück."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)

    abw = _offene(db, termin.id)[0]
    assert dfbnet.entscheiden(db, abw, 'verworfen', actor='betreuer') is True

    assert db.termine.get(termin.id).beginn == '2026-08-15T16:00'   # Team behält recht
    assert _stand(db, termin.id)['beginn'] == '2026-08-15T17:30'    # Stand zieht mit

    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    assert (ergebnis.abweichungen, ergebnis.aktualisiert) == (0, 0)
    assert db.termine.get(termin.id).beginn == '2026-08-15T16:00'


def test_entscheidung_ist_nur_einmal_moeglich(db, stammdaten):
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)

    abw = _offene(db, termin.id)[0]
    assert dfbnet.entscheiden(db, abw, 'verworfen', actor='betreuer') is True
    # Dieselbe (veraltete) Fassung erneut: kein zweiter Durchgriff
    assert dfbnet.entscheiden(db, abw, 'uebernommen', actor='wer-anders') is False


def test_unstrittiges_feld_laeuft_trotz_konflikt_durch(db, stammdaten):
    """Feldweise, nicht je Termin: Die Ortsverlegung darf nicht an der Zeit hängen."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')      # Team ändert NUR die Zeit

    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile(**{
        'Uhrzeit': '17:30', 'Gastmannschaft': 'SV Ersatz'})), actor=_MARKE)
    assert ergebnis.aktualisiert == 1

    danach = db.termine.get(termin.id)
    assert danach.gegner == 'SV Ersatz'            # unstrittig -> übernommen
    assert danach.beginn == '2026-08-15T16:00'     # strittig -> unangetastet
    assert [a.feld for a in _offene(db, termin.id)] == ['beginn']


def test_erledigte_frage_wird_hinfaellig(db, stammdaten):
    """Zieht das Team den Termin selbst auf den DFBnet-Stand, ist nichts mehr offen."""
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)
    assert len(_offene(db, termin.id)) == 1

    _verlegen(db, db.termine.get(termin.id), '2026-08-15T17:30')   # Team zieht nach
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)

    assert _offene(db, termin.id) == []
    alle = db.termin_abweichungen.list_for_termin(termin.id)
    assert [a.status for a in alle] == ['hinfaellig']


def test_zaehler_fuers_badge(db, stammdaten):
    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')
    dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})), actor=_MARKE)

    assert db.termin_abweichungen.counts_offen([termin.id]) == {termin.id: 1}
    assert db.termin_abweichungen.counts_offen([]) == {}


# ------------------------------------------------ im Export nicht mehr enthalten

# Anders als der Rest der Datei rechnet dieser Block relativ zu heute: „steht
# nicht mehr im Export" wird nur für Spiele gefragt, die noch bevorstehen – mit
# dem sonst üblichen festen 15.08.2026 prüften diese Tests ab dem Folgetag nichts
# mehr. Zwei Spieltage: der erste bleibt in jedem Export stehen und hält damit
# das Datumsfenster offen, am zweiten verschwindet das eigene Spiel.
def _tag(plus_tage: int) -> str:
    return (date.today() + timedelta(days=plus_tage)).strftime('%d.%m.%Y')


_FRUEH = {'Spieldatum': _tag(7)}          # Spielkennung 900000001, wie im Default
_SPAETER = {'Spielkennung': '900000011', 'Spieldatum': _tag(14)}
# Fremdes Spiel am selben Tag: sorgt im „Export ohne" dafür, dass das
# Datumsfenster der Datei gleich bleibt.
_SPAETER_FREMD = {'Spielkennung': '900000012', 'Spieldatum': _tag(14),
                  'Heimmannschaft': 'SV Fremd', 'Gastmannschaft': 'FC Anders'}


def _export_voll():
    return _datei(_zeile(**_FRUEH), _zeile(**_SPAETER))


def _export_ohne():
    return _datei(_zeile(**_FRUEH), _zeile(**_SPAETER_FREMD))


def _export_nur_erster_tag():
    return _datei(_zeile(**_FRUEH))


def test_vorschau_meldet_die_luecke_vorab(db, stammdaten):
    """Was der Lauf als Frage stellen wird, steht schon in der Vorschau."""
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    verschwunden = db.termine.get_by_extern_ref('900000011', stammdaten['erste'])

    bericht = dfbnet.dry_run(db, _export_ohne())

    assert [e['termin_id'] for e in bericht.entfallene] == [verschwunden.id]
    eintrag = bericht.entfallene[0]
    assert (eintrag['mannschaft'], eintrag['spielkennung']) == ('Erste', '900000011')
    assert eintrag['gemeldet'] is False
    assert _offene(db, verschwunden.id) == []        # die Vorschau schreibt nichts


def test_vorschau_kennzeichnet_die_schon_gestellte_frage(db, stammdaten):
    """Zweiter Lauf mit derselben Lücke: Der Termin weiß längst Bescheid."""
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    dfbnet.uebernehmen(db, _export_ohne(), actor=_MARKE)

    assert [e['gemeldet'] for e in dfbnet.dry_run(db, _export_ohne()).entfallene] == [True]


def test_vorschau_ohne_luecke_bleibt_leer(db, stammdaten):
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    assert dfbnet.dry_run(db, _export_voll()).entfallene == []


def test_vorschau_behauptet_nichts_ausserhalb_des_dateifensters(db, stammdaten):
    """Ein Auszug über eine Woche darf nichts über die nächste sagen."""
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    assert dfbnet.dry_run(db, _export_nur_erster_tag()).entfallene == []


def test_fehlendes_spiel_wird_gemeldet_aber_nicht_abgesagt(db, stammdaten):
    """„Fehlt" heißt nicht „abgesagt" – der Export ist ein Zeitfenster-Auszug."""
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    verschwunden = db.termine.get_by_extern_ref('900000011', stammdaten['erste'])

    ergebnis = dfbnet.uebernehmen(db, _export_ohne(), actor=_MARKE)

    assert ergebnis.entfallen == 1
    assert db.termine.get(verschwunden.id).status == 'geplant'     # nichts abgesagt
    assert [a.feld for a in _offene(db, verschwunden.id)] == ['entfallen']


def test_vergangenes_spiel_ohne_zeile_bleibt_unberuehrt(db, stammdaten):
    """Was gelaufen ist, kann nicht mehr entfallen.

    DFBnet räumt ältere Spieltage aus dem Vereinsspielplan; ein Spiel von letzter
    Woche fehlt im nächsten Export ganz normal. Daraus eine Frage an den Betreuer
    zu machen, hieße, jeden Import mit Altlasten zu beantworten.
    """
    vergangen = {'Spielkennung': '900000014', 'Spieldatum': _tag(-7)}
    vergangen_fremd = {'Spielkennung': '900000015', 'Spieldatum': _tag(-7),
                       'Heimmannschaft': 'SV Fremd', 'Gastmannschaft': 'FC Anders'}
    dfbnet.uebernehmen(db, _datei(_zeile(**vergangen), _zeile(**_FRUEH)), actor=_MARKE)
    alt = db.termine.get_by_extern_ref('900000014', stammdaten['erste'])

    # Datei reicht zeitlich bis in die Vergangenheit zurück – nur das eigene
    # Spiel von damals steht nicht mehr drin.
    ohne = _datei(_zeile(**vergangen_fremd), _zeile(**_FRUEH))
    assert dfbnet.dry_run(db, ohne).entfallene == []

    ergebnis = dfbnet.uebernehmen(db, ohne, actor=_MARKE)
    assert ergebnis.entfallen == 0
    assert _offene(db, alt.id) == []
    assert db.termine.get(alt.id).status == 'geplant'


def test_spiel_ausserhalb_des_dateifensters_bleibt_unberuehrt(db, stammdaten):
    """Ein Auszug über eine Woche darf nichts über die nächste behaupten."""
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    spaeter = db.termine.get_by_extern_ref('900000011', stammdaten['erste'])

    ergebnis = dfbnet.uebernehmen(db, _export_nur_erster_tag(), actor=_MARKE)
    assert ergebnis.entfallen == 0
    assert _offene(db, spaeter.id) == []


def test_fehlendes_spiel_wird_nicht_zweimal_gemeldet(db, stammdaten):
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    verschwunden = db.termine.get_by_extern_ref('900000011', stammdaten['erste'])

    erst = dfbnet.uebernehmen(db, _export_ohne(), actor=_MARKE)
    nochmal = dfbnet.uebernehmen(db, _export_ohne(), actor=_MARKE)
    assert (erst.entfallen, nochmal.entfallen) == (1, 0)
    assert len(_offene(db, verschwunden.id)) == 1


def test_wieder_aufgetauchtes_spiel_erledigt_die_meldung(db, stammdaten):
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    verschwunden = db.termine.get_by_extern_ref('900000011', stammdaten['erste'])
    dfbnet.uebernehmen(db, _export_ohne(), actor=_MARKE)
    assert len(_offene(db, verschwunden.id)) == 1

    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    assert _offene(db, verschwunden.id) == []


def test_teil_export_meldet_fremde_mannschaften_nicht_als_entfallen(db, stammdaten):
    """Nur Mannschaften, die im Export vorkommen, werden überhaupt verglichen."""
    dfbnet.uebernehmen(db, _datei(_zeile(**{
        **_FRUEH, 'Heimmannschaft': 'Testteam DFBnet 2',
        'Spielkennung': '900000013'})), actor=_MARKE)
    fremd = db.termine.get_by_extern_ref('900000013', stammdaten['zweite'])

    # Export nur für die Erste, im selben Zeitfenster
    ergebnis = dfbnet.uebernehmen(db, _export_nur_erster_tag(), actor=_MARKE)
    assert ergebnis.entfallen == 0
    assert _offene(db, fremd.id) == []


def test_entfallenes_spiel_uebernehmen_sagt_den_termin_ab(db, stammdaten):
    dfbnet.uebernehmen(db, _export_voll(), actor=_MARKE)
    verschwunden = db.termine.get_by_extern_ref('900000011', stammdaten['erste'])
    dfbnet.uebernehmen(db, _export_ohne(), actor=_MARKE)

    abw = _offene(db, verschwunden.id)[0]
    assert dfbnet.entscheiden(db, abw, 'uebernommen', actor='betreuer') is True
    assert db.termine.get(verschwunden.id).status == 'abgesagt'
    # Abgesagte Termine stehen nicht mehr zur Debatte
    assert dfbnet.uebernehmen(db, _export_ohne(), actor=_MARKE).entfallen == 0


# --------------------------------------- Meldung an die Betreuer/ÜL (#95)
def test_lauf_meldet_nur_frisch_aufgeworfene_fragen(db, stammdaten):
    """Nur die erste Meldung erreicht die Betreuer, das Auffrischen nicht mehr.

    Der Import läuft womöglich wöchentlich. Ohne die Unterscheidung bekämen
    Betreuer und ÜL jeden Montag dieselbe Aufforderung erneut – und würden sie
    nach der zweiten Woche ignorieren.
    """
    gemeldet = []

    def _melden(mannschaft_id, fragen):
        gemeldet.append((mannschaft_id, sorted(fragen)))

    dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE)
    termin = db.termine.get_by_extern_ref('900000001', stammdaten['erste'])
    _verlegen(db, termin, '2026-08-15T16:00')

    erster = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '17:30'})),
                                actor=_MARKE, notify_entscheidung=_melden)
    assert erster.entscheidungen_gemeldet == 1
    assert gemeldet == [(stammdaten['erste'], [(termin.id, 'beginn')])]

    zweiter = dfbnet.uebernehmen(db, _datei(_zeile(**{'Uhrzeit': '18:00'})),
                                 actor=_MARKE, notify_entscheidung=_melden)
    assert zweiter.abweichungen == 1          # die Frage steht weiter offen …
    assert zweiter.entscheidungen_gemeldet == 0   # … ist aber nicht neu
    assert len(gemeldet) == 1


def test_stille_laeufe_melden_nichts(db, stammdaten):
    """Ohne Konflikt gibt es nichts zu entscheiden – und keine Meldung."""
    gemeldet = []
    ergebnis = dfbnet.uebernehmen(db, _datei(_zeile()), actor=_MARKE,
                                  notify_entscheidung=lambda m, f: gemeldet.append(m))
    assert ergebnis.angelegt == 1
    assert gemeldet == []


def test_verwalter_liste_laesst_spieler_aussen_vor(db, stammdaten):
    """Empfängerkreis der Meldung: nur wer die Frage auch entscheiden darf."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied (vorname, nachname, zahlungsart, created_by, "
            "updated_by) VALUES ('Test', 'Betreuer', 'ueberweisung', %s, %s) "
            "RETURNING id", (_MARKE, _MARKE))
        betreuer_mitglied = cur.fetchone()['id']
        cur.execute(
            "INSERT INTO mitglied (vorname, nachname, zahlungsart, created_by, "
            "updated_by) VALUES ('Test', 'Spieler', 'ueberweisung', %s, %s) "
            "RETURNING id", (_MARKE, _MARKE))
        spieler_mitglied = cur.fetchone()['id']
        ids = {}
        for schluessel, mitglied_id, rolle in (
                ('betreuer', betreuer_mitglied, 'betreuer'),
                ('spieler', spieler_mitglied, 'spieler')):
            cur.execute(
                "INSERT INTO users (username, email, password_hash, role, active, "
                "created_by, updated_by) VALUES (%s, %s, 'x', 'mitglied', 1, %s, %s) "
                "RETURNING id",
                (f'{_MARKE}-{schluessel}', f'{_MARKE}-{schluessel}@example.invalid',
                 _MARKE, _MARKE))
            ids[schluessel] = cur.fetchone()['id']
            cur.execute("UPDATE mitglied SET user_id = %s WHERE id = %s",
                        (ids[schluessel], mitglied_id))
            cur.execute(
                "INSERT INTO mitglied_mannschaft (mitglied_id, mannschaft_id, rolle, "
                "von, created_by, updated_by) VALUES (%s, %s, %s, '2026-01-01', %s, %s)",
                (mitglied_id, stammdaten['erste'], rolle, _MARKE, _MARKE))

    try:
        assert db.termine.list_verwalter_user_ids(stammdaten['erste']) == [ids['betreuer']]
        alle = db.termine.list_kader_user_ids(stammdaten['erste'])
        assert set(alle) == {ids['betreuer'], ids['spieler']}
    finally:
        # Kader und Benutzer kennt die stammdaten-Fixture nicht; ohne dieses
        # Aufräumen scheitert ihr DELETE auf mannschaft am Fremdschlüssel.
        with db.cursor() as cur:
            for tabelle in ('mitglied_mannschaft_history', 'mitglied_mannschaft',
                            'mitglied_history', 'mitglied', 'users'):
                cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (_MARKE,))
