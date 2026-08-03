"""Repository für Mannschaften/Teams (gehören zu einer Abteilung)."""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from app.db.base_repository import BaseRepository

# Kader-Rollen, die den Mannschaften-Bereich ihres Teams sehen (abteilungsweit)
# und den Kader ihres Teams pflegen dürfen (#121). 'spieler' bleibt außen vor.
VERWALTEN_ROLLEN = ('uebungsleiter', 'betreuer')


@dataclass
class Mannschaft:
    id: Optional[int] = None
    abteilung_id: Optional[int] = None
    abteilung_name: Optional[str] = None      # per JOIN befüllt
    name: str = ''
    saison: Optional[str] = None
    beschreibung: Optional[str] = None
    # DFBnet-Zuordnung (#95): Name UND Mannschaftsart, denn der Name allein ist
    # nicht eindeutig („VTB Chemnitz 2" gibt es bei Herren wie E-Junioren).
    dfbnet_name: Optional[str] = None
    dfbnet_mannschaftsart: Optional[str] = None
    dfbnet_aliasse: list = field(default_factory=list)   # per Query befüllt
    mitglieder_count: int = 0                 # per Subquery befüllt (aktiver Kader)
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


_SELECT = """
    SELECT m.id, m.abteilung_id, a.name AS abteilung_name,
           m.name, m.saison, m.beschreibung,
           m.dfbnet_name, m.dfbnet_mannschaftsart,
           (SELECT COALESCE(array_agg(al.name ORDER BY lower(al.name)), '{}')
              FROM mannschaft_dfbnet_alias al
             WHERE al.mannschaft_id = m.id AND al.deleted_at IS NULL) AS dfbnet_aliasse,
           (SELECT count(*) FROM mitglied_mannschaft mm
              WHERE mm.mannschaft_id = m.id AND mm.deleted_at IS NULL) AS mitglieder_count,
           m.version, m.created_at, m.created_by, m.updated_at, m.updated_by,
           m.deleted_at, m.deleted_by
    FROM mannschaft m
    LEFT JOIN abteilung a ON a.id = m.abteilung_id
"""


def _map(row) -> Mannschaft:
    return Mannschaft(**dict(row))


