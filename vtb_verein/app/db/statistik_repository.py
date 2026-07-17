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

# Die 12-Monats-Entwicklung blickt bewusst 3 Monate in die Zukunft (Ticket #56):
# vorerfasste Ein-/Austritte (Kündigung zum Quartals-/Jahresende, geplanter Eintritt)
# sollen sichtbar sein. Fenster damit: aktueller Monat -8 … +3 (weiterhin 12 Monate).
_MONATS_VORLAUF = 3

# "aktuell aktiv": Status aktiv UND Austritt nicht abgelaufen (am Austrittstag noch
# Mitglied → >= CURRENT_DATE). Mitglieder mit künftigem Eintritt bleiben hier drin.
_AKTIV = (
    "m.status = 'aktiv' "
    "AND (safe_to_date(m.austrittsdatum) IS NULL "
    "     OR safe_to_date(m.austrittsdatum) >= CURRENT_DATE)"
)
# "zählt zum Bestand": aktueller Mitgliederstand zum Anzeigetag (heute) – wer HEUTE
# Mitglied ist. Eintritt nicht in der Zukunft (am Eintrittstag schon dabei) UND Austritt
# nicht in der Vergangenheit (am Austrittstag noch dabei → >= CURRENT_DATE). Fehlende/
# ungültige Datumsfelder = dabei. Rein datumsbasiert (Status egal): wer laut Datum schon
# ausgetreten ist, fällt raus – auch wenn der Status noch 'aktiv' steht; wer als
# 'ausgetreten' geführt wird, aber erst künftig geht, ist heute noch dabei.
_BESTAND = (
    "(safe_to_date(m.eintrittsdatum) IS NULL "
    " OR safe_to_date(m.eintrittsdatum) <= CURRENT_DATE) "
    "AND (safe_to_date(m.austrittsdatum) IS NULL "
    "     OR safe_to_date(m.austrittsdatum) >= CURRENT_DATE)"
)
# Gastspieler (art='gastspieler', Schema v72) sind keine Vereinsmitglieder und
# bleiben aus sämtlichen Mitglieder-Kennzahlen draußen.
_NUR_MITGLIEDER = "m.art = 'mitglied'"


