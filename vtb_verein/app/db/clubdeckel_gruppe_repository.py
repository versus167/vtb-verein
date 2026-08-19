"""Artikel-Gruppen der Teamkasse (#98): clubdeckel_gruppe.

Jede Gruppe („Getränke", „Essen", …) hat einen VERKÄUFER: das Team
(verkaeufer_mitglied_id NULL) oder ein Mitglied — z. B. verkauft ein Mitglied
die Roster selbst. Der Verkäufer bestimmt beim Konsum, wem der Erlös gutge-
schrieben wird (Team implizit bzw. 'verkauf'-Gegenzeile beim Mitglied).
"""
from datetime import datetime
from typing import Optional

from app.models.clubdeckel import ClubdeckelGruppe
from app.db.base_repository import BaseRepository


def _jetzt_lokal() -> str:
    """Jetzt als lokale Wandzeit im Termin-Format — dieselbe Skala wie beginn."""
    return datetime.now().strftime('%Y-%m-%dT%H:%M')

_COLS = ("id, deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung, "
         "stamm_id, gilt_ab_termin_id, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")
_G_COLS = ", ".join("g." + s.strip() for s in _COLS.split(","))


def _map(row) -> ClubdeckelGruppe:
    return ClubdeckelGruppe(**dict(row))


