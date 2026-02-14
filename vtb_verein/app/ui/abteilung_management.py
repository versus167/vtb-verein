"""
Abteilungsverwaltungs-Seite
"""
from nicegui import ui
from app.db.datastore import VereinsDB
from app.models.abteilung import Abteilung
from app.auth.auth_helper import AuthHelper, require_role
from app.ui.navigation import create_navigation, set_current_path

def create_abteilung_management_page(db: VereinsDB):
    """Erstellt die Abteilungsverwaltungs-Seite"""
    
    @ui.page('/abteilungen')
    @require_role('user')  # user und admin können Abteilungen verwalten
    def abteilung_management_page():
        set_current_path('/abteilungen')
        create_navigation()
        current_user = AuthHelper.get_current_user()
        
        ui.label('Abteilungsverwaltung').classes('text-h4 q-mb-md q-mt-md q-ml-md')
        
        columns = [
            {'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'kuerzel', 'label': 'Kürzel', 'field': 'kuerzel', 'align': 'left'},
            {'name': 'beschreibung', 'label': 'Beschreibung', 'field': 'beschreibung', 'align': 'left'},
            {'name': 'actions', 'label': 'Aktionen', 'field': 'actions', 'align': 'center'},
        ]
        
        def load_abteilungen():
            abteilungen = db.list_abteilungen()
            return [
                {
                    'id': a.id,
                    'name': a.name,
                    'kuerzel': a.kuerzel or '',
                    'beschreibung': a.beschreibung or '',
                    'version': a.version,
                }
                for a in abteilungen
            ]
        
        with ui.card().classes('w-full q-ma-md'):
            table = ui.table(columns=columns, rows=load_abteilungen(), row_key='id').classes('w-full')
            table.add_slot('body-cell-actions', '''
                <q-td :props="props">
                    <q-btn flat dense icon="edit" @click="$parent.$emit('edit', props.row)" />
                    <q-btn flat dense icon="delete" @click="$parent.$emit('delete', props.row)" />
                </q-td>
            ''')
            
            def show_create_dialog():
                with ui.dialog() as dialog, ui.card():
                    ui.label('Neue Abteilung anlegen').classes('text-h6 q-mb-md')
                    
                    name = ui.input('Name').props('autofocus')
                    kuerzel = ui.input('Kürzel')
                    beschreibung = ui.textarea('Beschreibung')
                    
                    error_label = ui.label('').classes('text-negative')
                    error_label.visible = False
                    
                    def create_abteilung():
                        error_label.visible = False
                        
                        if not name.value:
                            error_label.text = 'Bitte Name eingeben'
                            error_label.visible = True
                            return
                        
                        try:
                            abt = Abteilung(
                                name=name.value,
                                kuerzel=kuerzel.value,
                                beschreibung=beschreibung.value
                            )
                            db.create_abteilung(abt, created_by=current_user.username)
                            table.rows = load_abteilungen()
                            table.update()
                            dialog.close()
                            ui.notify('Abteilung erfolgreich angelegt', type='positive')
                        except Exception as e:
                            error_label.text = f'Fehler: {str(e)}'
                            error_label.visible = True
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close)
                        ui.button('Anlegen', on_click=create_abteilung).props('color=primary')
                
                dialog.open()
            
            def show_edit_dialog(row):
                abt = db.get_abteilung(row['id'])
                
                with ui.dialog() as dialog, ui.card():
                    ui.label(f'Abteilung bearbeiten: {abt.name}').classes('text-h6 q-mb-md')
                    
                    name_input = ui.input('Name', value=abt.name)
                    kuerzel_input = ui.input('Kürzel', value=abt.kuerzel or '')
                    beschreibung_input = ui.textarea('Beschreibung', value=abt.beschreibung or '')
                    
                    error_label = ui.label('').classes('text-negative')
                    error_label.visible = False
                    
                    def update_abteilung():
                        error_label.visible = False
                        
                        if not name_input.value:
                            error_label.text = 'Bitte Name eingeben'
                            error_label.visible = True
                            return
                        
                        try:
                            abt.name = name_input.value
                            abt.kuerzel = kuerzel_input.value
                            abt.beschreibung = beschreibung_input.value
                            
                            success = db.update_abteilung(abt, updated_by=current_user.username)
                            if not success:
                                error_label.text = 'Update fehlgeschlagen - Versionkonflikt'
                                error_label.visible = True
                                return
                            
                            table.rows = load_abteilungen()
                            table.update()
                            dialog.close()
                            ui.notify('Abteilung erfolgreich aktualisiert', type='positive')
                        except Exception as e:
                            error_label.text = f'Fehler: {str(e)}'
                            error_label.visible = True
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close)
                        ui.button('Speichern', on_click=update_abteilung).props('color=primary')
                
                dialog.open()
            
            def show_delete_dialog(row):
                abt = db.get_abteilung(row['id'])
                
                with ui.dialog() as dialog, ui.card():
                    ui.label(f'Abteilung löschen?').classes('text-h6 q-mb-md')
                    ui.label(f'Soll die Abteilung "{abt.name}" wirklich gelöscht werden?')
                    
                    # Prüfen ob Löschung möglich
                    can_delete = db.can_delete_abteilung(abt.id)
                    if not can_delete:
                        ui.label('Diese Abteilung kann nicht gelöscht werden, da sie noch verwendet wird.').classes('text-warning q-mt-sm')
                    else:
                        ui.label('Gelöschte Abteilungen können später wiederhergestellt werden.').classes('text-caption q-mt-sm')
                    
                    def delete_abteilung():
                        try:
                            success = db.delete_abteilung(abt.id, deleted_by=current_user.username)
                            if success:
                                table.rows = load_abteilungen()
                                table.update()
                                dialog.close()
                                ui.notify('Abteilung erfolgreich gelöscht', type='positive')
                            else:
                                ui.notify('Abteilung kann nicht gelöscht werden (wird noch verwendet)', type='negative')
                                dialog.close()
                        except Exception as e:
                            ui.notify(f'Fehler: {str(e)}', type='negative')
                            dialog.close()
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close).props('color=secondary')
                        if can_delete:
                            ui.button('Löschen', on_click=delete_abteilung).props('color=negative')
                
                dialog.open()
            
            def show_deleted_abteilungen_dialog():
                """Zeigt Dialog mit gelöschten Abteilungen und Wiederherstellungs-Option"""
                deleted_columns = [
                    {'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left', 'sortable': True},
                    {'name': 'kuerzel', 'label': 'Kürzel', 'field': 'kuerzel', 'align': 'left'},
                    {'name': 'deleted_at', 'label': 'Gelöscht am', 'field': 'deleted_at', 'align': 'left'},
                    {'name': 'deleted_by', 'label': 'Gelöscht von', 'field': 'deleted_by', 'align': 'left'},
                    {'name': 'actions', 'label': 'Aktionen', 'field': 'actions', 'align': 'center'},
                ]
                
                def load_deleted_abteilungen():
                    deleted = db.list_deleted_abteilungen()
                    return [
                        {
                            'id': d['id'],
                            'name': d['name'],
                            'kuerzel': d['kuerzel'] or '',
                            'beschreibung': d['beschreibung'] or '',
                            'deleted_at': d['deleted_at'][:19] if d['deleted_at'] else '',  # Format timestamp
                            'deleted_by': d['deleted_by'] or '',
                        }
                        for d in deleted
                    ]
                
                with ui.dialog() as deleted_dialog, ui.card().style('min-width: 800px'):
                    ui.label('Gelöschte Abteilungen').classes('text-h6 q-mb-md')
                    
                    deleted_rows = load_deleted_abteilungen()
                    
                    if not deleted_rows:
                        ui.label('Keine gelöschten Abteilungen vorhanden.').classes('text-body2 q-mb-md')
                    else:
                        deleted_table = ui.table(
                            columns=deleted_columns, 
                            rows=deleted_rows, 
                            row_key='id'
                        ).classes('w-full')
                        
                        deleted_table.add_slot('body-cell-actions', '''
                            <q-td :props="props">
                                <q-btn flat dense icon="restore" color="positive" 
                                       @click="$parent.$emit('restore', props.row)">
                                    <q-tooltip>Wiederherstellen</q-tooltip>
                                </q-btn>
                            </q-td>
                        ''')
                        
                        def restore_abteilung(row):
                            """Stellt eine gelöschte Abteilung wieder her"""
                            with ui.dialog() as restore_dialog, ui.card():
                                ui.label(f'Abteilung wiederherstellen?').classes('text-h6 q-mb-md')
                                ui.label(f'Soll die Abteilung "{row["name"]}" wiederhergestellt werden?')
                                
                                def do_restore():
                                    try:
                                        success = db.restore_abteilung(row['id'], restored_by=current_user.username)
                                        if success:
                                            # Update beide Tabellen
                                            table.rows = load_abteilungen()
                                            table.update()
                                            deleted_table.rows = load_deleted_abteilungen()
                                            deleted_table.update()
                                            
                                            restore_dialog.close()
                                            ui.notify('Abteilung erfolgreich wiederhergestellt', type='positive')
                                            
                                            # Schließe den gelöschte-Abteilungen-Dialog wenn leer
                                            if not deleted_table.rows:
                                                deleted_dialog.close()
                                        else:
                                            ui.notify('Wiederherstellung fehlgeschlagen', type='negative')
                                            restore_dialog.close()
                                    except Exception as e:
                                        ui.notify(f'Fehler: {str(e)}', type='negative')
                                        restore_dialog.close()
                                
                                with ui.row().classes('w-full'):
                                    ui.button('Abbrechen', on_click=restore_dialog.close).props('color=secondary')
                                    ui.button('Wiederherstellen', on_click=do_restore).props('color=positive')
                            
                            restore_dialog.open()
                        
                        deleted_table.on('restore', lambda e: restore_abteilung(e.args))
                    
                    with ui.row().classes('w-full q-mt-md'):
                        ui.button('Schließen', on_click=deleted_dialog.close).props('color=secondary')
                
                deleted_dialog.open()
            
            table.on('edit', lambda e: show_edit_dialog(e.args))
            table.on('delete', lambda e: show_delete_dialog(e.args))
            
            # Button-Leiste
            with ui.row().classes('q-mt-md'):
                ui.button('Neue Abteilung anlegen', on_click=show_create_dialog, icon='add').props('color=primary')
                ui.button('Gelöschte Abteilungen anzeigen', on_click=show_deleted_abteilungen_dialog, icon='delete_sweep').props('color=secondary outline')
