"""
Service-Layer für Mitglied-Abteilung-Zuordnungen

Verantwortlich für:
- CRUD-Operationen auf mitglied_abteilung
- Business-Logik für Zuordnungen
- Validierung von Zuordnungen
"""

from typing import Optional
from dataclasses import dataclass
from app.db.datastore import VereinsDB


@dataclass
class MitgliedAbteilungZuordnung:
    """Repräsentiert eine Zuordnung zwischen Mitglied und Abteilung."""
    id: Optional[int] = None
    mitglied_id: int = None
    abteilung_id: int = None
    status: str = 'aktiv'
    von: Optional[str] = None  # Eintrittsdatum in die Abteilung
    bis: Optional[str] = None  # Austrittsdatum aus der Abteilung
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class MitgliedAbteilungService:
    """Service für Mitglied-Abteilung-Zuordnungen."""
    
    def __init__(self, db: VereinsDB):
        self.db = db
    
    # -----------------------------------
    # Read Operations
    # -----------------------------------
    
    def get_zuordnungen_fuer_mitglied(self, mitglied_id: int) -> list[dict]:
        """Hole alle aktiven Zuordnungen für ein Mitglied mit Abteilungsdetails.
        
        Returns:
            Liste von Dicts mit Zuordnungs- und Abteilungsdaten:
            {
                'id': zuordnung_id,
                'mitglied_id': ...,
                'abteilung_id': ...,
                'abteilung_name': ...,
                'abteilung_kuerzel': ...,
                'status': ...,
                'von': ...,
                'bis': ...,
                'version': ...
            }
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    ma.id,
                    ma.mitglied_id,
                    ma.abteilung_id,
                    a.name as abteilung_name,
                    a.kuerzel as abteilung_kuerzel,
                    ma.status,
                    ma.von,
                    ma.bis,
                    ma.version
                FROM mitglied_abteilung ma
                JOIN abteilung a ON ma.abteilung_id = a.id
                WHERE ma.mitglied_id = ? 
                  AND ma.deleted_at IS NULL
                  AND a.deleted_at IS NULL
                ORDER BY a.name
                """,
                (mitglied_id,)
            )
            return [dict(row) for row in cur.fetchall()]
    
    def get_mitglieder_fuer_abteilung(self, abteilung_id: int) -> list[dict]:
        """Hole alle aktiven Mitglieder einer Abteilung mit Details.
        
        Returns:
            Liste von Dicts mit Mitglied- und Zuordnungsdaten:
            {
                'zuordnung_id': ...,
                'mitglied_id': ...,
                'mitgliedsnummer': ...,
                'vorname': ...,
                'nachname': ...,
                'status': ...,
                'von': ...,
                'bis': ...
            }
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    ma.id as zuordnung_id,
                    m.id as mitglied_id,
                    m.mitgliedsnummer,
                    m.vorname,
                    m.nachname,
                    ma.status,
                    ma.von,
                    ma.bis
                FROM mitglied_abteilung ma
                JOIN mitglied m ON ma.mitglied_id = m.id
                WHERE ma.abteilung_id = ? 
                  AND ma.deleted_at IS NULL
                  AND m.deleted_at IS NULL
                ORDER BY m.nachname, m.vorname
                """,
                (abteilung_id,)
            )
            return [dict(row) for row in cur.fetchall()]
    
    def ist_mitglied_in_abteilung(self, mitglied_id: int, abteilung_id: int) -> bool:
        """Prüfe, ob ein Mitglied bereits einer Abteilung zugeordnet ist.
        
        Returns:
            True wenn aktive Zuordnung existiert, sonst False
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT 1 
                FROM mitglied_abteilung 
                WHERE mitglied_id = ? 
                  AND abteilung_id = ? 
                  AND deleted_at IS NULL
                LIMIT 1
                """,
                (mitglied_id, abteilung_id)
            )
            return cur.fetchone() is not None
    
    # -----------------------------------
    # Create Operation
    # -----------------------------------
    
    def create_zuordnung(
        self, 
        mitglied_id: int, 
        abteilung_id: int, 
        status: str = 'aktiv',
        von: Optional[str] = None,
        bis: Optional[str] = None,
        created_by: str = 'SYSTEM'
    ) -> Optional[int]:
        """Erstelle eine neue Mitglied-Abteilung-Zuordnung.
        
        Args:
            mitglied_id: ID des Mitglieds
            abteilung_id: ID der Abteilung
            status: Status der Zuordnung (z.B. 'aktiv', 'passiv', 'trainer')
            von: Eintrittsdatum (optional)
            bis: Austrittsdatum (optional)
            created_by: Username des Erstellers
        
        Returns:
            ID der erstellten Zuordnung oder None bei Fehler
        
        Raises:
            ValueError: Wenn Zuordnung bereits existiert
        """
        # Prüfe ob Zuordnung bereits existiert
        if self.ist_mitglied_in_abteilung(mitglied_id, abteilung_id):
            raise ValueError(f"Mitglied {mitglied_id} ist bereits der Abteilung {abteilung_id} zugeordnet")
        
        # Validiere dass Mitglied und Abteilung existieren
        try:
            self.db.get_mitglied(mitglied_id)
            self.db.get_abteilung(abteilung_id)
        except KeyError as e:
            raise ValueError(f"Mitglied oder Abteilung nicht gefunden: {e}")
        
        with self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mitglied_abteilung (
                    mitglied_id, abteilung_id, status, von, bis,
                    created_by, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (mitglied_id, abteilung_id, status, von, bis, created_by, created_by)
            )
            return cur.lastrowid
    
    # -----------------------------------
    # Update Operation
    # -----------------------------------
    
    def update_zuordnung(
        self,
        zuordnung_id: int,
        status: Optional[str] = None,
        von: Optional[str] = None,
        bis: Optional[str] = None,
        updated_by: str = 'SYSTEM'
    ) -> bool:
        """Aktualisiere eine Mitglied-Abteilung-Zuordnung.
        
        Args:
            zuordnung_id: ID der Zuordnung
            status: Neuer Status (optional)
            von: Neues Eintrittsdatum (optional)
            bis: Neues Austrittsdatum (optional)
            updated_by: Username des Bearbeiters
        
        Returns:
            True bei Erfolg, False bei Fehler
        """
        # Hole aktuelle Zuordnung
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT status, von, bis, version
                FROM mitglied_abteilung
                WHERE id = ? AND deleted_at IS NULL
                """,
                (zuordnung_id,)
            )
            row = cur.fetchone()
            if not row:
                return False
            
            current = dict(row)
            
            # Verwende aktuelle Werte wenn keine neuen angegeben
            new_status = status if status is not None else current['status']
            new_von = von if von is not None else current['von']
            new_bis = bis if bis is not None else current['bis']
            
            cur.execute(
                """
                UPDATE mitglied_abteilung
                SET status = ?,
                    von = ?,
                    bis = ?,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = ?
                WHERE id = ? AND version = ? AND deleted_at IS NULL
                """,
                (new_status, new_von, new_bis, updated_by, zuordnung_id, current['version'])
            )
            return cur.rowcount == 1
    
    # -----------------------------------
    # Delete Operation
    # -----------------------------------
    
    def delete_zuordnung(self, zuordnung_id: int, deleted_by: str = 'SYSTEM') -> bool:
        """Soft-Delete einer Mitglied-Abteilung-Zuordnung.
        
        Args:
            zuordnung_id: ID der Zuordnung
            deleted_by: Username des Löschers
        
        Returns:
            True bei Erfolg, False wenn nicht gefunden
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_abteilung
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = ?,
                    version = version + 1
                WHERE id = ? AND deleted_at IS NULL
                """,
                (deleted_by, zuordnung_id)
            )
            return cur.rowcount == 1
    
    def delete_alle_zuordnungen_fuer_mitglied(self, mitglied_id: int, deleted_by: str = 'SYSTEM') -> int:
        """Soft-Delete aller Zuordnungen eines Mitglieds.
        
        Args:
            mitglied_id: ID des Mitglieds
            deleted_by: Username des Löschers
        
        Returns:
            Anzahl gelöschter Zuordnungen
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_abteilung
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = ?,
                    version = version + 1
                WHERE mitglied_id = ? AND deleted_at IS NULL
                """,
                (deleted_by, mitglied_id)
            )
            return cur.rowcount
