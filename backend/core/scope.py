"""Abteilungs-Scope-Durchsetzung (Stufe E, siehe BERECHTIGUNGEN.md).

Bis Stufe D wirkten abteilungsgebunden geerbte Rechte „lenient" vereinsweit.
Stufe E setzt den Scope für die Personen-/Mitgliederliste durch: Wer
`personen.read` nur abteilungsgebunden (über eine Funktion) besitzt, sieht in
der Liste ausschließlich Mitglieder der erlaubten Abteilungen.

Wer das Recht vereinsweit hat (Admin, globaler Grant, vereinsweite Funktion),
ist nicht eingeschränkt – `allowed_abteilungen` liefert dann None.
"""
from app.models.permission import Permission


def visible_mitglied_ids(user, db, permission: str = Permission.PERSONEN_READ) -> set[int] | None:
    """Sichtbare Mitglieds-IDs gemäß Abteilungs-Scope des Users.

    Rückgabe:
      None       – keine Einschränkung (vereinsweit/Admin), alle Mitglieder sichtbar.
      set[int]   – nur diese Mitglieder sind sichtbar (ggf. leer).
    """
    allowed = user.allowed_abteilungen(permission)
    if allowed is None:
        return None
    if not allowed:
        return set()
    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT mitglied_id
            FROM mitglied_abteilung
            WHERE abteilung_id = ANY(%s) AND deleted_at IS NULL
            """,
            (list(allowed),),
        )
        return {row['mitglied_id'] for row in cur.fetchall()}


def visible_schloss_ids(user, db, permission: str = Permission.SCHLIESSANLAGE_READ) -> set[int] | None:
    """Sichtbare Schloss-IDs gemäß Abteilungs-Scope des Users (Phase 3, analog
    :func:`visible_mitglied_ids`).

    Rückgabe:
      None       – keine Einschränkung (vereinsweit/Admin), alle Schlösser sichtbar.
      set[int]   – nur diese Schlösser sind sichtbar (ggf. leer).

    Vereinsweite Schlösser (``abteilung_id IS NULL``) sind club-weite Ressourcen und
    erfordern das **vereinsweite** Recht; für rein abteilungsgebundene User sind sie
    daher **nicht** sichtbar (siehe :func:`darf_schloss`).
    """
    allowed = user.allowed_abteilungen(permission)
    if allowed is None:
        return None
    if not allowed:
        return set()
    with db.conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM tuer_schloss WHERE abteilung_id = ANY(%s) AND deleted_at IS NULL",
            (list(allowed),),
        )
        return {row['id'] for row in cur.fetchall()}


def darf_schloss(user, schloss, permission: str) -> bool:
    """Darf der User dieses konkrete Schloss unter ``permission``?

    Vereinsweite Schlösser (``abteilung_id IS NULL``) verlangen das vereinsweite Recht;
    abteilungsgebundene Schlösser erfüllt das Recht global ODER für genau diese Abteilung.
    """
    if schloss is None:
        return False
    if schloss.abteilung_id is None:
        return user.has_permission_global(permission)
    return user.has_permission_for_abteilung(permission, schloss.abteilung_id)
