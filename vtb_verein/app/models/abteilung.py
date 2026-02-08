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
    version: int = 1
    createdat: Optional[str] = None
    createdby: Optional[str] = None
    updatedat: Optional[str] = None
    updatedby: Optional[str] = None