class MannschaftRepository(BaseRepository):

    def list_all(self, abteilung_id: Optional[int] = None) -> list[Mannschaft]:
        where = "WHERE m.deleted_at IS NULL"
        params: list = []
        if abteilung_id is not None:
            where += " AND m.abteilung_id = %s"
            params.append(abteilung_id)
        with self.cursor() as cur:
            cur.execute(_SELECT + where + " ORDER BY a.name, m.name", params)
            return [_map(r) for r in cur.fetchall()]

    def get(self, id: int) -> Optional[Mannschaft]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE m.id = %s AND m.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    # ------------------------------------------------------------------ ACL (#121)
    def scope_abteilungen_kader(self, user_id: int,
                                stichtag: Optional[str] = None) -> set[int]:
        """Abteilungs-IDs, in denen der User am Stichtag Kader-ÜL/Betreuer ist
        (über das verknüpfte Mitglied). Basis der abteilungsweiten Lesesicht:
        Wer in einem Team einer Abteilung ÜL/Betreuer ist, sieht alle Teams
        dieser Abteilung."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ma.abteilung_id
                FROM mitglied m
                JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id
                    AND mm.deleted_at IS NULL AND mm.rolle = ANY(%(vroll)s)
                    AND mm.von <= %(tag)s AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                JOIN mannschaft ma ON ma.id = mm.mannschaft_id AND ma.deleted_at IS NULL
                WHERE m.user_id = %(uid)s AND m.deleted_at IS NULL
                  AND ma.abteilung_id IS NOT NULL
                """,
                {"uid": user_id, "tag": tag, "vroll": list(VERWALTEN_ROLLEN)},
            )
            return {r['abteilung_id'] for r in cur.fetchall()}

    def kader_verwalten_mannschaften(self, user_id: int,
                                     stichtag: Optional[str] = None) -> set[int]:
        """Mannschafts-IDs, in denen der User am Stichtag selbst Kader-ÜL/Betreuer
        ist – dort darf er den Kader pflegen (#121, „eigener Kader")."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT mm.mannschaft_id
                FROM mitglied m
                JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id
                    AND mm.deleted_at IS NULL AND mm.rolle = ANY(%(vroll)s)
                    AND mm.von <= %(tag)s AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                WHERE m.user_id = %(uid)s AND m.deleted_at IS NULL
                """,
                {"uid": user_id, "tag": tag, "vroll": list(VERWALTEN_ROLLEN)},
            )
            return {r['mannschaft_id'] for r in cur.fetchall()}

    def create(self, m: Mannschaft, created_by: str) -> Mannschaft:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mannschaft (abteilung_id, name, saison, beschreibung,
                                        dfbnet_name, dfbnet_mannschaftsart,
                                        created_by, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (m.abteilung_id, m.name, m.saison, m.beschreibung,
                 m.dfbnet_name, m.dfbnet_mannschaftsart, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, m: Mannschaft, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mannschaft
                SET abteilung_id=%s, name=%s, saison=%s, beschreibung=%s,
                    dfbnet_name=%s, dfbnet_mannschaftsart=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (m.abteilung_id, m.name, m.saison, m.beschreibung,
                 m.dfbnet_name, m.dfbnet_mannschaftsart, updated_by, m.id, m.version),
            )
            return cur.rowcount == 1

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mannschaft
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1
                WHERE id=%s AND deleted_at IS NULL
                """,
                (deleted_by, id),
            )
            return cur.rowcount == 1

    def has_active_mitglied_references(self, mannschaft_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM mitglied_mannschaft WHERE mannschaft_id=%s AND deleted_at IS NULL LIMIT 1",
                (mannschaft_id,),
            )
            return cur.fetchone() is not None

    def list_kandidaten(self, mannschaft_id: int) -> list[dict]:
        """Mitglieder der Abteilung dieses Teams, die noch NICHT im Team sind, samt ihren
        aktuellen Teamnamen. Für das Sammel-Hinzufügen zum Kader.

        Ausgetretene bleiben draußen: Eine Kaderzuordnung gehört zur laufenden
        Vereinsmitgliedschaft, ihr Beginn darf nicht nach dem Austritt liegen
        (``mitgliedschaft.pruefe_von_in_mitgliedschaft``). Wer hier auftaucht, ohne
        hinzufügbar zu sein, produziert nur eine Fehlermeldung. Stichtag ist heute,
        wie bei der Statistik: Austritt genau heute zählt noch als Mitglied."""
        with self.cursor() as cur:
            cur.execute("SELECT abteilung_id FROM mannschaft WHERE id=%s AND deleted_at IS NULL",
                        (mannschaft_id,))
            row = cur.fetchone()
            if row is None:
                return []
            abteilung_id = row['abteilung_id']
            cur.execute(
                """
                SELECT m.id, m.vorname, m.nachname, m.geburtsdatum,
                       (SELECT array_agg(t.name ORDER BY t.name)
                          FROM mitglied_mannschaft mm JOIN mannschaft t ON t.id = mm.mannschaft_id
                          WHERE mm.mitglied_id = m.id AND mm.deleted_at IS NULL AND t.deleted_at IS NULL) AS teams
                FROM mitglied m
                WHERE m.deleted_at IS NULL
                  AND (safe_to_date(m.austrittsdatum) IS NULL
                       OR safe_to_date(m.austrittsdatum) >= CURRENT_DATE)
                  AND EXISTS (SELECT 1 FROM mitglied_abteilung ma
                               WHERE ma.mitglied_id = m.id AND ma.abteilung_id = %s AND ma.deleted_at IS NULL)
                  AND NOT EXISTS (SELECT 1 FROM mitglied_mannschaft mmx
                               WHERE mmx.mitglied_id = m.id AND mmx.mannschaft_id = %s AND mmx.deleted_at IS NULL)
                """,
                (abteilung_id, mannschaft_id),
            )
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------- DFBnet-Aliasse (#95)
    def set_aliasse(self, mannschaft_id: int, namen: list[str], actor: str) -> None:
        """Alias-Liste einer Mannschaft auf `namen` setzen (Ersetzen-Semantik).

        Entfernte Aliasse werden soft-gelöscht, nicht hart entfernt; ein wieder
        eingetragener Alias reaktiviert die alte Zeile nicht, sondern bekommt eine
        neue — die History bleibt dadurch lesbar.
        """
        gewuenscht = {n.strip() for n in namen if n and n.strip()}
        with self.cursor() as cur:
            cur.execute(
                "SELECT id, name FROM mannschaft_dfbnet_alias "
                "WHERE mannschaft_id = %s AND deleted_at IS NULL",
                (mannschaft_id,),
            )
            vorhanden = {r['name']: r['id'] for r in cur.fetchall()}
            for name, alias_id in vorhanden.items():
                if name not in gewuenscht:
                    cur.execute(
                        "UPDATE mannschaft_dfbnet_alias SET deleted_at = CURRENT_TIMESTAMP, "
                        "deleted_by = %s, version = version + 1 WHERE id = %s",
                        (actor, alias_id),
                    )
            for name in sorted(gewuenscht - set(vorhanden)):
                cur.execute(
                    "INSERT INTO mannschaft_dfbnet_alias (mannschaft_id, name, "
                    "created_by, updated_by) VALUES (%s, %s, %s, %s)",
                    (mannschaft_id, name, actor, actor),
                )

    def find_by_dfbnet(self, name: str,
                       mannschaftsart: Optional[str] = None) -> Optional[Mannschaft]:
        """Mannschaft zu einem DFBnet-Teamnamen – Grundlage des Spielplan-Imports.

        Exakter Vergleich (ohne Groß-/Kleinschreibung), nie per Teilstring:
        „VTB Chemnitz" steckt sonst in „VTB Chemnitz 2". Die Mannschaftsart muss
        mitpassen, sofern am Team gepflegt — derselbe Name existiert im Export
        für unterschiedliche Altersklassen. Aliasse decken Spielgemeinschaften ab
        und gelten unabhängig von der Mannschaftsart.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT m.id FROM mannschaft m
                WHERE m.deleted_at IS NULL AND m.dfbnet_name IS NOT NULL
                  AND lower(m.dfbnet_name) = lower(%(name)s)
                  AND (m.dfbnet_mannschaftsart IS NULL OR %(art)s::text IS NULL
                       OR lower(m.dfbnet_mannschaftsart) = lower(%(art)s))
                UNION
                SELECT al.mannschaft_id FROM mannschaft_dfbnet_alias al
                JOIN mannschaft m2 ON m2.id = al.mannschaft_id AND m2.deleted_at IS NULL
                WHERE al.deleted_at IS NULL AND lower(al.name) = lower(%(name)s)
                LIMIT 2
                """,
                {"name": name, "art": mannschaftsart},
            )
            treffer = cur.fetchall()
        if len(treffer) != 1:      # 0 = unbekannt, >1 = mehrdeutig -> Importbericht
            return None
        return self.get(treffer[0]['id'])
