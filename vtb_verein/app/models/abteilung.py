'''
Created on 08.02.2026

@author: volker
'''

from dataclasses import dataclass
from typing import Optional

@dataclass
class Abteilung:
    id: Optional[int] = None
    name: str = ""
    kuerzel: Optional[str] = None
    beschreibung: Optional[str] = None
    kostenstelle: Optional[int] = None   # Fibu-Kostenstelle (FBASC Feld 07)
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
