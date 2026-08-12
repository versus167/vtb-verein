"""Abteilungs-Scope-Durchsetzung (Stufe E, siehe BERECHTIGUNGEN.md).

Bis Stufe D wirkten abteilungsgebunden geerbte Rechte „lenient" vereinsweit.
Stufe E setzt den Scope durch: Wer `personen.read` nur abteilungsgebunden (über
eine Funktion) besitzt, sieht ausschließlich Mitglieder der erlaubten Abteilungen.

Zwei Sorten Helfer, weil es zwei Sorten Zugriff gibt:

* :func:`visible_mitglied_ids` filtert **Listen** – „zeig mir alles, was ich darf".
* :func:`require_mitglied` / :func:`require_person` bewachen **ID-adressierte**
  Endpunkte – „darf ich an genau dieses Mitglied?". Ohne sie wäre die
  Listenfilterung bloß Kosmetik: Wer die Liste gefiltert bekommt, könnte die
  übersprungenen Datensätze weiterhin über ihre ID einzeln abrufen und ändern.

Wer das Recht vereinsweit hat (Admin, globaler Grant, vereinsweite Funktion),
ist nicht eingeschränkt – `allowed_abteilungen` liefert dann None.
"""
from fastapi import HTTPException, status

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


def darf_mitglied(user, db, mitglied_id: int | None,
                  permission: str = Permission.PERSONEN_READ) -> bool:
    """Darf der User unter ``permission`` an dieses konkrete Mitglied?

    Gezielte Abfrage statt :func:`visible_mitglied_ids`: Für die Frage nach einem
    einzelnen Mitglied wäre es Verschwendung, erst alle sichtbaren IDs zu laden.

    Der Soft-Delete des Mitglieds spielt hier bewusst keine Rolle – die
    Abteilungs-Zuordnungen bleiben beim Löschen bestehen (s.
    ``PersonService.delete_person``), damit Papierkorb und Wiederherstellen
    denselben Scope kennen wie die lebende Liste.
    """
    allowed = user.allowed_abteilungen(permission)
    if allowed is None:
        return True
    if not allowed or mitglied_id is None:
        return False
    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM mitglied_abteilung
            WHERE mitglied_id = %s AND abteilung_id = ANY(%s) AND deleted_at IS NULL
            LIMIT 1
            """,
            (mitglied_id, list(allowed)),
        )
        return cur.fetchone() is not None


def require_mitglied(user, db, mitglied_id: int | None,
                     permission: str = Permission.PERSONEN_READ) -> None:
    """403, wenn das Mitglied außerhalb des Abteilungs-Scope liegt."""
    if not darf_mitglied(user, db, mitglied_id, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dieses Mitglied liegt außerhalb deines Bereichs",
        )


def require_person(user, db, user_id: int,
                   permission: str = Permission.PERSONEN_READ) -> None:
    """Wie :func:`require_mitglied`, nur über die User-ID einer Person.

    Ein Benutzerkonto ohne Mitglied-Datensatz hat keine Abteilung und ist für
    abteilungsgebundene Bearbeiter deshalb tabu – dieselbe Regel, nach der die
    Personenliste solche Konten für sie ausblendet.
    """
    mitglied = db.get_mitglied_by_user_id(user_id)
    require_mitglied(user, db, mitglied.id if mitglied else None, permission)


def require_abteilung(user, abteilung_id: int | None,
                      permission: str = Permission.PERSONEN_WRITE) -> None:
    """403, wenn die Abteilung außerhalb des Scope liegt.

    Für Zuordnungen ist *die Abteilung* die richtige Frage, nicht das Mitglied:
    Wer neu in den Verein kommt, hängt noch an keiner Abteilung und wäre über
    :func:`require_mitglied` für jeden abteilungsgebundenen Bearbeiter
    unerreichbar — auch für den, der ihn gerade aufnehmen soll. Umgekehrt hindert
    diese Prüfung ihn daran, jemanden in eine fremde Abteilung zu schieben.

    ``abteilung_id is None`` heißt „vereinsweit" und verlangt deshalb das
    vereinsweite Recht — dieselbe Regel wie bei vereinsweiten Schlössern
    (:func:`darf_schloss`).
    """
    erlaubt = (user.has_permission_global(permission) if abteilung_id is None
               else user.has_permission_for_abteilung(permission, abteilung_id))
    if not erlaubt:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Diese Abteilung liegt außerhalb deines Bereichs",
        )


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
