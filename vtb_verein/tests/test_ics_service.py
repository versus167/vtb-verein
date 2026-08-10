"""ICS-Feed für „Meine Termine" (#153, app/services/ics_service.py).

Reine Textbau-Funktionen, deshalb ohne DB: Geprüft wird gegen feste Strings,
denn genau an den Details scheitert ein selbstgebautes ICS — Zeitzone, Faltung
auf 75 Oktett, Escaping und eine UID, die sich zwischen zwei Abrufen nicht ändert.
"""
from datetime import datetime, timezone

from app.services import ics_service as ics


def _termin(**kw) -> dict:
    """Vollständiger Termin, wie ihn TerminRepository.list_for_user liefert."""
    basis = {
        'id': 7, 'version': 3, 'typ': 'training', 'beginn': '2026-08-30T13:00',
        'ende': None, 'ort': None, 'gegner': None, 'heim_auswaerts': None,
        'status': 'geplant', 'beschreibung': None, 'treffpunkt': None,
        'treffpunkt_zeit': None, 'mannschaft_name': 'AH',
        'spielstaette_name': None, 'spielstaette_strasse': None,
        'spielstaette_plz': None, 'spielstaette_ort': None,
        'spielstaette_untergrund': None, 'meine_antwort': None,
    }
    basis.update(kw)
    return basis


def _kalender(*termine, **kw) -> str:
    kw.setdefault('host', 'app.example.de')
    kw.setdefault('jetzt', datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc))
    return ics.baue_kalender(list(termine), **kw)


# ------------------------------------------------------------------ Escaping

def test_escape_maskiert_sonderzeichen():
    assert ics.escape("a,b;c\\d") == "a\\,b\\;c\\\\d"


def test_escape_umbrueche_werden_zu_backslash_n():
    assert ics.escape("Zeile1\r\nZeile2\nZeile3") == "Zeile1\\nZeile2\\nZeile3"


def test_escape_laesst_doppelpunkt_stehen():
    """Ein maskierter Doppelpunkt landet sichtbar im Kalender – er ist erlaubt."""
    assert ics.escape("http://x/y") == "http://x/y"


# ------------------------------------------------------------------- Faltung

def test_kurze_zeile_bleibt_ungefaltet():
    assert ics.falten("SUMMARY:Training") == ["SUMMARY:Training"]


def test_lange_zeile_wird_auf_75_oktett_gefaltet():
    zeilen = ics.falten("X:" + "a" * 200)
    assert len(zeilen[0].encode()) == 75
    assert all(z.startswith(" ") for z in zeilen[1:])
    assert all(len(z.encode()) <= 75 for z in zeilen)
    # Verlustfrei: zusammengesetzt (ohne die führenden Leerzeichen) das Original
    assert zeilen[0] + "".join(z[1:] for z in zeilen[1:]) == "X:" + "a" * 200


def test_faltung_schneidet_nicht_in_ein_mehrbyte_zeichen():
    """Ein „ü" belegt zwei Oktett; ein Schnitt dazwischen ergäbe Buchstabensalat."""
    zeilen = ics.falten("X:" + "ü" * 60)
    assert "".join([zeilen[0]] + [z[1:] for z in zeilen[1:]]) == "X:" + "ü" * 60
    assert all(len(z.encode()) <= 75 for z in zeilen)


# ------------------------------------------------------------------ Zeitzone

def test_dtstart_traegt_die_zeitzone():
    """Ohne TZID deuten Clients die Wandzeit als UTC – zwei Stunden daneben."""
    assert "DTSTART;TZID=Europe/Berlin:20260830T130000" in _kalender(_termin())


def test_vtimezone_ist_eingebettet():
    """Clients, die Europe/Berlin nicht selbst kennen, brauchen die Regeln mit."""
    text = _kalender(_termin())
    assert "BEGIN:VTIMEZONE" in text and "TZID:Europe/Berlin" in text
    assert "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU" in text