class StatistikRepository(BaseRepository):
    """Aggregierte Vereins-Kennzahlen für Berichte."""

    def _scope(self, abteilung_id: int | None):
        """Geltungsbereich der mitgliederbasierten Aggregate.

        Verein (``abteilung_id`` None) → ganze Mitglied-Tabelle, Vereins-Datumsfelder.
        Abteilung → JOIN auf die aktive Zuordnung; Eintritt/Austritt nehmen das
        Abteilungsdatum (``von``/``bis``) und fallen sonst auf das Vereinsdatum
        zurück (``bis`` ist in den Bestandsdaten kaum gepflegt).

        Liefert ``(join_sql, eintritt_expr, austritt_expr, params)``; die Mitglied-
        Tabelle ist in allen Queries als ``m`` aliasiert.
        """
        if abteilung_id is None:
            return "", "m.eintrittsdatum", "m.austrittsdatum", {}
        join = (
            "JOIN mitglied_abteilung ma "
            "ON ma.mitglied_id = m.id AND ma.abteilung_id = %(aid)s "
            "AND ma.deleted_at IS NULL AND ma.status = 'aktiv'"
        )
        return (
            join,
            "COALESCE(NULLIF(ma.von, ''), m.eintrittsdatum)",
            "COALESCE(NULLIF(ma.bis, ''), m.austrittsdatum)",
            {"aid": abteilung_id},
        )

    def kpis(self, abteilung_id: int | None = None) -> dict:
        """Eckdaten: Mitglieder nach Status, Zu-/Abgänge im laufenden Jahr, Ø-Alter.

        ``gesamt`` = aktueller Mitgliederstand heute (weder Zukunfts-Eintritte noch bereits
        Ausgetretene, s. ``_BESTAND``), ``aktiv`` = aktuell aktiv (Status aktiv, Austritt
        nicht abgelaufen, künftige Eintritte zählen mit, s. ``_AKTIV``). Damit kann ``gesamt``
        ≥ ``aktiv`` sein (z. B. gekündigte Mitglieder, die erst künftig gehen), und in
        seltenen Fällen ``aktiv`` > ``gesamt`` (künftiger Eintritt: schon aktiv, aber heute
        noch kein Bestand). Mit ``abteilung_id`` auf diese Abteilung beschränkt;
        Eintritte/Austritte zählen dann über das Abteilungsdatum (s. ``_scope``).
        """
        jahr = date.today().year
        join, ein, aus, params = self._scope(abteilung_id)
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE {_BESTAND})                    AS gesamt,
                    COUNT(*) FILTER (WHERE {_AKTIV})                      AS aktiv,
                    COUNT(*) FILTER (WHERE m.status = 'passiv')           AS passiv,
                    COUNT(*) FILTER (WHERE m.status = 'inaktiv')          AS inaktiv,
                    COUNT(*) FILTER (WHERE m.status = 'ausgetreten')      AS ausgetreten,
                    COUNT(*) FILTER (
                        WHERE LEFT(({ein}), 4) = %(jahr)s
                    )                                                     AS eintritte_jahr,
                    COUNT(*) FILTER (
                        WHERE LEFT(({aus}), 4) = %(jahr)s
                    )                                                     AS austritte_jahr,
                    ROUND(AVG(
                        date_part('year', age(safe_to_date(m.geburtsdatum)))
                    ))                                                    AS durchschnittsalter
                FROM mitglied m
                {join}
                WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                """,
                {**params, "jahr": str(jahr)},
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

    def mitglieder_entwicklung(self, granularitaet: str = "jahr", anzahl: int = 12,
                               abteilung_id: int | None = None) -> list[dict]:
        """Zu- und Abgänge je Periode.

        granularitaet='jahr'  → die letzten `anzahl` Kalenderjahre, periode 'YYYY'
        granularitaet='monat' → `anzahl` Monate, periode 'YYYY-MM'; das Fenster reicht
                                 ``_MONATS_VORLAUF`` Monate in die Zukunft (aktuell -8 … +3).

        Mit ``abteilung_id`` zählen Ein-/Austritte über das Abteilungsdatum
        (``von``/``bis``) mit Fallback auf das Vereinsdatum (s. ``_scope``).
        Leere/ungültige Datumsfelder werden per Regex-Guard ausgeklammert; die
        Periodenliste begrenzt das Fenster (Daten außerhalb fallen raus).
        """
        if granularitaet == "monat":
            laenge, guard = 7, r"^\d{4}-\d{2}$"
            perioden = self._monatsfenster(anzahl, _MONATS_VORLAUF)
        else:
            laenge, guard = 4, r"^\d{4}$"
            perioden = self._letzte_jahre(anzahl)
        von = perioden[0]
        join, ein, aus, scope_params = self._scope(abteilung_id)

        def _zaehle(datum_expr: str) -> dict[str, int]:
            with self.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT LEFT(({datum_expr}), %(laenge)s) AS periode, COUNT(*) AS anzahl
                    FROM mitglied m
                    {join}
                    WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                      AND LEFT(({datum_expr}), %(laenge)s) ~ %(guard)s
                      AND LEFT(({datum_expr}), %(laenge)s) >= %(von)s
                    GROUP BY LEFT(({datum_expr}), %(laenge)s)
                    """,
                    {**scope_params, "laenge": laenge, "guard": guard, "von": von},
                )
                return {r["periode"]: int(r["anzahl"]) for r in cur.fetchall()}

        eintritte = _zaehle(ein)
        austritte = _zaehle(aus)
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
    def _monatsfenster(anzahl: int, vorlauf: int = 0) -> list[str]:
        """`anzahl` Monate als 'YYYY-MM', aufsteigend; das Fenster endet `vorlauf`
        Monate in der Zukunft (vorlauf=0 → bis einschließlich aktuellem Monat).

        Beispiel: anzahl=12, vorlauf=3 → aktueller Monat -8 … +3.
        """
        heute = date.today()
        basis = heute.year * 12 + (heute.month - 1) + vorlauf
        monate = []
        for i in range(anzahl - 1, -1, -1):
            jahr, monat = divmod(basis - i, 12)
            monate.append(f"{jahr:04d}-{monat + 1:02d}")
        return monate

    def altersstruktur(self, abteilung_id: int | None = None) -> list[dict]:
        """Altersgruppen der aktuell aktiven Mitglieder mit hinterlegtem Geburtsdatum."""
        join, _ein, _aus, params = self._scope(abteilung_id)
        with self.cursor() as cur:
            cur.execute(
                f"""
                WITH alter_cte AS (
                    SELECT date_part('year', age(safe_to_date(m.geburtsdatum))) AS jahre
                    FROM mitglied m
                    {join}
                    WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                      AND {_AKTIV}
                      AND safe_to_date(m.geburtsdatum) IS NOT NULL
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
                """,
                params,
            )
            rows = {r["gruppe"]: int(r["anzahl"]) for r in cur.fetchall()}
        ordnung = ["0–17", "18–26", "27–40", "41–60", "61+"]
        return [{"gruppe": g, "anzahl": rows.get(g, 0)} for g in ordnung]

    def geschlechterverteilung(self, abteilung_id: int | None = None) -> list[dict]:
        """Verteilung nach Geschlecht der aktuell aktiven Mitglieder."""
        labels = {"m": "männlich", "w": "weiblich", "d": "divers"}
        join, _ein, _aus, params = self._scope(abteilung_id)
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT COALESCE(NULLIF(m.geschlecht, ''), '?') AS geschlecht, COUNT(*) AS anzahl
                FROM mitglied m
                {join}
                WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER} AND {_AKTIV}
                GROUP BY COALESCE(NULLIF(m.geschlecht, ''), '?')
                """,
                params,
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
                f"""
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
                      AND {_NUR_MITGLIEDER}
                WHERE a.deleted_at IS NULL
                GROUP BY a.id, a.name
                ORDER BY anzahl DESC, a.name
                """
            )
            return [
                {"abteilung_id": r["id"], "name": r["name"], "anzahl": int(r["anzahl"] or 0)}
                for r in cur.fetchall()
            ]
