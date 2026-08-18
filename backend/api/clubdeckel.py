"""Teamkasse/Clubdeckel (#98) — mannschaftsinterne Getränke-Strichliste.

Zugriffsmodell (komplett teamintern, KEIN globaler Permission-Key, kein
Vorstands-Einblick): Stufen je Deckel sind mitglied < wart < verwalten.

- 'mitglied':  aktives Kader-Mitglied — sieht den Deckel, bucht den eigenen
               Konsum, sieht Salden und die eigenen Buchungen.
- 'wart':      mitglied + Zeile in clubdeckel_berechtigung — pflegt Gruppen/
               Artikel, sieht alle Buchungen, bucht Zahlungen und Einkäufe,
               storniert.
- 'verwalten': Kader-Rolle uebungsleiter/betreuer — alles inkl. einschalten,
               Stammdaten (Beitrag, Zahlungsempfänger, Zahlwege), Warte und
               Beitragsbefreiungen; impliziert Wart-Rechte.

Einzige Ausnahme ist der app-weite Admin-Durchgriff (role == 'admin') als
Notfall-Fallback. Konsum bucht standardmäßig für das EIGENE Kader-Mitglied; ein
Wart bucht mit `mitglied_id` auch für andere (Tresendienst, #167).

Jede Konsum-Buchung wird dem gerade laufenden Termin der Mannschaft zugeordnet
(#167). Darüber laufen die Matrix (Gitter Mitglied × Artikel, Vorbild
consumptions.php des Club-Tresors) und die Tages-/Termin-Auswertung.

Buchungsmodell: Saldo je Mitglied = SUM(betrag), Team-Saldo = −Σ Mitglieder.
Konsum negativ (bei Mitglieds-Verkäufer mit 'verkauf'-Gegenzeile als Nullsummen-
Paar), Einkauf (Team kauft vom Mitglied) positiv, Zahlung Mitglied→Mitglied als
Nullsummen-Paar, Monatsbeitrag automatisch beim Zugriff nachgebucht (Befreiungen
pro Mitglied; Storno eines Beitrags heißt „erlassen").
"""
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/clubdeckel", tags=["clubdeckel"])

_STUFEN_RANG = {'mitglied': 1, 'wart': 2, 'verwalten': 3}


# --------------------------------------------------------------------------- I/O
class DeckelCreate(BaseModel):
    name: Optional[str] = None               # Default: "Teamkasse <Mannschaft>"


class DeckelUpdate(BaseModel):
    name: str
    aktiv: bool = True
    beitrag: Optional[float] = None          # Monatspauschale; None = kein Beitrag
    zahlungsempfaenger_mitglied_id: Optional[int] = None
    zahlweg_iban: Optional[str] = None
    zahlweg_wero: Optional[str] = None
    zahlweg_paypal: Optional[str] = None
    expected_version: int


class AktivUpdate(BaseModel):
    aktiv: bool
    expected_version: int


class GruppeWrite(BaseModel):
    name: str
    verkaeufer_mitglied_id: Optional[int] = None   # None = das Team verkauft
    aktiv: bool = True
    sortierung: int = 0
    # Ab welchem Spieltag der Stand gilt (#167, v100). None = ab dem aktuellen
    # Termin (bzw. von Anfang an, wenn die Mannschaft noch keinen hat).
    ab_termin_id: Optional[int] = None
    # Schon gebuchte Striche dieses Spieltags auf den neuen Stand umstellen.
    bestand_uebernehmen: bool = False


class GruppeUpdate(GruppeWrite):
    expected_version: int


class ArtikelWrite(BaseModel):
    name: str
    preis: float
    gruppe_id: Optional[int] = None
    aktiv: bool = True
    sortierung: int = 0
    # Ab welchem Spieltag der Stand gilt (#167, v100). None = ab dem aktuellen.
    ab_termin_id: Optional[int] = None
    # Schon gebuchte Striche dieses Spieltags auf den neuen Stand umstellen.
    bestand_uebernehmen: bool = False


class ArtikelUpdate(ArtikelWrite):
    expected_version: int


class KonsumCreate(BaseModel):
    artikel_id: int
    menge: int = 1
    mitglied_id: Optional[int] = None    # Fremdbuchung durch den Wart (#167)
    termin_id: Optional[int] = None      # explizit statt automatisch
    ohne_termin: bool = False            # bewusst keinem Termin zuordnen


class ZahlungCreate(BaseModel):
    von_mitglied_id: int                     # Zahler (+betrag, Schuld sinkt)
    an_mitglied_id: int                      # Empfänger (−betrag, hält das Geld)
    betrag: float
    methode: Optional[str] = None            # 'bar' | 'unbar'
    notiz: Optional[str] = None
    datum: Optional[str] = None              # ISO 'YYYY-MM-DDTHH:MM' (sonst jetzt)


class EinkaufCreate(BaseModel):
    mitglied_id: int                         # Verkäufer ans Team (+betrag)
    betrag: float
    notiz: Optional[str] = None


class AnVerkaufCreate(BaseModel):
    mitglied_id: int                         # das buchende Mitglied
    verkauft: bool = False                   # False = kauft von, True = verkauft an
    gegen_mitglied_id: Optional[int] = None  # None = Team/Club, sonst Gegen-Mitglied
    betrag: float
    notiz: Optional[str] = None
    datum: Optional[str] = None              # ISO 'YYYY-MM-DDTHH:MM' (sonst jetzt)


_METHODE_LABEL = {'bar': 'bar', 'unbar': 'unbar'}


def _euro(wert: float) -> Decimal:
    return Decimal(str(wert)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_datum(datum: Optional[str]) -> Optional[str]:
    """Optionales Buchungsdatum validieren (ISO). Leerwert -> None (= jetzt)."""
    if not datum:
        return None
    try:
        datetime.fromisoformat(datum)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ungültiges Datum")
    return datum


# ----------------------------------------------------------------- Authorisierung
def _stufe(db: DB, user, deckel) -> Optional[str]:
    """Effektive Stufe des Users auf einen Deckel: 'verwalten' | 'wart' |
    'mitglied' | None. Admin-Bypass nur als Notfall-Fallback."""
    if user.role == 'admin':
        return 'verwalten'
    kader = db.clubdeckel.get_access_for_user(user.id, deckel.mannschaft_id)
    if kader == 'verwalten':
        return 'verwalten'
    if kader is None:
        return None
    if db.clubdeckel_berechtigungen.ist_wart_user(deckel.id, user.id):
        return 'wart'
    return 'mitglied'


def _deckel_mit_stufe(db: DB, user, deckel_id: int, mindest: str):
    deckel = db.clubdeckel.get(deckel_id)
    if deckel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teamkasse nicht gefunden")
    stufe = _stufe(db, user, deckel)
    if stufe is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Kein Zugriff auf die Teamkasse dieser Mannschaft")
    if _STUFEN_RANG[stufe] < _STUFEN_RANG[mindest]:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Keine Berechtigung für diese Aktion an der Teamkasse")
    return deckel, stufe


def _require_aktiv(deckel) -> None:
    if not deckel.aktiv:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Teamkasse ist deaktiviert — Buchen nicht möglich")


def _require_admin(user) -> None:
    """Löschen und Wiederherstellen einer Teamkasse sind app-weit admin-only (#125)."""
    if user.role != 'admin':
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Nur Administratoren dürfen eine Teamkasse löschen "
                            "oder wiederherstellen")


