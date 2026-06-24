"""
Permission-Konstanten für die Vereinsverwaltung.

Jede Permission hat die Form 'ressource.aktion'.
Rollen werden beim Anlegen eines Users als Default-Permissions vergeben.

Effektive Rechte eines Users (siehe BERECHTIGUNGEN.md):
    (Sockel ∪ Funktionsrechte ∪ individuelle Grants) − individuelle Denies
Funktionsrechte kommen aus funktion_permission über die aktiven (von/bis)
Funktions-Zuordnungen des verknüpften Mitglieds; abteilungsgebundene
Zuordnungen tragen einen Abteilungs-Scope (Durchsetzung folgt in einer
späteren Stufe – bis dahin wirken sie vereinsweit, "lenient").

HINWEIS: Kassenbuch-Zugriff wird NICHT über globale Permissions geregelt,
sondern kassenspezifisch über kasse_berechtigungen (siehe KasseBerechtigungRepository).
"""
from dataclasses import dataclass, field


class Permission:
    """Alle verfügbaren globalen Permissions als Konstanten."""

    # --- Personen (Mitglieder + Benutzer) ---
    PERSONEN_READ        = 'personen.read'
    PERSONEN_WRITE       = 'personen.write'
    PERSONEN_DELETE      = 'personen.delete'
    PERSONEN_PERMISSIONS = 'personen.permissions'

    # --- Abteilungen ---
    ABTEILUNGEN_READ   = 'abteilungen.read'
    ABTEILUNGEN_WRITE  = 'abteilungen.write'
    ABTEILUNGEN_DELETE = 'abteilungen.delete'

    # --- Mannschaften / Teams ---
    MANNSCHAFTEN_READ   = 'mannschaften.read'
    MANNSCHAFTEN_WRITE  = 'mannschaften.write'
    MANNSCHAFTEN_DELETE = 'mannschaften.delete'

    # --- Beiträge ---
    BEITRAEGE_READ      = 'beitraege.read'
    BEITRAEGE_WRITE     = 'beitraege.write'
    BEITRAEGE_ABRECHNEN = 'beitraege.abrechnen'

    # --- Gebühren (Einmal-/Aufnahmegebühren) ---
    GEBUEHREN_READ      = 'gebuehren.read'
    GEBUEHREN_WRITE     = 'gebuehren.write'
    GEBUEHREN_ABRECHNEN = 'gebuehren.abrechnen'

    # --- Finanzbuchhaltung (Fibu-Delta-Export der Sollstellungen, Format FBASC) ---
    FIBU_EXPORT = 'fibu.export'

    # --- Übungsleiter-Stundenerfassung ---
    # ÜL erfasst/bearbeitet/reicht eigene Abrechnungen ein (Funktion 'uebungsleiter').
    UL_STUNDEN_ERFASSEN    = 'ulstunden.erfassen'
    # AL bestätigt/lehnt ab – abteilungs-scoped (Funktion 'abteilungsleiter').
    UL_STUNDEN_BESTAETIGEN = 'ulstunden.bestaetigen'
    # Admin/Fibu: alle Abrechnungen sehen, Vergütungssätze/Konten pflegen.
    UL_STUNDEN_VERWALTEN   = 'ulstunden.verwalten'

    # --- Berichte / Export ---
    BERICHTE_READ   = 'berichte.read'
    BERICHTE_EXPORT = 'berichte.export'

    # --- System / Verwaltung ---
    SYSTEM_CONFIG       = 'system.config'
    # Funktionskatalog verwalten (Funktionen anlegen/umbenennen/löschen).
    # Die Funktions-Berechtigungsmatrix selbst bleibt hart Admin-only.
    FUNKTIONEN_VERWALTEN = 'funktionen.verwalten'
    # Globaler Kassen-Admin: Kassen anlegen/bearbeiten/löschen, Kassen-Berechtigungen
    # vergeben und alle Kassen einsehen/bebuchen (umgeht die per-Kasse-ACL).
    KASSEN_VERWALTEN     = 'kassen.verwalten'
    # Zugriffsprotokoll einsehen (Anmelde-Events + Seitenaufrufe).
    SYSTEM_PROTOKOLL     = 'system.protokoll'

    # --- Tickets ---
    # Grundzugriff: Zugang zur Ticket-Seite, alle Tickets lesen, Tickets erstellen, öffentliche Kommentare schreiben
    TICKETS_ACCESS           = 'tickets.access'
    # Ticket bearbeiten (Status ändern, interne Kommentare hinzufügen)
    TICKETS_EDIT             = 'tickets.edit'
    # Ticket einem anderen User zuweisen
    TICKETS_ASSIGN           = 'tickets.assign'
    # Ticket schließen / wieder öffnen
    TICKETS_CLOSE            = 'tickets.close'
    # Ticket soft-deleten
    TICKETS_DELETE           = 'tickets.delete'
    # Interne (nicht-öffentliche) Kommentare lesen
    TICKETS_INTERN_READ      = 'tickets.intern_read'
    # Ticket-Bereiche und Ticket-Kategorien verwalten (anlegen, umbenennen, löschen)
    TICKETS_BEREICHE_VERWALTEN = 'tickets.bereiche_verwalten'

    # Legacy - für Migration (werden später entfernt)
    TICKETS_READ             = 'tickets.read'
    TICKETS_CREATE           = 'tickets.create'

    @classmethod
    def all(cls) -> list[str]:
        """Alle definierten globalen Permissions."""
        return [
            v for k, v in vars(cls).items()
            if not k.startswith('_') and isinstance(v, str)
        ]

    # Hinweis (Stufe D, siehe BERECHTIGUNGEN.md): Es gibt keine Rollen-Defaults mehr.
    # Rechte ergeben sich aus Sockel (BASE_PERMISSIONS) ∪ Funktionsrechten ∪
    # individuellen Grants − Denies. Die Rolle kennt nur noch 'admin' (uneingeschränkt)
    # und 'mitglied'. defaults_for_role wurde entfernt.


