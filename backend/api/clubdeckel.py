"""Teamtresor/Clubdeckel (#98) — mannschaftsinterne Getränke-Strichliste.

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
Notfall-Fallback. Konsum bucht immer für das EIGENE Kader-Mitglied.

Buchungsmodell: Saldo je Mitglied = SUM(betrag), Team-Saldo = −Σ Mitglieder.
Konsum negativ (bei Mitglieds-Verkäufer mit 'verkauf'-Gegenzeile als Nullsummen-
Paar), Einkauf (Team kauft vom Mitglied) positiv, Zahlung Mitglied→Mitglied als
Nullsummen-Paar, Monatsbeitrag automatisch beim Zugriff nachgebucht (Befreiungen
pro Mitglied; Storno eines Beitrags heißt „erlassen").
"""
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/clubdeckel", tags=["clubdeckel"])

_STUFEN_RANG = {'mitglied': 1, 'wart': 2, 'verwalten': 3}


# --------------------------------------------------------------------------- I/O
class DeckelCreate(BaseModel):
    name: Optional[str] = None               # Default: "Teamtresor <Mannschaft>"


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


class GruppeUpdate(GruppeWrite):
    expected_version: int


class ArtikelWrite(BaseModel):
    name: str
    preis: float
    gruppe_id: Optional[int] = None
    aktiv: bool = True
    sortierung: int = 0


class ArtikelUpdate(ArtikelWrite):
    expected_version: int


class KonsumCreate(BaseModel):
    artikel_id: int
    menge: int = 1


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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teamtresor nicht gefunden")
    stufe = _stufe(db, user, deckel)
    if stufe is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Kein Zugriff auf den Teamtresor dieser Mannschaft")
    if _STUFEN_RANG[stufe] < _STUFEN_RANG[mindest]:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Keine Berechtigung für diese Aktion am Teamtresor")
    return deckel, stufe


def _require_aktiv(deckel) -> None:
    if not deckel.aktiv:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Teamtresor ist deaktiviert — Buchen nicht möglich")


def _require_admin(user) -> None:
    """Löschen und Wiederherstellen eines Teamtresors sind app-weit admin-only (#125)."""
    if user.role != 'admin':
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Nur Administratoren dürfen einen Teamtresor löschen "
                            "oder wiederherstellen")


def _mitglied_am_deckel(db: DB, deckel, mitglied_id: int) -> bool:
    """Ziel-Prüfung für Zahlung/Einkauf: aktives Kader-Mitglied ODER Mitglied
    mit Buchungen auf dem Deckel (Restschuld eines Ausgetretenen bleibt regelbar)."""
    if db.clubdeckel.is_mitglied_in_kader(mitglied_id, deckel.mannschaft_id):
        return True
    return db.clubdeckel_buchungen.saldo_for_mitglied(deckel.id, mitglied_id) != 0


def _beitragslauf(db: DB, deckel) -> None:
    """Lazy-Nachbuchung offener Monatsbeiträge beim Zugriff (nur aktiver Deckel
    mit konfiguriertem Beitrag)."""
    if deckel.aktiv and deckel.beitrag and deckel.beitrag_ab:
        db.clubdeckel_buchungen.buche_faellige_beitraege(
            deckel.id, deckel.mannschaft_id, deckel.beitrag, deckel.beitrag_ab)


