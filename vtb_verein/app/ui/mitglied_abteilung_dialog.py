"""
Sub-Dialog für Mitglied-Abteilung-Zuordnungen
"""
from nicegui import ui
from app.db.datastore import VereinsDB
from app.services.mitglied_abteilung_service import MitgliedAbteilungService


def show_abteilung_zuordnung_dialog(db: VereinsDB, mitglied_id: int, mitglied_name: str, current_user_name: str, on_close_callback=None):
    """Zeigt Dialog zur Verwaltung von Abteilungszuordnungen eines Mitglieds.
    
    Args:
        db: Datenbank-Instanz
        mitglied_id: ID des Mitglieds
        mitglied_name: Name des Mitglieds (für Titel)
        current_user_name: Username des aktuellen Benutzers
        on_close_callback: Optional callback beim Schließen
    """
    service = MitgliedAbteilungService(db)
    
    with ui.dialog() as dialog, ui.card().style('min-width: 700px; max-height: 80vh; overflow-y: auto'):
        ui.label(f'Abteilungen für {mitglied_name}').classes('text-h6 q-mb-md')
        
        columns = [
            {'name': 'abteilung_name', 'label': 'Abteilung', 'field': 'abteilung_name', 'align': 'left', 'sortable': True},
            {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'left'},
            {'name': 'von', 'label': 'Von', 'field': 'von', 'align': 'left'},
            {'name': 'bis', 'label': 'Bis', 'field': 'bis', 'align': 'left'},
            {'name': 'actions', 'label': 'Aktionen', 'field': 'actions', 'align': 'center'},
        ]
        
        def load_zuordnungen():
            zuordnungen = service.get_zuordnungen_fuer_mitglied(mitglied_id)
            return [
                {
                    'id': z['id'],
                    'abteilung_id': z['abteilung_id'],
                    'abteilung_name': z['abteilung_name'],
                    'status': z['status'] or 'aktiv',
                    'von': z['von'] or '',
                    'bis': z['bis'] or '',
                    'version': z['version'],
                }
                for z in zuordnungen
            ]
        
        table = ui.table(columns=columns, rows=load_zuordnungen(), row_key='id').classes('w-full q-mb-md')
        table.add_slot('body-cell-actions', '''
            <q-td :props="props">
                <q-btn flat dense icon="edit" @click="$parent.$emit('edit', props.row)" />
                <q-btn flat dense icon="delete" @click="$parent.$emit('delete', props.row)" />
            </q-td>
        ''')
        
        def show_add_dialog():
            # Hole verfügbare Abteilungen (noch nicht zugeordnet)
            alle_abteilungen = db.list_abteilungen()
            zugeordnete_ids = [z['abteilung_id'] for z in service.get_zuordnungen_fuer_mitglied(mitglied_id)]
            verfuegbare_abteilungen = [a for a in alle_abteilungen if a.id not in zugeordnete_ids]
            
            if not verfuegbare_abteilungen:
                ui.notify('Alle Abteilungen sind bereits zugeordnet', type='warning')
                return
            
            with ui.dialog() as add_dialog, ui.card():
                ui.label('Abteilung hinzufügen').classes('text-h6 q-mb-md')
                
                abteilung_select = ui.select(
                    label='Abteilung *',
                    options={a.id: a.name for a in verfuegbare_abteilungen},
                    with_input=True
                ).classes('w-full')
                
                status_input = ui.select(
                    label='Status',
                    options=['aktiv', 'passiv', 'trainer', 'vorstand', 'ehrenmitglied'],
                    value='aktiv'
                ).classes('w-full')
                
                von_input = ui.input('Von (YYYY-MM-DD)').classes('w-full')
                bis_input = ui.input('Bis (YYYY-MM-DD)').classes('w-full')
                
                error_label = ui.label('').classes('text-negative')
                error_label.visible = False
                
                def add_zuordnung():
                    error_label.visible = False
                    
                    if not abteilung_select.value:
                        error_label.text = 'Bitte wählen Sie eine Abteilung'
                        error_label.visible = True
                        return
                    
                    try:
                        service.create_zuordnung(
                            mitglied_id=mitglied_id,
                            abteilung_id=abteilung_select.value,
                            status=status_input.value or 'aktiv',
                            von=von_input.value or None,
                            bis=bis_input.value or None,
                            created_by=current_user_name
                        )
                        table.rows = load_zuordnungen()
                        table.update()
                        add_dialog.close()
                        ui.notify('Zuordnung erfolgreich hinzugefügt', type='positive')
                    except ValueError as e:
                        error_label.text = str(e)
                        error_label.visible = True
                    except Exception as e:
                        error_label.text = f'Fehler: {str(e)}'
                        error_label.visible = True
                
                with ui.row().classes('w-full q-mt-md'):
                    ui.button('Abbrechen', on_click=add_dialog.close)
                    ui.button('Hinzufügen', on_click=add_zuordnung).props('color=primary')
            
            add_dialog.open()
        
        def show_edit_dialog(row):
            with ui.dialog() as edit_dialog, ui.card():
                ui.label(f'Zuordnung bearbeiten: {row["abteilung_name"]}').classes('text-h6 q-mb-md')
                
                status_input = ui.select(
                    label='Status',
                    options=['aktiv', 'passiv', 'trainer', 'vorstand', 'ehrenmitglied'],
                    value=row['status']
                ).classes('w-full')
                
                von_input = ui.input('Von (YYYY-MM-DD)', value=row['von']).classes('w-full')
                bis_input = ui.input('Bis (YYYY-MM-DD)', value=row['bis']).classes('w-full')
                
                error_label = ui.label('').classes('text-negative')
                error_label.visible = False
                
                def update_zuordnung():
                    error_label.visible = False
                    
                    try:
                        success = service.update_zuordnung(
                            zuordnung_id=row['id'],
                            status=status_input.value,
                            von=von_input.value or None,
                            bis=bis_input.value or None,
                            updated_by=current_user_name
                        )
                        
                        if success:
                            table.rows = load_zuordnungen()
                            table.update()
                            edit_dialog.close()
                            ui.notify('Zuordnung erfolgreich aktualisiert', type='positive')
                        else:
                            error_label.text = 'Update fehlgeschlagen - Versionkonflikt oder nicht gefunden'
                            error_label.visible = True
                    except Exception as e:
                        error_label.text = f'Fehler: {str(e)}'
                        error_label.visible = True
                
                with ui.row().classes('w-full q-mt-md'):
                    ui.button('Abbrechen', on_click=edit_dialog.close)
                    ui.button('Speichern', on_click=update_zuordnung).props('color=primary')
            
            edit_dialog.open()
        
        def show_delete_dialog(row):
            with ui.dialog() as delete_dialog, ui.card():
                ui.label('Zuordnung löschen?').classes('text-h6 q-mb-md')
                ui.label(f'Soll die Zuordnung zu "{row["abteilung_name"]}" wirklich gelöscht werden?')
                
                def delete_zuordnung():
                    try:
                        success = service.delete_zuordnung(row['id'], deleted_by=current_user_name)
                        if success:
                            table.rows = load_zuordnungen()
                            table.update()
                            delete_dialog.close()
                            ui.notify('Zuordnung erfolgreich gelöscht', type='positive')
                        else:
                            ui.notify('Zuordnung konnte nicht gelöscht werden', type='negative')
                            delete_dialog.close()
                    except Exception as e:
                        ui.notify(f'Fehler: {str(e)}', type='negative')
                        delete_dialog.close()
                
                with ui.row().classes('w-full'):
                    ui.button('Abbrechen', on_click=delete_dialog.close).props('color=secondary')
                    ui.button('Löschen', on_click=delete_zuordnung).props('color=negative')
            
            delete_dialog.close()
        
        table.on('edit', lambda e: show_edit_dialog(e.args))
        table.on('delete', lambda e: show_delete_dialog(e.args))
        
        with ui.row().classes('w-full q-mt-md'):
            ui.button('Abteilung hinzufügen', on_click=show_add_dialog, icon='add').props('color=primary')
            ui.button('Schließen', on_click=lambda: (dialog.close(), on_close_callback() if on_close_callback else None))
    
    dialog.open()
    return dialog