def _mitglied_am_deckel(db: DB, deckel, mitglied_id: int) -> bool:
    """Ziel-Prüfung für Zahlung/Einkauf: aktives Kader-Mitglied ODER Mitglied
    mit Buchungen auf dem Deckel (Restschuld eines Ausgetretenen bleibt regelbar)."""
    if db.clubdeckel.is_mitglied_in_kader(mitglied_id, deckel.mannschaft_id):
        return True
    return db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mitglied_id) != 0


_TYP_LABEL = {'training': 'Training', 'spiel': 'Spiel', 'sonstiges': 'Termin'}


def _termin_label(termin) -> str:
    """Kurzer Anzeigename („Spiel 16.08. 15:00 · SV X"). Beim Spiel steht der
    Gegner dabei — daran erkennt man den Abend wieder, nicht an der Uhrzeit."""
    kopf = _TYP_LABEL.get(termin.typ, 'Termin')
    try:
        wann = datetime.fromisoformat(termin.beginn).strftime('%d.%m. %H:%M')
    except ValueError:
        wann = termin.beginn
    teile = [f"{kopf} {wann}"]
    if termin.typ == 'spiel' and termin.gegner:
        teile.append(termin.gegner)
    return ' · '.join(teile)


def _termin_fuer_buchung(db: DB, deckel, termin_id: Optional[int],
                         ohne_termin: bool) -> Optional[int]:
    """Welchem Termin gehört diese Buchung (#167)?

    Rangfolge: explizite Wahl > ausdrückliches „ohne" > der gerade laufende
    Termin. Die Automatik ist der Normalfall — am Tresen tippt niemand erst einen
    Kalender durch —, das Nachbuchen für einen vergangenen Abend braucht die
    explizite Wahl, und „ohne_termin" bleibt für den Fall, dass sich jemand
    außerhalb des Betriebs bedient und das nicht dem Training angehängt haben will.
    """
    if termin_id is not None:
        termin = db.termine.get(termin_id)
        if termin is None or termin.mannschaft_id != deckel.mannschaft_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Termin gehört nicht zu dieser Mannschaft")
        return termin.id
    if ohne_termin:
        return None
    laufend = db.termine.get_laufenden(deckel.mannschaft_id)
    return laufend.id if laufend else None


def _beitragslauf(db: DB, deckel) -> None:
    """Lazy-Nachbuchung offener Monatsbeiträge beim Zugriff (nur aktiver Deckel
    mit konfiguriertem Beitrag)."""
    if deckel.aktiv and deckel.beitrag and deckel.beitrag_ab:
        db.clubdeckel_buchungen.buche_faellige_beitraege(
            deckel.id, deckel.mannschaft_id, deckel.beitrag, deckel.beitrag_ab)


# ---------------------------------------------------------------------- Teams
@router.get("/teams")
def list_meine_teams(user: CurrentUser, db: DB):
    """Meine Teamkassen-Teams (= Nav-Probe): Kader-Teams mit vorhandenem Deckel
    sowie — für Verwalter — Teams ohne Deckel (Einschalt-Angebot)."""
    teams = (db.clubdeckel.list_all_teams() if user.role == 'admin'
             else db.clubdeckel.list_teams_for_user(user.id))
    return [t for t in teams if t["deckel"] is not None or t["zugriff"] == 'verwalten']


@router.post("/teams/{mannschaft_id}", status_code=status.HTTP_201_CREATED)
def deckel_einschalten(mannschaft_id: int, data: DeckelCreate,
                       user: CurrentUser, db: DB):
    mannschaft = db.get_mannschaft(mannschaft_id)
    if mannschaft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mannschaft nicht gefunden")
    if user.role != 'admin' and \
            db.clubdeckel.get_access_for_user(user.id, mannschaft_id) != 'verwalten':
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Nur Übungsleiter/Betreuer der Mannschaft dürfen den "
                            "Teamkasse einschalten")
    if db.clubdeckel.get_by_mannschaft(mannschaft_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Diese Mannschaft hat bereits eine Teamkasse")
    name = (data.name or '').strip() or f"Teamkasse {mannschaft.name}"
    deckel = db.clubdeckel.create(mannschaft_id, name, user.username)
    return asdict(deckel)


# ------------------------------------------------------------------ Papierkorb
# WICHTIG: vor der "/{deckel_id}"-Route deklarieren, sonst versucht der
# int-Pfadparameter, "papierkorb" zu parsen (422). Admin-only (#125).
@router.get("/papierkorb")
def list_papierkorb(user: CurrentUser, db: DB):
    """Gelöschte Teamkassen (Admin-Papierkorb) — Grundlage fürs Wiederherstellen."""
    _require_admin(user)
    return db.clubdeckel.list_geloescht()


@router.post("/papierkorb/{deckel_id}/restore")
def restore_deckel(deckel_id: int, user: CurrentUser, db: DB):
    """Eine gelöschte Teamkasse komplett wiederherstellen (Deckel + Buchungen +
    Katalog + Warte + Befreiungen). 409, wenn die Mannschaft inzwischen wieder eine
    aktive Teamkasse hat."""
    _require_admin(user)
    ergebnis = db.clubdeckel.restore(deckel_id, user.username)
    if ergebnis == 'not_found':
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Keine gelöschte Teamkasse mit dieser ID")
    if ergebnis == 'conflict':
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Diese Mannschaft hat bereits wieder eine aktive "
                            "Teamkasse — Wiederherstellen nicht möglich")
    return {"status": "wiederhergestellt"}


