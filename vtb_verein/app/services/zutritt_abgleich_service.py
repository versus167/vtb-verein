"""Soll-Ist-Abgleich der IC-Karten: Was bei uns steht, gegen das, was am Schloss liegt.

Der Sync holt viermal am Tag das Ist herein — Inventar, Karten, Credential-Mirror,
Logs —, aber verglichen hat es bisher niemand. Er zieht nur nach, was die Cloud über
die Karten sagt, die *da* sind; wonach nicht gefragt wird, fällt durch:

  * eine Berechtigung, deren Karte am Schloss gar nicht mehr liegt (die Zeile wird nie
    angefasst und behauptet weiter, sie öffne),
  * eine Karte am Schloss, zu der es bei uns keine Berechtigung gibt (per BLE in der
    TTLock-App angelernt, oder ein Entziehen ist nicht durchgelaufen),
  * ein Gültigkeitsfenster, das vom hinterlegten abweicht,
  * und der Fall, auf den es wirklich ankommt: ein gesperrter oder verlorener Chip,
    dessen Karte am Schloss noch ein gültiges Fenster trägt — er öffnet weiter,
    während er in jeder Liste als gesperrt steht.

Der Vergleich ist reine DB-Arbeit: Das Soll steht in `tuer_berechtigung` (inklusive
Chip-Status), das Ist im Credential-Mirror `tuer_credential` (typ='ic'), den der Sync
je Schloss autoritativ ersetzt. Kein zusätzlicher Cloud-Aufruf, dadurch beliebig oft
abrufbar — die Befunde sind abgeleitet und werden deshalb auch nirgends gespeichert.
Gemerkt wird nur, worüber schon benachrichtigt wurde (siehe `melde_sperrluecken`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.permission import Permission
from app.models.schliessanlage import CHIP_AKTIV, CRED_IC
# Dieselbe Umrechnung und dieselbe Definition von „wirkungslos" wie auf dem Schreibweg –
# ein zweiter Begriff davon wäre genau die Abweichung, die hier gefunden werden soll.
from app.services.zutritt_service import _iso_to_ms, karte_wirkungslos

logger = logging.getLogger(__name__)

# Ein Fenster gilt als übereinstimmend, wenn es auf die Minute genau passt: Der
# Schreibweg rechnet ISO → ms, die Cloud gibt ms → ISO zurück, da wandert schon mal
# eine Sekunde. Ab einer Minute ist die Abweichung eine echte, keine Rundung.
TOLERANZ_MS = 60_000

BEFUND_KARTE_FEHLT = 'karte_fehlt'
BEFUND_KARTE_FREMD = 'karte_fremd'
BEFUND_FENSTER = 'fenster_abweichend'
BEFUND_SPERRE_OFFEN = 'sperre_offen'
BEFUND_SPERRE_HAENGT = 'sperre_haengt'

# Nur einer davon ist ein Sicherheitsproblem: ein gesperrter Chip, der weiter öffnet.
# Die übrigen sind Buchhaltung — ärgerlich, aber niemand kommt dadurch herein.
KRITISCH = (BEFUND_SPERRE_OFFEN,)

_EVENT_MELDUNG = 'schliessanlage_abgleich_alarm'


def _jetzt_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _chip_name(b) -> str:
    """Wie der Chip im Befund heißt: Inhaber, sonst Bezeichnung, sonst Kartennummer."""
    if b.mitglied_vorname or b.mitglied_nachname:
        return f"{b.mitglied_vorname or ''} {b.mitglied_nachname or ''}".strip()
    return b.chip_bezeichnung or f"Chip {b.kartennummer or b.chip_id}"


def _fenster(von: Optional[str], bis: Optional[str]) -> tuple[int, int]:
    """Gültigkeitsfenster in ms. 0 heißt bei TTLock *unbefristet*, nicht „nie"."""
    return _iso_to_ms(von), _iso_to_ms(bis)


def _passt(soll: tuple[int, int], ist: tuple[int, int]) -> bool:
    return all(abs(s - i) <= TOLERANZ_MS for s, i in zip(soll, ist))


def _lesbar(von: Optional[str], bis: Optional[str]) -> str:
    """Fenster für den Befundtext; nichts hinterlegt heißt unbefristet."""
    if not von and not bis:
        return 'unbefristet'
    return f"{(von or 'sofort')[:16]} – {(bis or 'unbefristet')[:16]}"


