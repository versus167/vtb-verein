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
from app.db.statistik_repository import _NUR_MITGLIEDER, _STICHTAG, _bestand


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
