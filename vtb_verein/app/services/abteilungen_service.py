'''
Created on 08.02.2026

@author: volker
'''
# app/services/abteilungen_service.py
from typing import List
from app.db.datastore import VereinsDB
from app.models.abteilung import Abteilung

class AbteilungenService:
    def __init__(self, db: VereinsDB):
        self.db = db

    def get_abteilung(self, id: int) -> Abteilung:
        return self.db.get_abteilung(id)

    def list_abteilungen(self) -> List[Abteilung]:
        return self.db.list_abteilungen()

    def create_abteilung(self, name: str, kuerzel: str | None,
                         beschreibung: str | None, user: str) -> Abteilung:
        abt = Abteilung(name=name, kuerzel=kuerzel, beschreibung=beschreibung)
        return self.db.create_abteilung(abt, created_by=user)

    def update_abteilung(self, abt: Abteilung, user: str) -> bool:
        return self.db.update_abteilung(abt, updated_by=user)
    
    def delete_abteilung(self, abteilung_id: int) -> bool:
        return self.db.delete_abteilung(abteilung_id)
