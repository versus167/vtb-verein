"""Benachrichtigungen zu Mannschafts-Terminen (Opt-in durch den Verwalter, #95).

Beim Anlegen/Bearbeiten/Absagen/Reaktivieren eines Termins (und beim Anlegen
einer Serie) fragt das Frontend ab, ob das Team informiert werden soll; die
API reicht das als `benachrichtigen`-Flag hierher durch. Empfänger ist der am
Termin-Datum aktive Kader (alle Rollen, mit Benutzerkonto) plus Gäste mit
Zu-/Absage zum Termin, jeweils ohne den Auslöser.

Versand best-effort und nicht-blockierend über NotificationService (bevorzugter
Kanal des Users: Matrix/Push, Fallback E-Mail). User-Objekte werden im
Request-Thread geladen — im Hintergrund-Thread sind keine DB-Zugriffe erlaubt
(nicht-thread-sicheres Singleton, s. notification_service).
"""
import os
from datetime import date, datetime
from typing import Optional

AKTION_NEU = 'neu'
AKTION_GEAENDERT = 'geaendert'
AKTION_ABGESAGT = 'abgesagt'
AKTION_REAKTIVIERT = 'reaktiviert'
AKTION_EINGELADEN = 'eingeladen'

_TITEL = {
    AKTION_NEU: 'Neuer Termin',
    AKTION_GEAENDERT: 'Termin geändert',
    AKTION_ABGESAGT: 'Termin abgesagt',
    AKTION_REAKTIVIERT: 'Termin findet statt',
    AKTION_EINGELADEN: 'Einladung',
}

_WOCHENTAGE_KURZ = ('Mo.', 'Di.', 'Mi.', 'Do.', 'Fr.', 'Sa.', 'So.')
_WOCHENTAGE_WOECHENTLICH = ('montags', 'dienstags', 'mittwochs', 'donnerstags',
                            'freitags', 'samstags', 'sonntags')

_TYP_LABELS = {'training': 'Training', 'spiel': 'Spiel', 'sonstiges': 'Sonstiges'}

# Feld → Klartext in der Abweichungs-Meldung. Gleiche Wortwahl wie im Dialog
# (ABWEICHUNG_FELDER in frontend/src/composables/useTermine.js), damit die
# Meldung und das, was der Betreuer dann sieht, dieselbe Sprache sprechen.
_ABWEICHUNG_FELDER = {
    'beginn': 'Anstoß', 'ort': 'Spielort', 'heim_auswaerts': 'Heimrecht',
    'gegner': 'Gegner', 'entfallen': 'nicht mehr in diesem Auszug',
}

# Feld → Anzeige-Label, Reihenfolge = Reihenfolge im Änderungs-Diff.
_DIFF_FELDER = (
    ('typ', 'Typ'), ('beginn', 'Beginn'), ('ende', 'Ende'), ('ort', 'Ort'),
    ('treffpunkt', 'Treffpunkt'), ('treffpunkt_zeit', 'Treffpunkt-Zeit'),
    ('gegner', 'Gegner'), ('heim_auswaerts', 'Heim/Auswärts'),
    ('beschreibung', 'Beschreibung'),
)


# ------------------------------------------------------------------ Formatierung
def format_datum(wert: Optional[str]) -> str:
    """'2026-07-22' → 'Mi., 22.07.2026' (None → '–')."""
    if not wert:
        return '–'
    try:
        d = date.fromisoformat(wert)
    except ValueError:
        return wert
    return f"{_WOCHENTAGE_KURZ[d.weekday()]}, {d:%d.%m.%Y}"


def format_wandzeit(wert: Optional[str]) -> str:
    """'2026-07-22T18:30' → 'Mi., 22.07.2026 18:30' (None → '–')."""
    if not wert:
        return '–'
    try:
        dt = datetime.fromisoformat(wert)
    except ValueError:
        return wert
    return f"{_WOCHENTAGE_KURZ[dt.weekday()]}, {dt:%d.%m.%Y %H:%M}"