# ---------------------------------------------------------------------- Teams
@router.get("/teams")
def list_meine_teams(user: CurrentUser, db: DB):
    """Meine Teamtresor-Teams (= Nav-Probe): Kader-Teams mit vorhandenem Deckel
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
                            "Teamtresor einschalten")
    if db.clubdeckel.get_by_mannschaft(mannschaft_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Diese Mannschaft hat bereits einen Teamtresor")
    name = (data.name or '').strip() or f"Teamtresor {mannschaft.name}"
    deckel = db.clubdeckel.create(mannschaft_id, name, user.username)
    return asdict(deckel)


# ------------------------------------------------------------------ Papierkorb
# WICHTIG: vor der "/{deckel_id}"-Route deklarieren, sonst versucht der
# int-Pfadparameter, "papierkorb" zu parsen (422). Admin-only (#125).
@router.get("/papierkorb")
def list_papierkorb(user: CurrentUser, db: DB):
    """Gelöschte Teamtresore (Admin-Papierkorb) — Grundlage fürs Wiederherstellen."""
    _require_admin(user)
    return db.clubdeckel.list_geloescht()


@router.post("/papierkorb/{deckel_id}/restore")
def restore_deckel(deckel_id: int, user: CurrentUser, db: DB):
    """Einen gelöschten Teamtresor komplett wiederherstellen (Deckel + Buchungen +
    Katalog + Warte + Befreiungen). 409, wenn die Mannschaft inzwischen wieder einen
    aktiven Teamtresor hat."""
    _require_admin(user)
    ergebnis = db.clubdeckel.restore(deckel_id, user.username)
    if ergebnis == 'not_found':
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Kein gelöschter Teamtresor mit dieser ID")
    if ergebnis == 'conflict':
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Diese Mannschaft hat bereits wieder einen aktiven "
                            "Teamtresor — Wiederherstellen nicht möglich")
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
    artikel = db.clubdeckel_artikel.list_for_deckel(deckel_id, nur_aktive=True)
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
                            "Zahlungsempfänger gehört nicht zu diesem Teamtresor")
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
                            "Der Teamtresor wurde zwischenzeitlich geändert")
    return asdict(db.clubdeckel.get(deckel_id))


@router.put("/{deckel_id}/aktiv")
def set_deckel_aktiv(deckel_id: int, data: AktivUpdate, user: CurrentUser, db: DB):
    """Teamtresor (de)aktivieren durch den Verwalter — nur der Aktiv-Status, ohne die
    Stammdaten anzufassen. Deaktiviert = Buchen gesperrt, jederzeit reversibel."""
    _deckel_mit_stufe(db, user, deckel_id, 'verwalten')
    if not db.clubdeckel.set_aktiv(deckel_id, 1 if data.aktiv else 0,
                                   user.username, data.expected_version):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Der Teamtresor wurde zwischenzeitlich geändert")
    return asdict(db.clubdeckel.get(deckel_id))


@router.delete("/{deckel_id}")
def delete_deckel(deckel_id: int, user: CurrentUser, db: DB):
    """Kompletter Soft-Delete des Teamtresors (Deckel + Buchungen + Katalog + Warte +
    Befreiungen) als ein Batch — admin-only (#125), über den Papierkorb wiederherstellbar."""
    _require_admin(user)
    if db.clubdeckel.loesche_komplett(deckel_id, user.username) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teamtresor nicht gefunden")
    return {"status": "geloescht"}


# -------------------------------------------------------------------- Gruppen
@router.get("/{deckel_id}/gruppen")
def list_gruppen(deckel_id: int, user: CurrentUser, db: DB):
    _deckel_mit_stufe(db, user, deckel_id, 'wart')
    return [asdict(g) for g in db.clubdeckel_gruppen.list_for_deckel(deckel_id)]


def _validate_gruppe(db: DB, deckel, data: GruppeWrite) -> str:
    name = data.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name fehlt")
    v = data.verkaeufer_mitglied_id
    if v is not None and not _mitglied_am_deckel(db, deckel, v):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Verkäufer gehört nicht zu diesem Teamtresor")
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
                            "Gruppe nicht in diesem Teamtresor gefunden")
    return gruppe


@router.put("/{deckel_id}/gruppen/{gruppe_id}")
def update_gruppe(deckel_id: int, gruppe_id: int, data: GruppeUpdate,
                  user: CurrentUser, db: DB):
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    _gruppe_im_deckel(db, deckel_id, gruppe_id)
    name = _validate_gruppe(db, deckel, data)
    if not db.clubdeckel_gruppen.update(gruppe_id, name,
                                        data.verkaeufer_mitglied_id,
                                        1 if data.aktiv else 0, data.sortierung,
                                        user.username, data.expected_version):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Die Gruppe wurde zwischenzeitlich geändert")
    return asdict(db.clubdeckel_gruppen.get(gruppe_id))


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
@router.get("/{deckel_id}/artikel")
def list_artikel(deckel_id: int, user: CurrentUser, db: DB, alle: bool = False):
    """Katalog: standardmäßig nur aktive Artikel (aktive Gruppen); alle ab Wart."""
    _deckel_mit_stufe(db, user, deckel_id, 'wart' if alle else 'mitglied')
    return db.clubdeckel_artikel.list_for_deckel(deckel_id, nur_aktive=not alle)


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


@router.post("/{deckel_id}/artikel", status_code=status.HTTP_201_CREATED)
def create_artikel(deckel_id: int, data: ArtikelWrite, user: CurrentUser, db: DB):
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
                            "Artikel nicht in diesem Teamtresor gefunden")
    return artikel


@router.put("/{deckel_id}/artikel/{artikel_id}")
def update_artikel(deckel_id: int, artikel_id: int, data: ArtikelUpdate,
                   user: CurrentUser, db: DB):
    _deckel_mit_stufe(db, user, deckel_id, 'wart')
    _artikel_im_deckel(db, deckel_id, artikel_id)
    name, preis = _validate_artikel(db, deckel_id, data)
    if not db.clubdeckel_artikel.update(artikel_id, data.gruppe_id, name, preis,
                                        1 if data.aktiv else 0, data.sortierung,
                                        user.username, data.expected_version):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Der Artikel wurde zwischenzeitlich geändert")
    return asdict(db.clubdeckel_artikel.get(artikel_id))


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


