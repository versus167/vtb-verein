'''
StatistikRepository – aggregierte Kennzahlen für das Berichte-/Statistik-Dashboard.

Liefert ausschließlich lesende Aggregat-Abfragen (keine personenbezogenen
Einzeldaten). Datumsfelder (geburtsdatum/eintrittsdatum/austrittsdatum) sind im
Schema TEXT im ISO-Format 'YYYY-MM-DD'; leere Strings werden vor dem Cast per
NULLIF abgefangen.

Bewusst OHNE Zahlungsstatus-Auswertung (siehe TODO/Branch feature/statistik-dashboard).
'''

from datetime import date

from app.db.base_repository import BaseRepository


class StatistikRepository(BaseRepository):
    """Aggregierte Vereins-Kennzahlen für Berichte."""

    def kpis(self) -> dict:
        """Eckdaten: Mitglieder nach Status, Zu-/Abgänge im laufenden Jahr, Ø-Alter."""
        jahr = date.today().year
        with self.cursor() as cur:
            cur.execute(
                r"""
                SELECT
                    COUNT(*)                                              AS gesamt,
                    COUNT(*) FILTER (WHERE status = 'aktiv')              AS aktiv,
                    COUNT(*) FILTER (WHERE status = 'passiv')             AS passiv,
                    COUNT(*) FILTER (WHERE status = 'inaktiv')            AS inaktiv,
                    COUNT(*) FILTER (WHERE status = 'ausgetreten')        AS ausgetreten,
                    COUNT(*) FILTER (
                        WHERE LEFT(eintrittsdatum, 4) = %(jahr)s
                    )                                                     AS eintritte_jahr,
                    COUNT(*) FILTER (
                        WHERE LEFT(austrittsdatum, 4) = %(jahr)s
                    )                                                     AS austritte_jahr,
                    ROUND(AVG(
                        CASE WHEN geburtsdatum ~ '^\d{4}-\d{2}-\d{2}$'
                             THEN date_part('year', age(geburtsdatum::date))
                        END
                    ))                                                    AS durchschnittsalter
                FROM mitglied
                WHERE deleted_at IS NULL
                """,
                {"jahr": str(jahr)},
            )
            row = cur.fetchone()
        return {
            "gesamt":             int(row["gesamt"] or 0),
            "aktiv":              int(row["aktiv"] or 0),
            "passiv":             int(row["passiv"] or 0),
            "inaktiv":            int(row["inaktiv"] or 0),
            "ausgetreten":        int(row["ausgetreten"] or 0),
            "eintritte_jahr":     int(row["eintritte_jahr"] or 0),
            "austritte_jahr":     int(row["austritte_jahr"] or 0),
            "durchschnittsalter": int(row["durchschnittsalter"]) if row["durchschnittsalter"] is not None else None,
            "jahr":               jahr,
        }

    def mitglieder_entwicklung(self, jahre: int = 6) -> list[dict]:
        """Zu- und Abgänge je Kalenderjahr für die letzten `jahre` Jahre."""
        bis = date.today().year
        von = bis - jahre + 1
        with self.cursor() as cur:
            cur.execute(
                r"""
                SELECT LEFT(eintrittsdatum, 4) AS jahr, COUNT(*) AS anzahl
                FROM mitglied
                WHERE deleted_at IS NULL
                  AND LEFT(eintrittsdatum, 4) ~ '^\d{4}$'
                  AND LEFT(eintrittsdatum, 4) >= %s
                GROUP BY LEFT(eintrittsdatum, 4)
                """,
                (str(von),),
            )
            eintritte = {int(r["jahr"]): int(r["anzahl"]) for r in cur.fetchall()}

            cur.execute(
                r"""
                SELECT LEFT(austrittsdatum, 4) AS jahr, COUNT(*) AS anzahl
                FROM mitglied
                WHERE deleted_at IS NULL
                  AND LEFT(austrittsdatum, 4) ~ '^\d{4}$'
                  AND LEFT(austrittsdatum, 4) >= %s
                GROUP BY LEFT(austrittsdatum, 4)
                """,
                (str(von),),
            )
            austritte = {int(r["jahr"]): int(r["anzahl"]) for r in cur.fetchall()}

        return [
            {
                "jahr":      j,
                "eintritte": eintritte.get(j, 0),
                "austritte": austritte.get(j, 0),
                "saldo":     eintritte.get(j, 0) - austritte.get(j, 0),
            }
            for j in range(von, bis + 1)
        ]

    def altersstruktur(self) -> list[dict]:
        """Altersgruppen der nicht ausgetretenen Mitglieder mit hinterlegtem Geburtsdatum."""
        with self.cursor() as cur:
            cur.execute(
                r"""
                WITH alter_cte AS (
                    SELECT date_part('year', age(geburtsdatum::date)) AS jahre
                    FROM mitglied
                    WHERE deleted_at IS NULL
                      AND status <> 'ausgetreten'
                      AND geburtsdatum ~ '^\d{4}-\d{2}-\d{2}$'
                )
                SELECT gruppe, COUNT(*) AS anzahl
                FROM (
                    SELECT CASE
                        WHEN jahre < 18 THEN '0–17'
                        WHEN jahre < 27 THEN '18–26'
                        WHEN jahre < 41 THEN '27–40'
                        WHEN jahre < 61 THEN '41–60'
                        ELSE '61+'
                    END AS gruppe
                    FROM alter_cte
                ) g
                GROUP BY gruppe
                """
            )
            rows = {r["gruppe"]: int(r["anzahl"]) for r in cur.fetchall()}
        ordnung = ["0–17", "18–26", "27–40", "41–60", "61+"]
        return [{"gruppe": g, "anzahl": rows.get(g, 0)} for g in ordnung]

    def geschlechterverteilung(self) -> list[dict]:
        """Verteilung nach Geschlecht der nicht ausgetretenen Mitglieder."""
        labels = {"m": "männlich", "w": "weiblich", "d": "divers"}
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(NULLIF(geschlecht, ''), '?') AS geschlecht, COUNT(*) AS anzahl
                FROM mitglied
                WHERE deleted_at IS NULL AND status <> 'ausgetreten'
                GROUP BY COALESCE(NULLIF(geschlecht, ''), '?')
                """
            )
            rows = {r["geschlecht"]: int(r["anzahl"]) for r in cur.fetchall()}
        result = [
            {"geschlecht": code, "label": label, "anzahl": rows.get(code, 0)}
            for code, label in labels.items()
        ]
        if rows.get("?"):
            result.append({"geschlecht": "?", "label": "ohne Angabe", "anzahl": rows["?"]})
        return result

    def abteilungsuebersicht(self) -> list[dict]:
        """Anzahl aktiver Mitglieder je Abteilung (aktive Zuordnungen)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.name, COUNT(DISTINCT m.id) AS anzahl
                FROM abteilung a
                LEFT JOIN mitglied_abteilung ma
                       ON ma.abteilung_id = a.id
                      AND ma.deleted_at IS NULL
                      AND ma.status = 'aktiv'
                LEFT JOIN mitglied m
                       ON m.id = ma.mitglied_id
                      AND m.deleted_at IS NULL
                      AND m.status <> 'ausgetreten'
                WHERE a.deleted_at IS NULL
                GROUP BY a.id, a.name
                ORDER BY anzahl DESC, a.name
                """
            )
            return [
                {"abteilung_id": r["id"], "name": r["name"], "anzahl": int(r["anzahl"] or 0)}
                for r in cur.fetchall()
            ]
