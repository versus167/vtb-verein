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