def eigenes_team(mannschaft_name: Optional[str]) -> str:
    """'AH' → 'VTB AH': Vereinskürzel vor den Mannschaftsnamen.

    Das Kürzel ist Stammdatum (``VTB_VEREIN_KURZ``, im Backend
    ``settings.VEREIN_KURZ``) – die Domänenschicht kennt die API-Settings nicht
    und liest die Env darum direkt; der Platzhalter-Default („Beispiel") ist
    derselbe. Trägt der Mannschaftsname das Kürzel schon, bleibt er unverändert;
    sonst stünde da „VTB VTB Chemnitz 2".
    """
    name = (mannschaft_name or '').strip()
    kurz = os.getenv('VTB_VEREIN_KURZ', 'Beispiel').strip()
    if not name or not kurz or name.lower().startswith(kurz.lower()):
        return name
    return f"{kurz} {name}"


def termin_titel(t, mannschaft_name: Optional[str] = None) -> str:
    """Kurztitel analog Frontend: 'Spiel (A) SV X - VTB AH' | 'Training' | 'Sonstiges'.

    Die Paarung steht in Spielrichtung – Heimmannschaft zuerst, wie auf jedem
    Spielplan. `mannschaft_name` reicht der Aufrufer durch, wenn er ihn ohnehin
    schon geladen hat; sonst zählt der am Termin mitgelesene Name.
    """
    if t.typ != 'spiel':
        return _TYP_LABELS.get(t.typ, t.typ)
    eigen = eigenes_team(mannschaft_name if mannschaft_name is not None
                         else getattr(t, 'mannschaft_name', None))
    gegner = (t.gegner or '').strip()
    kennung = {'heim': ' (H)', 'auswaerts': ' (A)'}.get(t.heim_auswaerts, '')
    if not eigen or not gegner:
        paarung = eigen or gegner
    elif t.heim_auswaerts == 'auswaerts':
        paarung = f"{gegner} - {eigen}"
    elif t.heim_auswaerts == 'heim':
        paarung = f"{eigen} - {gegner}"
    else:
        # Ohne Heimrecht wäre jede Reihenfolge eine Behauptung – dann neutral.
        paarung = f"{eigen} vs. {gegner}"
    return f"Spiel{kennung}{f' {paarung}' if paarung else ''}"


def _feld_wert(feld: str, wert) -> str:
    if feld in ('beginn', 'ende'):
        return format_wandzeit(wert)
    if feld == 'typ':
        return _TYP_LABELS.get(wert, wert or '–')
    if feld == 'heim_auswaerts':
        return {'heim': 'Heim', 'auswaerts': 'Auswärts'}.get(wert, '–')
    return wert if wert else '–'


def diff_termin(alt, neu) -> list[str]:
    """Lesbare Änderungszeilen ('Ort: Halle 1 → Halle 2') zwischen zwei
    Termin-Ständen; leere Liste, wenn sich fachlich nichts geändert hat
    (dann wird auch nicht benachrichtigt)."""
    zeilen = []
    for feld, label in _DIFF_FELDER:
        a, n = getattr(alt, feld), getattr(neu, feld)
        if a != n:
            zeilen.append(f"{label}: {_feld_wert(feld, a)} → {_feld_wert(feld, n)}")
    return zeilen


def detail_zeilen(t) -> list[str]:
    """Ende/Ort/Treffpunkt/Beschreibung als Meldungszeilen – geteilt mit der
    Erinnerung an fehlende Meldungen (termin_erinnerung_service)."""
    zeilen = []
    if t.ende:
        zeilen.append(f"Ende: {format_wandzeit(t.ende)}")
    if t.ort:
        zeilen.append(f"Ort: {t.ort}")
    if t.treffpunkt or t.treffpunkt_zeit:
        treff = ' '.join(x for x in (t.treffpunkt_zeit, t.treffpunkt) if x)
        zeilen.append(f"Treffpunkt: {treff}")
    if t.beschreibung:
        zeilen.append(f"Beschreibung: {t.beschreibung}")
    return zeilen


