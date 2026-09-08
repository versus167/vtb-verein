"""
Offene Aufgaben – der Hinweis mit der Zahl an Kachel und Nav-Punkt (Ticket #133).

Bewusst *ein* Endpunkt statt einer Zählung je Bereich: Kacheln und Nav-Leiste
brauchen die Zahlen gemeinsam und bei jedem Refresh, und mit jeder weiteren
Aufgabenart käme sonst ein weiterer Roundtrip dazu.

Gezählt wird nicht hier, sondern in der jeweiligen Domäne – dieser Router ruft
nur zusammen. Das ist die Bedingung dafür, dass die Zahl stimmt: sie muss
denselben Rechte-/Abteilungs-Scope haben wie die Liste, die sich hinter der
Kachel öffnet, und der gehört in die Domäne.

Neue Aufgabenart? Eine Zählfunktion in ihrer Domäne bereitstellen und unten in
_QUELLEN eintragen; der Schlüssel ist der Routenname im Frontend.

Eine Quelle darf statt einer Zahl auch eine Aufschlüsselung liefern. Nötig wird
das, wenn hinter einem Nav-Punkt mehrere Aufgabenarten liegen — der Bereich
Rechnungen hat Reiter, und Freigeben und Exportieren sind verschiedene Rollen
(#195). Nav und Kachel zeigen weiterhin die Summe; die Aufschlüsselung kommt
zusätzlich unter `detail` mit und setzt die Zahl im Bereich an den richtigen
Reiter. Ohne sie stünde am Nav-Punkt eine Zahl, die man drinnen nicht wiederfindet.
"""
from fastapi import APIRouter

from backend.core.deps import CurrentUser, DB
from backend.api.ul_stunden import anzahl_zu_bestaetigen

router = APIRouter(prefix="/aufgaben", tags=["aufgaben"])


# (Schlüssel = Routenname im Frontend, Zählfunktion)
_QUELLEN = (
    ("rechnungen", lambda user, db: {
        "freigabe": db.rechnungen.anzahl_zur_freigabe(user),
        "export": db.rechnungen.anzahl_export_bereit(user),
    }),
    ("uebungsleiter", anzahl_zu_bestaetigen),
    ("tickets", lambda user, db: db.tickets.anzahl_zustaendig(user)),
    # Termine der nächsten zwei Wochen ohne eigene Meldung (#95-Nachgang). Anders
    # als die übrigen Arten wartet hier niemand auf eine Entscheidung – wohl aber
    # der Betreuer auf die Antwort, und ohne Zahl vergisst man sie genau so lange,
    # bis die Erinnerung kommt.
    ("termine", lambda user, db: db.termine.anzahl_offene_meldungen(user.id)),
)


@router.get("/offen")
def offene_aufgaben(user: CurrentUser, db: DB):
    """Was wartet auf eine Entscheidung dieses Benutzers?

    Nur Aufgaben, die er selbst erledigen kann – wer nichts freigeben darf,
    bekommt überall 0 und sieht damit keinen Hinweis. Eine Aufgabenart, die
    scheitert, darf den Rest nicht mitreißen: sie zählt dann als 0.
    """
    offen: dict[str, int] = {}
    detail: dict[str, dict[str, int]] = {}
    for schluessel, zaehle in _QUELLEN:
        try:
            wert = zaehle(user, db)
        except Exception:      # ein Hinweis am Nav-Punkt ist kein Grund für einen 500er
            offen[schluessel] = 0
            continue
        if isinstance(wert, dict):
            teile = {name: int(anzahl) for name, anzahl in wert.items()}
            detail[schluessel] = teile
            offen[schluessel] = sum(teile.values())
        else:
            offen[schluessel] = int(wert)
    return {"gesamt": sum(offen.values()), "offen": offen, "detail": detail}
