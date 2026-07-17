"""
GebuehrenService – einmalige Gebühren-Forderungen anlegen und einziehen.

Beiträge/Gebühren werden nie auf Kassen gebucht; zahler_typ='abteilung' ist lediglich
die Zahler-Zuordnung. Einzug per SEPA (Export offener Forderungen).
"""
from datetime import date

from app.models.gebuehr import Gebuehr, GebuehrForderung


def _alter_am(geburtsdatum: str | None, stichtag: str) -> int | None:
    """Alter in vollen Jahren am Stichtag; None bei fehlendem/ungültigem Datum."""
    def _iso(s):
        try:
            return date.fromisoformat(str(s)[:10])
        except (ValueError, TypeError):
            return None
    gb, st = _iso(geburtsdatum), _iso(stichtag)
    if gb is None or st is None:
        return None
    return st.year - gb.year - ((st.month, st.day) < (gb.month, gb.day))


def _alter_passt(g: Gebuehr, alter: int | None) -> bool:
    """True, wenn die Altersbedingung der Gebühr zum Alter passt. Bei gesetzter
    Bedingung und unbekanntem Alter -> False (analog Beitragsregel-Logik)."""
    if g.bedingung_alter_min is None and g.bedingung_alter_max is None:
        return True
    if alter is None:
        return False
    if g.bedingung_alter_min is not None and alter < g.bedingung_alter_min:
        return False
    if g.bedingung_alter_max is not None and alter > g.bedingung_alter_max:
        return False
    return True


class GebuehrenService:

    def __init__(self, db):
        self.db = db

    def vorschlag_aufnahmegebuehren(self, mitglied_id: int, abteilung_id: int | None,
                                    datum: str) -> list[Gebuehr]:
        """Aufnahmegebühren, die am Stichtag gelten, zur Altersbedingung passen und
        für die das Mitglied noch keine (nicht stornierte) Forderung hat – für den
        Vorschlag bei Neuanlage / Abteilungs-Neuzuordnung.

        abteilung_id None  -> Vereins-Aufnahmegebühren (abteilung_id IS NULL),
        abteilung_id gesetzt -> Aufnahmegebühren genau dieser Abteilung.
        """
        try:
            mitglied = self.db.get_mitglied(mitglied_id)
        except KeyError:
            return []
        # Gastspieler treten nicht in den Verein ein → keine Aufnahmegebühr
        # vorschlagen. (Manuelles Anlegen einer Forderung bleibt möglich.)
        if getattr(mitglied, 'art', 'mitglied') == 'gastspieler':
            return []
        alter = _alter_am(getattr(mitglied, 'geburtsdatum', None), datum)

        kandidaten = []
        for g in self.db.gebuehren.list_aktive(datum):
            if g.anlass != 'aufnahme':
                continue
            if g.abteilung_id != abteilung_id:
                continue
            if not _alter_passt(g, alter):
                continue
            if self.db.gebuehr_forderung_exists(mitglied_id, g.id):
                continue
            kandidaten.append(g)
        return kandidaten

    def create_forderung(self, mitglied_id: int, gebuehr_id: int, datum: str,
                         erstellt_von: str) -> GebuehrForderung:
        gebuehr = self.db.get_gebuehr(gebuehr_id)
        if gebuehr is None:
            raise ValueError("Gebühr nicht gefunden")
        if self.db.gebuehr_forderung_exists(mitglied_id, gebuehr_id):
            raise ValueError("Für dieses Mitglied besteht bereits eine Forderung dieser Gebühr")

        f = GebuehrForderung(
            mitglied_id=mitglied_id, gebuehr_id=gebuehr_id,
            datum=datum, betrag_soll=gebuehr.betrag,
        )
        return self.db.create_gebuehr_forderung(f, erstellt_von)