# ---------------------------------------------------------------- Zeitpunkte

def test_termin_ohne_ende_bekommt_standarddauer():
    assert "DTEND;TZID=Europe/Berlin:20260830T150000" in _kalender(_termin())


def test_gepflegtes_ende_wird_uebernommen():
    text = _kalender(_termin(ende='2026-08-30T14:30'))
    assert "DTEND;TZID=Europe/Berlin:20260830T143000" in text


def test_ende_vor_beginn_faellt_auf_standarddauer_zurueck():
    """Tippfehler in der Erfassung: sonst stünde ein Termin mit Negativdauer drin."""
    text = _kalender(_termin(ende='2026-08-30T11:00'))
    assert "DTEND;TZID=Europe/Berlin:20260830T150000" in text


def test_termin_ohne_beginn_wird_uebersprungen():
    text = _kalender(_termin(beginn=None))
    assert "BEGIN:VEVENT" not in text
    assert text.startswith("BEGIN:VCALENDAR") and text.endswith("END:VCALENDAR\r\n")


# --------------------------------------------------------------- Identität

def test_uid_ist_stabil_und_traegt_die_termin_id():
    assert "UID:termin-7@app.example.de" in _kalender(_termin())


def test_uid_aendert_sich_nicht_zwischen_abrufen():
    """Würfelte sie neu, legte jeder Poll des Kalenders alles noch einmal an."""
    erst = _kalender(_termin(), jetzt=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc))
    spaeter = _kalender(_termin(), jetzt=datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc))
    hole_uid = lambda t: [z for z in t.split("\r\n") if z.startswith("UID:")]  # noqa: E731
    assert hole_uid(erst) == hole_uid(spaeter)


def test_sequence_kommt_aus_der_version():
    assert "SEQUENCE:3" in _kalender(_termin(version=3))


# ------------------------------------------------------------------- Inhalte

def test_spiel_bekommt_die_paarung_als_titel():
    text = _kalender(_termin(typ='spiel', gegner='TSV Oberfrohna', heim_auswaerts='heim'))
    assert "SUMMARY:Spiel (H) " in text and "TSV Oberfrohna" in text


def test_training_nennt_die_mannschaft():
    """Im eigenen Kalender steht der Termin ohne Kontext – „Training" allein
    sagt bei zwei Mannschaften nichts."""
    assert "SUMMARY:Training AH" in _kalender(_termin(typ='training'))


def test_location_enthaelt_die_anschrift():
    """Mit der Anschrift kann ein Navi etwas anfangen, mit dem Platznamen nicht."""
    text = _kalender(_termin(spielstaette_name='Sportplatz Ebersdorf',
                             spielstaette_strasse='Höhensonnenweg 3',
                             spielstaette_plz='09131', spielstaette_ort='Chemnitz'))
    entfaltet = text.replace("\r\n ", "")
    assert "LOCATION:Sportplatz Ebersdorf\\, Höhensonnenweg 3\\, 09131 Chemnitz" in entfaltet


def test_beschreibung_buendelt_treffpunkt_untergrund_und_link():
    text = _kalender(_termin(treffpunkt='Vereinsheim', treffpunkt_zeit='12:15',
                             spielstaette_untergrund='Kunstrasen',
                             beschreibung='Trikots mitbringen'),
                     basis_url='https://app.example.de')
    entfaltet = text.replace("\r\n ", "")
    assert "Treffpunkt: 12:15 Vereinsheim" in entfaltet
    assert "Untergrund: Kunstrasen" in entfaltet
    assert "Trikots mitbringen" in entfaltet
    assert "https://app.example.de/termine" in entfaltet


def test_abgesagter_termin_bleibt_sichtbar_und_ist_markiert():
    """Wer schon hinfährt, soll die Absage sehen – nicht ein leeres Kalenderblatt."""
    text = _kalender(_termin(status='abgesagt'))
    assert "STATUS:CANCELLED" in text
    assert "BEGIN:VEVENT" in text