@router.get("/{deckel_id}/kader")
def list_kader_kandidaten(deckel_id: int, user: CurrentUser, db: DB):
    """Aktiver Kader als Kandidaten für Wart-Ernennung, Verkäufer-Auswahl,
    Zahlungs-/Einkaufsziele und Zahlungsempfänger."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart')
    warte = {w['mitglied_id'] for w in
             db.clubdeckel_berechtigungen.list_for_deckel(deckel_id)}
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
            "ist_wart": zuordnung.mitglied_id in warte,
        })
        if zuordnung.rolle not in eintrag["rollen"]:
            eintrag["rollen"].append(zuordnung.rolle)
    return sorted(kandidaten.values(), key=lambda k: k["name"].lower())


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
@router.post("/{deckel_id}/konsum", status_code=status.HTTP_201_CREATED)
def buche_konsum(deckel_id: int, data: KonsumCreate, user: CurrentUser, db: DB):
    """Tap-Buchung: bucht IMMER für das eigene Kader-Mitglied (auch Admins
    brauchen dafür eine aktive Kader-Zugehörigkeit). Verkauft die Artikel-Gruppe
    über ein Mitglied, bekommt dieses die 'verkauf'-Gegenzeile."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    _require_aktiv(deckel)
    if not 1 <= data.menge <= 99:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Menge muss zwischen 1 und 99 liegen")
    artikel = db.clubdeckel_artikel.get_mit_verkaeufer(data.artikel_id)
    if artikel is None or artikel['deckel_id'] != deckel_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Artikel nicht in diesem Teamtresor gefunden")
    if not artikel['aktiv'] or not (artikel['gruppe_aktiv'] if
                                    artikel['gruppe_aktiv'] is not None else 1):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Dieser Artikel ist nicht mehr im Angebot")
    mitglied_id = db.clubdeckel.get_kader_mitglied_id(user.id, deckel.mannschaft_id)
    if mitglied_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Du stehst nicht im aktiven Kader dieser Mannschaft")
    buchung = db.clubdeckel_buchungen.create_konsum(
        deckel_id, mitglied_id, artikel['id'], artikel['name'], data.menge,
        artikel['preis'], artikel['verkaeufer_mitglied_id'], user.username)
    return asdict(buchung)


@router.delete("/{deckel_id}/konsum/{artikel_id}")
def undo_konsum(deckel_id: int, artikel_id: int, user: CurrentUser, db: DB):
    """Nimmt den letzten eigenen Konsum-Strich dieses Artikels zurück
    (Undo-Zone am Tresen-Button). Storniert die jüngste eigene Konsum-Buchung."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'mitglied')
    mitglied_id = db.clubdeckel.get_kader_mitglied_id(user.id, deckel.mannschaft_id)
    if mitglied_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Du stehst nicht im aktiven Kader dieser Mannschaft")
    buchung_id = db.clubdeckel_buchungen.letzte_konsum_id(
        deckel_id, mitglied_id, artikel_id)
    if buchung_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Keine eigene Buchung dieses Artikels zum Zurücknehmen")
    db.clubdeckel_buchungen.storno(buchung_id, user.username)
    return {"status": "storniert"}


@router.get("/{deckel_id}/buchungen")
def list_buchungen(deckel_id: int, user: CurrentUser, db: DB,
                   alle: bool = False, limit: int = 50,
                   mit_storniert: bool = False,
                   mitglied_id: Optional[int] = None,
                   suche: Optional[str] = None):
    """Eigene Buchungen; mit ?alle=1 (ab Wart) alle Buchungen des Deckels.
    ?mit_storniert=1 blendet in der Wart-History auch stornierte Zeilen ein (#127),
    ?mitglied_id=N filtert die Wart-History auf ein Mitglied und ?suche=…
    volltextig über den Buchungstext (#129)."""
    deckel, _ = _deckel_mit_stufe(db, user, deckel_id, 'wart' if alle else 'mitglied')
    limit = max(1, min(limit, 500))
    if alle:
        buchungen = db.clubdeckel_buchungen.list_for_deckel(
            deckel_id, mitglied_id=mitglied_id, limit=limit,
            mit_storniert=mit_storniert, suche=(suche or '').strip() or None)
    else:
        mitglied_id = db.clubdeckel.get_kader_mitglied_id(user.id, deckel.mannschaft_id)
        if mitglied_id is None:
            return []
        buchungen = db.clubdeckel_buchungen.list_for_deckel(
            deckel_id, mitglied_id=mitglied_id, limit=limit)
    return [asdict(b) for b in buchungen]


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
                                "Mitglied gehört nicht zu diesem Teamtresor")
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
                            "Mitglied gehört nicht zu diesem Teamtresor")
    if data.gegen_mitglied_id is not None:
        if data.gegen_mitglied_id == data.mitglied_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Gegenkonto muss ein anderes Mitglied sein")
        if not _mitglied_am_deckel(db, deckel, data.gegen_mitglied_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Gegen-Mitglied gehört nicht zu diesem Teamtresor")
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
