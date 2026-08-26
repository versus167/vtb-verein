"""Erinnerung an fehlende Termin-Meldungen (#95-Nachgang).

Anlegen, Ändern, Absagen, Einladen — für jeden dieser Vorgänge geht bereits eine
Benachrichtigung raus (termin_notification_service). Was danach kommt, sieht
niemand: Wer die Meldung überflogen und dann vergessen hat, taucht am Spieltag
als Fragezeichen in der Kader-Liste auf, und der Betreuer weiß bis zuletzt nicht,
ob er elf Leute hat.

Dieser Lauf schließt die Lücke. Kurz vor dem Termin erinnert er genau die, von
denen noch keine Meldung vorliegt — Kader wie eingeladene Gäste, jeder einzeln
und nur zu seinen eigenen offenen Terminen. Wer geantwortet hat, hört nichts;
„vielleicht" ist eine Antwort.

Erinnert wird in zwei Stufen mit Vorlauf in Tagen (Vorgabe 3 und 1). Die Zahlen
stehen NICHT im Code, sondern in `termin_erinnerung_einstellungen` (#95-Nachgang):
Wie viel Vorlauf eine Mannschaft braucht, weiß der Verein, nicht der Entwickler.
Stufe 0 schaltet die einzelne Stufe ab, `aktiv=False` den ganzen Lauf.

Je Termin und Stufe geht die Erinnerung genau einmal raus; das Gedächtnis dafür
ist das Zugriffsprotokoll (eine Zeile je Termin und Stufe, wie bei den
Ticket-Erinnerungen). Der Lauf hängt damit nicht an seinem Takt: Ein
ausgefallener Lauf holt die Stufe nach (der Vorlauf ist dann eben kürzer), ein
doppelter schickt nichts zweimal.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from app.models.termin import TerminErinnerungEinstellungen
from app.services import termin_notification_service as terminmeldung

logger = logging.getLogger(__name__)

EVENT_ERINNERUNG = 'termin_erinnerung'
_KATEGORIE = 'termin'

# Vorgabe, solange keine Einstellungen vorliegen (Tests, ganz frische DB): die
# Standardwerte der Dataclass – also genau die Werte, die auch in der Tabelle stehen.
STANDARD_EINSTELLUNGEN = TerminErinnerungEinstellungen()


# ------------------------------------------------------------------ Fälligkeit
def stufen(einstellungen: Optional[TerminErinnerungEinstellungen] = None) -> tuple[int, ...]:
    """Die eingestellten Vorläufe in Tagen, absteigend und ohne Dubletten.

    0 heißt „diese Stufe nicht" und fällt heraus; stehen beide auf demselben Wert,
    bleibt eine Stufe übrig (zweimal derselbe Tag wäre eine Erinnerung zu viel).
    """
    e = einstellungen or STANDARD_EINSTELLUNGEN
    return tuple(sorted({t for t in (e.erste_stufe_tage, e.zweite_stufe_tage) if t > 0},
                        reverse=True))


def vorlauf_tage(beginn: Optional[str], heute: date) -> Optional[int]:
    """Wie viele Tage liegen zwischen heute und dem Termin-Tag? None, wenn nicht lesbar.

    Gezählt wird in Kalendertagen, nicht in Stunden: „einen Tag vorher" heißt für
    jeden am Vortag – egal ob der Termin um 9 oder um 20 Uhr beginnt.
    """
    try:
        tag = date.fromisoformat((beginn or '')[:10])
    except ValueError:
        return None
    return (tag - heute).days


def stufe_fuer(vorlauf: Optional[int], stufen_tage: tuple[int, ...]) -> Optional[int]:
    """Welche Stufe ist bei diesem Vorlauf dran? None = keine.

    Zuständig ist die ENGSTE Stufe, die den Vorlauf noch abdeckt: bei drei Tagen
    Vorlauf die 3er-Stufe, am Vortag die 1er. Das hält zwei Fälle sauber
    auseinander, die sich sonst beißen würden:

    * Der Lauf ist einen Tag ausgefallen (Vorlauf 2, Stufen 3/1): Die 3er-Stufe
      kommt verspätet nach, statt ersatzlos auszufallen.
    * Ein Termin wird erst morgen für morgen angelegt: Es geht NUR die 1er-Stufe
      raus, nicht beide auf einmal.
    """
    if vorlauf is None or vorlauf < 1:
        return None                     # heute oder vorbei – da ist Erinnern zu spät
    passend = [s for s in stufen_tage if vorlauf <= s]
    return min(passend) if passend else None


def schluessel(termin_id: int, stufe: int) -> str:
    """Gedächtnis-Schlüssel im Protokoll: je Termin und Stufe eine Zeile."""
    return f"{termin_id}:{stufe}"


def faellige(termine: list, bereits_erinnert: dict,
             einstellungen: Optional[TerminErinnerungEinstellungen] = None,
             heute: Optional[date] = None) -> list[tuple]:
    """Aus den anstehenden Terminen die fälligen heraussuchen – (Termin, Stufe, Vorlauf).

    `bereits_erinnert` sind die Protokoll-Schlüssel der schon verschickten Stufen
    (access_log_repository.letzte_je_detail).
    """
    einst = einstellungen or STANDARD_EINSTELLUNGEN
    heute = heute or date.today()
    if not einst.aktiv:
        return []
    st = stufen(einst)
    faellig = []
    for t in termine:
        vorlauf = vorlauf_tage(t.beginn, heute)
        stufe = stufe_fuer(vorlauf, st)
        if stufe is None or schluessel(t.id, stufe) in bereits_erinnert:
            continue
        faellig.append((t, stufe, vorlauf))
    return faellig


# ------------------------------------------------------------------- Nachricht
def wann_text(vorlauf: int) -> str:
    """1 → 'morgen', 2 → 'übermorgen', sonst 'in N Tagen'."""
    return {1: 'morgen', 2: 'übermorgen'}.get(vorlauf, f"in {vorlauf} Tagen")


def build_erinnerung(termin, vorlauf: int, mannschaft_name: Optional[str] = None) -> tuple:
    """Titel und Text der Erinnerung. Der Text sagt, warum sie kommt – sonst liest
    er sich wie die dritte Kopie der ursprünglichen Termin-Meldung."""
    m_name = mannschaft_name or getattr(termin, 'mannschaft_name', None) \
        or f"Mannschaft {termin.mannschaft_id}"
    titel = f"Rückmeldung fehlt – {m_name}"
    zeilen = [f"{terminmeldung.termin_titel(termin, m_name)} am "
              f"{terminmeldung.format_wandzeit(termin.beginn)} ({m_name})"]
    zeilen += terminmeldung.detail_zeilen(termin)
    zeilen += ["", f"Von dir liegt noch keine Meldung vor – der Termin ist "
                   f"{wann_text(vorlauf)}.",
               "Bitte in der App zu- oder absagen."]
    return titel, "\n".join(zeilen)


# --------------------------------------------------------------------- Versand
def _versenden(db, user_ids: list[int], titel: str, text: str, url: str) -> int:
    """An die aktiven Konten aus `user_ids` schicken; gibt die Zahl der Erreichten
    zurück. Ein Fehler bei einem Empfänger stoppt den Lauf nicht.

    Bewusst synchron (wie bei den Ticket-Erinnerungen): Der Lauf ist ein
    kurzlebiger Prozess, der einen Hintergrund-Pool beim Beenden mitrisse.
    """
    from app.services.notification_service import NotificationService
    erreicht = 0
    for user_id in dict.fromkeys(user_ids):
        user = db.users.get_by_id(user_id)
        if not (user and user.active):
            continue
        try:
            if NotificationService.send_notification(user, titel, text,
                                                     push_service=db.push, url=url):
                erreicht += 1
        except Exception:
            logger.exception("Termin-Erinnerung an %s fehlgeschlagen.", user.username)
    return erreicht


def einstellungen(db) -> TerminErinnerungEinstellungen:
    """Vorlauf aus der DB; fällt auf die Vorgaben zurück, wenn es sie (noch) nicht gibt."""
    repo = getattr(db, 'termin_erinnerung_einstellungen', None)
    if repo is None:
        return STANDARD_EINSTELLUNGEN
    return repo.get()


def anstehende_termine(db, einst: TerminErinnerungEinstellungen,
                       heute: Optional[date] = None) -> list:
    """Die Termine, die im längsten eingestellten Vorlauf liegen (ab morgen).

    Das Fenster ist bewusst der VOLLE Vorlauf und nicht nur der eine Stichtag:
    Fällt ein Lauf aus, liegen die Termine von gestern noch drin und ihre Stufe
    kommt nach (s. stufe_fuer).
    """
    heute = heute or date.today()
    st = stufen(einst)
    if not st:
        return []
    return db.termine.list_geplante_im_fenster(
        (heute + timedelta(days=1)).isoformat(),
        (heute + timedelta(days=max(st))).isoformat())


def erinnern(db, *, heute: Optional[date] = None) -> dict:
    """Fällige Erinnerungen verschicken.

    Gibt zurück, wie viele Termine überhaupt anstanden (`anstehend`), zu wie vielen
    erinnert wurde und wie viele Empfänger dabei erreicht wurden.
    """
    heute = heute or date.today()
    einst = einstellungen(db)
    if not einst.aktiv:
        return {"anstehend": 0, "erinnert": 0, "empfaenger": 0}

    # Serien-Instanzen entstehen erst, wenn jemand sie anfordert (rollierender
    # Horizont, s. TerminSerieRepository). Ohne das hier hinge der Lauf daran, dass
    # vorher jemand die App geöffnet hat; der Aufruf ist idempotent und
    # parallel-sicher, kostet also nichts. Der Trockenlauf lässt ihn bewusst weg –
    # er soll nichts schreiben.
    db.termin_serien.materialize_due()
    termine = anstehende_termine(db, einst, heute)
    bereits = db.access_log_repository.letzte_je_detail(EVENT_ERINNERUNG)
    erinnert = empfaenger_gesamt = 0
    for termin, stufe, vorlauf in faellige(termine, bereits, einst, heute):
        offene = db.termin_zusagen.list_offene_user_ids(termin.id)
        if not offene:
            # Alle haben gemeldet – dann gibt es nichts zu erinnern, und die Stufe
            # bleibt bewusst unvermerkt: Nimmt jemand seine Antwort morgen zurück,
            # darf ihn die Erinnerung noch erreichen.
            continue
        titel, text = build_erinnerung(termin, vorlauf)
        erreicht = _versenden(db, offene, titel, text,
                              terminmeldung.termin_url(termin.id))
        db.access_log_repository.log(EVENT_ERINNERUNG, category=_KATEGORIE,
                                     detail=schluessel(termin.id, stufe))
        erinnert += 1
        empfaenger_gesamt += erreicht

    if erinnert:
        logger.info("Termin-Erinnerungen: %d Termin(e) mit offenen Meldungen, "
                    "%d Empfänger erreicht.", erinnert, empfaenger_gesamt)
    return {"anstehend": len(termine), "erinnert": erinnert,
            "empfaenger": empfaenger_gesamt}