class ClubdeckelGruppeRepository(BaseRepository):

    def list_for_deckel(self, deckel_id: int) -> list[ClubdeckelGruppe]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_G_COLS},
                       v.vorname || ' ' || v.nachname AS verkaeufer_name
                FROM clubdeckel_gruppe g
                LEFT JOIN mitglied v ON v.id = g.verkaeufer_mitglied_id
                WHERE g.deckel_id = %s AND g.deleted_at IS NULL
                ORDER BY g.sortierung, lower(g.name), g.id
                """,
                (deckel_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, gruppe_id: int) -> Optional[ClubdeckelGruppe]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_G_COLS},
                       v.vorname || ' ' || v.nachname AS verkaeufer_name
                FROM clubdeckel_gruppe g
                LEFT JOIN mitglied v ON v.id = g.verkaeufer_mitglied_id
                WHERE g.id = %s AND g.deleted_at IS NULL
                """,
                (gruppe_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, deckel_id: int, name: str,
               verkaeufer_mitglied_id: Optional[int], aktiv: int,
               sortierung: int, created_by: str,
               gilt_ab_termin_id: Optional[int] = None) -> ClubdeckelGruppe:
        """Neue Gruppe als ERSTE Generation ihres Stammes (#167): stamm_id zeigt
        auf die eigene id, damit spätere Generationen daran andocken."""
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_gruppe "
                "(deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung, "
                " gilt_ab_termin_id, created_by, updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung,
                 gilt_ab_termin_id, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
            cur.execute("UPDATE clubdeckel_gruppe SET stamm_id=%s, version=version+1 "
                        "WHERE id=%s", (new_id, new_id))
        return self.get(new_id)

    def update(self, gruppe_id: int, name: str,
               verkaeufer_mitglied_id: Optional[int], aktiv: int,
               sortierung: int, updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_gruppe SET name=%s, verkaeufer_mitglied_id=%s, "
                "aktiv=%s, sortierung=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (name, verkaeufer_mitglied_id, aktiv, sortierung, updated_by,
                 gruppe_id, expected_version),
            )
            return cur.rowcount > 0

    def list_stand(self, deckel_id: int,
                   termin_id: Optional[int] = None,
                   jetzt: Optional[str] = None) -> list[ClubdeckelGruppe]:
        """Das Sortiment, wie es zu einem Ziel-Termin galt (#167).

        Je Stamm genau EINE Generation: die jüngste, deren `gilt_ab`-Termin nicht
        NACH dem Ziel beginnt. Sortiert wird über `termine.beginn` (Wandzeit-TEXT,
        lexikografisch vergleichbar); eine Generation ohne Termin gilt „von Anfang
        an" und trägt dabei den leeren String, liegt also vor jedem Datum.

        Ohne `termin_id` ist das Ziel die aktuelle Wandzeit — das ist der Stand,
        den Tresen und Katalog zeigen.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                WITH ziel AS (
                    SELECT COALESCE(
                        (SELECT beginn FROM termine WHERE id = %(tid)s),
                        %(jetzt)s) AS rang
                )
                SELECT DISTINCT ON (COALESCE(g.stamm_id, g.id)) {_G_COLS},
                       v.vorname || ' ' || v.nachname AS verkaeufer_name
                FROM clubdeckel_gruppe g
                LEFT JOIN mitglied v ON v.id = g.verkaeufer_mitglied_id
                LEFT JOIN termine t ON t.id = g.gilt_ab_termin_id
                CROSS JOIN ziel z
                WHERE g.deckel_id = %(did)s AND g.deleted_at IS NULL
                  AND COALESCE(t.beginn, '') <= z.rang
                ORDER BY COALESCE(g.stamm_id, g.id),
                         COALESCE(t.beginn, '') DESC, g.id DESC
                """,
                {"did": deckel_id, "tid": termin_id,
                 "jetzt": jetzt or _jetzt_lokal()},
            )
            gruppen = [_map(r) for r in cur.fetchall()]
        return sorted(gruppen, key=lambda g: (g.sortierung, g.name.lower(), g.id))

    def stand_termine_je_stamm(self, deckel_id: int) -> dict[int, list]:
        """Je Stamm die Spieltage, für die ein eigener Stand existiert — damit der
        Umschalter im Katalog zeigen kann, wo schon etwas hinterlegt ist. Eine
        Abfrage für den ganzen Deckel statt einer je Gruppe."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(stamm_id, id) AS stamm, gilt_ab_termin_id "
                "FROM clubdeckel_gruppe "
                "WHERE deckel_id = %s AND deleted_at IS NULL",
                (deckel_id,),
            )
            treffer: dict[int, list] = {}
            for r in cur.fetchall():
                treffer.setdefault(r['stamm'], []).append(r['gilt_ab_termin_id'])
        return treffer

    def neue_generation(self, gruppe_id: int, gilt_ab_termin_id: Optional[int],
                        name: str, verkaeufer_mitglied_id: Optional[int],
                        aktiv: int, sortierung: int,
                        benutzer: str) -> Optional[tuple[int, dict[int, int]]]:
        """Änderung als neuen Stand ab einem Spieltag festhalten (#167).

        Gibt es für genau diesen Spieltag schon eine Generation dieses Stammes,
        wird sie überschrieben — sonst sammelte jedes Nachjustieren am selben
        Abend eine weitere Generation an. Sonst entsteht eine Kopie der Gruppe
        samt ihrer Artikel; die Artikel sind Teil des Standes, nicht der Gruppe,
        und müssen deshalb mitkopiert werden.

        Gibt (id der Generation, {alter Artikel: neuer Artikel}) zurück — die
        Abbildung braucht der Aufrufer, um „diesen Artikel ändern" auf die Kopie
        zu übertragen. None, wenn es die Gruppe nicht gibt.
        """
        quelle = self.get(gruppe_id)
        if quelle is None:
            return None
        stamm = quelle.stamm_id or quelle.id
        with self.cursor() as cur:
            cur.execute(
                "SELECT id FROM clubdeckel_gruppe "
                "WHERE COALESCE(stamm_id, id) = %s AND deleted_at IS NULL "
                "  AND gilt_ab_termin_id IS NOT DISTINCT FROM %s",
                (stamm, gilt_ab_termin_id),
            )
            vorhanden = cur.fetchone()
            if vorhanden:
                cur.execute(
                    "UPDATE clubdeckel_gruppe SET name=%s, verkaeufer_mitglied_id=%s, "
                    "aktiv=%s, sortierung=%s, updated_at=CURRENT_TIMESTAMP, "
                    "updated_by=%s, version=version+1 WHERE id=%s",
                    (name, verkaeufer_mitglied_id, aktiv, sortierung, benutzer,
                     vorhanden['id']),
                )
                # Ziel-Generation existiert schon: Artikel bleiben, wie sie sind.
                # Die Abbildung ist dann die Identität für die eigenen Artikel.
                cur.execute(
                    "SELECT id FROM clubdeckel_artikel "
                    "WHERE gruppe_id = %s AND deleted_at IS NULL", (vorhanden['id'],))
                eigene = {r['id']: r['id'] for r in cur.fetchall()}
                return vorhanden['id'], eigene
            cur.execute(
                "INSERT INTO clubdeckel_gruppe "
                "(deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung, "
                " stamm_id, gilt_ab_termin_id, created_by, updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (quelle.deckel_id, name, verkaeufer_mitglied_id, aktiv, sortierung,
                 stamm, gilt_ab_termin_id, benutzer, benutzer),
            )
            neue_id = cur.fetchone()['id']
            # Artikel der Quell-Generation mitkopieren: Preis und Bezeichnung
            # gehören zum Stand, sonst zeigte die neue Generation ein leeres Regal.
            # Zeilenweise statt INSERT..SELECT, weil nur so die Zuordnung
            # alt→neu entsteht, die der Aufrufer zurückbekommt.
            cur.execute(
                "SELECT id, deckel_id, name, preis, aktiv, sortierung, nur_wart "
                "FROM clubdeckel_artikel WHERE gruppe_id = %s AND deleted_at IS NULL "
                "ORDER BY id", (gruppe_id,))
            abbildung: dict[int, int] = {}
            for a in cur.fetchall():
                cur.execute(
                    "INSERT INTO clubdeckel_artikel "
                    "(deckel_id, gruppe_id, name, preis, aktiv, sortierung, nur_wart, "
                    " created_by, updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (a['deckel_id'], neue_id, a['name'], a['preis'], a['aktiv'],
                     a['sortierung'], a['nur_wart'], benutzer, benutzer),
                )
                abbildung[a['id']] = cur.fetchone()['id']
        return neue_id, abbildung

    def list_generationen(self, stamm_id: int) -> list[dict]:
        """Alle Stände eines Stammes, jüngster zuerst — für die Anzeige."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT g.id, g.name, g.verkaeufer_mitglied_id, g.gilt_ab_termin_id,
                       v.vorname || ' ' || v.nachname AS verkaeufer_name,
                       t.typ AS termin_typ, t.beginn AS termin_beginn,
                       t.gegner AS termin_gegner
                FROM clubdeckel_gruppe g
                LEFT JOIN mitglied v ON v.id = g.verkaeufer_mitglied_id
                LEFT JOIN termine t ON t.id = g.gilt_ab_termin_id
                WHERE COALESCE(g.stamm_id, g.id) = %s AND g.deleted_at IS NULL
                ORDER BY COALESCE(t.beginn, '') DESC, g.id DESC
                """,
                (stamm_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def has_active_artikel(self, gruppe_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM clubdeckel_artikel "
                "WHERE gruppe_id = %s AND deleted_at IS NULL LIMIT 1",
                (gruppe_id,),
            )
            return cur.fetchone() is not None

    def mark_deleted(self, gruppe_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_gruppe SET deleted_at=CURRENT_TIMESTAMP, "
                "deleted_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, gruppe_id),
            )
            return cur.rowcount > 0
