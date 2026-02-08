# app/web/main.py
from nicegui import ui

from app.db.datastore import VereinsDB
from app.services.abteilungen_service import AbteilungenService
from app.models.abteilung import Abteilung

db = VereinsDB('vereinsdb.sqlite')
abteilungen_service = AbteilungenService(db)


@ui.page('/')
def index():
    ui.label('Abteilungen verwalten').classes('text-h5 mb-4')

    # ---------- Formular-Zustand ----------
    current_abt: Abteilung | None = None
    form_dirty = False

    def mark_dirty(e=None):
        nonlocal form_dirty
        form_dirty = True

    # ---------- Formular ----------
    name_input = ui.input('Name').on('input', mark_dirty)
    kuerzel_input = ui.input('Kürzel').on('input', mark_dirty)
    beschreibung_input = ui.input('Beschreibung').on('input', mark_dirty)

    status_label = ui.label().classes('text-positive text-caption mt-1')

    # ---------- Platzhalter, wird später definiert ----------
    def refresh_table():
        ...

    # ---------- Bestätigungs-Dialog fürs Verwerfen ----------
    confirm_dialog = ui.dialog()
    with confirm_dialog:
        with ui.card():
            ui.label('Ungespeicherte Änderungen verwerfen?').classes('text-h6 mb-2')
            ui.label(
                'Es liegen Änderungen im Formular vor, die noch nicht gespeichert wurden.'
            ).classes('mb-3')
            with ui.row():
                ui.button(
                    'Ja',
                    on_click=lambda: confirm_dialog.submit(True),
                    color='primary',
                )
                ui.button(
                    'Nein',
                    on_click=lambda: confirm_dialog.submit(False),
                )

    async def confirm_discard_if_dirty() -> bool:
        nonlocal form_dirty
        if not form_dirty:
            return True
        result = await confirm_dialog
        return bool(result)

    # ---------- Bestätigungs-Dialog fürs Löschen ----------
    delete_dialog = ui.dialog()
    with delete_dialog:
        with ui.card():
            delete_title_label = ui.label().classes('text-h6 mb-2')
            ui.label(
                'Dieser Vorgang kann nicht rückgängig gemacht werden.'
            ).classes('mb-3')
            with ui.row():
                ui.button(
                    'Ja',
                    on_click=lambda: delete_dialog.submit(True),
                    color='red',
                )
                ui.button(
                    'Nein',
                    on_click=lambda: delete_dialog.submit(False),
                )

    async def confirm_delete() -> bool:
        """Fragt mit dynamischem Titel nach, ob gelöscht werden soll."""
        if current_abt is None:
            return False
        delete_title_label.text = f'Abteilung #{current_abt.id} wirklich löschen?'
        result = await delete_dialog
        return bool(result)

    # ---------- Aktionen: Neu / Speichern / Löschen (ÜBER der Tabelle) ----------
    async def new_abteilung():
        nonlocal current_abt, form_dirty
        if not await confirm_discard_if_dirty():
            return
        current_abt = None
        name_input.value = ''
        kuerzel_input.value = ''
        beschreibung_input.value = ''
        status_label.text = 'Neu-Modus (neue Abteilung anlegen)'
        form_dirty = False

    def save_abteilung():
        nonlocal current_abt, form_dirty
        name = name_input.value or ''
        kuerzel = kuerzel_input.value or None
        beschreibung = beschreibung_input.value or None

        if current_abt is None:
            abteilungen_service.create_abteilung(
                name=name,
                kuerzel=kuerzel,
                beschreibung=beschreibung,
                user='webui',
            )
            status_label.text = 'Abteilung angelegt'
        else:
            current_abt.name = name
            current_abt.kuerzel = kuerzel
            current_abt.beschreibung = beschreibung
            ok = abteilungen_service.update_abteilung(current_abt, user='webui')
            if not ok:
                status_label.text = (
                    'Konflikt: Abteilung wurde inzwischen geändert. '
                    'Bitte Ansicht aktualisieren.'
                )
                return
            status_label.text = f'Abteilung #{current_abt.id} gespeichert'

        form_dirty = False
        refresh_table()

    async def delete_abteilung():
        nonlocal current_abt, form_dirty

        if current_abt is None:
            status_label.text = 'Keine Abteilung ausgewählt.'
            return

        # optional: erst Dirty-Check
        if form_dirty and not await confirm_discard_if_dirty():
            return

        if not await confirm_delete():
            return

        success = abteilungen_service.delete_abteilung(current_abt.id)
        if not success:
            status_label.text = (
                'Löschen nicht möglich: Es existieren noch Verknüpfungen '
                '(inkl. History).'
            )
            return

        status_label.text = f'Abteilung #{current_abt.id} gelöscht'
        current_abt = None
        name_input.value = ''
        kuerzel_input.value = ''
        beschreibung_input.value = ''
        form_dirty = False
        refresh_table()

    with ui.row().classes('mt-2'):
        ui.button('Neu', on_click=new_abteilung)
        ui.button('Speichern', on_click=save_abteilung, color='primary')
        ui.button('Löschen', on_click=delete_abteilung, color='red')

    # ---------- Tabelle (unterhalb der Buttons) ----------
    columns = [
        {'name': 'id', 'label': 'ID', 'field': 'id'},
        {'name': 'name', 'label': 'Name', 'field': 'name'},
        {'name': 'kuerzel', 'label': 'Kürzel', 'field': 'kuerzel'},
        {'name': 'beschreibung', 'label': 'Beschreibung', 'field': 'beschreibung'},
    ]
    table = ui.table(columns=columns, rows=[], row_key='id').classes('mt-2 w-full')

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
        table.update()

    # ---------- Tabellen-Klick lädt Abteilung ins Formular ----------
    async def on_row_click(e):
        nonlocal current_abt, form_dirty
        if not await confirm_discard_if_dirty():
            return

        row = e.args[1]
        abteilungs_id = row['id']
        current_abt = abteilungen_service.get_abteilung(abteilungs_id)

        name_input.value = current_abt.name
        kuerzel_input.value = current_abt.kuerzel or ''
        beschreibung_input.value = current_abt.beschreibung or ''
        status_label.text = f'Bearbeite Abteilung #{current_abt.id}'
        form_dirty = False

    table.on('rowClick', on_row_click)

    refresh_table()


ui.run(title='Vereinsverwaltung – Abteilungen')