# --------------------------------------------------------------------- Deckel
@router.get("/{deckel_id}")
def get_deckel(deckel_id: int, user: CurrentUser, db: DB):
    deckel, stufe = _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    _beitragslauf(db, deckel)
    mein_mitglied_id = db.clubdeckel.get_kader_mitglied_id(user.id, deckel.mannschaft_id)
    mein_saldo = (db.clubdeckel_buchungen.saldo_for_mitglied(deckel_id, mein_mitglied_id)
                  if mein_mitglied_id else Decimal("0.00"))
    stats = (db.clubdeckel_buchungen.konsum_24h(deckel_id, mein_mitglied_id)
             if mein_mitglied_id else {'summe': Decimal("0.00"), 'anzahl': {}})
    salden = db.clubdeckel_buchungen.salden(deckel_id)
    # Laufender Termin: der Tresen zeigt ihn an, damit sichtbar ist, worauf der
    # nächste Strich landet (#167) — und er bestimmt zugleich, welcher Stand des
    # Sortiments angeboten wird.
    laufend = db.termine.get_laufenden(deckel.mannschaft_id)
    _, artikel = _sortiment(db, deckel_id, laufend.id if laufend else None)
    for a in artikel:
        a['mein_24h_anzahl'] = stats['anzahl'].get(a['id'], 0)
    return {
        **asdict(deckel),
        "zugriff": stufe,
        "mein_mitglied_id": mein_mitglied_id,
        "mein_saldo": mein_saldo,
        "mein_24h_summe": stats['summe'],
        "team_saldo": -sum((s['saldo'] for s in salden), Decimal("0.00")),
        "artikel": artikel,
        "laufender_termin": ({"id": laufend.id, "label": _termin_label(laufend)}
                             if laufend else None),
    }


@router.put("/{deckel_id}")
def update_deckel(deckel_id: int, data: DeckelUpdate, user: CurrentUser, db: DB):
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'verwalten')
    name = data.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name fehlt")
    beitrag = None
    if data.beitrag is not None:
        beitrag = _euro(data.beitrag)
        if beitrag < 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Beitrag darf nicht negativ sein")
    ze = data.zahlungsempfaenger_mitglied_id
    if ze is not None and not _mitglied_am_deckel(db, deckel, ze):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Zahlungsempfänger gehört nicht zu dieser Teamkasse")
    # Vor einer Beitragsänderung offene Monate noch zum ALTEN Satz abschließen;
    # der (evtl. neue) Beitrag greift erst ab dem Folgemonat (siehe update()).
    _beitragslauf(db, deckel)
    if not db.clubdeckel.update(
            deckel_id, name, 1 if data.aktiv else 0, beitrag, ze,
            (data.zahlweg_iban or '').strip() or None,
            (data.zahlweg_wero or '').strip() or None,
            (data.zahlweg_paypal or '').strip() or None,
            user.username, data.expected_version):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Die Teamkasse wurde zwischenzeitlich geändert")
    return asdict(db.clubdeckel.get(deckel_id))


@router.put("/{deckel_id}/aktiv")
def set_deckel_aktiv(deckel_id: int, data: AktivUpdate, user: CurrentUser, db: DB):
    """Teamkasse (de)aktivieren durch den Verwalter — nur der Aktiv-Status, ohne die
    Stammdaten anzufassen. Deaktiviert = Buchen gesperrt, jederzeit reversibel."""
    _deckel_mit_stufe(db, user, deckel_id, 'verwalten')
    if not db.clubdeckel.set_aktiv(deckel_id, 1 if data.aktiv else 0,
                                   user.username, data.expected_version):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Die Teamkasse wurde zwischenzeitlich geändert")
    return asdict(db.clubdeckel.get(deckel_id))


@router.delete("/{deckel_id}")
def delete_deckel(deckel_id: int, user: CurrentUser, db: DB):
    """Kompletter Soft-Delete der Teamkasse (Deckel + Buchungen + Katalog + Warte +
    Befreiungen) als ein Batch — admin-only (#125), über den Papierkorb wiederherstellbar."""
    _require_admin(user)
    if db.clubdeckel.loesche_komplett(deckel_id, user.username) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teamkasse nicht gefunden")
    return {"status": "geloescht"}


# -------------------------------------------------------------------- Gruppen
@router.get("/{deckel_id}/gruppen")
def list_gruppen(deckel_id: int, user: CurrentUser, db: DB,
                 termin_id: Optional[int] = None):
    """Die gültigen Gruppen-Stände (#167, v100) — je Gruppe genau einer, nicht
    alle Generationen. Ohne `termin_id` der heute gültige Stand. `gilt_ab_label`
    macht im Katalog sichtbar, seit wann er greift."""
    _deckel_mit_stufe(db, user, deckel_id, 'wart')
    gruppen = db.clubdeckel_gruppen.list_stand(deckel_id, termin_id)
    # Welche Spieltage haben schon einen eigenen Stand? Der Katalog markiert sie
    # im Zeitraum-Umschalter, damit sichtbar ist, wo etwas hinterlegt ist.
    bekannt = db.clubdeckel_gruppen.stand_termine_je_stamm(deckel_id)
    ergebnis = []
    for g in gruppen:
        d = asdict(g)
        d['gilt_ab_label'] = (
            'von Anfang an' if g.gilt_ab_termin_id is None
            else _termin_label(db.termine.get(g.gilt_ab_termin_id)))
        d['stand_termine'] = [t for t in bekannt.get(g.stamm_id or g.id, [])
                              if t is not None]
        ergebnis.append(d)
    return ergebnis


def _validate_gruppe(db: DB, deckel, data: GruppeWrite) -> str:
    name = data.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name fehlt")
    v = data.verkaeufer_mitglied_id
    if v is not None and not _mitglied_am_deckel(db, deckel, v):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Verkäufer gehört nicht zu dieser Teamkasse")
    return name


@router.post("/{deckel_id}/gruppen", status_code=status.HTTP_201_CREATED)
def create_gruppe(deckel_id: int, data: GruppeWrite, user: CurrentUser, db: DB):
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    name = _validate_gruppe(db, deckel, data)
    gruppe = db.clubdeckel_gruppen.create(
        deckel_id, name, data.verkaeufer_mitglied_id, 1 if data.aktiv else 0,
        data.sortierung, user.username)
    return asdict(gruppe)


def _gruppe_im_deckel(db: DB, deckel_id: int, gruppe_id: int):
    gruppe = db.clubdeckel_gruppen.get(gruppe_id)
    if gruppe is None or gruppe.deckel_id != deckel_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Gruppe nicht in dieser Teamkasse gefunden")
    return gruppe


