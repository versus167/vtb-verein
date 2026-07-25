"""RechnungService – Einreichen und Freigeben von Rechnungen.

Workflow: entwurf → eingereicht → freigegeben | abgelehnt. Die Freigabe ist
abteilungs-scoped (Recht `rechnungen.freigeben`, i.d.R. über die Funktion
'abteilungsleiter'); Rechnungen ohne Abteilung gibt nur die Geschäftsstelle
(`rechnungen.verwalten`) frei.

Der Einreicher pflegt bewusst nur Beleg + Kategorie – Betrag, Rechnungsdatum und
Empfänger sind optional und können von der Geschäftsstelle nachgetragen werden.
Ohne Beleg ist ein Einreichen nicht möglich: die Rechnung IST der Beleg.

Die Statuswechsel selbst erzwingt das Repository über die WHERE-Klausel; hier
stehen Rechteprüfung, Vorbedingungen und Benachrichtigungen.
"""
import os
from typing import Optional

from app.models.permission import Permission
from app.models.rechnung import (
    Rechnung, RechnungAnhang, RechnungKategorie, STATUS_ENTWURF,
    EMPFAENGER_TYPEN, EMPFAENGER_MITGLIED, EMPFAENGER_EXTERN,
)


class RechnungFehler(Exception):
    """Basis für fachliche Fehler des Rechnungs-Workflows."""


class KeinZugriffError(RechnungFehler):
    """Der Benutzer darf diese Rechnung nicht sehen/bearbeiten."""


class KeineFreigabeberechtigungError(RechnungFehler):
    """Der Benutzer darf für diese Abteilung nicht freigeben."""


class FalscherStatusError(RechnungFehler):
    """Der Übergang passt nicht zum aktuellen Status (oder war ein Wettlauf)."""


class BelegFehltError(RechnungFehler):
    """Einreichen ohne Beleg – die Rechnung ist der Beleg."""


class EmpfaengerFehltError(RechnungFehler):
    """Einreichen ohne Zahlungsempfänger – niemand kann eine Zahlung freigeben,
    ohne zu wissen, an wen sie geht."""


class RechnungGesperrtError(RechnungFehler):
    """Die Rechnung wurde bereits exportiert und ist damit festgeschrieben."""


class KategorieInBenutzungError(RechnungFehler):
    """Die Kategorie hängt noch an lebenden Rechnungen."""


