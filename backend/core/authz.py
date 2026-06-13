"""Autorisierungs-Helfer rund um die Benutzerrolle.

Seit Stufe D (siehe BERECHTIGUNGEN.md) gibt es nur noch zwei Rollen:
'admin' (uneingeschränkt) und 'mitglied' (Rechte über Funktionen + Grants).
Das Administrator-Recht darf ausschließlich von Administratoren vergeben oder
entzogen werden – unabhängig von personen.write.
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
