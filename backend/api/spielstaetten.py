"""Spielstätten-Stammdaten (#95, Grundlage für Spielplan-Import und Belegungsplan).

Lesen darf jeder angemeldete Nutzer: Die Liste hängt in jedem Termin-Dialog, und
wer einen Termin seiner Mannschaft pflegen darf, braucht sie zwingend. Verwalten
(anlegen/ändern/löschen) hängt am globalen `spielstaetten.verwalten` — es sind
Stammdaten für den ganzen Verein, nicht Sache einer einzelnen Mannschaft.
`system.config` gilt zusätzlich als Obermenge (Altbestand, siehe
`_require_verwalten`).

Die beiden Platzhalter-Zeilen („Kein Vereinsgelände", „Nicht erfasst") sind
Schema-Bestandteil: Sie lassen sich weder ändern noch löschen. „Nicht erfasst"
wird beim Lesen ausgeblendet, damit es niemand aktiv auswählt — es trägt nur den
Altbestand aus der Migration.
"""
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.permission import Permission
from app.models.spielstaette import Spielstaette
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/spielstaetten", tags=["spielstaetten"])


class SpielstaetteWrite(BaseModel):
    name: str
    dfbnet_nr: Optional[str] = None
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    ist_eigen: bool = False
    parallel_moeglich: int = 1
    untergrund: Optional[str] = None


class SpielstaetteUpdate(SpielstaetteWrite):
    expected_version: int


def _require_verwalten(user) -> None:
    """`spielstaetten.verwalten` ist das gemeinte Recht; `system.config` gilt als
    Obermenge weiter, damit niemand beim Aufteilen des Rechts Zugriff verliert."""
    if not (user.has_permission(Permission.SPIELSTAETTEN_VERWALTEN)
            or user.has_permission(Permission.SYSTEM_CONFIG)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Keine Berechtigung, Spielstätten zu verwalten")


def _clean(w: SpielstaetteWrite) -> Spielstaette:
    name = (w.name or '').strip()
    if not name:
        raise HTTPException(422, "Name ist erforderlich")
    if w.parallel_moeglich < 1:
        raise HTTPException(422, "Parallel mögliche Belegungen müssen mindestens 1 sein")
    return Spielstaette(
        name=name,
        dfbnet_nr=(w.dfbnet_nr or '').strip() or None,
        strasse=(w.strasse or '').strip() or None,
        plz=(w.plz or '').strip() or None,
        ort=(w.ort or '').strip() or None,
        ist_eigen=w.ist_eigen,
        parallel_moeglich=w.parallel_moeglich,
        untergrund=(w.untergrund or '').strip() or None,
    )


@router.get("/")
def list_spielstaetten(user: CurrentUser, db: DB, mit_unbekannt: bool = False):
    """Auswählbare Spielstätten. `mit_unbekannt` nur für Auswertungen."""
    return [asdict(s) for s in db.spielstaetten.list_all(mit_unbekannt=mit_unbekannt)]


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_spielstaette(data: SpielstaetteWrite, user: CurrentUser, db: DB):
    _require_verwalten(user)
    s = _clean(data)
    if s.dfbnet_nr and db.spielstaetten.get_by_dfbnet_nr(s.dfbnet_nr) is not None:
        raise HTTPException(409, "Diese DFBnet-Spielstätten-Nr. ist schon vergeben")
    return asdict(db.spielstaetten.create(s, user.username))


@router.put("/{spielstaette_id}")
def update_spielstaette(spielstaette_id: int, data: SpielstaetteUpdate,
                        user: CurrentUser, db: DB):
    _require_verwalten(user)
    vorhanden = db.spielstaetten.get(spielstaette_id)
    if vorhanden is None:
        raise HTTPException(404, "Spielstätte nicht gefunden")
    if vorhanden.platzhalter is not None:
        raise HTTPException(422, "Diese Vorgabe lässt sich nicht bearbeiten")
    s = _clean(data)
    doppelt = db.spielstaetten.get_by_dfbnet_nr(s.dfbnet_nr) if s.dfbnet_nr else None
    if doppelt is not None and doppelt.id != spielstaette_id:
        raise HTTPException(409, "Diese DFBnet-Spielstätten-Nr. ist schon vergeben")
    if not db.spielstaetten.update(spielstaette_id, s, user.username,
                                   data.expected_version):
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    return asdict(db.spielstaetten.get(spielstaette_id))


@router.delete("/{spielstaette_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_spielstaette(spielstaette_id: int, user: CurrentUser, db: DB):
    _require_verwalten(user)
    vorhanden = db.spielstaetten.get(spielstaette_id)
    if vorhanden is None:
        raise HTTPException(404, "Spielstätte nicht gefunden")
    if vorhanden.platzhalter is not None:
        raise HTTPException(422, "Diese Vorgabe lässt sich nicht löschen")
    # Freundliche Meldung statt FK-Fehler: Termine hängen an der Spielstätte.
    anzahl = db.spielstaetten.zaehle_termine(spielstaette_id)
    if anzahl:
        raise HTTPException(
            409,
            f"Spielstätte wird noch von {anzahl} Termin(en) genutzt – "
            "bitte dort zuerst umtragen",
        )
    db.spielstaetten.mark_deleted(spielstaette_id, user.username)