def _befund(art: str, *, schloss_id: int, schloss: str, text: str,
            chip_id: Optional[int] = None, chip: Optional[str] = None,
            kartennummer: Optional[str] = None, veraltet: bool = False) -> dict:
    # Ein Befund aus einem veralteten Spiegel ist keine Aussage über heute – er wird
    # angezeigt (mit Hinweis), löst aber keine Meldung aus. Sonst weckt ein Schloss,
    # das beim letzten Sync nicht erreichbar war, nachts jemanden wegen eines
    # Zustands, den es seit Tagen nicht mehr gibt.
    return {
        'art': art, 'schloss_id': schloss_id, 'schloss': schloss,
        'chip_id': chip_id, 'chip': chip, 'kartennummer': kartennummer,
        'text': text, 'veraltet': veraltet,
        'kritisch': art in KRITISCH and not veraltet,
    }


def befunde(berechtigungen: list, karten: list, *, jetzt_ms: Optional[int] = None) -> list[dict]:
    """Soll (Berechtigungen) gegen Ist (gespiegelte IC-Karten) – reine Funktion.

    Zugeordnet wird über die `cardId`; wo wir keine haben (nie angelernt), hilft die
    Kartennummer weiter — dieselbe Karte kann am Schloss längst liegen, per BLE an
    unserer App vorbei angelernt.
    """
    jetzt_ms = jetzt_ms if jetzt_ms is not None else _jetzt_ms()
    # Der Mirror wird je Schloss UND Typ ersetzt – und nur nach erfolgreichem Abruf.
    # Ein Schloss, dessen Kartenliste beim letzten Lauf nicht kam, behält also seinen
    # alten Stand. `gesehen_am` verrät das: Es liegt dann hinter dem jüngsten Stand.
    stand_je_schloss: dict[int, object] = {}
    for k in karten:
        if k.gesehen_am and (k.schloss_id not in stand_je_schloss
                             or k.gesehen_am > stand_je_schloss[k.schloss_id]):
            stand_je_schloss[k.schloss_id] = k.gesehen_am
    neuster = max(stand_je_schloss.values(), default=None)

    def _veraltet(schloss_id: int) -> bool:
        stand = stand_je_schloss.get(schloss_id)
        # Gar kein Spiegel: entweder nie synchronisiert oder das Schloss hat wirklich
        # keine Karte – das ist von hier aus nicht zu unterscheiden.
        return stand is None or (neuster is not None and stand < neuster)

    nach_id = {(k.schloss_id, k.ttlock_credential_id): k for k in karten}
    nach_nummer = {(k.schloss_id, (k.detail or '').strip()): k
                   for k in karten if (k.detail or '').strip()}
    zugeordnet: set[int] = set()
    out: list[dict] = []

    for b in berechtigungen:
        schloss = b.schloss_name or f'Schloss #{b.schloss_id}'
        chip = _chip_name(b)
        karte = (nach_id.get((b.schloss_id, b.ttlock_card_id)) if b.ttlock_card_id
                 else nach_nummer.get((b.schloss_id, (b.kartennummer or '').strip())))
        if karte is None:
            # Ohne cardId wissen wir selbst, dass die Karte nie ankam – das steht schon
            # an der Zeile („nicht am Schloss") und braucht keinen zweiten Kanal.
            if b.ttlock_card_id:
                out.append(_befund(
                    BEFUND_KARTE_FEHLT, schloss_id=b.schloss_id, schloss=schloss,
                    chip_id=b.chip_id, chip=chip, kartennummer=b.kartennummer,
                    veraltet=_veraltet(b.schloss_id),
                    text=f'„{chip}" ist an „{schloss}" zugeteilt, die Karte liegt dort '
                         f'aber nicht (mehr) – die Tür öffnet er nicht.'))
            continue
        zugeordnet.add(id(karte))
        ist = _fenster(karte.gueltig_von, karte.gueltig_bis)
        ist_gesperrt = karte_wirkungslos({'startDate': ist[0], 'endDate': ist[1]}, jetzt_ms)
        soll_gesperrt = (b.chip_status or CHIP_AKTIV) != CHIP_AKTIV
        if soll_gesperrt and not ist_gesperrt:
            out.append(_befund(
                BEFUND_SPERRE_OFFEN, schloss_id=b.schloss_id, schloss=schloss,
                chip_id=b.chip_id, chip=chip, kartennummer=b.kartennummer,
                veraltet=_veraltet(b.schloss_id),
                text=f'„{chip}" ist als „{b.chip_status}" markiert, öffnet „{schloss}" '
                     f'aber weiter – die Karte ist dort '
                     f'{_lesbar(karte.gueltig_von, karte.gueltig_bis)} gültig.'))
        elif soll_gesperrt:
            continue                     # gesperrt und wirkungslos: genau so soll es sein
        elif ist_gesperrt:
            out.append(_befund(
                BEFUND_SPERRE_HAENGT, schloss_id=b.schloss_id, schloss=schloss,
                chip_id=b.chip_id, chip=chip, kartennummer=b.kartennummer,
                veraltet=_veraltet(b.schloss_id),
                text=f'„{chip}" ist aktiv, seine Karte an „{schloss}" trägt aber ein '
                     f'abgelaufenes Fenster – die Tür bleibt stumm.'))
        elif not _passt(_fenster(b.gueltig_von, b.gueltig_bis), ist):
            out.append(_befund(
                BEFUND_FENSTER, schloss_id=b.schloss_id, schloss=schloss,
                chip_id=b.chip_id, chip=chip, kartennummer=b.kartennummer,
                veraltet=_veraltet(b.schloss_id),
                text=f'Die Gültigkeit von „{chip}" an „{schloss}" weicht ab: '
                     f'{_lesbar(b.gueltig_von, b.gueltig_bis)} bei uns, '
                     f'{_lesbar(karte.gueltig_von, karte.gueltig_bis)} am Schloss.'))

    for k in karten:
        if id(k) in zugeordnet:
            continue
        schloss = k.schloss_name or f'Schloss #{k.schloss_id}'
        name = k.name or (f'Nr. {k.detail}' if k.detail else f'cardId {k.ttlock_credential_id}')
        out.append(_befund(
            BEFUND_KARTE_FREMD, schloss_id=k.schloss_id, schloss=schloss,
            kartennummer=k.detail, veraltet=_veraltet(k.schloss_id),
            text=f'An „{schloss}" liegt die Karte „{name}", zu der es bei uns keine '
                 f'Berechtigung gibt.'))
    return out


