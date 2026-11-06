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
from app.db.funktion_repository import FUNKTION_PASSIV

# Die 12-Monats-Entwicklung blickt bewusst 3 Monate in die Zukunft (Ticket #56):
# vorerfasste Ein-/Austritte (Kündigung zum Quartals-/Jahresende, geplanter Eintritt)
# sollen sichtbar sein. Fenster damit: aktueller Monat -8 … +3 (weiterhin 12 Monate).
_MONATS_VORLAUF = 3


# SQL-Ausdruck für den Stichtag der Auswertung. Das Dashboard rechnet mit heute,
# die Meldungen (#155) mit einem gewählten Tag – als Platzhalter ``%(stichtag)s``.
_HEUTE = "CURRENT_DATE"
_STICHTAG = "%(stichtag)s::date"


def _laeuft_am(alias: str, tag: str = _HEUTE) -> str:
    """Zeitfilter für eine Abteilungs-Zuordnung: am Stichtag ``tag`` gültig. Am Von-
    und am Bis-Tag selbst zählt sie mit; fehlende Daten heißen „unbefristet".

    Als Funktion, weil dieselbe Bedingung an drei Stellen gebraucht wird und sie
    an zweien schlicht gefehlt hat: Eine vor Jahren beendete Zuordnung lief in der
    Abteilungsübersicht und im Abteilungs-Scope weiter mit, weil dort nur
    `status = 'aktiv'` geprüft wurde, ein Kennzeichen ohne Datum (bis v105).
    """
    return (f"(safe_to_date({alias}.von) IS NULL "
            f"     OR safe_to_date({alias}.von) <= {tag}) "
            f"AND (safe_to_date({alias}.bis) IS NULL "
            f"     OR safe_to_date({alias}.bis) >= {tag})")


def _nicht_passiv(alias: str, tag: str = _HEUTE) -> str:
    """„Macht in dieser Abteilung aktiv mit": keine laufende `passiv`-Funktion.

    Seit v105 sagt das die Funktion und nicht mehr ein Kennzeichen an der
    Zuordnung — mit Zeitraum, den das Kennzeichen nie hatte. Eine vereinsweit
    eingetragene `passiv`-Funktion (ohne Abteilung) zählt für jede Abteilung;
    eine mit Abteilung nur für ihre eigene.
    """
    return (
        "NOT EXISTS (SELECT 1 FROM mitglied_funktion mf_p "
        f"            WHERE mf_p.mitglied_id = {alias}.mitglied_id "
        f"              AND mf_p.funktion = '{FUNKTION_PASSIV}' "
        "               AND mf_p.deleted_at IS NULL "
        f"              AND (mf_p.abteilung_id IS NULL "
        f"                   OR mf_p.abteilung_id = {alias}.abteilung_id) "
        f"              AND {_laeuft_am('mf_p', tag)})"
    )


# "aktiv in einer Abteilung": mindestens eine heute laufende Zuordnung, in der
# das Mitglied nicht passiv geführt wird. Bewusst NICHT über m.status – der wird
# weder angezeigt noch gepflegt (#173) und wäre eine Kennzahl über ein totes
# Feld. Die Abteilungs-Zuordnung dagegen wird gepflegt und hat von/bis.
def _in_abteilung(tag: str = _HEUTE) -> str:
    return (
        "EXISTS (SELECT 1 FROM mitglied_abteilung ma_a "
        "         WHERE ma_a.mitglied_id = m.id AND ma_a.deleted_at IS NULL "
        f"           AND {_laeuft_am('ma_a', tag)} "
        f"           AND {_nicht_passiv('ma_a', tag)})"
    )


_IN_ABTEILUNG = _in_abteilung()
# "zählt zum Bestand": Mitgliederstand am Stichtag (Dashboard: heute) – wer an dem
# Tag Mitglied ist. Eintritt nicht danach (am Eintrittstag schon dabei) UND Austritt
# nicht davor (am Austrittstag noch dabei → >= Stichtag). Fehlende/ungültige
# Datumsfelder = dabei. Rein datumsbasiert – der Status sagt seit v103 nur noch,
# welche FORM die Mitgliedschaft hat (aktiv/passiv), nicht ob sie besteht (#173).
def _bestand(tag: str = _HEUTE) -> str:
    return (
        "(safe_to_date(m.eintrittsdatum) IS NULL "
        f" OR safe_to_date(m.eintrittsdatum) <= {tag}) "
        "AND (safe_to_date(m.austrittsdatum) IS NULL "
        f"     OR safe_to_date(m.austrittsdatum) >= {tag})"
    )


_BESTAND = _bestand()
# Gastspieler (art='gastspieler', Schema v72) sind keine Vereinsmitglieder und
# bleiben aus sämtlichen Mitglieder-Kennzahlen draußen.
_NUR_MITGLIEDER = "m.art = 'mitglied'"