class RechnungService:

    def __init__(
        self,
        rechnung_repo,
        kategorie_repo,
        anhang_repo,
        user_repo,
        mitglied_repo,
        permission_repo,
        abteilung_repo,
        mitglied_abteilung_repo=None,
        mitglied_funktion_repo=None,
        anhang_service=None,
        push_service=None,
    ):
        self._rechnung = rechnung_repo
        self._kategorie = kategorie_repo
        self._anhang_repo = anhang_repo
        self._user_repo = user_repo
        self._mitglied_repo = mitglied_repo
        self._permission_repo = permission_repo
        self._abteilung_repo = abteilung_repo
        self._mitglied_abteilung_repo = mitglied_abteilung_repo
        self._mitglied_funktion_repo = mitglied_funktion_repo
        self._anhang_service = anhang_service
        self._push_service = push_service

    # ------------------------------------------------------------------
    # Rechteprüfung
    # ------------------------------------------------------------------

    @staticmethod
    def darf_verwalten(user) -> bool:
        return user.has_permission(Permission.RECHNUNGEN_VERWALTEN)

    @classmethod
    def darf_freigeben(cls, user, abteilung_id: Optional[int]) -> bool:
        """Freigabe ist abteilungs-scoped – hier wird der Scope STRICT geprüft.

        Ein Abteilungsleiter Fußball darf keine Handball-Rechnung freigeben, auch
        wenn `has_permission` (lenient) das Recht global bejahen würde.
        """
        if cls.darf_verwalten(user):
            return True
        if abteilung_id is None:
            # Vereinsrechnung: kein Abteilungs-Scope, der greifen könnte.
            return False
        return user.has_permission_for_abteilung(
            Permission.RECHNUNGEN_FREIGEBEN, abteilung_id)

    @classmethod
    def darf_sehen(cls, user, r: Rechnung) -> bool:
        """Sehen darf: der Ersteller, die Geschäftsstelle – und der zuständige
        Freigeber, sobald eingereicht wurde.

        Ein fremder Entwurf bleibt auch über die Detail-URL verborgen, sonst wäre
        das Ausblenden in der Freigabe-Liste nur Kosmetik.
        """
        if cls.darf_verwalten(user) or r.ersteller_user_id == user.id:
            return True
        if r.status == STATUS_ENTWURF:
            return False
        return cls.darf_freigeben(user, r.abteilung_id)

    def _hole_sichtbar(self, rechnung_id: int, user) -> Rechnung:
        r = self._rechnung.get(rechnung_id)
        if r is None:
            raise KeyError(f"Rechnung {rechnung_id} nicht gefunden")
        if not self.darf_sehen(user, r):
            raise KeinZugriffError("Kein Zugriff auf diese Rechnung.")
        return r

    @staticmethod
    def _darf_bearbeiten(user, r: Rechnung) -> bool:
        """Inhaltlich ändern darf der Ersteller im Entwurf – und die Geschäftsstelle,
        solange die Rechnung nicht exportiert ist (Fibu-Felder nachtragen)."""
        if user.has_permission(Permission.RECHNUNGEN_VERWALTEN):
            return not r.ist_exportiert
        return r.ersteller_user_id == user.id and r.status == STATUS_ENTWURF

    # ------------------------------------------------------------------
    # Abteilungs-Vorbelegung
    # ------------------------------------------------------------------

    def abteilungen_fuer_user(self, user) -> list[dict]:
        """Abteilungen, für die dieser Benutzer eine Rechnung einreichen kann.

        Quelle sind die aktiven Abteilungs-Zuordnungen des verknüpften Mitglieds
        (Mitgliedschaft) und dessen abteilungsgebundene Funktionen. Genau eine →
        das Frontend setzt sie ohne Auswahlfeld; keine → Vereinsrechnung.
        Verwalter dürfen jede Abteilung wählen.
        """
        if self.darf_verwalten(user):
            return self._alle_abteilungen()

        mitglied = self._mitglied_repo.get_by_user_id(user.id)
        if mitglied is None:
            return []
        ids: set[int] = set()
        if self._mitglied_abteilung_repo is not None:
            ids |= {za.abteilung_id
                    for za in self._mitglied_abteilung_repo.list_for_mitglied(mitglied.id)
                    if za.abteilung_id is not None}
        if self._mitglied_funktion_repo is not None:
            ids |= {aid
                    for aid in self._mitglied_funktion_repo.abteilung_ids_fuer_mitglied(
                        mitglied.id)
                    if aid is not None}
        if not ids:
            return []
        return [a for a in self._alle_abteilungen() if a["id"] in ids]

    def _alle_abteilungen(self) -> list[dict]:
        return [{"id": a.id, "name": a.name, "kostenstelle": a.kostenstelle}
                for a in self._abteilung_repo.list_abteilungen()]

    # ------------------------------------------------------------------
    # Listen
    # ------------------------------------------------------------------

    def list_meine(self, user, status: Optional[str] = None) -> list[Rechnung]:
        return self._rechnung.list_for_ersteller(user.id, status)

    def list_zur_freigabe(self, user, status: Optional[str] = None) -> list[Rechnung]:
        """Was dieser Benutzer freigeben darf.

        Fremde Entwürfe bleiben außen vor – der Freigeber sieht eine Rechnung erst,
        wenn sie eingereicht ist. Die eigenen Entwürfe stehen unter „Meine Rechnungen".
        """
        if self.darf_verwalten(user):
            return self._rechnung.list_for_abteilungen(None, status, ohne_entwuerfe=True)
        erlaubt = user.allowed_abteilungen(Permission.RECHNUNGEN_FREIGEBEN)
        # Vereinsrechnungen (ohne Abteilung) sieht hier niemand ohne Verwaltungsrecht.
        return self._rechnung.list_for_abteilungen(
            erlaubt if erlaubt is not None else None, status,
            include_vereinsrechnungen=False, ohne_entwuerfe=True)

    def list_alle(self, user, status: Optional[str] = None) -> list[Rechnung]:
        if not self.darf_verwalten(user):
            raise KeinZugriffError("Nur mit dem Recht 'rechnungen.verwalten'.")
        return self._rechnung.list_all(status)

    def get(self, rechnung_id: int, user) -> Rechnung:
        return self._hole_sichtbar(rechnung_id, user)

    # ------------------------------------------------------------------
    # Anlegen / Ändern
    # ------------------------------------------------------------------

    def anlegen(self, user, *, kategorie_id: int, abteilung_id: Optional[int] = None,
                beschreibung: Optional[str] = None, betrag_cent: Optional[int] = None,
                rechnungsdatum: Optional[str] = None, rechnungsnummer: Optional[str] = None,
                empfaenger_typ: Optional[str] = None,
                empfaenger_mitglied_id: Optional[int] = None,
                empfaenger_name: Optional[str] = None,
                empfaenger_iban: Optional[str] = None) -> Rechnung:
        if not (user.has_permission(Permission.RECHNUNGEN_EINREICHEN)
                or self.darf_verwalten(user)):
            raise KeinZugriffError("Kein Recht zum Einreichen von Rechnungen.")
        self._pruefe_kategorie(kategorie_id)
        self._pruefe_empfaenger(empfaenger_typ)
        self._pruefe_abteilung_waehlbar(user, abteilung_id)
        empfaenger_mitglied_id = self._aufloesen_empfaenger_mitglied(
            user, empfaenger_typ, empfaenger_mitglied_id)
        return self._rechnung.create(
            Rechnung(
                abteilung_id=abteilung_id, kategorie_id=kategorie_id,
                ersteller_user_id=user.id, beschreibung=beschreibung,
                betrag_cent=betrag_cent, rechnungsdatum=rechnungsdatum,
                rechnungsnummer=rechnungsnummer, empfaenger_typ=empfaenger_typ,
                empfaenger_mitglied_id=empfaenger_mitglied_id,
                empfaenger_name=empfaenger_name, empfaenger_iban=empfaenger_iban,
            ),
            created_by=user.username,
        )

    def aktualisieren(self, rechnung_id: int, user, *, expected_version: int,
                      **felder) -> Rechnung:
        r = self._hole_sichtbar(rechnung_id, user)
        if r.ist_exportiert:
            raise RechnungGesperrtError(
                "Die Rechnung wurde bereits exportiert und kann nicht mehr geändert werden.")
        if not self._darf_bearbeiten(user, r):
            raise KeinZugriffError("Diese Rechnung darfst du nicht bearbeiten.")

        neu = Rechnung(
            id=r.id, version=expected_version,
            abteilung_id=felder.get("abteilung_id", r.abteilung_id),
            kategorie_id=felder.get("kategorie_id", r.kategorie_id),
            beschreibung=felder.get("beschreibung", r.beschreibung),
            betrag_cent=felder.get("betrag_cent", r.betrag_cent),
            rechnungsdatum=felder.get("rechnungsdatum", r.rechnungsdatum),
            rechnungsnummer=felder.get("rechnungsnummer", r.rechnungsnummer),
            empfaenger_typ=felder.get("empfaenger_typ", r.empfaenger_typ),
            empfaenger_mitglied_id=felder.get("empfaenger_mitglied_id",
                                              r.empfaenger_mitglied_id),
            empfaenger_name=felder.get("empfaenger_name", r.empfaenger_name),
            empfaenger_iban=felder.get("empfaenger_iban", r.empfaenger_iban),
        )
        self._pruefe_kategorie(neu.kategorie_id)
        self._pruefe_empfaenger(neu.empfaenger_typ)
        neu.empfaenger_mitglied_id = self._aufloesen_empfaenger_mitglied(
            user, neu.empfaenger_typ, neu.empfaenger_mitglied_id)
        if neu.abteilung_id != r.abteilung_id:
            self._pruefe_abteilung_waehlbar(user, neu.abteilung_id)

        ok = self._rechnung.update(
            neu, user.username, nur_entwurf=not self.darf_verwalten(user))
        if not ok:
            raise FalscherStatusError(
                "Die Rechnung wurde zwischenzeitlich geändert oder ist nicht mehr im Entwurf.")
        return self._rechnung.get(rechnung_id)

    def loeschen(self, rechnung_id: int, user) -> None:
        r = self._hole_sichtbar(rechnung_id, user)
        if r.ist_exportiert:
            raise RechnungGesperrtError("Exportierte Rechnungen können nicht gelöscht werden.")
        verwalter = self.darf_verwalten(user)
        if not verwalter and r.ersteller_user_id != user.id:
            raise KeinZugriffError("Nur der Einreicher kann seine Rechnung löschen.")
        if not self._rechnung.soft_delete(rechnung_id, user.username,
                                          nur_entwurf=not verwalter):
            raise FalscherStatusError(
                "Nur Entwürfe können gelöscht werden – eingereichte bitte ablehnen lassen.")

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def einreichen(self, rechnung_id: int, user) -> Rechnung:
        r = self._hole_sichtbar(rechnung_id, user)
        if r.ersteller_user_id != user.id and not self.darf_verwalten(user):
            raise KeinZugriffError("Nur der Einreicher kann die Rechnung einreichen.")
        if self._anhang_repo.count_by_rechnung(rechnung_id) == 0:
            raise BelegFehltError("Bitte zuerst den Beleg hochladen.")
        self._pruefe_empfaenger_vollstaendig(r)
        if not self._rechnung.einreichen(rechnung_id, eingereicht_von=user.username):
            raise FalscherStatusError("Nur Entwürfe können eingereicht werden.")
        aktuell = self._rechnung.get(rechnung_id)
        self._benachrichtige_freigeber(aktuell, user)
        return aktuell

    def freigeben(self, rechnung_id: int, user) -> Rechnung:
        r = self._hole_sichtbar(rechnung_id, user)
        if not self.darf_freigeben(user, r.abteilung_id):
            raise KeineFreigabeberechtigungError(
                "Keine Freigabeberechtigung für diese Abteilung.")
        if not self._rechnung.freigeben(rechnung_id, freigegeben_von=user.username):
            raise FalscherStatusError("Nur eingereichte Rechnungen können freigegeben werden.")
        aktuell = self._rechnung.get(rechnung_id)
        self._benachrichtige_ersteller(
            aktuell, user, "freigegeben",
            "Deine Rechnung wurde freigegeben und geht mit dem nächsten Export "
            "an die Buchhaltung.")
        return aktuell

    def ablehnen(self, rechnung_id: int, user, grund: Optional[str] = None) -> Rechnung:
        r = self._hole_sichtbar(rechnung_id, user)
        if not self.darf_freigeben(user, r.abteilung_id):
            raise KeineFreigabeberechtigungError(
                "Keine Freigabeberechtigung für diese Abteilung.")
        if not self._rechnung.ablehnen(rechnung_id, grund=grund,
                                       abgelehnt_von=user.username):
            raise FalscherStatusError("Nur eingereichte Rechnungen können abgelehnt werden.")
        aktuell = self._rechnung.get(rechnung_id)
        self._benachrichtige_ersteller(
            aktuell, user, "abgelehnt",
            f"Begründung: {grund}" if grund else "Ohne Begründung.")
        return aktuell

    def zuruecksetzen(self, rechnung_id: int, user) -> Rechnung:
        """Freigabe/Ablehnung zurücknehmen – nur solange nicht exportiert."""
        r = self._hole_sichtbar(rechnung_id, user)
        if not self.darf_freigeben(user, r.abteilung_id):
            raise KeineFreigabeberechtigungError(
                "Keine Freigabeberechtigung für diese Abteilung.")
        if r.ist_exportiert:
            raise RechnungGesperrtError(
                "Die Rechnung ist exportiert – bitte zuerst den Export zurücknehmen.")
        if not self._rechnung.zuruecksetzen(rechnung_id, updated_by=user.username):
            raise FalscherStatusError(
                "Nur freigegebene oder abgelehnte Rechnungen können zurückgesetzt werden.")
        return self._rechnung.get(rechnung_id)

    # ------------------------------------------------------------------
    # Belege
    # ------------------------------------------------------------------

    def list_anhaenge(self, rechnung_id: int, user) -> list[RechnungAnhang]:
        self._hole_sichtbar(rechnung_id, user)
        return self._anhang_repo.list_by_rechnung(rechnung_id)

    def add_anhang(self, rechnung_id: int, user, *, original_name: str,
                   mime_type: str, inhalt: bytes) -> RechnungAnhang:
        """Beleg speichern. Bilder werden verkleinert und als JPEG abgelegt.

        Reihenfolge wie beim Kassenbuch: erst der DB-Eintrag (er liefert den
        stored_name), dann die Datei – schlägt das Schreiben fehl, wird der
        Eintrag kompensierend soft-gelöscht, damit kein Zeiger ins Leere bleibt.
        """
        r = self._hole_sichtbar(rechnung_id, user)
        if not self._darf_bearbeiten(user, r):
            raise KeinZugriffError(
                "Belege können nur im Entwurf hochgeladen werden.")
        if self._anhang_service is None:
            raise RuntimeError("AnhangService nicht konfiguriert")

        if mime_type.startswith("image/"):
            inhalt = self._anhang_service.bild_zu_jpeg(inhalt)
            original_name = os.path.splitext(original_name)[0] + ".jpg"
            mime_type = "image/jpeg"

        self._anhang_service.validiere(mime_type, len(inhalt))
        db_anhang = self._anhang_repo.create(RechnungAnhang(
            rechnung_id=rechnung_id,
            original_name=original_name,
            mime_type=mime_type,
            dateigroesse=len(inhalt),
            hochgeladen_von=user.username,
        ))
        try:
            self._anhang_service.schreibe(db_anhang.stored_name, inhalt)
        except IOError:
            self._anhang_repo.mark_deleted(db_anhang.id, "SYSTEM_FEHLER")
            raise
        return db_anhang

    def delete_anhang(self, rechnung_id: int, anhang_id: int, user) -> None:
        r = self._hole_sichtbar(rechnung_id, user)
        if not self._darf_bearbeiten(user, r):
            raise KeinZugriffError("Belege können nur im Entwurf gelöscht werden.")
        anhang = self._anhang_repo.get(anhang_id)
        if anhang is None or anhang.rechnung_id != rechnung_id:
            raise KeyError(f"Anhang {anhang_id} nicht gefunden")
        # Datei bleibt liegen – der Prune räumt sie später weg (Soft-Delete-Prinzip).
        self._anhang_repo.mark_deleted(anhang_id, user.username)

    # ------------------------------------------------------------------
    # Kategorien
    # ------------------------------------------------------------------

    def list_kategorien(self) -> list:
        return self._kategorie.list_alle()

    def kategorie_anlegen(self, user, **felder):
        self._require_verwalten(user)
        return self._kategorie.create(RechnungKategorie(**felder), user.username)

    def kategorie_aktualisieren(self, kategorie_id: int, user, *, expected_version: int,
                                **felder):
        self._require_verwalten(user)
        k = self._kategorie.get(kategorie_id)
        if k is None:
            raise KeyError(f"Kategorie {kategorie_id} nicht gefunden")
        neu = RechnungKategorie(
            id=kategorie_id, version=expected_version,
            name=felder.get("name", k.name),
            beschreibung=felder.get("beschreibung", k.beschreibung),
            sachkonto=felder.get("sachkonto", k.sachkonto),
            kostenstelle=felder.get("kostenstelle", k.kostenstelle),
            kostentraeger=felder.get("kostentraeger", k.kostentraeger),
        )
        if not self._kategorie.update(neu, user.username):
            raise FalscherStatusError("Die Kategorie wurde zwischenzeitlich geändert.")
        return self._kategorie.get(kategorie_id)

    def kategorie_loeschen(self, kategorie_id: int, user) -> None:
        self._require_verwalten(user)
        if self._kategorie.wird_verwendet(kategorie_id):
            raise KategorieInBenutzungError(
                "Die Kategorie wird noch von Rechnungen verwendet.")
        if not self._kategorie.soft_delete(kategorie_id, user.username):
            raise KeyError(f"Kategorie {kategorie_id} nicht gefunden")

    def _require_verwalten(self, user) -> None:
        if not self.darf_verwalten(user):
            raise KeinZugriffError("Nur mit dem Recht 'rechnungen.verwalten'.")

    # ------------------------------------------------------------------
    # Validierung
    # ------------------------------------------------------------------

    def _pruefe_kategorie(self, kategorie_id: int) -> None:
        if self._kategorie.get(kategorie_id) is None:
            raise ValueError("Unbekannte oder gelöschte Kategorie.")

    @staticmethod
    def _pruefe_empfaenger(empfaenger_typ: Optional[str]) -> None:
        if empfaenger_typ is not None and empfaenger_typ not in EMPFAENGER_TYPEN:
            raise ValueError(
                f"Unbekannter Empfängertyp – erlaubt: {', '.join(EMPFAENGER_TYPEN)}.")

    def _aufloesen_empfaenger_mitglied(self, user, empfaenger_typ: Optional[str],
                                       empfaenger_mitglied_id: Optional[int]):
        """Bei „Erstattung an ein Mitglied" ohne konkrete Angabe: der Einreicher.

        Das ist der Normalfall (jemand hat ausgelegt und will es zurück) – das
        Frontend schickt dann nur den Typ. Die Bankverbindung kommt aus dem
        Mitgliedsstamm und wird an der Rechnung nicht doppelt gepflegt.
        """
        if empfaenger_typ != EMPFAENGER_MITGLIED or empfaenger_mitglied_id is not None:
            return empfaenger_mitglied_id
        mitglied = self._mitglied_repo.get_by_user_id(user.id)
        if mitglied is None:
            raise ValueError(
                "Zu diesem Benutzer gibt es kein Mitglied – bitte den "
                "Rechnungsaussteller als Empfänger angeben.")
        return mitglied.id

    def _pruefe_empfaenger_vollstaendig(self, r: Rechnung) -> None:
        """Vor dem Einreichen: Wer bekommt das Geld? Ohne Antwort kann niemand
        die Zahlung freigeben."""
        if r.empfaenger_typ not in EMPFAENGER_TYPEN:
            raise EmpfaengerFehltError(
                "Bitte angeben, an wen gezahlt werden soll.")
        if r.empfaenger_typ == EMPFAENGER_EXTERN and not (r.empfaenger_name or '').strip():
            raise EmpfaengerFehltError(
                "Bitte den Rechnungsaussteller angeben, an den gezahlt werden soll.")
        if r.empfaenger_typ == EMPFAENGER_MITGLIED and r.empfaenger_mitglied_id is None:
            raise EmpfaengerFehltError(
                "Für die Erstattung fehlt das Mitglied, an das gezahlt werden soll.")

    def _pruefe_abteilung_waehlbar(self, user, abteilung_id: Optional[int]) -> None:
        """Ein Einreicher darf nur „seine" Abteilungen wählen – sonst könnte er die
        Rechnung an einem fremden Freigeber vorbei in eine Abteilung schieben, in
        der er nichts zu suchen hat."""
        if abteilung_id is None or self.darf_verwalten(user):
            return
        erlaubt = {a["id"] for a in self.abteilungen_fuer_user(user)}
        if abteilung_id not in erlaubt:
            raise KeinZugriffError("Für diese Abteilung kannst du nichts einreichen.")

    # ------------------------------------------------------------------
    # Benachrichtigungen
    # ------------------------------------------------------------------

    def _notify(self, user_ids, exclude_user_id: Optional[int], title: str,
                message: str, url: str = "/") -> None:
        """Lädt die User-Objekte im Request-Thread und stößt den Versand
        nicht-blockierend an (im Hintergrund-Thread sind keine DB-Zugriffe erlaubt)."""
        from app.services.notification_service import NotificationService
        seen: set[int] = set()
        for uid in user_ids:
            if uid is None or uid in seen or uid == exclude_user_id:
                continue
            seen.add(uid)
            user = self._user_repo.get_by_id(uid)
            if user and user.active:
                NotificationService.send_notification_async(
                    user, title, message, push_service=self._push_service, url=url)

    @staticmethod
    def _url(rechnung_id: int) -> str:
        return f"/rechnungen?rechnung={rechnung_id}"

    def _bezeichnung(self, r: Rechnung) -> str:
        teile = [r.kategorie_name or "Rechnung"]
        if r.abteilung_name:
            teile.append(r.abteilung_name)
        if r.betrag_cent is not None:
            teile.append(f"{r.betrag_cent / 100:.2f} €".replace(".", ","))
        return " · ".join(teile)

    def _benachrichtige_freigeber(self, r: Rechnung, ausloeser) -> None:
        if self._permission_repo is None:
            return
        # Vereinsrechnung (ohne Abteilung) kann nur die Geschäftsstelle freigeben –
        # dann sind die Inhaber von 'rechnungen.freigeben' die falschen Empfänger.
        if r.abteilung_id is None:
            empfaenger = self._permission_repo.list_user_ids_mit_permission(
                Permission.RECHNUNGEN_VERWALTEN)
        else:
            empfaenger = self._permission_repo.list_user_ids_mit_permission(
                Permission.RECHNUNGEN_FREIGEBEN, r.abteilung_id)
        self._notify(
            empfaenger, ausloeser.id,
            f"🧾 Rechnung #{r.id} wartet auf Freigabe",
            f"{self._bezeichnung(r)}\n\nEingereicht von: {ausloeser.username}"
            + (f"\n{r.beschreibung}" if r.beschreibung else ""),
            url=self._url(r.id),
        )

    def _benachrichtige_ersteller(self, r: Rechnung, ausloeser,
                                  vorgang: str, zusatz: str) -> None:
        self._notify(
            [r.ersteller_user_id], ausloeser.id,
            f"🧾 Rechnung #{r.id} {vorgang}",
            f"{self._bezeichnung(r)}\n\n{vorgang.capitalize()} von: "
            f"{ausloeser.username}\n{zusatz}",
            url=self._url(r.id),
        )