@router.put("/{deckel_id}/gruppen/{gruppe_id}")
def update_gruppe(deckel_id: int, gruppe_id: int, data: GruppeUpdate,
                  user: CurrentUser, db: DB):
    """Sortiment ändern (#167, v100): Name, Verkäufer oder Aktiv-Status werden als
    NEUER STAND ab einem Spieltag festgehalten (`ab_termin_id`; ohne Angabe ab dem
    aktuellen Termin). Ältere Termine behalten ihren Stand, damit Nachbuchungen
    den Verkäufer und die Preise von damals treffen."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    alt = _gruppe_im_deckel(db, deckel_id, gruppe_id)
    name = _validate_gruppe(db, deckel, data)
    ab_termin = _stand_termin(db, deckel, data.ab_termin_id)
    if ab_termin == alt.gilt_ab_termin_id:
        # Derselbe Spieltag: den vorhandenen Stand bearbeiten, keine Generation.
        if not db.clubdeckel_gruppen.update(gruppe_id, name,
                                            data.verkaeufer_mitglied_id,
                                            1 if data.aktiv else 0, data.sortierung,
                                            user.username, data.expected_version):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Die Gruppe wurde zwischenzeitlich geändert")
        # Auch hier kann es etwas umzustellen geben: Ein geänderter VERKÄUFER
        # verschiebt die Gegenbuchung, und die hängt an jedem einzelnen Strich.
        umgestellt = (_bestand_uebernehmen(
            db, deckel_id, ab_termin, _eigene_abbildung(db, gruppe_id),
            user.username) if data.bestand_uebernehmen else 0)
        return {**asdict(db.clubdeckel_gruppen.get(gruppe_id)),
                "umgestellt": umgestellt}
    ergebnis = db.clubdeckel_gruppen.neue_generation(
        gruppe_id, ab_termin, name, data.verkaeufer_mitglied_id,
        1 if data.aktiv else 0, data.sortierung, user.username)
    if ergebnis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gruppe nicht gefunden")
    neue_gruppe_id, abbildung = ergebnis
    umgestellt = (_bestand_uebernehmen(db, deckel_id, ab_termin, abbildung,
                                       user.username)
                  if data.bestand_uebernehmen else 0)
    return {**asdict(db.clubdeckel_gruppen.get(neue_gruppe_id)),
            "umgestellt": umgestellt}


@router.get("/{deckel_id}/gruppen/{gruppe_id}/staende")
def list_gruppen_staende(deckel_id: int, gruppe_id: int,
                         user: CurrentUser, db: DB):
    """Die Stände einer Gruppe („ab welchem Spieltag galt was", #167)."""
    _deckel_mit_stufe(db, user, deckel_id, 'wart')
    gruppe = _gruppe_im_deckel(db, deckel_id, gruppe_id)
    staende = db.clubdeckel_gruppen.list_generationen(gruppe.stamm_id or gruppe.id)
    for s in staende:
        s['gilt_ab_label'] = _stand_label(s)
    return staende


@router.delete("/{deckel_id}/gruppen/{gruppe_id}")
def delete_gruppe(deckel_id: int, gruppe_id: int, user: CurrentUser, db: DB):
    _deckel_mit_stufe(db, user, deckel_id, 'wart')
    _gruppe_im_deckel(db, deckel_id, gruppe_id)
    if db.clubdeckel_gruppen.has_active_artikel(gruppe_id):
        # Sonst würden die Artikel still zu „ohne Gruppe" = Team-Verkauf.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Gruppe enthält noch Artikel — bitte zuerst verschieben "
                            "oder löschen")
    db.clubdeckel_gruppen.mark_deleted(gruppe_id, user.username)
    return {"status": "geloescht"}


# -------------------------------------------------------------------- Artikel
def _stand_label(stand: dict) -> str:
    """„gilt ab"-Text eines Sortiments-Standes (#167): der Spieltag, ab dem er
    greift. Ohne Termin gilt der Stand von Anfang an."""
    if stand.get('gilt_ab_termin_id') is None:
        return 'von Anfang an'
    return _termin_label(SimpleNamespace(
        typ=stand['termin_typ'], beginn=stand['termin_beginn'],
        gegner=stand['termin_gegner']))


def _sortiment(db: DB, deckel_id: int, termin_id: Optional[int] = None,
               nur_aktive: bool = True) -> tuple[list, list[dict]]:
    """Das Sortiment zu einem Ziel-Termin (#167, v100): die gültigen
    Gruppen-Stände und deren Artikel. Einzige Quelle für Tresen, Katalog,
    Matrix und Buchung — damit können Anzeige und Buchung nicht auseinanderlaufen.
    """
    gruppen = db.clubdeckel_gruppen.list_stand(deckel_id, termin_id)
    if nur_aktive:
        gruppen = [g for g in gruppen if g.aktiv]
    artikel = db.clubdeckel_artikel.list_fuer_gruppen(
        [g.id for g in gruppen], nur_aktive=nur_aktive)
    return gruppen, artikel


@router.get("/{deckel_id}/artikel")
def list_artikel(deckel_id: int, user: CurrentUser, db: DB, alle: bool = False,
                 termin_id: Optional[int] = None):
    """Katalog: standardmäßig nur aktive Artikel (aktive Gruppen); alle ab Wart.
    Geliefert wird das Sortiment des Ziel-Termins (#167) — ohne Angabe der heute
    gültige Stand."""
    _deckel_mit_stufe(db, user, deckel_id, 'wart' if alle else 'mitglied')
    _, artikel = _sortiment(db, deckel_id, termin_id, nur_aktive=not alle)
    return artikel


def _validate_artikel(db: DB, deckel_id: int, data: ArtikelWrite) -> tuple[str, Decimal]:
    name = data.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name fehlt")
    preis = _euro(data.preis)
    if preis <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Preis muss größer 0 sein")
    if data.gruppe_id is not None:
        _gruppe_im_deckel(db, deckel_id, data.gruppe_id)
    return name, preis


def _stand_termin(db: DB, deckel, ab_termin_id: Optional[int]) -> Optional[int]:
    """Ab welchem Spieltag ein Sortiments-Stand gilt (#167). Ohne Angabe ab dem
    aktuellen Termin; hat die Mannschaft noch gar keinen, gilt der Stand von
    Anfang an (None) — eine andere Lesart gäbe es dann nicht."""
    if ab_termin_id is None:
        laufend = db.termine.get_laufenden(deckel.mannschaft_id)
        return laufend.id if laufend else None
    termin = db.termine.get(ab_termin_id)
    if termin is None or termin.mannschaft_id != deckel.mannschaft_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Termin gehört nicht zu dieser Mannschaft")
    return termin.id


def _eigene_abbildung(db: DB, gruppe_id: int) -> dict:
    """Artikel einer Gruppe auf sich selbst abgebildet — für das Umstellen an
    einem BESTEHENDEN Stand, wo keine Kopien entstehen."""
    return {a['id']: a['id']
            for a in db.clubdeckel_artikel.list_fuer_gruppen([gruppe_id])}


