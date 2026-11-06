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
from app.db.statistik_repository import _NUR_MITGLIEDER, _STICHTAG, _bestand, _laeuft_am

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