# Meldungen (#155) gruppieren nach Jahrgang × Geschlecht. Was nicht m/w/d ist oder
# fehlt, landet in „ohne" – die Zeile mit ``jahrgang`` None sammelt fehlende
# Geburtsdaten. So geht niemand still verloren; die Summe stimmt immer.
_JAHRGANG = "EXTRACT(YEAR FROM safe_to_date(m.geburtsdatum))::int"
_GESCHLECHT = ("CASE WHEN m.geschlecht IN ('m', 'w', 'd') "
               "THEN m.geschlecht ELSE 'ohne' END")
_GESCHLECHTER = ("m", "w", "d", "ohne")


def _jahrgangstabelle(rows) -> dict:
    """``(jahrgang, geschlecht, anzahl)``-Zeilen → Tabelle je Jahrgang plus Summe.

    Jahrgänge aufsteigend, „ohne Geburtsdatum" (None) zuletzt; nur Jahrgänge, die
    jemand belegt.
    """
    zeilen: dict = {}
    for r in rows:
        z = zeilen.setdefault(r["jahrgang"], {"jahrgang": r["jahrgang"],
                                               **{g: 0 for g in _GESCHLECHTER}})
        z[r["geschlecht"]] += int(r["anzahl"])
    liste = sorted(zeilen.values(),
                   key=lambda z: (z["jahrgang"] is None, z["jahrgang"] or 0))
    for z in liste:
        z["summe"] = sum(z[g] for g in _GESCHLECHTER)
    summe = {g: sum(z[g] for z in liste) for g in (*_GESCHLECHTER, "summe")}
    return {"zeilen": liste, "summe": summe}


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
            "AND ma.deleted_at IS NULL "
            f"AND {_laeuft_am('ma')} "
            f"AND {_nicht_passiv('ma')}"
        )
        return (
            join,
            "COALESCE(NULLIF(ma.von, ''), m.eintrittsdatum)",
            "COALESCE(NULLIF(ma.bis, ''), m.austrittsdatum)",
            {"aid": abteilung_id},
        )

    def kpis(self, abteilung_id: int | None = None) -> dict:
        """Eckdaten: Mitgliederstand, davon in Abteilungen aktiv, Zu-/Abgänge, Ø-Alter.

        ``gesamt`` = aktueller Mitgliederstand heute (weder Zukunfts-Eintritte noch
        bereits Ausgetretene, s. ``_BESTAND``). ``aktiv_in_abteilung`` = davon jene mit
        mindestens einer heute laufenden, aktiven Abteilungs-Zuordnung – die Differenz
        sind Mitglieder, die dem Verein angehören, aber in keiner Abteilung mitmachen
        (oder dort passiv geführt werden).

        Bewusst über die Zuordnung statt über ``m.status``: Der Vereinsstatus wird weder
        angezeigt noch gepflegt (#173); eine Kennzahl darüber sagte nur, was zuletzt
        importiert wurde. Mit ``abteilung_id`` ist die ganze Auswertung auf diese
        Abteilung beschränkt (s. ``_scope``) – dort ist ``aktiv_in_abteilung`` gleich
        ``gesamt``, weil der Scope-JOIN schon nur aktive Zuordnungen zulässt.
        """
        jahr = date.today().year
        join, ein, aus, params = self._scope(abteilung_id)
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE {_BESTAND})                    AS gesamt,
                    COUNT(*) FILTER (WHERE {_BESTAND} AND {_IN_ABTEILUNG}) AS aktiv_in_abteilung,
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
            "aktiv_in_abteilung":  int(row["aktiv_in_abteilung"] or 0),
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
                      AND {_BESTAND}
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
                WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER} AND {_BESTAND}
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
                      -- Zeitraum UND Passiv-Funktion: Beides fehlte hier, solange
                      -- nur ein Status geprüft wurde, der kein Datum kannte.
                      AND {_laeuft_am('ma')}
                      AND {_nicht_passiv('ma')}
                LEFT JOIN mitglied m
                       ON m.id = ma.mitglied_id
                      AND m.deleted_at IS NULL
                      AND {_NUR_MITGLIEDER}
                      -- Hier stand ein Ausschluss über den Status 'ausgetreten'.
                      -- Gemeint war „wer heute dabei ist" – das sagt seit v103
                      -- allein das Datum (#173), und zwar auch für Zeilen, deren
                      -- Status damals nie nachgepflegt wurde.
                      AND {_BESTAND}
                WHERE a.deleted_at IS NULL
                GROUP BY a.id, a.name
                ORDER BY anzahl DESC, a.name
                """
            )
            return [
                {"abteilung_id": r["id"], "name": r["name"], "anzahl": int(r["anzahl"] or 0)}
                for r in cur.fetchall()
            ]

    def lsb_meldung(self, stichtag: date) -> dict:
        """Bestandsmeldung an den LSB zum ``stichtag`` (#155).

        A-Meldung: jedes Vereinsmitglied einmal, auch passive und solche ohne
        Abteilung. B-Meldung: je Abteilung, wer dort am Stichtag aktiv (nicht
        passiv) zugeordnet ist – wer in zwei Abteilungen ist, zählt in beiden.
        ``ohne_abteilung`` ist keine Meldezahl, sondern die Kontrolle, warum die
        Summen von A und B auseinanderlaufen.

        Am Austrittstag zählt man noch mit (wie im Dashboard): Stichtag 31.12.
        meldet also auch, wer zum Jahresende gekündigt hat.
        """
        params = {"stichtag": stichtag.isoformat()}
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_JAHRGANG} AS jahrgang, {_GESCHLECHT} AS geschlecht,
                       COUNT(*) AS anzahl
                FROM mitglied m
                WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                  AND {_bestand(_STICHTAG)}
                GROUP BY 1, 2
                """,
                params,
            )
            a = _jahrgangstabelle(cur.fetchall())

            # DISTINCT je (Abteilung, Mitglied): Zwei überlappende Zuordnungen zur
            # selben Abteilung sind immer noch eine Person in dieser Abteilung.
            cur.execute(
                f"""
                SELECT abteilung_id, jahrgang, geschlecht, COUNT(*) AS anzahl
                FROM (
                    SELECT DISTINCT ma.abteilung_id, m.id,
                           {_JAHRGANG} AS jahrgang, {_GESCHLECHT} AS geschlecht
                    FROM mitglied_abteilung ma
                    JOIN mitglied m ON m.id = ma.mitglied_id
                    WHERE ma.deleted_at IS NULL
                      AND {_laeuft_am('ma', _STICHTAG)}
                      AND {_nicht_passiv('ma', _STICHTAG)}
                      AND m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                      AND {_bestand(_STICHTAG)}
                ) z
                GROUP BY 1, 2, 3
                """,
                params,
            )
            je_abteilung: dict[int, list] = {}
            for r in cur.fetchall():
                je_abteilung.setdefault(r["abteilung_id"], []).append(r)

            cur.execute(
                f"""
                SELECT COUNT(*) AS anzahl
                FROM mitglied m
                WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                  AND {_bestand(_STICHTAG)}
                  AND NOT {_in_abteilung(_STICHTAG)}
                """,
                params,
            )
            ohne_abteilung = int(cur.fetchone()["anzahl"] or 0)

            cur.execute("SELECT id, name FROM abteilung WHERE deleted_at IS NULL ORDER BY name")
            abteilungen = cur.fetchall()

        b = []
        for abt in abteilungen:
            tabelle = _jahrgangstabelle(je_abteilung.get(abt["id"], []))
            b.append({"abteilung_id": abt["id"], "name": abt["name"],
                      "anzahl": tabelle["summe"]["summe"], **tabelle})
        return {
            "stichtag":       stichtag.isoformat(),
            "a":              a,
            "b":              b,
            "b_summe":        sum(x["anzahl"] for x in b),
            "ohne_abteilung": ohne_abteilung,
        }

    # (Bezeichnung, Mindestalter, Höchstalter) – beide Grenzen einschließlich.
    ALTERSGRUPPEN_STICHTAG = (("unter 18", 0, 17), ("18–50", 18, 50), ("über 50", 51, None))

    def altersgruppen_am(self, stichtag: date) -> dict:
        """Mitglieder je Altersgruppe, Alter am ``stichtag`` (#155-Nachtrag).

        Wie die A-Meldung: alle Vereinsmitglieder im Bestand am Stichtag, ohne
        Gastspieler. Wer kein gültiges Geburtsdatum hat, steht unter
        ``ohne_geburtsdatum`` – so stimmt die Summe mit der A-Meldung überein.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT date_part('year', age({_STICHTAG},
                                             safe_to_date(m.geburtsdatum)))::int AS jahre
                FROM mitglied m
                WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                  AND {_bestand(_STICHTAG)}
                """,
                {"stichtag": stichtag.isoformat()},
            )
            alter = [r["jahre"] for r in cur.fetchall()]
        gruppen = [
            {"gruppe": name,
             "anzahl": sum(1 for j in alter
                           if j is not None and j >= von and (bis is None or j <= bis))}
            for name, von, bis in self.ALTERSGRUPPEN_STICHTAG
        ]
        return {
            "stichtag":          stichtag.isoformat(),
            "gruppen":           gruppen,
            "ohne_geburtsdatum": sum(1 for j in alter if j is None),
            "summe":             len(alter),
        }