# ----------------------------------------------------------------------- Versand
def termin_url(termin_id: Optional[int] = None) -> str:
    """Ziel für den Klick auf die Nachricht (#158).

    Mit ID direkt auf den Termin — dort stecken die Zusage-Knöpfe, und genau die
    will man drücken, wenn einen die Meldung erreicht. Ohne ID (Serie: viele
    Termine, keiner davon „der" gemeinte) bleibt es bei der Liste.
    Pendant für Tickets: TicketService._ticket_url.
    """
    return f"/termine?termin={termin_id}" if termin_id else "/termine"


def _mannschaft_name(db, mannschaft_id: int) -> str:
    mannschaft = db.get_mannschaft(mannschaft_id)
    return mannschaft.name if mannschaft else f"Mannschaft {mannschaft_id}"


def _send(db, user_ids: list[int], exclude_user_id: Optional[int],
          title: str, message: str, url: str = '/') -> None:
    """Lädt die Empfänger im Request-Thread und stößt den Versand im
    Hintergrund an; der Auslöser selbst und inaktive User werden übersprungen.
    `url` ist das Ziel beim Klick auf die Nachricht (Push-Deep-Link bzw. Link
    in der E-Mail)."""
    from app.services.notification_service import NotificationService
    for uid in dict.fromkeys(user_ids):
        if uid == exclude_user_id:
            continue
        user = db.users.get_by_id(uid)
        if user and user.active:
            NotificationService.send_notification_async(user, title, message,
                                                        push_service=db.push, url=url)


def notify_termin(db, termin, aktion: str, actor_user_id: Optional[int],
                  aenderungen: Optional[list[str]] = None) -> None:
    """Informiert den aktiven Kader (Stichtag = Termin-Datum) und die Gäste des
    Termins. Bei AKTION_GEAENDERT gehören die `aenderungen` (aus diff_termin)
    in die Nachricht, sonst die Termin-Details."""
    m_name = _mannschaft_name(db, termin.mannschaft_id)
    title = f"{_TITEL.get(aktion, aktion)} – {m_name}"
    zeilen = [f"{termin_titel(termin, m_name)} am {format_wandzeit(termin.beginn)} ({m_name})"]
    if aktion == AKTION_GEAENDERT and aenderungen:
        zeilen += ["", "Änderungen:"] + [f"- {z}" for z in aenderungen]
    else:
        zeilen += detail_zeilen(termin)
    if aktion == AKTION_ABGESAGT:
        zeilen += ["", "Der Termin wurde abgesagt."]
    elif aktion == AKTION_REAKTIVIERT:
        zeilen += ["", "Der abgesagte Termin findet wieder statt."]
    user_ids = db.termine.list_kader_user_ids(termin.mannschaft_id, termin.beginn[:10])
    user_ids += db.termin_zusagen.list_user_ids_mit_zusage(termin.id)   # Gäste
    _send(db, user_ids, actor_user_id, title, "\n".join(zeilen),
          url=termin_url(termin.id))


def notify_einladung(db, termin, mitglied_ids: list[int],
                     actor_user_id: Optional[int]) -> None:
    """Lädt die genannten Mitglieder zu einem Termin ein (Nachricht an ihr Konto).

    Eigener Anlass statt AKTION_NEU: Für die Eingeladenen ist der Termin nicht
    „neu", sondern eine Bitte um Antwort – und die Nachricht geht bewusst NUR an
    sie, nicht an den Kader, der den Termin längst kennt. Wer kein Benutzerkonto
    hat, bleibt hier still übrig; eingetragen ist er trotzdem.
    """
    m_name = _mannschaft_name(db, termin.mannschaft_id)
    zeilen = [f"Du bist eingeladen: {termin_titel(termin, m_name)} am "
              f"{format_wandzeit(termin.beginn)} ({m_name})"]
    zeilen += detail_zeilen(termin)
    zeilen += ["", "Bitte in der App zu- oder absagen."]
    user_ids = []
    for mid in mitglied_ids:
        try:
            mitglied = db.get_mitglied(mid)
        except KeyError:
            continue
        if mitglied.user_id:
            user_ids.append(mitglied.user_id)
    if not user_ids:
        return
    _send(db, user_ids, actor_user_id, f"{_TITEL[AKTION_EINGELADEN]} – {m_name}",
          "\n".join(zeilen), url=termin_url(termin.id))


