"""
Datenmodelle für Einmalgebühren (z.B. Aufnahmegebühren) und deren Forderungen.

Analog zu Beitragsregel/Sollstellung, aber EINMALIG statt wiederkehrend.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Gebuehr:
    """Katalog-Eintrag einer Einmalgebühr (mit Gültigkeitszeitraum)."""
    id: Optional[int] = None
    name: str = ""
    abteilung_id: Optional[int] = None           # NULL = Vereinsgebühr
    abteilung_name: Optional[str] = None          # per JOIN
    betrag: float = 0.0
    anlass: str = "aufnahme"
    gueltig_ab: str = ""
    gueltig_bis: Optional[str] = None
    zahler_typ: str = "mitglied"                  # mitglied | abteilung
    bedingung_alter_min: Optional[int] = None     # Mindestalter (Jahre) am Stichtag, None = keine Untergrenze
    bedingung_alter_max: Optional[int] = None     # Höchstalter (Jahre) am Stichtag, None = keine Obergrenze
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


@dataclass
class GebuehrForderung:
    """Konkrete einmalige Forderung einer Gebühr an ein Mitglied."""
    id: Optional[int] = None
    mitglied_id: int = 0
    gebuehr_id: int = 0
    datum: str = ""
    betrag_soll: float = 0.0
    status: str = "offen"                          # offen | bezahlt | storniert
    bezahlt_am: Optional[str] = None
    kassenbuchung_id: Optional[int] = None
    # per JOIN befüllt
    mitglied_vorname: Optional[str] = None
    mitglied_nachname: Optional[str] = None
    mitglied_iban: Optional[str] = None
    mitglied_kontoinhaber: Optional[str] = None
    gebuehr_name: Optional[str] = None
    zahler_typ: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
