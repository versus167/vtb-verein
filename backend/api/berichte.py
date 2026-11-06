from datetime import date

from fastapi import APIRouter, HTTPException, status

from app.db.berichtslisten_repository import EHRUNG_STUFEN
from app.models.permission import Permission
from ..core.deps import CurrentUser, DB
from ..core.scope import visible_mitglied_ids

router = APIRouter(prefix="/berichte", tags=["berichte"])


def _require_read(user):
    if not user.has_permission(Permission.BERICHTE_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Keine Berechtigung für Berichte",
        )


def _darf_namen(user) -> bool:
    """Namenslisten in Berichten: zusätzlich zum Berichte- das Personen-Leserecht.
    Wer Personen nur für eine Abteilung lesen darf, sieht nur deren Leute
    (s. ``_im_scope``)."""
    return user.has_permission(Permission.PERSONEN_READ)


def _require_namen(user):
    _require_read(user)
    if not _darf_namen(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Für Namenslisten fehlt das Recht, Personen zu sehen",
        )


def _im_scope(user, db, zeilen: list[dict]) -> list[dict]:
    sichtbar = visible_mitglied_ids(user, db)
    return zeilen if sichtbar is None else [z for z in zeilen if z["mitglied_id"] in sichtbar]


@router.get("/statistik")
def get_statistik(user: CurrentUser, db: DB, abteilung_id: int | None = None):
    """Aggregierte Kennzahlen für das Statistik-Dashboard.

    Ohne ``abteilung_id`` vereinsweit; mit gesetzter ``abteilung_id`` auf die aktiven
    Mitglieder dieser Abteilung gefiltert. Die Abteilungsliste fürs Dropdown wird
    immer mitgeliefert (kein Zusatz-Recht nötig). Bewusst ohne Zahlungsstatus.
    """
    _require_read(user)
    return {
        "kpis":                 db.statistik.kpis(abteilung_id),
        "entwicklung": {
            "jahr":  db.statistik.mitglieder_entwicklung("jahr", 12, abteilung_id),
            "monat": db.statistik.mitglieder_entwicklung("monat", 12, abteilung_id),
        },
        "altersstruktur":       db.statistik.altersstruktur(abteilung_id),
        "geschlechter":         db.statistik.geschlechterverteilung(abteilung_id),
        # Abteilungs-Übersicht nur vereinsweit (bei Filter auf eine Abteilung redundant).
        "abteilungen":          db.statistik.abteilungsuebersicht() if abteilung_id is None else [],
        "abteilung_optionen":   [{"id": a.id, "name": a.name} for a in db.list_abteilungen()],
    }


@router.get("/lsb-meldung")
def get_lsb_meldung(user: CurrentUser, db: DB, stichtag: date | None = None):
    """A- und B-Meldung für die LSB-Bestandserhebung (#155).

    Vorgabe für den Stichtag ist der 31.12. des Vorjahres – gemeldet wird im
    Januar. ``luecken`` (wer ohne Geburtsdatum/Geschlecht unter „ohne Angabe"
    steht) nur mit Personen-Leserecht, sonst None.
    """
    _require_read(user)
    if stichtag is None:
        stichtag = date(date.today().year - 1, 12, 31)
    meldung = db.statistik.lsb_meldung(stichtag)
    meldung["luecken"] = (_im_scope(user, db, db.berichtslisten.fehlende_meldeangaben(stichtag))
                          if _darf_namen(user) else None)
    return meldung


def _naechster_31_maerz(heute: date) -> date:
    """Vorgabe-Stichtag der Ehrungen: der nächste 31.3. ab heute – im Januar der
    des laufenden Jahres, ab April schon der fürs kommende."""
    stichtag = date(heute.year, 3, 31)
    return stichtag if heute <= stichtag else date(heute.year + 1, 3, 31)


@router.get("/ehrungen")
def get_ehrungen(user: CurrentUser, db: DB, stichtag: date | None = None):
    """Jubilare der Mitgliedschaft für das Ehrungsjahr = Jahr des Stichtags (#155)."""
    _require_namen(user)
    if stichtag is None:
        stichtag = _naechster_31_maerz(date.today())
    return {
        "stichtag": stichtag.isoformat(),
        "stufen":   list(EHRUNG_STUFEN),
        "ehrungen": _im_scope(user, db, db.berichtslisten.ehrungen(stichtag)),
    }


@router.get("/uebungsleiter")
def get_uebungsleiter(user: CurrentUser, db: DB):
    """Übungsleiter mit Lizenzstand – LSB-Meldung und Januar-Liste der
    auslaufenden Lizenzen (#155); den Jahresfilter macht die Oberfläche."""
    _require_namen(user)
    return _im_scope(user, db, db.berichtslisten.uebungsleiter())


@router.get("/altersgruppen")
def get_altersgruppen(user: CurrentUser, db: DB, stichtag: date | None = None):
    """Mitglieder unter 18 / 18–50 / über 50 am Stichtag (Vorgabe heute)."""
    _require_read(user)
    return db.statistik.altersgruppen_am(stichtag or date.today())
