"""Autorisierungs-Helfer rund um die Benutzerrolle und die Weitergabe von Rechten.

Seit Stufe D (siehe BERECHTIGUNGEN.md) gibt es nur noch zwei Rollen:
'admin' (uneingeschränkt) und 'mitglied' (Rechte über Funktionen + Grants).
Das Administrator-Recht darf ausschließlich von Administratoren vergeben oder
entzogen werden – unabhängig von personen.write.

Dazu kommt die **Delegationsregel** (:func:`authorize_permission_delegation`):
Niemand gibt weiter, was er selbst nicht hat. Sie bewacht beide Türen, durch die
sich fremde Rechte verändern lassen – die individuellen Grants und die
Funktionszuordnung – und ergänzt damit die zwei Türen, die schon vorher
Admin-only waren: die Funktions-Berechtigungsmatrix und die Admin-Rolle selbst.
"""
from fastapi import HTTPException, status

ALLOWED_ROLES = {"admin", "mitglied"}


def normalize_role(role: str | None) -> str:
    """Normalisiert eine Rolle auf das Stufe-D-Schema: alles außer 'admin' → 'mitglied'."""
    return "admin" if role == "admin" else "mitglied"


def authorize_role_assignment(actor, requested_role: str | None,
                              current_role: str | None = None) -> str:
    """Prüft eine Rollen-Zuweisung und gibt die normalisierte Zielrolle zurück.

    Nur das *Ändern* des Admin-Flags (Vergeben oder Entziehen) erfordert, dass der
    handelnde User selbst Admin ist. Bleibt das Flag unverändert, darf z. B. ein
    Bearbeiter (personen.write) die übrigen Account-Daten auch eines Admins
    bearbeiten. Beim Anlegen (current_role=None) zählt das Setzen auf 'admin' als
    Änderung.
    """
    new_role = normalize_role(requested_role)
    flag_aenderung = (new_role == "admin") != (current_role == "admin")
    if flag_aenderung and (actor is None or actor.role != "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Administratoren dürfen das Administrator-Recht vergeben oder entziehen.",
        )
    return new_role


def authorize_permission_delegation(actor, permissions, *,
                                    abteilung_id: int | None = None,
                                    anlass: str = "vergeben") -> None:
    """Delegationsregel: Weitergeben darf nur, wer das Recht selbst besitzt.

    Ohne sie kann jeder, der Stammdaten pflegen darf, über eine Funktionszuordnung
    Rechte verteilen, die weit über seinen eigenen liegen – die Rechteverwaltung
    hinge dann daran, dass niemand auf die Idee kommt.

    Der Vergleich richtet sich nach der Reichweite dessen, was vergeben wird:

    * ``abteilung_id is None`` – die Rechte gelten vereinsweit, also muss der
      Handelnde sie **vereinsweit** besitzen. Ein abteilungsgebundenes Recht
      reicht nicht: Sonst würde ein Abteilungsleiter aus seinem Fußball-Recht ein
      vereinsweites machen.
    * ``abteilung_id`` gesetzt – die Rechte gelten nur dort, also genügt das
      Recht für genau diese Abteilung (oder vereinsweit).

    Admins bestehen die Prüfung ohne Sonderfall: ``has_permission_*`` ist für sie
    immer wahr. Eine Funktion ohne hinterlegte Rechte ebenso – die leere Menge
    erfüllt die Bedingung von selbst und bleibt damit frei zuordenbar.
    """
    fehlend = sorted(
        p for p in permissions
        if not (actor.has_permission_global(p) if abteilung_id is None
                else actor.has_permission_for_abteilung(p, abteilung_id))
    )
    if fehlend:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(f"Diese Rechte kannst du nicht {anlass}, weil du sie selbst "
                    f"nicht hast: {', '.join(fehlend)}"),
        )