def abgleich(db, *, schloss_ids: Optional[set[int]] = None) -> dict:
    """Befunde aus dem gespiegelten Ist. `schloss_ids` = Abteilungs-Scope (None = alle).

    `stand` sagt, wie alt das Ist ist – ohne diese Angabe wäre „keine Befunde" nicht von
    „seit drei Tagen kein Sync" zu unterscheiden.

    Jeder Befund trägt die Abteilung seines Schlosses; daran entscheidet sich, wer ihn
    zu sehen bekommt (`darf_sehen`) – vereinsweite Schlösser gehören niemandem und
    verlangen deshalb das vereinsweite Recht.
    """
    karten = db.tuer_credentials.list_fuer_abgleich(CRED_IC)
    berechtigungen = db.tuer_berechtigungen.list_fuer_abgleich()
    if schloss_ids is not None:
        karten = [k for k in karten if k.schloss_id in schloss_ids]
        berechtigungen = [b for b in berechtigungen if b.schloss_id in schloss_ids]
    abteilung = {s.id: s.abteilung_id for s in db.tuer_schloesser.list_all()}
    gefunden = befunde(berechtigungen, karten)
    for b in gefunden:
        b['abteilung_id'] = abteilung.get(b['schloss_id'])
    return {
        'stand': max((k.gesehen_am for k in karten if k.gesehen_am), default=None),
        'befunde': gefunden,
        'kritisch': sum(1 for b in gefunden if b['kritisch']),
    }


def darf_sehen(user, befund: dict) -> bool:
    """Darf dieser Benutzer diesen Befund sehen? Gleiche Regel wie `darf_schloss`.

    Der Befundtext nennt den Inhaber des Chips – das ist ein personenbezogenes Datum
    und geht niemanden an, der die Tür nicht verwaltet.
    """
    abteilung_id = befund.get('abteilung_id')
    if abteilung_id is None:
        return user.has_permission_global(Permission.SCHLIESSANLAGE_VERWALTEN)
    return user.has_permission_for_abteilung(Permission.SCHLIESSANLAGE_VERWALTEN,
                                             abteilung_id)


