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
from datetime import date, datetime
from typing import Optional

AKTION_NEU = 'neu'
AKTION_GEAENDERT = 'geaendert'
AKTION_ABGESAGT = 'abgesagt'
AKTION_REAKTIVIERT = 'reaktiviert'

_TITEL = {
    AKTION_NEU: 'Neuer Termin',
    AKTION_GEAENDERT: 'Termin geändert',
    AKTION_ABGESAGT: 'Termin abgesagt',
    AKTION_REAKTIVIERT: 'Termin findet statt',
}

_WOCHENTAGE_KURZ = ('Mo.', 'Di.', 'Mi.', 'Do.', 'Fr.', 'Sa.', 'So.')
_WOCHENTAGE_WOECHENTLICH = ('montags', 'dienstags', 'mittwochs', 'donnerstags',
                            'freitags', 'samstags', 'sonntags')

_TYP_LABELS = {'training': 'Training', 'spiel': 'Spiel', 'sonstiges': 'Sonstiges'}

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


def termin_titel(t) -> str:
    """Kurztitel analog Frontend: 'Spiel vs. SV X (H)' | 'Training' | 'Sonstiges'."""
    if t.typ == 'spiel':
        ha = {'heim': ' (H)', 'auswaerts': ' (A)'}.get(t.heim_auswaerts, '')
        gegner = f" vs. {t.gegner}" if t.gegner else ''
        return f"Spiel{gegner}{ha}"
    return _TYP_LABELS.get(t.typ, t.typ)


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


def _detail_zeilen(t) -> list[str]:
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
def _mannschaft_name(db, mannschaft_id: int) -> str:
    mannschaft = db.get_mannschaft(mannschaft_id)
    return mannschaft.name if mannschaft else f"Mannschaft {mannschaft_id}"


def _send(db, user_ids: list[int], exclude_user_id: Optional[int],
          title: str, message: str) -> None:
    """Lädt die Empfänger im Request-Thread und stößt den Versand im
    Hintergrund an; der Auslöser selbst und inaktive User werden übersprungen."""
    from app.services.notification_service import NotificationService
    for uid in dict.fromkeys(user_ids):
        if uid == exclude_user_id:
            continue
        user = db.users.get_by_id(uid)
        if user and user.active:
            NotificationService.send_notification_async(user, title, message,
                                                        push_service=db.push)


def notify_termin(db, termin, aktion: str, actor_user_id: Optional[int],
                  aenderungen: Optional[list[str]] = None) -> None:
    """Informiert den aktiven Kader (Stichtag = Termin-Datum) und die Gäste des
    Termins. Bei AKTION_GEAENDERT gehören die `aenderungen` (aus diff_termin)
    in die Nachricht, sonst die Termin-Details."""
    m_name = _mannschaft_name(db, termin.mannschaft_id)
    title = f"{_TITEL.get(aktion, aktion)} – {m_name}"
    zeilen = [f"{termin_titel(termin)} am {format_wandzeit(termin.beginn)} ({m_name})"]
    if aktion == AKTION_GEAENDERT and aenderungen:
        zeilen += ["", "Änderungen:"] + [f"- {z}" for z in aenderungen]
    else:
        zeilen += _detail_zeilen(termin)
    if aktion == AKTION_ABGESAGT:
        zeilen += ["", "Der Termin wurde abgesagt."]
    elif aktion == AKTION_REAKTIVIERT:
        zeilen += ["", "Der abgesagte Termin findet wieder statt."]
    user_ids = db.termine.list_kader_user_ids(termin.mannschaft_id, termin.beginn[:10])
    user_ids += db.termin_zusagen.list_user_ids_mit_zusage(termin.id)   # Gäste
    _send(db, user_ids, actor_user_id, title, "\n".join(zeilen))


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
    _send(db, user_ids, actor_user_id, f"Neue Terminserie – {m_name}", "\n".join(zeilen))