def _bestand_uebernehmen(db: DB, deckel_id: int, termin_id: Optional[int],
                         abbildung: dict, benutzer: str) -> int:
    """Schon gebuchte Striche dieses Spieltags auf den neuen Stand umstellen (#167).

    Umgesetzt als STORNO + Neubuchung gegen den neuen Artikel, nicht als
    Betrags-Korrektur. Grund: Am Stand hängt nicht nur der Preis, sondern auch
    die Bezeichnung und der VERKÄUFER — und der entscheidet, ob eine
    'verkauf'-Gegenzeile existiert und bei wem. Diese Paarung von Hand
    umzuschreiben hieße, die Buchungslogik ein zweites Mal zu bauen; über
    create_konsum entsteht sie garantiert richtig. Der Vorgang bleibt über die
    stornierten Zeilen nachvollziehbar, und die Ersatzbuchung übernimmt die
    Uhrzeit der ursprünglichen.

    Artikel, die es im neuen Stand nicht mehr gibt (gelöscht), stehen NICHT in
    der Abbildung — ihre Buchungen bleiben unangetastet. Etwas anderes ginge
    auch nicht: Man kann einen Strich nicht auf ein Produkt umbuchen, das es
    nicht mehr gibt.
    """
    if termin_id is None or not abbildung:
        return 0
    alte = db.clubdeckel_buchungen.konsum_je_artikel(
        deckel_id, termin_id, list(abbildung.keys()))
    umgestellt = 0
    for b in alte:
        neu_id = abbildung.get(b['artikel_id'])
        if neu_id is None:
            continue
        # Kein Überspringen bei neu_id == alt: Wird ein BESTEHENDER Stand
        # geändert (z. B. nur der Verkäufer), bleibt die Artikel-id dieselbe —
        # die Buchung muss trotzdem neu entstehen, damit Gegenkonto und Paarung
        # stimmen.
        ziel = db.clubdeckel_artikel.get_mit_verkaeufer(neu_id)
        if ziel is None:
            continue
        db.clubdeckel_buchungen.storno(b['id'], benutzer)
        db.clubdeckel_buchungen.create_konsum(
            deckel_id, b['mitglied_id'], ziel['id'], ziel['name'], b['menge'],
            ziel['preis'], ziel['verkaeufer_mitglied_id'], benutzer,
            termin_id=termin_id, wert_datum=str(b['created_at']))
        umgestellt += 1
    return umgestellt


@router.get("/{deckel_id}/sortiment-status")
def sortiment_status(deckel_id: int, user: CurrentUser, db: DB,
                     termin_id: Optional[int] = None):
    """Wurde bei diesem Spieltag schon gebucht (#167)? Der Katalog fragt das,
    bevor er einen Stand ändert — die Rückfrage „bestehende Striche umstellen?"
    soll nur kommen, wenn es wirklich etwas umzustellen gibt."""
    _deckel_mit_stufe(db, user, deckel_id, 'wart')
    if termin_id is None:
        return {"buchungen": 0, "betrag": Decimal("0.00")}
    return db.clubdeckel_buchungen.zaehle_konsum_fuer_termin(deckel_id, termin_id)


@router.post("/{deckel_id}/artikel", status_code=status.HTTP_201_CREATED)
def create_artikel(deckel_id: int, data: ArtikelWrite, user: CurrentUser, db: DB):
    """Neuer Artikel — er entsteht im Stand seiner Gruppe. Ältere Stände bleiben
    unberührt, der Artikel taucht dort also gar nicht auf; das ist richtig, denn
    es gab ihn damals nicht."""
    _deckel_mit_stufe(db, user, deckel_id, 'wart')
    name, preis = _validate_artikel(db, deckel_id, data)
    artikel = db.clubdeckel_artikel.create(
        deckel_id, data.gruppe_id, name, preis, 1 if data.aktiv else 0,
        data.sortierung, user.username)
    return asdict(artikel)


def _artikel_im_deckel(db: DB, deckel_id: int, artikel_id: int):
    artikel = db.clubdeckel_artikel.get(artikel_id)
    if artikel is None or artikel.deckel_id != deckel_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Artikel nicht in dieser Teamkasse gefunden")
    return artikel