def signatur(kritische: list[dict]) -> str:
    """Kennung der offenen Sperr-Lücken – Grundlage der Wiederholungssperre."""
    return ";".join(sorted(f"{b['schloss_id']}:{b['kartennummer'] or b['chip_id']}"
                           for b in kritische))


def build_sperr_digest(kritische: list[dict]) -> Optional[tuple[str, str]]:
    """Aus offenen Sperr-Lücken eine Benachrichtigung bauen; None, wenn es keine gibt."""
    if not kritische:
        return None
    titel = f"⚠️ Schließanlage: {len(kritische)} gesperrte(r) Chip(s) öffnen weiter"
    text = ('Der Abgleich mit den Schlössern hat ergeben, dass gesperrte oder verlorene '
            'Chips dort noch gültige Karten haben:\n\n'
            + "\n".join(f"• {b['text']}" for b in kritische)
            + '\n\nBitte den Chip erneut sperren (Chip öffnen → Status setzen). Bleibt der '
              'Befund, kam der Auftrag nicht bis zum Schloss – dann Gateway und Batterie '
              'prüfen.')
    return titel, text


def empfaenger(db) -> list:
    """Wer wird benachrichtigt: aktive Konten mit `schliessanlage.verwalten`.

    Nicht nur Admins – die Schließanlage verwaltet, wer das Recht dafür hat, und genau
    der kann eine offene Sperre auch schließen. Abteilungsgebundene Rechte zählen mit;
    was der Einzelne davon zu sehen bekommt, entscheidet danach `darf_sehen`.
    """
    from app.services.user_service import UserService
    return [u for u in UserService(db).list_all()
            if u.active and u.has_permission(Permission.SCHLIESSANLAGE_VERWALTEN)]


def melde_sperrluecken(db) -> int:
    """Über NEUE Sperr-Lücken benachrichtigen; Zahl der erreichten Empfänger.

    Läuft am Ende des Syncs, wenn das Ist frisch ist. Gemeldet wird nur, was sich seit
    der letzten Meldung geändert hat – der Sync läuft alle sechs Stunden, und eine Lücke,
    die eine Woche offen steht, darf keine 28 Nachrichten erzeugen. Auch die Entwarnung
    (leere Signatur) wird protokolliert, sonst bliebe ein zweites Auftreten derselben
    Lücke später stumm. Das Gedächtnis ist das Zugriffsprotokoll: eine Zeile je Meldung
    und Empfänger, mit derselben Aufbewahrung wie die übrigen Schließanlagen-Ereignisse.

    Je Empfänger, nicht global: Ein abteilungsgebundener Verwalter sieht nur seine Türen,
    und eine Lücke in einer anderen Abteilung darf ihn weder erreichen noch seine
    Wiederholungssperre verbrauchen.
    """
    kritische = [b for b in abgleich(db)['befunde'] if b['kritisch']]
    erreicht = 0
    for u in empfaenger(db):
        seine = [b for b in kritische if darf_sehen(u, b)]
        sig = signatur(seine)
        letzte = db.access_log_repository.list(event_type=_EVENT_MELDUNG,
                                               user_id=u.id, limit=1)
        if letzte and (letzte[0].get('detail') or '') == sig:
            continue
        if not sig and not letzte:
            continue                 # noch nie etwas gemeldet und nichts zu melden
        digest = build_sperr_digest(seine)
        if digest is not None:
            from app.services.notification_service import NotificationService
            titel, text = digest
            try:
                if NotificationService.send_notification(u, titel, text,
                                                         push_service=db.push):
                    erreicht += 1
            except Exception:
                logger.exception("Sperr-Lücken-Meldung an %s fehlgeschlagen.", u.username)
        db.access_log_repository.log(_EVENT_MELDUNG, category='schliessanlage',
                                     user_id=u.id, username=u.username, detail=sig)
    if kritische:
        logger.info("Sperr-Lücken-Meldung: %d Befund(e), %d Empfänger erreicht.",
                    len(kritische), erreicht)
    return erreicht