def notify_abweichungen(db, mannschaft_id: int, fragen: list[tuple],
                        actor_user_id: Optional[int]) -> None:
    """Betreuer/ÜL über neue offene Fragen aus dem Spielplan-Import informieren.

    Bewusst ein engerer Kreis und ein eigener Anlass: Der Kader bekommt Meldungen
    über *geänderte* Termine, hier hat sich aber gerade nichts geändert — der
    Import hat den Termin nicht angefasst, weil beide Seiten abweichen. Ohne
    diese Meldung fiele der einzige Fall, der eine Handlung verlangt, still unter
    den Tisch: Das Badge am Termin sieht nur, wer von sich aus hinschaut.
    """
    empfaenger = db.termine.list_verwalter_user_ids(mannschaft_id)
    if not empfaenger:
        return
    m_name = _mannschaft_name(db, mannschaft_id)
    anzahl = len({t for t, _ in fragen})
    # Neutral formuliert: Es stecken zwei Anlässe drin – „beide Seiten geändert"
    # und „Spiel nicht mehr im Export". Eine Begründung im Kopf träfe je nach
    # Lauf nur die Hälfte der Zeilen.
    kopf = ("Eine Ansetzung braucht" if anzahl == 1
            else f"{anzahl} Ansetzungen brauchen")
    zeilen = [f"{kopf} eine Entscheidung – der Import hat sie nicht "
              f"angefasst ({m_name}).", ""]
    for termin_id, felder in _fragen_je_termin(db, fragen):
        termin = db.termine.get(termin_id)
        if termin is None:
            continue
        zeilen.append(f"- {termin_titel(termin, m_name)} am {format_wandzeit(termin.beginn)}"
                      f": {', '.join(felder)}")
    zeilen += ["", "Bitte im Termin entscheiden, welcher Stand gilt."]
    # Betrifft es genau einen Termin, führt der Klick dorthin; bei mehreren gäbe
    # es kein richtiges Ziel, dann bleibt es bei der Liste.
    betroffene = {t for t, _ in fragen}
    _send(db, empfaenger, actor_user_id,
          f"Spielplan: Entscheidung nötig – {m_name}", "\n".join(zeilen),
          url=termin_url(next(iter(betroffene)) if len(betroffene) == 1 else None))


def _fragen_je_termin(db, fragen: list[tuple]) -> list[tuple]:
    """[(termin_id, feld), …] -> [(termin_id, ['Anstoß', …]), …] in Eingabereihenfolge."""
    gebuendelt: dict[int, list] = {}
    for termin_id, feld in fragen:
        gebuendelt.setdefault(termin_id, []).append(_ABWEICHUNG_FELDER.get(feld, feld))
    return list(gebuendelt.items())


def notify_serie(db, serie, actor_user_id: Optional[int]) -> None:
    """Informiert den Kader über eine neu angelegte wöchentliche Terminserie
    (Stichtag = erster Serientag, frühestens heute)."""
    m_name = _mannschaft_name(db, serie.mannschaft_id)
    wtag = _WOCHENTAGE_WOECHENTLICH[date.fromisoformat(serie.start_datum).weekday()]
    typ = _TYP_LABELS.get(serie.typ, serie.typ)
    zeilen = [f"{typ} wöchentlich {wtag} um {serie.beginn_zeit} Uhr ({m_name})",
              f"Ab {format_datum(serie.start_datum)}"
              + (f" bis {format_datum(serie.ende_datum)}" if serie.ende_datum else "")]
    if serie.ort:
        zeilen.append(f"Ort: {serie.ort}")
    if serie.treffpunkt or serie.treffpunkt_zeit:
        treff = ' '.join(x for x in (serie.treffpunkt_zeit, serie.treffpunkt) if x)
        zeilen.append(f"Treffpunkt: {treff}")
    if serie.beschreibung:
        zeilen.append(f"Beschreibung: {serie.beschreibung}")
    stichtag = max(serie.start_datum, date.today().isoformat())
    user_ids = db.termine.list_kader_user_ids(serie.mannschaft_id, stichtag)
    _send(db, user_ids, actor_user_id, f"Neue Terminserie – {m_name}", "\n".join(zeilen),
          url=termin_url())
