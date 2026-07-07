"""Datenmodelle für den Passwort-Tresor (#85, Schema v66).

- Tresor:          benannte Sammlung von Zugangsdaten.
- TresorFreigabe:  ACL je Tresor – Freigabe an User / Abteilung / Funktion (read|write).
                   Der Zugriff wird NICHT über globale Rechte, sondern hierüber geregelt
                   (analog kasse_berechtigungen); nur das Verwalten hängt an tresor.verwalten.
- TresorEintrag:   ein Eintrag; die geheime Nutzlast (Passwort + Notiz) liegt ausschließlich
                   verschlüsselt in secret_ciphertext (BYTEA) und ist bewusst NICHT Teil des
                   Metadaten-Objekts – Entschlüsseln passiert nur explizit beim Reveal.
- TresorZugriffLog: append-only Audit jedes Enthüllens (wer, wann, welcher Eintrag).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Tresor:
    id: int
    name: str
    beschreibung: Optional[str]
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class TresorFreigabe:
    id: int
    tresor_id: int
    principal_typ: str          # 'user' | 'abteilung' | 'funktion'
    principal_id: int
    zugriff: str                # 'read' | 'write'
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige (per JOIN aufgelöst), keine Tabellenspalte:
    principal_name: Optional[str] = None


@dataclass
class TresorEintrag:
    """Metadaten eines Eintrags – ohne die verschlüsselte Nutzlast (kommt nur beim Reveal)."""
    id: int
    tresor_id: int
    titel: str
    benutzername: Optional[str]
    url: Optional[str]
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class TresorZugriffLog:
    id: int
    tresor_id: Optional[int]
    eintrag_id: Optional[int]
    eintrag_titel: Optional[str]
    user_id: Optional[int]
    username: Optional[str]
    aktion: str
    ip: Optional[str]
    created_at: str
