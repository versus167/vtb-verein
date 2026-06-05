"""
GebuehrenService – einmalige Gebühren-Forderungen anlegen und einziehen.

Analog zum BeitragsService: bei zahler_typ='abteilung' wird eine Ausgaben-Umbuchung
in der Abteilungskasse erzeugt; bei zahler_typ='mitglied' erfolgt der Einzug per SEPA
(Export offener Forderungen).
"""
from datetime import date

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
        forderung = self.db.create_gebuehr_forderung(f, erstellt_von)

        # Bei Abteilungs-Zahler: Ausgabe-Umbuchung in der Abteilungskasse anlegen
        if gebuehr.zahler_typ == 'abteilung' and gebuehr.zahler_kasse_id:
            buchung_id = self._erstelle_umbuchung(gebuehr.zahler_kasse_id, forderung, erstellt_von)
            self.db.set_gebuehr_forderung_kassenbuchung(forderung.id, buchung_id, erstellt_von)
            forderung = self.db.get_gebuehr_forderung(forderung.id)

        return forderung

    def _erstelle_umbuchung(self, kasse_id: int, forderung: GebuehrForderung,
                            erstellt_von: str) -> int:
        from app.models.kasse import Kassenbuchung
        name = f"{forderung.mitglied_vorname or ''} {forderung.mitglied_nachname or ''}".strip()
        kb = Kassenbuchung(
            kasse_id=kasse_id,
            buchungsdatum=date.today().isoformat(),
            buchungstext=f"{forderung.gebuehr_name or 'Gebühr'} {name}".strip(),
            kategorie="Gebühren",
            einnahme_cent=0,
            ausgabe_cent=round(forderung.betrag_soll * 100),
            notiz=f"Automatisch erzeugte Umbuchung für Gebühren-Forderung #{forderung.id}",
        )
        buchung = self.db.kassenbuch.create_buchung(kb, created_by=erstellt_von)
        return buchung.id
