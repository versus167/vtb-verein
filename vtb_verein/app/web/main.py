'''
Created on 08.02.2026

@author: volker
'''
# app/web/main.py
from nicegui import ui

from app.db.datastore import VereinsDB
from app.services.abteilungen_service import AbteilungenService

db = VereinsDB('vereinsdb.sqlite')   # Pfad anpassen
abteilungen_service = AbteilungenService(db)


@ui.page('/')
def index():
    ui.label('Abteilungen verwalten').classes('text-h5 mb-4')

    name_input = ui.input('Name')
    kuerzel_input = ui.input('Kürzel')
    beschreibung_input = ui.input('Beschreibung')

    status_label = ui.label().classes('text-positive')

    def refresh_table():
        table.rows = [
            {
                'id': a.id,
                'name': a.name,
                'kuerzel': a.kuerzel,
                'beschreibung': a.beschreibung,
            }
            for a in abteilungen_service.list_abteilungen()
        ]

    def create_abteilung():
        abteilungen_service.create_abteilung(
            name=name_input.value or '',
            kuerzel=kuerzel_input.value or None,
            beschreibung=beschreibung_input.value or None,
            user='webui',
        )
        name_input.value = ''
        kuerzel_input.value = ''
        beschreibung_input.value = ''
        status_label.text = 'Abteilung angelegt'
        refresh_table()

    ui.button('Anlegen', on_click=create_abteilung).classes('mt-2')

    columns = [
        {'name': 'id', 'label': 'ID', 'field': 'id'},
        {'name': 'name', 'label': 'Name', 'field': 'name'},
        {'name': 'kuerzel', 'label': 'Kürzel', 'field': 'kuerzel'},
        {'name': 'beschreibung', 'label': 'Beschreibung', 'field': 'beschreibung'},
    ]
    table = ui.table(columns=columns, rows=[], row_key='id').classes('mt-6 w-full')

    refresh_table()


ui.run(title='Vereinsverwaltung – Abteilungen')