def test_absage_steht_im_titel():
    """Google stellt abonnierte Kalender nicht durch – STATUS:CANCELLED allein
    bliebe dort unsichtbar, der Termin sähe aus wie jeder andere."""
    assert "SUMMARY:Abgesagt: Training AH" in _kalender(_termin(status='abgesagt'))


def test_absage_steht_am_anfang_der_beschreibung():
    text = _kalender(_termin(status='abgesagt', treffpunkt='Vereinsheim'))
    beschreibung = [z for z in text.replace("\r\n ", "").split("\r\n")
                    if z.startswith("DESCRIPTION:")][0]
    assert beschreibung.startswith("DESCRIPTION:Dieser Termin wurde abgesagt.")


def test_abgesagter_termin_blockiert_die_zeit_nicht():
    """Sonst gilt man in dieser Stunde als beschäftigt, obwohl nichts stattfindet."""
    assert "TRANSP:TRANSPARENT" in _kalender(_termin(status='abgesagt'))


def test_geplanter_termin_ist_bestaetigt_und_belegt_die_zeit():
    text = _kalender(_termin())
    assert "STATUS:CONFIRMED" in text
    assert "TRANSP:OPAQUE" in text
    assert "Abgesagt" not in text


# --------------------------------------------------------- Eigene Zu-/Absage

def test_eigene_absage_steht_im_titel():
    """Sonst sähe ein Training, für das man abgesagt hat, aus wie jedes andere."""
    assert "SUMMARY:Nicht dabei: Training AH" in _kalender(_termin(meine_antwort='ab'))


def test_eigene_absage_blockiert_die_zeit_nicht():
    assert "TRANSP:TRANSPARENT" in _kalender(_termin(meine_antwort='ab'))


def test_vielleicht_wird_markiert_belegt_die_zeit_aber_weiter():
    """Man könnte ja hingehen – der Kalender soll die Stunde freihalten."""
    text = _kalender(_termin(meine_antwort='vielleicht'))
    assert "SUMMARY:Vielleicht: Training AH" in text
    assert "TRANSP:OPAQUE" in text


def test_zusage_laesst_den_titel_unberuehrt():
    text = _kalender(_termin(meine_antwort='zu'))
    assert "SUMMARY:Training AH" in text
    assert "TRANSP:OPAQUE" in text


def test_eigene_antwort_steht_in_der_beschreibung():
    text = _kalender(_termin(meine_antwort='zu')).replace("\r\n ", "")
    assert "DESCRIPTION:Deine Antwort: Zusage" in text


def test_abgesagter_termin_schlaegt_die_eigene_antwort():
    """Findet er nicht statt, ist unerheblich, ob man zugesagt hatte."""
    text = _kalender(_termin(status='abgesagt', meine_antwort='zu'))
    assert "SUMMARY:Abgesagt: Training AH" in text
    assert "Nicht dabei" not in text
    assert "Deine Antwort" not in text.replace("\r\n ", "")


# ------------------------------------------------------------------- Rahmen

def test_kalender_ist_crlf_terminiert_und_vollstaendig():
    text = _kalender(_termin())
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")


def test_kein_method_feld():
    """METHOD kennzeichnet eine Einladung; ein Abo ist keine – manche Clients
    fragen sonst nach einer Antwort."""
    assert "METHOD:" not in _kalender(_termin())


def test_kalendername_wird_gesetzt_und_maskiert():
    text = _kalender(_termin(), kalender_name='Meine Termine (SV Nord, e.V.)')
    assert "X-WR-CALNAME:Meine Termine (SV Nord\\, e.V.)" in text


def test_leerer_kalender_ist_gueltig():
    text = _kalender()
    assert "BEGIN:VCALENDAR" in text and "END:VCALENDAR" in text
    assert "BEGIN:VEVENT" not in text
