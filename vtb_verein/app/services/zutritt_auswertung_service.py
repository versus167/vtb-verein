"""Auswertung des Zutrittslogs (#161) – aus rohen Aggregaten wird ein fertiger Bericht.

Die SQL-Arbeit macht ``TuerZutrittLogRepository.auswertung``; hier entstehen daraus die
Dinge, die niemand in SQL lesen möchte: aufgefüllte Achsen (jede Stunde, jeder Wochentag,
jeder Tag im Verlauf – auch die ohne einen einzigen Zutritt), Anteile, lesbare Labels und
die „Auszeichnungen" – kleine Bestenlisten wie Frühaufsteher, Nachteule oder Rekordtag.

Alle Zeitangaben sind bereits Ortszeit (Europe/Berlin, s. Repository) und kommen als
Strings – hier wird nur noch formatiert, nie gerechnet.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.models.schliessanlage import record_type_label

# „Heute" ist die Vereinsuhr, nicht die des Servers – dieselbe Zone, in die das
# Repository die Zeitstempel dreht.
ZEITZONE = ZoneInfo('Europe/Berlin')

# Auswählbare Zeiträume in Tagen; 0 = seit jeher.
ZEITRAEUME: tuple[int, ...] = (30, 90, 365, 0)

WOCHENTAGE = ('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So')
MONATE = ('Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
          'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez')

# Ab welcher Spannweite der Verlauf gröber wird – 30 Tagesbalken sind am Handy die
# Obergrenze, darüber wird pro Woche bzw. pro Monat gebündelt.
_GRENZE_TAG = 45
_GRENZE_WOCHE = 200


def _tag(text: Optional[str]) -> Optional[date]:
    return date.fromisoformat(text) if text else None


def _datum_de(text: Optional[str]) -> str:
    """'2026-07-14' → '14.07.2026'; nimmt auch '…THH:MM' entgegen."""
    d = _tag((text or '')[:10])
    return d.strftime('%d.%m.%Y') if d else ''


def _uhrzeit(text: Optional[str]) -> str:
    """'2026-07-14T05:12' → '05:12'."""
    return (text or '')[11:16]


def _anteil(anzahl: int, gesamt: int) -> float:
    return round(anzahl / gesamt, 4) if gesamt else 0.0


def _laengste_serie(tage: list[dict]) -> dict:
    """Längste Kette aufeinanderfolgender Tage mit mindestens einer Öffnung."""
    beste, laufend, start, bestes_ende = 0, 0, None, None
    vorheriger: Optional[date] = None
    for eintrag in tage:
        d = _tag(eintrag['datum'])
        laufend = laufend + 1 if vorheriger and (d - vorheriger).days == 1 else 1
        if laufend == 1:
            start = d
        if laufend > beste:
            beste, bestes_ende = laufend, d
        vorheriger = d
    if not beste:
        return {'tage': 0, 'von': None, 'bis': None}
    return {'tage': beste,
            'von': (bestes_ende - timedelta(days=beste - 1)).isoformat(),
            'bis': bestes_ende.isoformat()}


def _verlauf(tage: list[dict], start: date, ende: date) -> dict:
    """Zeitreihe über den Zeitraum, je nach Spannweite pro Tag, Woche oder Monat.
    Lücken werden mit 0 aufgefüllt – sonst suggerieren die Balken durchgehend Betrieb."""
    if ende < start:
        return {'granularitaet': 'tag', 'punkte': []}
    spanne = (ende - start).days + 1
    gran = 'tag' if spanne <= _GRENZE_TAG else 'woche' if spanne <= _GRENZE_WOCHE else 'monat'
    werte = {e['datum']: e['anzahl'] for e in tage}

    def schluessel(d: date) -> date:
        if gran == 'tag':
            return d
        if gran == 'woche':
            return d - timedelta(days=d.weekday())
        return d.replace(day=1)

    def label(d: date) -> str:
        if gran == 'tag':
            return d.strftime('%d.%m.')
        if gran == 'woche':
            return f'KW{d.isocalendar().week}'
        return f'{MONATE[d.month - 1]} {d:%y}'

    punkte: dict[date, int] = {}
    lauf = start
    while lauf <= ende:                       # zuerst alle Körbe anlegen (auch leere)
        punkte.setdefault(schluessel(lauf), 0)
        lauf += timedelta(days=1)
    for datum_text, anzahl in werte.items():
        d = _tag(datum_text)
        if start <= d <= ende:
            punkte[schluessel(d)] = punkte.get(schluessel(d), 0) + anzahl
    return {
        'granularitaet': gran,
        'punkte': [{'label': label(k), 'datum': k.isoformat(), 'anzahl': v}
                   for k, v in sorted(punkte.items())],
    }


def _auszeichnungen(roh: dict, schloesser: list[dict], personen: list[dict],
                    rekordtag: Optional[dict], serie: dict) -> list[dict]:
    """Die spielerische Seite der Auswertung – nur, was tatsächlich Daten hat."""
    aus: list[dict] = []

    def dazu(schluessel, titel, icon, wert, *, wer=None, detail='', spruch=''):
        aus.append({'schluessel': schluessel, 'titel': titel, 'icon': icon,
                    'wer': wer, 'wert': wert, 'detail': detail, 'spruch': spruch})

    frueh = roh.get('frueheste')
    if frueh:
        dazu('frueheste', 'Frühaufsteher', 'wb_twilight', frueh['uhrzeit'] + ' Uhr',
             wer=frueh.get('wer'),
             detail=f"{_datum_de(frueh['zeitpunkt'])} · {frueh.get('schloss_name') or '?'}",
             spruch='Früheste Öffnung im Zeitraum – der Hahn war noch nicht wach.')

    spaet = roh.get('spaeteste')
    if spaet:
        dazu('spaeteste', 'Nachteule', 'bedtime', spaet['uhrzeit'] + ' Uhr',
             wer=spaet.get('wer'),
             detail=f"{_datum_de(spaet['zeitpunkt'])} · {spaet.get('schloss_name') or '?'}",
             spruch='Späteste Öffnung im Zeitraum – Licht aus nicht vergessen.')

    if personen:
        top = personen[0]
        dazu('stammgast', 'Stammgast', 'local_fire_department', f"{top['anzahl']}×",
             wer=top['wer'], detail='so oft aufgeschlossen wie sonst niemand',
             spruch='Kennt den Weg auch im Dunkeln.')

    if schloesser:
        tuer = schloesser[0]
        dazu('tuer', 'Meistgenutzte Tür', 'meeting_room', f"{tuer['anzahl']}×",
             wer=tuer['name'], detail='Spitzenreiter im Zeitraum',
             spruch='Diese Klinke hat den härtesten Job im Verein.')

    we = roh.get('wochenende')
    if we and we['anzahl']:
        dazu('wochenende', 'Wochenend-Held', 'weekend', f"{we['anzahl']}×",
             wer=we['wer'], detail='Öffnungen an Sa/So',
             spruch='Für andere ist frei – für den hier fängt es erst an.')

    nacht = roh.get('nachtaktiv')
    if nacht and nacht['anzahl']:
        dazu('nacht', 'Nachtschicht', 'nights_stay', f"{nacht['anzahl']}×",
             wer=nacht['wer'], detail='Öffnungen zwischen 0 und 5 Uhr',
             spruch='Die Geisterstunde hat einen Stammgast.')

    vielfalt = roh.get('vielfalt')
    if vielfalt and vielfalt['schloesser'] > 1:
        dazu('vielfalt', 'Schlüsselbund', 'vpn_key', f"{vielfalt['schloesser']} Türen",
             wer=vielfalt['wer'], detail='an so vielen verschiedenen Türen unterwegs',
             spruch='Kommt überall rein – zum Glück offiziell.')

    if rekordtag:
        dazu('rekordtag', 'Rekordtag', 'emoji_events', f"{rekordtag['anzahl']}×",
             detail=_datum_de(rekordtag['datum']),
             spruch='So viel Betrieb war an keinem anderen Tag.')

    if serie['tage'] > 1:
        dazu('serie', 'Längste Serie', 'bolt', f"{serie['tage']} Tage",
             detail=f"{_datum_de(serie['von'])} – {_datum_de(serie['bis'])}",
             spruch='An jedem einzelnen dieser Tage ging jemand rein.')

    return aus


def bericht(db, *, tage: int = 90, schloss_ids: Optional[set[int]] = None) -> dict:
    """Fertiger Auswertungs-Bericht für das Frontend.

    `tage` = Länge des Zeitraums (0 = seit jeher), `schloss_ids` = sichtbare Schlösser
    aus dem Abteilungs-Scope (None = keine Einschränkung).
    """
    heute = datetime.now(ZEITZONE).date()
    von_iso = None
    if tage:
        von_iso = (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat()

    roh = db.tuer_zutritt_logs.auswertung(
        schloss_ids=None if schloss_ids is None else sorted(schloss_ids), von=von_iso)

    k = roh['kennzahlen']
    oeffnungen = k['oeffnungen'] or 0
    erster, letzter = _tag(k['erster_tag']), _tag(k['letzter_tag'])
    spanne = (letzter - erster).days + 1 if erster and letzter else 0

    schloesser = [{**s, 'anteil': _anteil(s['anzahl'], oeffnungen)} for s in roh['schloesser']]
    personen = [{**p, 'anteil': _anteil(p['anzahl'], oeffnungen)} for p in roh['personen']]
    methoden = [{'label': record_type_label(m['record_type']) if m['record_type'] is not None
                 else (m['methode'] or 'unbekannt'),
                 'record_type': m['record_type'], 'anzahl': m['anzahl'],
                 'anteil': _anteil(m['anzahl'], oeffnungen)}
                for m in roh['methoden']]

    gezaehlt = {s['stunde']: s['anzahl'] for s in roh['stunden']}
    stunden = [{'stunde': h, 'label': f'{h:02d}', 'anzahl': gezaehlt.get(h, 0)} for h in range(24)]
    je_tag = {t['tag']: t['anzahl'] for t in roh['wochentage']}
    wochentage = [{'tag': i, 'label': WOCHENTAGE[i - 1], 'anzahl': je_tag.get(i, 0)}
                  for i in range(1, 8)]

    tage_liste = roh['tage']
    rekordtag = max(tage_liste, key=lambda t: (t['anzahl'], t['datum']), default=None)
    serie = _laengste_serie(tage_liste)
    start = max(heute - timedelta(days=(tage or 3650) - 1), erster) if erster else heute
    verlauf = _verlauf(tage_liste, start, max(heute, letzter or heute))

    return {
        'zeitraum': {
            'tage': tage,
            'von': start.isoformat() if erster else None,
            'bis': heute.isoformat(),
            'erster_tag': k['erster_tag'],
            'letzter_tag': k['letzter_tag'],
        },
        'kennzahlen': {
            'oeffnungen': oeffnungen,
            'ereignisse': k['ereignisse'],
            'aktive_tage': k['aktive_tage'],
            'akteure': k['akteure'],
            'schloesser': k['schloesser'],
            'fehlversuche': k['fehlversuche'],
            'alarme': k['alarme'],
            'pro_tag': round(oeffnungen / spanne, 1) if spanne else 0.0,
            'spitze_pro_tag': rekordtag['anzahl'] if rekordtag else 0,
        },
        'schloesser': schloesser,
        'personen': personen,
        'methoden': methoden,
        'stunden': stunden,
        'wochentage': wochentage,
        'verlauf': verlauf,
        'auszeichnungen': _auszeichnungen(roh, schloesser, personen, rekordtag, serie),
    }
