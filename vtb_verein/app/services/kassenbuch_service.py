'''
Kassenbuch Service – Business-Logik für das Kassenbuch.

@author: AI Assistant
'''

import csv
import io
from datetime import date
from app.models.kasse import Kasse, Kassenbuchung, KassenbuchExport
from app.db.kasse_repository import KasseRepository
from app.db.kassenbuchung_repository import KassenbuchungRepository
from app.db.kassenbuch_export_repository import KassenbuchExportRepository


class BuchungGesperrtError(Exception):
    """Wird geworfen wenn eine exportierte Buchung geändert oder storniert werden soll."""
    pass


class NegativerBestandError(Exception):
    """Wird geworfen wenn eine Buchung zu einem negativen Kassenbestand führen würde."""
    pass


class KassenbuchService:
    """Service für alle Kassenbuch-Operationen.

    Enthält:
    - Buchungssperre (Export-Schutz)
    - Bestandsprüfung (kein negativer Bestand)
    - Belegnummer-Generierung
    - Export-Logik (CSV)
    - Kassenbericht-Daten für PDF
    """

    def __init__(
        self,
        kasse_repo: KasseRepository,
        buchung_repo: KassenbuchungRepository,
        export_repo: KassenbuchExportRepository,
    ):
        self._kasse = kasse_repo
        self._buchung = buchung_repo
        self._export = export_repo

    # -----------------------------------
    # Kassen-Verwaltung
    # -----------------------------------

    def create_kasse(self, kasse: Kasse, created_by: str) -> Kasse:
        return self._kasse.create_kasse(kasse, created_by)

    def update_kasse(self, kasse: Kasse, updated_by: str) -> bool:
        return self._kasse.update_kasse(kasse, updated_by)

    def delete_kasse(self, kasse_id: int, deleted_by: str) -> bool:
        """Soft-Delete einer Kasse.

        Raises:
            ValueError: Wenn noch aktive Buchungen existieren.
        """
        buchungen = self._buchung.list_kassenbuchungen(kasse_id, include_storniert=False)
        if buchungen:
            raise ValueError(
                f"Kasse {kasse_id} hat noch {len(buchungen)} aktive Buchungen und kann nicht gelöscht werden."
            )
        return self._kasse.mark_kasse_deleted(kasse_id, deleted_by)

    # -----------------------------------
    # Buchungs-Verwaltung
    # -----------------------------------

    def create_buchung(
        self, buchung: Kassenbuchung, created_by: str
    ) -> Kassenbuchung:
        """Erstellt eine neue Buchung inkl. Bestandsprüfung und Belegnummer.

        Raises:
            NegativerBestandError: Wenn die Buchung zu einem negativen Bestand führen würde.
        """
        # Belegnummer automatisch vergeben
        jahr = int(buchung.buchungsdatum[:4])
        buchung.belegnummer = self._buchung.get_naechste_belegnummer(buchung.kasse_id, jahr)

        # Bestandsprüfung: aktueller Bestand - neue Ausgabe >= 0
        if buchung.ausgabe_cent > 0:
            aktuell = self._kasse.get_bestand_cent(buchung.kasse_id)
            if aktuell - buchung.ausgabe_cent < 0:
                raise NegativerBestandError(
                    f"Ausgabe von {buchung.ausgabe_cent / 100:.2f} € würde zu negativem Bestand führen. "
                    f"Aktueller Bestand: {aktuell / 100:.2f} €"
                )

        return self._buchung.create_kassenbuchung(buchung, created_by)

    def update_buchung(
        self, buchung: Kassenbuchung, updated_by: str
    ) -> bool:
        """Aktualisiert eine Buchung.

        Raises:
            BuchungGesperrtError: Wenn die Buchung bereits exportiert wurde.
            NegativerBestandError: Wenn die Änderung zu einem negativen Bestand führen würde.
        """
        self._pruefe_nicht_gesperrt(buchung.id)

        # Bestandsprüfung: simulierter Bestand nach Update
        if buchung.ausgabe_cent > 0:
            # Aktuellen Bestand ohne diese Buchung berechnen
            alte_buchung = self._buchung.get_kassenbuchung(buchung.id)
            bestand_ohne = (
                self._kasse.get_bestand_cent(buchung.kasse_id)
                + alte_buchung.ausgabe_cent
                - alte_buchung.einnahme_cent
            )
            neuer_bestand = bestand_ohne + buchung.einnahme_cent - buchung.ausgabe_cent
            if neuer_bestand < 0:
                raise NegativerBestandError(
                    f"Geänderter Betrag würde zu negativem Bestand führen."
                )

        return self._buchung.update_kassenbuchung(buchung, updated_by)

    def storniere_buchung(self, buchung_id: int, deleted_by: str) -> bool:
        """Storniert (Soft-Delete) eine Buchung.

        Raises:
            BuchungGesperrtError: Wenn die Buchung bereits exportiert wurde.
        """
        self._pruefe_nicht_gesperrt(buchung_id)
        return self._buchung.mark_kassenbuchung_deleted(buchung_id, deleted_by)

    def _pruefe_nicht_gesperrt(self, buchung_id: int) -> None:
        """Wirft BuchungGesperrtError wenn Buchung exportiert ist."""
        if self._export.ist_buchung_gesperrt(buchung_id):
            raise BuchungGesperrtError(
                f"Buchung {buchung_id} wurde bereits exportiert und kann nicht mehr geändert werden."
            )

    # -----------------------------------
    # Export (CSV, sperrend)
    # -----------------------------------

    def exportiere_csv(
        self,
        kasse_id: int,
        bis_datum: str,
        exported_by: str,
    ) -> tuple[str, bytes]:
        """Exportiert alle nicht-exportierten Buchungen bis bis_datum als CSV.

        Die exportierten Buchungen werden danach gesperrt.

        Returns:
            Tuple (dateiname, csv_bytes)
        """
        buchungen = self._export.get_nicht_exportierte_buchungen(kasse_id, bis_datum)
        if not buchungen:
            raise ValueError("Keine exportierbaren Buchungen im angegebenen Zeitraum.")

        kasse = self._kasse.get_kasse(kasse_id)
        dateiname = f"kasse-{kasse.name.lower().replace(' ', '-')}-bis-{bis_datum}.csv"

        # CSV erstellen
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["Belegnummer", "Datum", "Text", "Kategorie",
                        "Einnahme (EUR)", "Ausgabe (EUR)"],
        )
        writer.writeheader()
        for b in buchungen:
            writer.writerow({
                "Belegnummer": b["belegnummer"],
                "Datum": b["buchungsdatum"],
                "Text": b["buchungstext"],
                "Kategorie": b["kategorie"],
                "Einnahme (EUR)": f"{b['einnahme_cent'] / 100:.2f}" if b["einnahme_cent"] else "",
                "Ausgabe (EUR)": f"{b['ausgabe_cent'] / 100:.2f}" if b["ausgabe_cent"] else "",
            })

        csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM für Excel

        # Export-Datensatz anlegen
        von_datum = buchungen[0]["buchungsdatum"]
        export = KassenbuchExport(
            kasse_id=kasse_id,
            zeitraum_von=von_datum,
            zeitraum_bis=bis_datum,
            dateiname=dateiname,
            anzahl_buchungen=len(buchungen),
        )
        gespeicherter_export = self._export.create_export(export, exported_by)

        # Buchungen sperren
        buchung_ids = [b["id"] for b in buchungen]
        self._buchung.mark_buchungen_exportiert(buchung_ids, gespeicherter_export.id)

        return dateiname, csv_bytes

    # -----------------------------------
    # Kassenbericht-Daten (für PDF)
    # -----------------------------------

    def get_kassenbericht_daten(
        self,
        kasse_id: int,
        von_datum: str,
        bis_datum: str,
        include_storniert: bool = False,
    ) -> dict:
        """Gibt alle Daten für den PDF-Kassenbericht zurück.

        Berechnet:
        - Anfangsbestand zum von_datum (Vortag)
        - Buchungen im Zeitraum mit laufendem Bestand
        - Endbestand
        - Summen nach Kategorie

        Der Bericht ist NICHT sperrend – er kann jederzeit neu erstellt werden.
        """
        kasse = self._kasse.get_kasse(kasse_id)

        # Anfangsbestand: Bestand am Tag VOR von_datum
        vortag = str(date.fromisoformat(von_datum).replace(day=1))
        # Bestand bis Ende des Vortages
        from datetime import timedelta
        vortag = str(date.fromisoformat(von_datum) - timedelta(days=1))
        anfangsbestand_cent = self._kasse.get_bestand_zum_datum_cent(kasse_id, vortag)

        buchungen = self._buchung.list_kassenbuchungen(
            kasse_id, von_datum, bis_datum, include_storniert=include_storniert
        )

        # Laufenden Bestand berechnen
        laufender_bestand = anfangsbestand_cent
        buchungen_mit_bestand = []
        for b in buchungen:
            laufender_bestand += b.einnahme_cent - b.ausgabe_cent
            buchungen_mit_bestand.append({
                "buchung": b,
                "bestand_cent": laufender_bestand,
            })

        # Kategorien-Summen
        kategorien: dict[str, dict] = {}
        for b in buchungen:
            if b.ist_storniert:
                continue
            k = b.kategorie
            if k not in kategorien:
                kategorien[k] = {"einnahmen_cent": 0, "ausgaben_cent": 0}
            kategorien[k]["einnahmen_cent"] += b.einnahme_cent
            kategorien[k]["ausgaben_cent"] += b.ausgabe_cent

        return {
            "kasse": kasse,
            "von_datum": von_datum,
            "bis_datum": bis_datum,
            "erstellt_am": date.today().isoformat(),
            "anfangsbestand_cent": anfangsbestand_cent,
            "endbestand_cent": laufender_bestand,
            "buchungen": buchungen_mit_bestand,
            "kategorien": kategorien,
        }
