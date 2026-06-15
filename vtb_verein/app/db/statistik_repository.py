'''
StatistikRepository – aggregierte Kennzahlen für das Berichte-/Statistik-Dashboard.

Liefert ausschließlich lesende Aggregat-Abfragen (keine personenbezogenen
Einzeldaten). Datumsfelder (geburtsdatum/eintrittsdatum/austrittsdatum) sind im
Schema TEXT im ISO-Format 'YYYY-MM-DD'. Wo gerechnet wird, läuft der Cast über
die DB-Funktion `safe_to_date()` (Migration v39), die leere/ungültige Werte –
auch format-gültige Unmöglichkeiten wie '2026-02-30' – als NULL liefert statt
die Query abzubrechen. Reine Jahres-/Monats-Buckets nutzen LEFT()+Regex-Guard.

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
                        date_part('year', age(safe_to_date(geburtsdatum)))
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

    def mitglieder_entwicklung(self, granularitaet: str = "jahr", anzahl: int = 12) -> list[dict]:
        """Zu- und Abgänge je Periode für die letzten `anzahl` Perioden.

        granularitaet='jahr'  → Kalenderjahre, periode 'YYYY'
        granularitaet='monat' → Monate,        periode 'YYYY-MM'

        Leere/ungültige Datumsfelder werden per Regex-Guard ausgeklammert;
        die Periodenliste begrenzt das Fenster (zukünftige Daten fallen raus).
        """
        if granularitaet == "monat":
            laenge, guard = 7, r"^\d{4}-\d{2}$"
            perioden = self._letzte_monate(anzahl)
        else:
            laenge, guard = 4, r"^\d{4}$"
            perioden = self._letzte_jahre(anzahl)
        von = perioden[0]

        def _zaehle(spalte: str) -> dict[str, int]:
            # `spalte` ist eine interne Konstante (kein User-Input) – kein Injection-Risiko.
            with self.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT LEFT({spalte}, %(laenge)s) AS periode, COUNT(*) AS anzahl
                    FROM mitglied
                    WHERE deleted_at IS NULL
                      AND LEFT({spalte}, %(laenge)s) ~ %(guard)s
                      AND LEFT({spalte}, %(laenge)s) >= %(von)s
                    GROUP BY LEFT({spalte}, %(laenge)s)
                    """,
                    {"laenge": laenge, "guard": guard, "von": von},
                )
                return {r["periode"]: int(r["anzahl"]) for r in cur.fetchall()}

        eintritte = _zaehle("eintrittsdatum")
        austritte = _zaehle("austrittsdatum")
        return [
            {
                "periode":   p,
                "eintritte": eintritte.get(p, 0),
                "austritte": austritte.get(p, 0),
                "saldo":     eintritte.get(p, 0) - austritte.get(p, 0),
            }
            for p in perioden
        ]

    @staticmethod
    def _letzte_jahre(anzahl: int) -> list[str]:
        """Die letzten `anzahl` Kalenderjahre als 'YYYY', aufsteigend."""
        bis = date.today().year
        return [str(bis - i) for i in range(anzahl - 1, -1, -1)]

    @staticmethod
    def _letzte_monate(anzahl: int) -> list[str]:
        """Die letzten `anzahl` Monate als 'YYYY-MM', aufsteigend (inkl. aktuellem Monat)."""
        heute = date.today()
        basis = heute.year * 12 + (heute.month - 1)
        monate = []
        for i in range(anzahl - 1, -1, -1):
            jahr, monat = divmod(basis - i, 12)
            monate.append(f"{jahr:04d}-{monat + 1:02d}")
        return monate

    def altersstruktur(self) -> list[dict]:
        """Altersgruppen der nicht ausgetretenen Mitglieder mit hinterlegtem Geburtsdatum."""
        with self.cursor() as cur:
            cur.execute(
                r"""
                WITH alter_cte AS (
                    SELECT date_part('year', age(safe_to_date(geburtsdatum))) AS jahre
                    FROM mitglied
                    WHERE deleted_at IS NULL
                      AND status <> 'ausgetreten'
                      AND safe_to_date(geburtsdatum) IS NOT NULL
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
