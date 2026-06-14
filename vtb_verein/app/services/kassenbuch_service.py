'''
Kassenbuch Service – Business-Logik für das Kassenbuch.

@author: AI Assistant
'''

import csv
import io
import os
from datetime import date
from app.models.kasse import Kasse, Kassenbuchung, KassenbuchExport, KassenbuchungAnhang
from app.db.kasse_repository import KasseRepository
from app.db.kassenbuchung_repository import KassenbuchungRepository
from app.db.kassenbuch_export_repository import KassenbuchExportRepository
from app.db.kasse_berechtigung_repository import KasseBerechtigungRepository
from app.db.kassenbuchung_anhang_repository import KassenbuchungAnhangRepository
from app.db.kassen_kategorie_repository import KassenKategorieRepository
from app.services.anhang_service import AnhangService, DateitypNichtErlaubtError, DateiZuGrossError


class BuchungGesperrtError(Exception):
    """Wird geworfen wenn eine exportierte Buchung geändert oder storniert werden soll."""
    pass


class NegativerBestandError(Exception):
    """Wird geworfen wenn eine Buchung zu einem negativen Kassenbestand führen würde."""
    pass


class KeinLesezugriffError(Exception):
    """Wird geworfen wenn der User keinen Lesezugriff auf die Kasse hat."""
    pass


class KeinSchreibzugriffError(Exception):
    """Wird geworfen wenn der User keinen Schreibzugriff auf die Kasse hat."""
    pass


class KeinExportrechtError(Exception):
    """Wird geworfen wenn der User kein Exportrecht für die Kasse hat."""
    pass


class KategorieUngueltigError(Exception):
    """Wird geworfen wenn eine Buchungs-Kategorie nicht zu den für die Kasse
    zugelassenen Stammdaten-Kategorien gehört."""
    pass


class DatumAusserhalbBereichError(Exception):
    """Wird geworfen wenn das Buchungsdatum außerhalb des erlaubten Bereichs liegt.

    Attributes:
        min_datum: Frühestes erlaubtes Datum (ISO-String, kann None sein wenn kein Export).
        max_datum: Spätestes erlaubtes Datum (ISO-String, immer date.today()).
    """

    def __init__(self, min_datum: str | None, max_datum: str) -> None:
        self.min_datum = min_datum
        self.max_datum = max_datum
        if min_datum:
            super().__init__(
                f"Datum muss zwischen {min_datum} und {max_datum} liegen."
            )
        else:
            super().__init__(
                f"Datum darf nicht nach heute ({max_datum}) liegen."
            )