@router.put("/{deckel_id}/artikel/{artikel_id}")
def update_artikel(deckel_id: int, artikel_id: int, data: ArtikelUpdate,
                   user: CurrentUser, db: DB):
    """Artikel ändern (#167, v100). Preis und Bezeichnung gehören zum STAND der
    Gruppe: Zielt die Änderung auf einen anderen Spieltag als den, ab dem der
    aktuelle Stand gilt, entsteht eine neue Generation der Gruppe (Kopie samt
    Artikeln), und geändert wird die Kopie. Ältere Termine behalten damit Preis,
    Bezeichnung UND Verkäufer von damals."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    alt = _artikel_im_deckel(db, deckel_id, artikel_id)
    name, preis = _validate_artikel(db, deckel_id, data)
    gruppe = _gruppe_im_deckel(db, deckel_id, alt.gruppe_id) if alt.gruppe_id else None
    ab_termin = _stand_termin(db, deckel, data.ab_termin_id)
    ziel_id, erwartete_version = artikel_id, data.expected_version
    abbildung: dict = {}
    if gruppe is not None and ab_termin != gruppe.gilt_ab_termin_id:
        ergebnis = db.clubdeckel_gruppen.neue_generation(
            gruppe.id, ab_termin, gruppe.name, gruppe.verkaeufer_mitglied_id,
            gruppe.aktiv, gruppe.sortierung, user.username)
        if ergebnis is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Gruppe nicht gefunden")
        neue_gruppe_id, abbildung = ergebnis
        ziel_id = abbildung.get(artikel_id, artikel_id)
        # Die Kopie ist frisch (version 1) — die Version des Originals passt nicht.
        erwartete_version = db.clubdeckel_artikel.get(ziel_id).version
        data = data.model_copy(update={"gruppe_id": neue_gruppe_id})
    if not db.clubdeckel_artikel.update(ziel_id, data.gruppe_id, name, preis,
                                        1 if data.aktiv else 0, data.sortierung,
                                        user.username, erwartete_version):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Der Artikel wurde zwischenzeitlich geändert")
    # Ohne neue Generation (Änderung an einem bestehenden Stand) betrifft das
    # Umstellen nur diesen einen Artikel — auf sich selbst abgebildet.
    if not abbildung:
        abbildung = {artikel_id: artikel_id}
    # Erst NACH dem Ändern umstellen: Sonst würden die Striche auf den noch
    # unveränderten Artikel umgebucht und trügen weiter den alten Preis.
    umgestellt = (_bestand_uebernehmen(db, deckel_id, ab_termin, abbildung,
                                       user.username)
                  if data.bestand_uebernehmen else 0)
    return {**asdict(db.clubdeckel_artikel.get(ziel_id)), "umgestellt": umgestellt}


@router.delete("/{deckel_id}/artikel/{artikel_id}")
def delete_artikel(deckel_id: int, artikel_id: int, user: CurrentUser, db: DB):
    _deckel_mit_stufe(db, user, deckel_id, 'wart')
    _artikel_im_deckel(db, deckel_id, artikel_id)
    db.clubdeckel_artikel.mark_deleted(artikel_id, user.username)
    return {"status": "geloescht"}


# ---------------------------------------------------------------------- Warte
@router.get("/{deckel_id}/warte")
def list_warte(deckel_id: int, user: CurrentUser, db: DB):
    """Wart-Liste — teamintern transparent (jedes Kader-Mitglied sieht sie)."""
    _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    return db.clubdeckel_berechtigungen.list_for_deckel(deckel_id)


def _kader_liste(db: DB, deckel, warte: Optional[set] = None) -> list[dict]:
    """Aktiver Kader der Mannschaft als Namensliste — gemeinsame Grundlage der
    Kandidaten-Auswahl und der Matrix-Zeilen (#167)."""
    heute = date.today().isoformat()
    kandidaten: dict[int, dict] = {}
    for zuordnung in db.list_mannschaft_kader(deckel.mannschaft_id):
        # list_mannschaft_kader liefert auch abgelaufene Zuordnungen — hier nur
        # der am Stichtag aktive Kader (von/bis-Fenster wie in der Kader-CTE).
        if zuordnung.von > heute or (zuordnung.bis and zuordnung.bis < heute):
            continue
        eintrag = kandidaten.setdefault(zuordnung.mitglied_id, {
            "mitglied_id": zuordnung.mitglied_id,
            "name": f"{zuordnung.mitglied_vorname} {zuordnung.mitglied_nachname}",
            "rollen": [],
            "ist_wart": zuordnung.mitglied_id in (warte or set()),
        })
        if zuordnung.rolle not in eintrag["rollen"]:
            eintrag["rollen"].append(zuordnung.rolle)
    return sorted(kandidaten.values(), key=lambda k: k["name"].lower())


@router.get("/{deckel_id}/kader")
def list_kader_kandidaten(deckel_id: int, user: CurrentUser, db: DB):
    """Aktiver Kader als Kandidaten für Wart-Ernennung, Verkäufer-Auswahl,
    Zahlungs-/Einkaufsziele und Zahlungsempfänger."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    warte = {w['mitglied_id'] for w in
             db.clubdeckel_berechtigungen.list_for_deckel(deckel_id)}
    return _kader_liste(db, deckel, warte)


@router.put("/{deckel_id}/warte/{mitglied_id}")
def set_wart(deckel_id: int, mitglied_id: int, user: CurrentUser, db: DB):
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'verwalten')
    if not db.clubdeckel.is_mitglied_in_kader(mitglied_id, deckel.mannschaft_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Das Mitglied steht nicht im aktiven Kader der Mannschaft")
    db.clubdeckel_berechtigungen.set_wart(deckel_id, mitglied_id, user.username)
    return {"status": "ok"}


@router.delete("/{deckel_id}/warte/{mitglied_id}")
def revoke_wart(deckel_id: int, mitglied_id: int, user: CurrentUser, db: DB):
    _deckel_mit_stufe(db, user, deckel_id, 'verwalten')
    if not db.clubdeckel_berechtigungen.revoke(deckel_id, mitglied_id, user.username):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Keine Wart-Berechtigung vorhanden")
    return {"status": "entfernt"}


# ---------------------------------------------------------- Beitragsbefreiungen
@router.get("/{deckel_id}/befreiungen")
def list_befreiungen(deckel_id: int, user: CurrentUser, db: DB):
    _deckel_mit_stufe(db, user, deckel_id, 'verwalten')
    return db.clubdeckel_befreiungen.list_for_deckel(deckel_id)


@router.put("/{deckel_id}/befreiungen/{mitglied_id}")
def set_befreiung(deckel_id: int, mitglied_id: int, user: CurrentUser, db: DB):
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'verwalten')
    if not db.clubdeckel.is_mitglied_in_kader(mitglied_id, deckel.mannschaft_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Das Mitglied steht nicht im aktiven Kader der Mannschaft")
    db.clubdeckel_befreiungen.set_befreiung(deckel_id, mitglied_id, user.username)
    return {"status": "ok"}


@router.delete("/{deckel_id}/befreiungen/{mitglied_id}")
def revoke_befreiung(deckel_id: int, mitglied_id: int, user: CurrentUser, db: DB):
    _deckel_mit_stufe(db, user, deckel_id, 'verwalten')
    if not db.clubdeckel_befreiungen.revoke(deckel_id, mitglied_id, user.username):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Keine Befreiung vorhanden")
    return {"status": "entfernt"}


# ------------------------------------------------------------------ Buchungen
def _ziel_mitglied(db: DB, user, deckel, stufe: str,
                   ziel_mitglied_id: Optional[int]) -> int:
    """Auf wen wird gebucht bzw. storniert (#167)?

    Ohne Angabe auf das eigene Kader-Mitglied — der Selbstbedienungs-Fall, der
    ohne Wart-Rechte auskommt. Mit Angabe auf ein anderes Mitglied; das ist der
    Tresendienst und deshalb ab Wart. Die eigene id ausdrücklich mitzuschicken
    (die Matrix tut das für jede Zeile) bleibt erlaubt, auch ohne Wart-Rechte.
    """
    eigenes = db.clubdeckel.get_kader_mitglied_id(user.id, deckel.mannschaft_id)
    if ziel_mitglied_id is None or ziel_mitglied_id == eigenes:
        if eigenes is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Du stehst nicht im aktiven Kader dieser Mannschaft")
        return eigenes
    if _STUFEN_RANG[stufe] < _STUFEN_RANG['wart']:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Nur Warte dürfen für andere Mitglieder buchen")
    if not _mitglied_am_deckel(db, deckel, ziel_mitglied_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Mitglied gehört nicht zu dieser Teamkasse")
    return ziel_mitglied_id


@router.post("/{deckel_id}/konsum", status_code=status.HTTP_201_CREATED)
def buche_konsum(deckel_id: int, data: KonsumCreate, user: CurrentUser, db: DB):
    """Tap-Buchung. Ohne `mitglied_id` bucht sie für das eigene Kader-Mitglied
    (auch Admins brauchen dafür eine aktive Kader-Zugehörigkeit); mit
    `mitglied_id` bucht ein WART für ein anderes Mitglied (#167, Tresendienst).
    Verkauft die Artikel-Gruppe über ein Mitglied, bekommt dieses die
    'verkauf'-Gegenzeile. Die Buchung wird dem laufenden Termin zugeordnet."""
    deckel, stufe = _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    _require_aktiv(deckel)
    if not 1 <= data.menge <= 99:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Menge muss zwischen 1 und 99 liegen")
    artikel = db.clubdeckel_artikel.get_mit_verkaeufer(data.artikel_id)
    if artikel is None or artikel['deckel_id'] != deckel_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Artikel nicht in dieser Teamkasse gefunden")
    if not artikel['aktiv'] or not (artikel['gruppe_aktiv'] if
                                    artikel['gruppe_aktiv'] is not None else 1):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Dieser Artikel ist nicht mehr im Angebot")
    mitglied_id = _ziel_mitglied(db, user, deckel, stufe, data.mitglied_id)
    termin_id = _termin_fuer_buchung(db, deckel, data.termin_id, data.ohne_termin)
    # Der Artikel MUSS aus dem Sortiments-Stand des Ziel-Termins stammen (#167,
    # v99). Sonst bekäme ein für ein altes Spiel nachgetragener Strich Preis,
    # Bezeichnung und Verkäufer von heute. Statt still den passenden Artikel zu
    # raten, sagen wir es: Die Oberfläche zeigt immer den Stand des gewählten
    # Ausschnitts und schickt damit ohnehin die richtige id — ein Treffer hier
    # heißt, dass die Seite veraltet ist.
    gueltige = {a['id'] for a in _sortiment(db, deckel_id, termin_id)[1]}
    if artikel['id'] not in gueltige:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Das Sortiment dieses Termins sieht anders aus — "
                            "bitte die Ansicht neu laden")
    buchung = db.clubdeckel_buchungen.create_konsum(
        deckel_id, mitglied_id, artikel['id'], artikel['name'], data.menge,
        artikel['preis'], artikel['verkaeufer_mitglied_id'], user.username,
        termin_id=termin_id)
    return asdict(buchung)


@router.delete("/{deckel_id}/konsum/{artikel_id}")
def undo_konsum(deckel_id: int, artikel_id: int, user: CurrentUser, db: DB,
                mitglied_id: Optional[int] = None,
                von: Optional[str] = None, bis: Optional[str] = None,
                termin_id: Optional[int] = None):
    """Nimmt den letzten Konsum-Strich dieses Artikels zurück (Undo-Zone am
    Tresen-Button, „−" in der Matrix). Ohne `mitglied_id` trifft es die eigene
    jüngste Buchung; mit `mitglied_id` die eines anderen Mitglieds — das darf
    erst ab Wart. von/bis/termin_id grenzen auf den angezeigten Ausschnitt ein,
    damit das „−" genau den Strich trifft, den die Zelle zählt (#167)."""
    deckel, stufe = _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    ziel = _ziel_mitglied(db, user, deckel, stufe, mitglied_id)
    buchung_id = db.clubdeckel_buchungen.letzte_konsum_id(
        deckel_id, ziel, artikel_id,
        von=_parse_datum(von), bis=_parse_datum(bis), termin_id=termin_id)
    if buchung_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Keine Buchung dieses Artikels zum Zurücknehmen")
    db.clubdeckel_buchungen.storno(buchung_id, user.username)
    return {"status": "storniert"}


@router.get("/{deckel_id}/buchungen")
def list_buchungen(deckel_id: int, user: CurrentUser, db: DB,
                   alle: bool = False, limit: int = 50,
                   mit_storniert: bool = False,
                   mitglied_id: Optional[int] = None,
                   suche: Optional[str] = None,
                   von: Optional[str] = None, bis: Optional[str] = None,
                   termin_id: Optional[int] = None):
    """Eigene Buchungen; mit ?alle=1 (ab Wart) alle Buchungen des Deckels.
    ?mit_storniert=1 blendet in der Wart-History auch stornierte Zeilen ein (#127),
    ?mitglied_id=N filtert die Wart-History auf ein Mitglied und ?suche=…
    volltextig über den Buchungstext (#129). ?von/?bis (ISO) bzw. ?termin_id
    schneiden den Tag- oder Termin-Ausschnitt heraus (#167)."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart' if alle else 'mitglied')
    limit = max(1, min(limit, 500))
    zeitraum = {"von": _parse_datum(von), "bis": _parse_datum(bis),
                "termin_id": termin_id}
    if alle:
        buchungen = db.clubdeckel_buchungen.list_for_deckel(
            deckel_id, mitglied_id=mitglied_id, limit=limit,
            mit_storniert=mit_storniert, suche=(suche or '').strip() or None,
            **zeitraum)
    else:
        mitglied_id = db.clubdeckel.get_kader_mitglied_id(user.id, deckel.mannschaft_id)
        if mitglied_id is None:
            return []
        buchungen = db.clubdeckel_buchungen.list_for_deckel(
            deckel_id, mitglied_id=mitglied_id, limit=limit, **zeitraum)
    return [asdict(b) for b in buchungen]


# ------------------------------------------------------- Termine & Matrix (#167)
@router.get("/{deckel_id}/termine")
def list_termine(deckel_id: int, user: CurrentUser, db: DB,
                 tage_zurueck: int = 365, tage_voraus: int = 365):
    """Termine der Mannschaft für die Auswahl in Matrix, Auswertung und
    Preisstand, plus die Kennzeichnung des aktuellen.

    Das Fenster reicht in BEIDE Richtungen: rückwärts fürs Nachbuchen („was war
    beim Spiel letzte Woche?"), vorwärts für Preisstände — ein Wart setzt einen
    Preis typischerweise „ab dem nächsten Heimspiel", und das liegt in der
    Zukunft.
    """
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    heute = date.today()
    termine = db.termine.list_for_mannschaft(
        deckel.mannschaft_id,
        von=(heute - timedelta(days=max(1, min(tage_zurueck, 1095)))).isoformat(),
        bis=(heute + timedelta(days=max(1, min(tage_voraus, 1095)))).isoformat())
    laufend = db.termine.get_laufenden(deckel.mannschaft_id)
    laufend_id = laufend.id if laufend else None
    # Der Termin, auf den man sich vorbereitet — Vorgabe für den Katalog. Nicht
    # derselbe wie `laufend`: Buchungen gehören nach dem Abpfiff noch zum Spiel,
    # die Speisekarte pflegt man dagegen fürs nächste Ereignis.
    naechster = db.termine.get_naechsten(deckel.mannschaft_id)
    return {
        "laufend_id": laufend_id,
        "naechster_id": naechster.id if naechster else None,
        "termine": [
            {"id": t.id, "typ": t.typ, "beginn": t.beginn, "ende": t.ende,
             "gegner": t.gegner, "status": t.status,
             "label": _termin_label(t), "laufend": t.id == laufend_id}
            for t in reversed(termine)
        ],
    }


@router.get("/{deckel_id}/matrix")
def get_matrix(deckel_id: int, user: CurrentUser, db: DB,
               von: Optional[str] = None, bis: Optional[str] = None,
               termin_id: Optional[int] = None):
    """Konsum-Gitter Mitglied × Artikel für einen Zeitraum oder Termin (#167).

    Zeilen sind der aktive Kader, ergänzt um alle, die im Ausschnitt gebucht
    haben — sonst verschwände die Buchung eines inzwischen ausgetretenen
    Spielers aus dem Gitter, obwohl sie in den Summen steckt.
    """
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    if termin_id is not None:
        termin = db.termine.get(termin_id)
        if termin is None or termin.mannschaft_id != deckel.mannschaft_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "Termin gehört nicht zu dieser Mannschaft")
    daten = db.clubdeckel_buchungen.matrix(
        deckel_id, von=_parse_datum(von), bis=_parse_datum(bis),
        termin_id=termin_id)
    gebucht = {m['mitglied_id']: m for m in daten['je_mitglied']}
    zeilen = []
    for k in _kader_liste(db, deckel):
        eintrag = gebucht.pop(k['mitglied_id'], None)
        zeilen.append({"mitglied_id": k['mitglied_id'], "name": k['name'],
                       "im_kader": True,
                       "anzahl": eintrag['anzahl'] if eintrag else 0,
                       "betrag": eintrag['betrag'] if eintrag else Decimal("0.00")})
    for rest in sorted(gebucht.values(), key=lambda x: x['mitglied_name'].lower()):
        zeilen.append({"mitglied_id": rest['mitglied_id'],
                       "name": rest['mitglied_name'], "im_kader": False,
                       "anzahl": rest['anzahl'], "betrag": rest['betrag']})
    # Spalten: das Sortiment des Ausschnitts (Preis, Bezeichnung und Verkäufer
    # also aus dem Stand dieses Spieltags) PLUS jeder Artikel, der im Ausschnitt
    # Umsatz hat. Ohne den Zusatz fiele ein Artikel aus einem anderen Stand aus
    # der Aufschlüsselung, steckte aber weiter in der Gesamtsumme — die Summen
    # gingen dann sichtbar nicht auf.
    _, artikel = _sortiment(db, deckel_id, termin_id)
    bekannt = {a['id'] for a in artikel}
    for a in artikel:
        a['ausser_dienst'] = False
    for weiterer in db.clubdeckel_artikel.list_fuer_ids(
            deckel_id, [aid for aid in daten['je_artikel'] if aid not in bekannt]):
        weiterer['ausser_dienst'] = True
        artikel.append(weiterer)
    for a in artikel:
        summe = daten['je_artikel'].get(a['id'])
        a['summe_anzahl'] = summe['anzahl'] if summe else 0
        a['summe_betrag'] = summe['betrag'] if summe else Decimal("0.00")
    return {
        "von": von, "bis": bis, "termin_id": termin_id,
        "artikel": artikel,
        "mitglieder": zeilen,
        "zellen": daten['zellen'],
        "gesamt": daten['gesamt'],
    }


@router.get("/{deckel_id}/salden")
def list_salden(deckel_id: int, user: CurrentUser, db: DB):
    """Deckelstand je Mitglied plus Team-Saldo — teamintern transparent."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    _beitragslauf(db, deckel)
    salden = db.clubdeckel_buchungen.salden(deckel_id)
    return {
        "team_saldo": -sum((s['saldo'] for s in salden), Decimal("0.00")),
        "mitglieder": salden,
    }


@router.post("/{deckel_id}/zahlung", status_code=status.HTTP_201_CREATED)
def buche_zahlung(deckel_id: int, data: ZahlungCreate, user: CurrentUser, db: DB):
    """Zahlung von Mitglied an Mitglied (bar/PayPal/…): Zahler +, Empfänger −."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    _require_aktiv(deckel)
    betrag = _euro(data.betrag)
    if betrag <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Betrag muss größer 0 sein")
    if data.von_mitglied_id == data.an_mitglied_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Zahlung braucht zwei verschiedene Mitglieder")
    for mid in (data.von_mitglied_id, data.an_mitglied_id):
        if not _mitglied_am_deckel(db, deckel, mid):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Mitglied gehört nicht zu dieser Teamkasse")
    datum = _parse_datum(data.datum)
    methode = _METHODE_LABEL.get(data.methode or '')
    freitext = (data.notiz or '').strip()
    notiz = ' · '.join(x for x in (methode, freitext) if x) or None
    ref = db.clubdeckel_buchungen.create_zahlung(
        deckel_id, data.von_mitglied_id, data.an_mitglied_id, betrag,
        notiz, user.username, datum)
    return {"paar_ref": ref}


@router.post("/{deckel_id}/an-verkauf", status_code=status.HTTP_201_CREATED)
def buche_an_verkauf(deckel_id: int, data: AnVerkaufCreate, user: CurrentUser, db: DB):
    """An-/Verkauf eines Mitglieds gegen Team oder ein anderes Mitglied.

    Gegenkonto Team (gegen_mitglied_id=None): Einzelbuchung (kauft = Belastung,
    verkauft = Gutschrift). Gegenkonto Mitglied: Nullsummen-Paar zwischen beiden.
    """
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    _require_aktiv(deckel)
    betrag = _euro(data.betrag)
    if betrag <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Betrag muss größer 0 sein")
    if not _mitglied_am_deckel(db, deckel, data.mitglied_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Mitglied gehört nicht zu dieser Teamkasse")
    if data.gegen_mitglied_id is not None:
        if data.gegen_mitglied_id == data.mitglied_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Gegenkonto muss ein anderes Mitglied sein")
        if not _mitglied_am_deckel(db, deckel, data.gegen_mitglied_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Gegen-Mitglied gehört nicht zu dieser Teamkasse")
    datum = _parse_datum(data.datum)
    ergebnis = db.clubdeckel_buchungen.create_an_verkauf(
        deckel_id, data.mitglied_id, data.gegen_mitglied_id, data.verkauft,
        betrag, (data.notiz or '').strip() or None, user.username, datum)
    return {"status": "gebucht", "ref": ergebnis}


@router.delete("/{deckel_id}/buchungen/{buchung_id}")
def storno_buchung(deckel_id: int, buchung_id: int, user: CurrentUser, db: DB):
    """Storno: ab Wart alles; ein Mitglied darf den EIGENEN Konsum stornieren
    (Fehltipp am Tresen). Paare (Zahlung, Mitglieds-Verkauf) werden immer
    komplett storniert; Beitrags-Storno heißt „erlassen" (keine Nachbuchung)."""
    deckel, stufe = _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    buchung = db.clubdeckel_buchungen.get(buchung_id)
    if buchung is None or buchung.deckel_id != deckel_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Buchung nicht gefunden")
    if _STUFEN_RANG[stufe] < _STUFEN_RANG['wart']:
        eigenes = db.clubdeckel.get_kader_mitglied_id(user.id, deckel.mannschaft_id)
        if buchung.typ != 'konsum' or buchung.mitglied_id != eigenes:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Nur eigene Konsum-Buchungen können storniert werden")
    db.clubdeckel_buchungen.storno(buchung_id, user.username)
    return {"status": "storniert"}


@router.post("/{deckel_id}/buchungen/{buchung_id}/restore")
def restore_buchung(deckel_id: int, buchung_id: int, user: CurrentUser, db: DB):
    """Storno rückgängig machen (ab Wart, #127): stellt eine stornierte Buchung
    wieder her; Paare (Zahlung, Mitglieds-Verkauf) werden komplett reaktiviert."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    buchung = db.clubdeckel_buchungen.get(buchung_id, include_deleted=True)
    if buchung is None or buchung.deckel_id != deckel_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Buchung nicht gefunden")
    if buchung.deleted_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Buchung ist nicht storniert")
    db.clubdeckel_buchungen.restore(buchung_id, user.username)
    return {"status": "wiederhergestellt"}
