"""
GebuehrenService – einmalige Gebühren-Forderungen anlegen und einziehen.

Beiträge/Gebühren werden nie auf Kassen gebucht; zahler_typ='abteilung' ist lediglich
die Zahler-Zuordnung. Einzug per SEPA (Export offener Forderungen).
"""
from app.models.gebuehr import GebuehrForderung


class GebuehrenService:

    def __init__(self, db):
        self.db = db

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
