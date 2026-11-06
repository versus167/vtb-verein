'''
BerichtslistenRepository – Namenslisten für den Bereich „Berichte" (#155).

Gegenstück zum StatistikRepository: Dort stehen bewusst nur Aggregate, hier die
Listen mit Personen (Lücken zur LSB-Meldung, Ehrungen, Übungsleiter). Die API
zeigt sie deshalb nur mit ``personen.read`` und filtert sie nach dem
Abteilungs-Scope; darum liefert jede Zeile ihre ``mitglied_id``.

Wer zum Bestand zählt, entscheidet dieselbe Regel wie in der Statistik – sonst
nennte die Lückenliste andere Leute, als die Meldung zählt.
'''

from datetime import date

from app.db.base_repository import BaseRepository
from app.db.funktion_repository import UL_FUNKTIONEN
from app.db.statistik_repository import (
    _BESTAND, _NUR_MITGLIEDER, _STICHTAG, _bestand, _laeuft_am,
)

# Jubiläumsstufen der Mitgliedschaft in Jahren (#155).
EHRUNG_STUFEN = (25, 40, 50, 60, 70, 75, 80)


class BerichtslistenRepository(BaseRepository):
    """Personenbezogene Listen für Berichte."""

    def fehlende_meldeangaben(self, stichtag: date) -> list[dict]:
        """Mitglieder im Bestand am ``stichtag`` ohne gültiges Geburtsdatum oder
        Geschlecht – genau die, die in der LSB-Meldung unter „ohne Angabe" stehen."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT m.id AS mitglied_id, m.mitgliedsnummer, m.vorname, m.nachname,
                       safe_to_date(m.geburtsdatum) IS NULL AS ohne_geburtsdatum,
                       COALESCE(m.geschlecht, '') NOT IN ('m', 'w', 'd') AS ohne_geschlecht
                FROM mitglied m
                WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                  AND {_bestand(_STICHTAG)}
                  AND (safe_to_date(m.geburtsdatum) IS NULL
                       OR COALESCE(m.geschlecht, '') NOT IN ('m', 'w', 'd'))
                ORDER BY m.nachname, m.vorname
                """,
                {"stichtag": stichtag.isoformat()},
            )
            return [dict(r) for r in cur.fetchall()]

    def ehrungen(self, stichtag: date, stufen=EHRUNG_STUFEN) -> list[dict]:
        """Wer im Jahr des ``stichtag`` für seine Mitgliedsdauer geehrt wird.

        Dabei ist, wer eine Stufe bis zum Stichtag erreicht, sie aber zum Stichtag
        des Vorjahres noch nicht hatte – so fällt jedes Jubiläum in genau ein
        Ehrungsjahr. Beispiel Stichtag 31.3.2027, 40 Jahre: Eintritt 1.4.1986 bis
        31.3.1987. Grundlage ist das Eintrittsdatum; wer am Stichtag nicht mehr
        Mitglied ist, fehlt. ``abteilungen`` sind die am Stichtag laufenden
        Zuordnungen, passive eingeschlossen.
        """
        jahre_am = "date_part('year', age({tag}, safe_to_date(m.eintrittsdatum)))::int"
        jahre = jahre_am.format(tag=_STICHTAG)
        jahre_vorjahr = jahre_am.format(tag=f"({_STICHTAG} - interval '1 year')")
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT m.id AS mitglied_id, m.mitgliedsnummer, m.vorname, m.nachname,
                       m.eintrittsdatum, {jahre} AS jahre,
                       (SELECT string_agg(DISTINCT a.name, ', ' ORDER BY a.name)
                        FROM mitglied_abteilung ma
                        JOIN abteilung a ON a.id = ma.abteilung_id AND a.deleted_at IS NULL
                        WHERE ma.mitglied_id = m.id AND ma.deleted_at IS NULL
                          AND {_laeuft_am('ma', _STICHTAG)}) AS abteilungen
                FROM mitglied m
                WHERE m.deleted_at IS NULL AND {_NUR_MITGLIEDER}
                  AND {_bestand(_STICHTAG)}
                  AND safe_to_date(m.eintrittsdatum) IS NOT NULL
                  AND {jahre} = ANY(%(stufen)s)
                  AND {jahre_vorjahr} < {jahre}
                ORDER BY jahre DESC, m.nachname, m.vorname
                """,
                {"stichtag": stichtag.isoformat(), "stufen": list(stufen)},
            )
            return [dict(r) for r in cur.fetchall()]

    def uebungsleiter(self) -> list[dict]:
        """Wer heute eine ÜL-Funktion hat, mit Lizenzdaten und Abteilung (#155).

        Abteilung ist die der Mannschaften, in deren Kader die Person heute als ÜL
        steht, und wenn es keine gibt, ihre Abteilungs-Zuordnung (``abteilung_quelle``
        sagt, woher). An der ÜL-Funktion selbst ist die Abteilung kaum gepflegt.

        ``lizenz`` = die Lizenz gilt heute. ``funktion_mit_lizenz`` = als „Übungsleiter
        mit Lizenz" geführt – fehlt dann die gültige Lizenz, ist das ein Pflegefall.
        """
        abteilungen_von = (
            "(SELECT string_agg(DISTINCT a.name, ', ' ORDER BY a.name) "
            " FROM {quelle} "
            " JOIN abteilung a ON a.id = {abteilung} AND a.deleted_at IS NULL "
            " WHERE {bedingung})"
        )
        mannschaft = abteilungen_von.format(
            quelle="mitglied_mannschaft mm "
                   "JOIN mannschaft t ON t.id = mm.mannschaft_id AND t.deleted_at IS NULL",
            abteilung="t.abteilung_id",
            bedingung="mm.mitglied_id = m.id AND mm.deleted_at IS NULL "
                      f"AND mm.rolle = 'uebungsleiter' AND {_laeuft_am('mm')}",
        )
        zuordnung = abteilungen_von.format(
            quelle="mitglied_abteilung ma",
            abteilung="ma.abteilung_id",
            bedingung=f"ma.mitglied_id = m.id AND ma.deleted_at IS NULL AND {_laeuft_am('ma')}",
        )
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT m.id AS mitglied_id, m.mitgliedsnummer, m.vorname, m.nachname,
                       m.geschlecht, m.trainerlizenz_nr, m.trainerlizenz_gueltig_von,
                       m.trainerlizenz_gueltig_bis,
                       COALESCE(safe_to_date(m.trainerlizenz_gueltig_von) <= CURRENT_DATE
                                AND safe_to_date(m.trainerlizenz_gueltig_bis) >= CURRENT_DATE,
                                FALSE) AS lizenz,
                       EXISTS (SELECT 1 FROM mitglied_funktion mf_l
                               WHERE mf_l.mitglied_id = m.id AND mf_l.deleted_at IS NULL
                                 AND mf_l.funktion = 'uebungsleiter_lizenz'
                                 AND {_laeuft_am('mf_l')}) AS funktion_mit_lizenz,
                       {mannschaft} AS abteilungen_mannschaft,
                       {zuordnung} AS abteilungen_zuordnung
                FROM mitglied m
                WHERE m.deleted_at IS NULL AND {_BESTAND}
                  AND EXISTS (SELECT 1 FROM mitglied_funktion mf
                              WHERE mf.mitglied_id = m.id AND mf.deleted_at IS NULL
                                AND mf.funktion = ANY(%(funktionen)s)
                                AND {_laeuft_am('mf')})
                ORDER BY m.nachname, m.vorname
                """,
                {"funktionen": list(UL_FUNKTIONEN)},
            )
            zeilen = []
            for r in cur.fetchall():
                z = dict(r)
                von_mannschaft = z.pop("abteilungen_mannschaft")
                von_zuordnung = z.pop("abteilungen_zuordnung")
                z["abteilungen"] = von_mannschaft or von_zuordnung
                z["abteilung_quelle"] = ("mannschaft" if von_mannschaft
                                         else "zuordnung" if von_zuordnung else None)
                zeilen.append(z)
            return zeilen