# Fester Sockel: gilt für JEDEN aktiven, eingeloggten User (auch ohne Funktion).
# Bewusst im Code statt in der DB – nicht editierbar, nie materialisiert.
# Ein individuelles Deny kann auch Sockel-Rechte entziehen (z. B. Ticket-Sperre).
BASE_PERMISSIONS: frozenset[str] = frozenset({Permission.TICKETS_ACCESS})


@dataclass
class EffectivePermissions:
    """Effektive Rechte eines Users inkl. Scope- und Herkunfts-Information.

    global_perms : vereinsweit wirksame Permission-Keys
    scoped       : permission → Menge von abteilung_ids (nur abteilungsgebunden geerbt)
    sources      : permission → Herkunftsliste für die Anzeige
                   ({'typ': 'sockel'|'funktion'|'override', ...})
    """
    global_perms: set[str] = field(default_factory=set)
    scoped: dict[str, set[int]] = field(default_factory=dict)
    sources: dict[str, list[dict]] = field(default_factory=dict)

    def keys(self) -> set[str]:
        """Alle wirksamen Permission-Keys (global + scoped) – lenient-Sicht."""
        return self.global_perms | set(self.scoped.keys())


def compute_effective_permissions(
    funktion_rows: list[dict],
    override_rows: list[dict],
    base: frozenset[str] = BASE_PERMISSIONS,
) -> EffectivePermissions:
    """Pure Mengenlogik: (Sockel ∪ Funktionsrechte ∪ Grants) − Denies.

    funktion_rows: Zeilen mit permission, abteilung_id (None = vereinsweit),
                   funktion_name, abteilung_name (Namen optional, nur für sources).
    override_rows: Zeilen mit permission, effect ('grant'|'deny'), abteilung_id.
                   In Stufe A ist abteilung_id bei Overrides immer None;
                   ein Deny mit Abteilungs-Scope entfernt nur diesen Scope.
    """
    eff = EffectivePermissions()

    def _source(perm: str, entry: dict) -> None:
        eff.sources.setdefault(perm, []).append(entry)

    for perm in base:
        eff.global_perms.add(perm)
        _source(perm, {'typ': 'sockel'})

    for row in funktion_rows:
        perm = row['permission']
        abteilung_id = row.get('abteilung_id')
        if abteilung_id is None:
            eff.global_perms.add(perm)
        else:
            eff.scoped.setdefault(perm, set()).add(abteilung_id)
        _source(perm, {
            'typ': 'funktion',
            'funktion_name': row.get('funktion_name'),
            'abteilung_id': abteilung_id,
            'abteilung_name': row.get('abteilung_name'),
        })

    denies: list[dict] = []
    for row in override_rows:
        perm = row['permission']
        effect = row.get('effect', 'grant')
        abteilung_id = row.get('abteilung_id')
        if effect == 'deny':
            denies.append(row)  # Denies erst nach allen Grants anwenden
            continue
        if abteilung_id is None:
            eff.global_perms.add(perm)
        else:
            eff.scoped.setdefault(perm, set()).add(abteilung_id)
        _source(perm, {'typ': 'override', 'effect': 'grant', 'abteilung_id': abteilung_id})

    for row in denies:
        perm = row['permission']
        abteilung_id = row.get('abteilung_id')
        if abteilung_id is None:
            # Totales Deny: entfernt global UND alle Scopes (schlägt auch Sockel)
            eff.global_perms.discard(perm)
            eff.scoped.pop(perm, None)
        else:
            scopes = eff.scoped.get(perm)
            if scopes is not None:
                scopes.discard(abteilung_id)
                if not scopes:
                    eff.scoped.pop(perm, None)
        # Denies immer in sources vermerken – auch wenn aktuell nichts Geerbtes
        # dagegensteht (Stickyness sichtbar machen, vgl. BERECHTIGUNGEN.md)
        _source(perm, {'typ': 'override', 'effect': 'deny', 'abteilung_id': abteilung_id})

    return eff


@dataclass
class UserPermission:
    """Einzelner Permission-Eintrag für einen User (entspricht einer DB-Zeile)."""
    id: int
    user_id: int
    permission: str
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: str | None = None
    deleted_by: str | None = None
    effect: str = 'grant'               # 'grant' | 'deny' (Tri-State-Override)
    abteilung_id: int | None = None     # Scope-Reserve (Stufe A: immer None)
