"""ICS-Feed für „Meine Termine" (#153, RFC 5545) — ohne Fremdbibliothek.

Reine Textbau-Funktionen: rein gehen Termin-Dicts (wie sie
`TerminRepository.list_for_user` liefert), raus geht ein fertiger Kalender.
Kein DB-Zugriff, keine Rechteprüfung — die passiert eine Schicht höher, damit
für den Feed exakt dieselbe Sichtbarkeit gilt wie in der App.

Drei Dinge, an denen ein selbstgebautes ICS üblicherweise scheitert:

* **Zeitzone.** Die Termine liegen als lokale Wandzeit ohne Offset in der DB
  ('2026-08-30T13:00'). Ein `DTSTART` ohne Zeitzonenbezug deuten Clients als UTC
  — das Spiel stünde im Sommer zwei Stunden zu früh im Kalender. Deshalb
  `TZID=Europe/Berlin` UND die VTIMEZONE-Komponente mit den Umstellungsregeln:
  Ein Client, der die Zone nicht selbst kennt, rechnet sonst falsch.
* **Zeilenlänge.** RFC 5545 erlaubt 75 Oktett je Zeile; längere werden
  „gefaltet". Gezählt wird in Oktett, nicht in Zeichen — ein Umlaut zählt zwei.
* **Stabile UID.** Sie darf sich zwischen zwei Abrufen nie ändern, sonst legt
  jeder Abruf alle Termine erneut an, statt sie zu aktualisieren.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from app.services.termin_notification_service import termin_titel

ZEITZONE = "Europe/Berlin"

# Termine ohne Ende bekommen eine Standarddauer: Ein VEVENT ohne DTEND hat sonst
# Null-Dauer und erscheint in manchen Kalendern als Punkt ohne Ausdehnung.
STANDARD_DAUER_MIN = 120

# Umstellungsregeln für Europe/Berlin. Fest verdrahtet statt aus einer Bibliothek:
# Die EU-Regel (letzter Sonntag im März bzw. Oktober) steht seit 1996 unverändert,
# und ein Kalender-Client braucht genau diese zwei Blöcke.
_VTIMEZONE = f"""BEGIN:VTIMEZONE
TZID:{ZEITZONE}
X-LIC-LOCATION:{ZEITZONE}
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE""".split("\n")

_TYP_LABEL = {'training': 'Training', 'spiel': 'Spiel', 'sonstiges': 'Termin'}

# Eigene Zu-/Absage – Wortwahl wie in der App (ANTWORTEN in useTermine.js).
_ANTWORT_LABEL = {'zu': 'Zusage', 'vielleicht': 'Vielleicht', 'ab': 'Absage'}


def escape(wert: Optional[str]) -> str:
    """Sonderzeichen nach RFC 5545 §3.3.11 maskieren.

    Backslash zuerst, sonst maskiert man die eigenen Maskierungen nach. Der
    Doppelpunkt gehört bewusst NICHT dazu — er ist in Werten erlaubt, und ein
    maskierter Doppelpunkt landet als „\\:" sichtbar im Kalender.
    """
    if not wert:
        return ""
    return (str(wert).replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
            .replace("\r", "\\n"))


def falten(zeile: str) -> list[str]:
    """Zeile auf 75 Oktett umbrechen; Folgezeilen beginnen mit einem Leerzeichen.

    Gerechnet wird auf den UTF-8-Bytes, denn RFC 5545 zählt Oktett. Geschnitten
    wird nie mitten in ein Mehrbyte-Zeichen — sonst kommt beim Client ein
    kaputtes Zeichen an (bei uns z. B. jedes „ü" in einem Straßennamen).
    """
    roh = zeile.encode("utf-8")
    if len(roh) <= 75:
        return [zeile]
    teile: list[bytes] = []
    rest = roh
    grenze = 75
    while len(rest) > grenze:
        schnitt = grenze
        while schnitt > 0 and (rest[schnitt] & 0xC0) == 0x80:
            schnitt -= 1
        teile.append(rest[:schnitt])
        rest = rest[schnitt:]
        grenze = 74          # das führende Leerzeichen der Folgezeile zählt mit
    teile.append(rest)
    return [teile[0].decode("utf-8")] + [" " + t.decode("utf-8") for t in teile[1:]]


def wandzeit(text: Optional[str]) -> Optional[str]:
    """'2026-08-30T13:00' → '20260830T130000' (Form für DTSTART mit TZID)."""
    if not text:
        return None
    datum, _, zeit = str(text).strip().partition("T")
    zeit = (zeit or "00:00")[:5]
    return f"{datum.replace('-', '')}T{zeit.replace(':', '')}00"


def _ende_wandzeit(beginn: str, ende: Optional[str]) -> Optional[str]:
    """Ende bestimmen: das gepflegte, sonst Beginn + Standarddauer.

    Ein Ende, das nicht nach dem Beginn liegt (Tippfehler in der Erfassung),
    ergäbe im Kalender einen Termin mit Null- oder Negativdauer — dann lieber
    ebenfalls die Standarddauer.
    """
    try:
        start = datetime.fromisoformat(beginn[:16])
    except (ValueError, TypeError):
        return None
    if ende:
        try:
            if datetime.fromisoformat(str(ende)[:16]) > start:
                return wandzeit(ende)
        except (ValueError, TypeError):
            pass
    return wandzeit((start + timedelta(minutes=STANDARD_DAUER_MIN)).isoformat(timespec="minutes"))


def _ort(t: dict) -> str:
    """Name der Spielstätte plus Anschrift — die Anschrift ist das, womit ein
    Navi etwas anfangen kann; Platzbezeichnungen findet kein Geocoder."""
    teile = [t.get('spielstaette_name'), t.get('spielstaette_strasse')]
    plz_ort = " ".join(x for x in (t.get('spielstaette_plz'), t.get('spielstaette_ort')) if x)
    teile.append(plz_ort or None)
    if not any(teile):
        return t.get('ort') or ""
    return ", ".join(x for x in teile if x)


def termin_link(t: dict, basis_url: str) -> str:
    """Link auf genau diesen Termin in der App (leer ohne basis_url).

    Dieselbe Form wie der Deep-Link aus den Benachrichtigungen (#158,
    termin_notification_service.termin_url): Die Termine-Seite springt zur Card
    und hebt sie hervor — dort sitzen die Zusage-Knöpfe. Eine Adresse ohne ID
    landete nur in der Liste, in der man den gemeinten Termin erst suchen muss.
    """
    if not basis_url or not t.get('id'):
        return ""
    return f"{basis_url.rstrip('/')}/termine?termin={t['id']}"


def _beschreibung(t: dict, basis_url: str) -> str:
    """Alles, was am Termin hängt und im Kalender sonst verloren ginge."""
    zeilen = []
    # Die Absage zuerst – wer die Details aufklappt, soll nicht erst
    # Treffpunkt und Untergrund lesen, bevor er erfährt, dass nichts stattfindet.
    if t.get('status') == 'abgesagt':
        zeilen.append("Dieser Termin wurde abgesagt.")
    elif t.get('meine_antwort') in _ANTWORT_LABEL:
        # Hier die Wörter aus der App (Zusage/Vielleicht/Absage), nicht die
        # Titelmarke: Wer nachsieht, soll denselben Begriff lesen wie im Termin.
        zeilen.append(f"Deine Antwort: {_ANTWORT_LABEL[t['meine_antwort']]}")
    if t.get('mannschaft_name'):
        zeilen.append(f"Mannschaft: {t['mannschaft_name']}")
    treff = " ".join(x for x in (t.get('treffpunkt_zeit'), t.get('treffpunkt')) if x)
    if treff:
        zeilen.append(f"Treffpunkt: {treff}")
    if t.get('spielstaette_untergrund'):
        zeilen.append(f"Untergrund: {t['spielstaette_untergrund']}")
    if t.get('beschreibung'):
        zeilen.append(str(t['beschreibung']))
    link = termin_link(t, basis_url)
    if link:
        # Zusätzlich zum URL-Feld: Google zeigt bei abonnierten Kalendern nur die
        # Beschreibung an und macht Adressen darin selbst klickbar.
        zeilen.append(f"In der App öffnen: {link}")
    return "\n".join(zeilen)


def _vevent(t: dict, host: str, basis_url: str, dtstamp: str) -> list[str]:
    beginn = wandzeit(t.get('beginn'))
    if not beginn:
        return []
    zeilen = [
        "BEGIN:VEVENT",
        # Stabil über die Termin-ID: Derselbe Termin muss bei jedem Abruf dieselbe
        # UID tragen, sonst legt der Client bei jedem Poll Dubletten an.
        f"UID:termin-{t.get('id')}@{host}",
        f"DTSTAMP:{dtstamp}",
        # SEQUENCE aus version: Daran erkennt der Client eine Änderung – und nur
        # deshalb ersetzt er einen schon importierten Termin, statt ihn zu behalten.
        f"SEQUENCE:{int(t.get('version') or 0)}",
        f"DTSTART;TZID={ZEITZONE}:{beginn}",
    ]
    ende = _ende_wandzeit(str(t.get('beginn')), t.get('ende'))
    if ende:
        zeilen.append(f"DTEND;TZID={ZEITZONE}:{ende}")
    zeilen.append(f"SUMMARY:{escape(_summary(t))}")
    ort = _ort(t)
    if ort:
        zeilen.append(f"LOCATION:{escape(ort)}")
    beschreibung = _beschreibung(t, basis_url)
    if beschreibung:
        zeilen.append(f"DESCRIPTION:{escape(beschreibung)}")
    link = termin_link(t, basis_url)
    if link:
        # Das dafür vorgesehene Feld (RFC 5545 §3.8.4.6). Apple und Thunderbird
        # zeigen es als eigenen Knopf; Google ignoriert es bei Abos, deshalb
        # steht der Link zusätzlich in der Beschreibung.
        zeilen.append(f"URL:{escape(link)}")
    # Abgesagte Termine bleiben im Kalender stehen, statt kommentarlos zu
    # verschwinden: Wer schon hinfährt, soll die Absage sehen. STATUS wertet
    # nicht jeder Client aus (Google bei Abos gar nicht) – deshalb tragen der
    # Titel und die Beschreibung die Absage ebenfalls.
    abgesagt = t.get('status') == 'abgesagt'
    zeilen.append("STATUS:CANCELLED" if abgesagt else "STATUS:CONFIRMED")
    # Die Zeit blockieren nur Termine, bei denen man wirklich gebunden ist. Ein
    # abgesagter Termin und einer, für den man selbst abgesagt hat, sollen einen
    # nicht als beschäftigt zeigen, wenn jemand nach der Stunde fragt.
    # „Vielleicht" bleibt bewusst belegt – man könnte ja hingehen.
    frei = abgesagt or t.get('meine_antwort') == 'ab'
    zeilen.append("TRANSP:TRANSPARENT" if frei else "TRANSP:OPAQUE")
    zeilen.append("END:VEVENT")
    return zeilen


def _summary(t: dict) -> str:
    """Titel wie in der App (termin_titel), bei Training/Sonstiges um die
    Mannschaft ergänzt: Im eigenen Kalender stehen die Termine ohne Kontext
    nebeneinander, und „Training" allein sagt bei zwei Teams nichts.

    Eine Absage steht VORNE im Titel, nicht nur in STATUS:CANCELLED. Google
    stellt abonnierte Kalender nicht durch — es streicht nur echte Einladungen
    durch. Ein abgesagter Termin sah dort deshalb aus wie jeder andere, und der
    Titel ist das Einzige, was jeder Client zuverlässig anzeigt.
    """
    titel = termin_titel(SimpleNamespace(**t))
    if t.get('typ') != 'spiel' and t.get('mannschaft_name'):
        titel = f"{titel} {t['mannschaft_name']}"
    # Der abgesagte Termin schlägt die eigene Antwort: Findet er gar nicht statt,
    # ist es unerheblich, ob man zugesagt hatte.
    if t.get('status') == 'abgesagt':
        return f"Abgesagt: {titel}"
    # „Nicht dabei" statt „Absage": Im Kalender stünde „Absage" direkt neben
    # „Abgesagt" und beides ließe sich im Vorbeigehen verwechseln – dabei meint
    # das eine den Termin und das andere nur mich.
    marke = {'ab': 'Nicht dabei', 'vielleicht': 'Vielleicht'}.get(t.get('meine_antwort'))
    return f"{marke}: {titel}" if marke else titel


def baue_kalender(termine: list[dict], *, host: str, basis_url: str = "",
                  kalender_name: str = "Meine Termine",
                  jetzt: Optional[datetime] = None) -> str:
    """Kompletter ICS-Text (CRLF-terminiert, gefaltet) für die übergebenen Termine.

    `host` geht in die UIDs ein und muss über die Zeit stabil bleiben — er kommt
    deshalb aus der konfigurierten BASE_URL, nicht aus dem Request.
    """
    jetzt = jetzt or datetime.now(timezone.utc)
    dtstamp = jetzt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{host}//Vereinsverwaltung//DE",
        "CALSCALE:GREGORIAN",
        # Kein METHOD: Das kennzeichnet eine Einladung (iTIP). Ein abonnierter
        # Kalender ist keine – manche Clients fragen sonst nach einer Antwort.
        f"X-WR-CALNAME:{escape(kalender_name)}",
        f"X-WR-TIMEZONE:{ZEITZONE}",
        *_VTIMEZONE,
    ]
    for t in termine:
        zeilen.extend(_vevent(t, host, basis_url, dtstamp))
    zeilen.append("END:VCALENDAR")

    gefaltet = []
    for zeile in zeilen:
        gefaltet.extend(falten(zeile))
    return "\r\n".join(gefaltet) + "\r\n"