class KassenbuchService:
    """Service für alle Kassenbuch-Operationen.

    Enthält:
    - Buchungssperre (Export-Schutz)
    - Bestandsprüfung (kein negativer Bestand)
    - Belegnummer-Generierung (einfache laufende Nummer pro Kasse)
    - Export-Logik (CSV)
    - Kassenbericht-Daten für PDF
    - Berechtigungsprüfung (kassenspezifisch, Admin-Bypass)
    - Datumsvalidierung (>= letztes Export-bis_datum, <= heute)
    """

    def __init__(
        self,
        kasse_repo: KasseRepository,
        buchung_repo: KassenbuchungRepository,
        export_repo: KassenbuchExportRepository,
        berechtigung_repo: KasseBerechtigungRepository,
        anhang_repo: KassenbuchungAnhangRepository | None = None,
        anhang_service: AnhangService | None = None,
        kategorie_repo: KassenKategorieRepository | None = None,
    ):
        self._kasse = kasse_repo
        self._buchung = buchung_repo
        self._export = export_repo
        self._berechtigung = berechtigung_repo
        self._anhang_repo = anhang_repo
        self._anhang_service = anhang_service
        self._kategorie = kategorie_repo

    # -----------------------------------
    # Berechtigungsprüfung
    # -----------------------------------

    def get_kassen_fuer_user(self, user_id: int, is_admin: bool) -> list[Kasse]:
        """Gibt alle Kassen zurück, auf die der User Lesezugriff hat.

        Admins erhalten alle Kassen.
        """
        alle_kassen = self._kasse.list_kassen()
        if is_admin:
            return alle_kassen
        berechtigte_ids = set(self._berechtigung.get_kassen_ids_fuer_user(user_id))
        return [k for k in alle_kassen if k.id in berechtigte_ids]

    def _pruefe_lesezugriff(self, kasse_id: int, user_id: int, is_admin: bool) -> None:
        """Wirft KeinLesezugriffError wenn kein Lesezugriff."""
        if is_admin:
            return
        if not self._berechtigung.hat_lesezugriff(kasse_id, user_id):
            raise KeinLesezugriffError(
                f"Kein Lesezugriff auf Kasse {kasse_id}."
            )

    def _pruefe_schreibzugriff(self, kasse_id: int, user_id: int, is_admin: bool) -> None:
        """Wirft KeinSchreibzugriffError wenn kein Schreibzugriff."""
        if is_admin:
            return
        if not self._berechtigung.hat_schreibzugriff(kasse_id, user_id):
            raise KeinSchreibzugriffError(
                f"Kein Schreibzugriff auf Kasse {kasse_id}."
            )

    def _pruefe_exportrecht(self, kasse_id: int, user_id: int, is_admin: bool) -> None:
        """Wirft KeinExportrechtError wenn kein Exportrecht."""
        if is_admin:
            return
        if not self._berechtigung.hat_exportrecht(kasse_id, user_id):
            raise KeinExportrechtError(
                f"Kein Exportrecht für Kasse {kasse_id}."
            )

    # -----------------------------------
    # Datumsvalidierung
    # -----------------------------------

    def get_datum_bereich(self, kasse_id: int) -> tuple[str | None, str]:
        """Gibt den erlaubten Datumsbereich für neue/bearbeitete Buchungen zurück.

        Returns:
            (min_datum, max_datum) als ISO-Strings.
            min_datum ist None wenn noch kein Export existiert.
            max_datum ist immer date.today().
        """
        max_datum = date.today().isoformat()
        min_datum = self._export.get_letztes_bis_datum(kasse_id)
        return min_datum, max_datum

    def _validate_datum(self, buchungsdatum: str, kasse_id: int) -> None:
        """Validiert das Buchungsdatum gegen den erlaubten Bereich.

        Raises:
            DatumAusserhalbBereichError: Wenn das Datum außerhalb des erlaubten Bereichs.
        """
        min_datum, max_datum = self.get_datum_bereich(kasse_id)
        if buchungsdatum > max_datum:
            raise DatumAusserhalbBereichError(min_datum, max_datum)
        if min_datum is not None and buchungsdatum < min_datum:
            raise DatumAusserhalbBereichError(min_datum, max_datum)

    def _validate_kategorie(
        self, kasse_id: int, kategorie: str, vorheriger_wert: str | None = None
    ) -> None:
        """Stellt sicher, dass eine nicht-leere Kategorie zu den für die Kasse
        zugelassenen Stammdaten gehört (allgemein ∪ kassenspezifisch).

        Leer bleibt erlaubt (Backend lenient – die Pflicht erzwingt das Frontend).
        Beim Bearbeiten bleibt der unveränderte Altwert zulässig, damit
        Legacy-Freitexte beim Editieren nicht erzwungen geändert werden müssen.
        Ohne konfiguriertes kategorie_repo wird nicht validiert.
        """
        if self._kategorie is None:
            return
        name = (kategorie or '').strip()
        if not name:
            return
        if vorheriger_wert is not None and name == (vorheriger_wert or '').strip():
            return
        erlaubt = {k.name for k in self._kategorie.list_for_kasse(kasse_id)}
        if name not in erlaubt:
            raise KategorieUngueltigError(
                f"Kategorie '{name}' ist für diese Kasse nicht zugelassen."
            )

    # -----------------------------------
    # Kassen-Verwaltung (Admin-only)
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
        self, buchung: Kassenbuchung, created_by: str,
        user_id: int = None, is_admin: bool = False,
    ) -> Kassenbuchung:
        """Erstellt eine neue Buchung inkl. Datumsvalidierung, Bestandsprüfung und Belegnummer.

        Raises:
            KeinSchreibzugriffError: Wenn kein Schreibzugriff auf die Kasse.
            DatumAusserhalbBereichError: Wenn das Datum außerhalb des erlaubten Bereichs liegt.
            NegativerBestandError: Wenn die Buchung zu einem negativen Bestand führen würde.
        """
        if user_id is not None:
            self._pruefe_schreibzugriff(buchung.kasse_id, user_id, is_admin)

        self._validate_datum(buchung.buchungsdatum, buchung.kasse_id)
        self._validate_kategorie(buchung.kasse_id, buchung.kategorie)

        # Belegnummer: einfache laufende Nummer pro Kasse
        buchung.belegnummer = self._buchung.get_naechste_belegnummer(buchung.kasse_id)

        # Bestandsprüfung: Bestand AM BUCHUNGSDATUM - neue Ausgabe >= 0
        # (nicht der aktuelle Gesamtbestand, damit Vergangenheitsbuchungen korrekt geprüft werden)
        if buchung.ausgabe_cent > 0:
            aktuell = self._kasse.get_bestand_zum_datum_cent(buchung.kasse_id, buchung.buchungsdatum)
            if aktuell - buchung.ausgabe_cent < 0:
                raise NegativerBestandError(
                    f"Ausgabe von {buchung.ausgabe_cent / 100:.2f} € würde zu negativem Bestand "
                    f"am {buchung.buchungsdatum} führen. "
                    f"Bestand an diesem Tag: {aktuell / 100:.2f} €"
                )

        return self._buchung.create_kassenbuchung(buchung, created_by)

    def update_buchung(
        self, buchung: Kassenbuchung, updated_by: str,
        user_id: int = None, is_admin: bool = False,
    ) -> bool:
        """Aktualisiert eine Buchung.

        Raises:
            KeinSchreibzugriffError: Wenn kein Schreibzugriff auf die Kasse.
            BuchungGesperrtError: Wenn die Buchung bereits exportiert wurde.
            DatumAusserhalbBereichError: Wenn das Datum außerhalb des erlaubten Bereichs liegt.
            NegativerBestandError: Wenn die Änderung zu einem negativen Bestand führen würde.
        """
        if user_id is not None:
            self._pruefe_schreibzugriff(buchung.kasse_id, user_id, is_admin)

        self._pruefe_nicht_gesperrt(buchung.id)

        self._validate_datum(buchung.buchungsdatum, buchung.kasse_id)

        alte_buchung = self._buchung.get_kassenbuchung(buchung.id)
        self._validate_kategorie(
            buchung.kasse_id, buchung.kategorie, vorheriger_wert=alte_buchung.kategorie
        )

        # Bestandsprüfung: simulierter Bestand nach Update, geprüft am Buchungsdatum
        if buchung.ausgabe_cent > 0:
            # Bestand am Buchungsdatum ohne den Effekt der alten Buchung
            bestand_am_datum = self._kasse.get_bestand_zum_datum_cent(buchung.kasse_id, buchung.buchungsdatum)
            bestand_ohne_alte = bestand_am_datum + alte_buchung.ausgabe_cent - alte_buchung.einnahme_cent
            neuer_bestand = bestand_ohne_alte + buchung.einnahme_cent - buchung.ausgabe_cent
            if neuer_bestand < 0:
                raise NegativerBestandError(
                    f"Geänderter Betrag würde zu negativem Bestand am {buchung.buchungsdatum} führen."
                )

        return self._buchung.update_kassenbuchung(buchung, updated_by)

    def storniere_buchung(
        self, buchung_id: int, deleted_by: str,
        user_id: int = None, is_admin: bool = False,
    ) -> bool:
        """Storniert (Soft-Delete) eine Buchung.

        Raises:
            KeinSchreibzugriffError: Wenn kein Schreibzugriff auf die Kasse.
            BuchungGesperrtError: Wenn die Buchung bereits exportiert wurde.
        """
        if user_id is not None:
            buchung = self._buchung.get_kassenbuchung(buchung_id)
            self._pruefe_schreibzugriff(buchung.kasse_id, user_id, is_admin)

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

    @staticmethod
    def _baue_dateiname(kasse_name: str, export_id: int, von_datum: str, bis_datum: str) -> str:
        """Erstellt den standardisierten Dateinamen für einen CSV-Export.

        Format: {kassename}-export-{id}-{von}-bis-{bis}.csv
        Leerzeichen im Kassennamen werden durch Bindestriche ersetzt.
        """
        name_slug = kasse_name.lower().replace(' ', '-')
        return f"{name_slug}-export-{export_id}-{von_datum}-bis-{bis_datum}.csv"

    def _baue_csv_bytes(self, buchungen: list[dict]) -> bytes:
        """Erstellt CSV-Bytes aus einer Liste von Buchungs-Dicts."""
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
        return output.getvalue().encode("utf-8-sig")  # BOM für Excel

    def exportiere_csv(
        self,
        kasse_id: int,
        bis_datum: str,
        exported_by: str,
        user_id: int = None,
        is_admin: bool = False,
    ) -> tuple[str, bytes]:
        """Exportiert alle nicht-exportierten Buchungen bis bis_datum als CSV.

        Die exportierten Buchungen werden danach gesperrt.
        Der Dateiname enthält Kassenname, Export-ID und Datumsbereich.

        Raises:
            KeinExportrechtError: Wenn kein Exportrecht für die Kasse.
            ValueError: Wenn keine exportierbaren Buchungen vorhanden.

        Returns:
            Tuple (dateiname, csv_bytes)
        """
        if user_id is not None:
            self._pruefe_exportrecht(kasse_id, user_id, is_admin)

        buchungen = self._export.get_nicht_exportierte_buchungen(kasse_id, bis_datum)
        if not buchungen:
            raise ValueError("Keine exportierbaren Buchungen im angegebenen Zeitraum.")

        kasse = self._kasse.get_kasse(kasse_id)
        von_datum = buchungen[0]["buchungsdatum"]

        # Vorläufiger Dateiname (Export-ID noch unbekannt)
        export = KassenbuchExport(
            kasse_id=kasse_id,
            zeitraum_von=von_datum,
            zeitraum_bis=bis_datum,
            dateiname="pending",
            anzahl_buchungen=len(buchungen),
        )
        gespeicherter_export = self._export.create_export(export, exported_by)

        # Dateiname mit echter Export-ID setzen
        dateiname = self._baue_dateiname(
            kasse.name, gespeicherter_export.id, von_datum, bis_datum
        )
        self._export.update_dateiname(gespeicherter_export.id, dateiname)
        gespeicherter_export.dateiname = dateiname

        # CSV erstellen
        csv_bytes = self._baue_csv_bytes(buchungen)

        # Buchungen sperren
        buchung_ids = [b["id"] for b in buchungen]
        self._buchung.mark_buchungen_exportiert(buchung_ids, gespeicherter_export.id)

        return dateiname, csv_bytes

    def reexportiere_csv(
        self,
        export_id: int,
        user_id: int = None,
        is_admin: bool = False,
    ) -> tuple[str, bytes]:
        """Erstellt den CSV-Download eines bereits abgeschlossenen Exports erneut.

        Es werden keine neuen Buchungen gesperrt und kein neuer Export-Datensatz
        angelegt. Der Dateiname des ursprünglichen Exports wird verwendet.

        Raises:
            KeinExportrechtError: Wenn kein Exportrecht für die Kasse.
            KeyError: Wenn der Export nicht gefunden wurde.

        Returns:
            Tuple (dateiname, csv_bytes)
        """
        gespeicherter_export = self._export.get_export(export_id)

        if user_id is not None:
            self._pruefe_exportrecht(gespeicherter_export.kasse_id, user_id, is_admin)

        buchungen = self._export.get_buchungen_fuer_export(export_id)
        csv_bytes = self._baue_csv_bytes(buchungen)

        return gespeicherter_export.dateiname, csv_bytes

    # -----------------------------------
    # Kassenbericht-Daten (für PDF)
    # -----------------------------------

    def get_kassenbericht_daten(
        self,
        kasse_id: int,
        von_datum: str,
        bis_datum: str,
        include_storniert: bool = False,
        user_id: int = None,
        is_admin: bool = False,
    ) -> dict:
        """Gibt alle Daten für den PDF-Kassenbericht zurück.

        Raises:
            KeinLesezugriffError: Wenn kein Lesezugriff auf die Kasse.
        """
        if user_id is not None:
            self._pruefe_lesezugriff(kasse_id, user_id, is_admin)

        kasse = self._kasse.get_kasse(kasse_id)

        # Anfangsbestand: Bestand am Tag VOR von_datum
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

    # -----------------------------------
    # Anhang-Operationen
    # -----------------------------------

    def add_anhang(
        self,
        buchung_id: int,
        original_name: str,
        mime_type: str,
        inhalt: bytes,
        hochgeladen_von: int,
    ) -> KassenbuchungAnhang:
        """Speichert einen Datei-Anhang für eine Kassenbuchung.

        Bilder werden automatisch herunterskaliert und als JPEG gespeichert.

        Raises:
            DateitypNichtErlaubtError: Wenn der MIME-Typ nicht erlaubt ist.
            DateiZuGrossError: Wenn die Datei die Maximalgröße überschreitet.
            IOError: Wenn das Schreiben auf die Festplatte fehlschlägt.
        """
        if mime_type.startswith('image/'):
            inhalt = self._anhang_service.bild_zu_jpeg(inhalt)
            original_name = os.path.splitext(original_name)[0] + '.jpg'
            mime_type = 'image/jpeg'

        self._anhang_service.validiere(mime_type, len(inhalt))
        db_anhang = self._anhang_repo.create(KassenbuchungAnhang(
            buchung_id=buchung_id,
            original_name=original_name,
            mime_type=mime_type,
            dateigroesse=len(inhalt),
            hochgeladen_von=hochgeladen_von,
        ))
        try:
            self._anhang_service.schreibe(db_anhang.stored_name, inhalt)
        except IOError:
            self._anhang_repo.mark_deleted(db_anhang.id, 'SYSTEM_FEHLER')
            raise
        return db_anhang

    def get_anhaenge(self, buchung_id: int) -> list[KassenbuchungAnhang]:
        return self._anhang_repo.list_by_buchung(buchung_id)

    def mark_anhang_deleted(self, id: int, deleted_by: str) -> bool:
        return self._anhang_repo.mark_deleted(id, deleted_by)
