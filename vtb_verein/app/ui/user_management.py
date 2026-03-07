"""
Benutzerverwaltungs-Seite
"""
from nicegui import ui
from app.services.user_service import UserService
from app.auth.auth_helper import AuthHelper, require_role
from app.db.datastore import VereinsDB
from app.ui.navigation import create_navigation, set_current_path
from app.models.user import User

def create_user_management_page(db: VereinsDB):
    """Erstellt die Benutzerverwaltungs-Seite"""
    
    @ui.page('/users')
    @require_role('admin')
    def user_management_page():
        set_current_path('/users')
        create_navigation()
        user_service = UserService(db)
        current_user = AuthHelper.get_current_user()
        
        # Rollen-Mapping für Anzeige
        role_labels = {
            'admin': 'Administrator',
            'user': 'Bearbeiter',
            'readonly': 'Nur Lesen',
            'special': 'Spezielle Funktion'
        }
        
        with ui.column().classes('q-ma-md'):
            ui.label('Benutzerverwaltung').classes('text-h4 q-mb-md')
            
            columns = [
                {'name': 'username', 'label': 'Benutzername', 'field': 'username', 'align': 'left'},
                {'name': 'email', 'label': 'E-Mail', 'field': 'email', 'align': 'left'},
                {'name': 'role', 'label': 'Rolle', 'field': 'role', 'align': 'left'},
                {'name': 'active', 'label': 'Aktiv', 'field': 'active', 'align': 'center'},
                {'name': 'last_login', 'label': 'Letzter Login', 'field': 'last_login', 'align': 'left'},
                {'name': 'actions', 'label': 'Aktionen', 'field': 'actions', 'align': 'center'},
            ]
            
            def load_users():
                users = user_service.list_all()
                return [
                    {
                        'id': u.id,
                        'username': u.username,
                        'email': u.email,
                        'role': role_labels.get(u.role, u.role),
                        'active': '✓' if u.active else '✗',
                        'last_login': u.last_login or 'Noch nie',
                        'version': u.version,
                        'role_key': u.role,  # Original-Rolle für Vergleich
                        'is_admin': u.role == 'admin',
                        'is_active': u.active,
                    }
                    for u in users
                ]
            
            table = ui.table(columns=columns, rows=load_users(), row_key='id').classes('w-full')
            table.add_slot('body-cell-actions', f'''
                <q-td :props="props">
                    <q-btn flat dense icon="edit" @click="$parent.$emit('edit', props.row)" />
                    <q-btn flat dense icon="vpn_key" @click="$parent.$emit('change_password', props.row)" />
                    <q-btn flat dense icon="delete" @click="$parent.$emit('delete', props.row)" 
                           :disable="props.row.username === '{current_user.username}'" />
                </q-td>
            ''')
            
            def show_create_dialog():
                with ui.dialog() as dialog, ui.card():
                    ui.label('Neuen Benutzer anlegen').classes('text-h6 q-mb-md')
                    
                    username = ui.input('Benutzername').props('autofocus')
                    email = ui.input('E-Mail')
                    password = ui.input('Passwort', password=True, password_toggle_button=True)
                    password_confirm = ui.input('Passwort wiederholen', password=True)
                    
                    role = ui.select(
                        label='Rolle',
                        options=User.get_available_roles(),
                        value='user'
                    )
                    
                    active = ui.checkbox('Aktiv', value=True)
                    
                    error_label = ui.label('').classes('text-negative')
                    error_label.visible = False
                    
                    def create_user():
                        error_label.visible = False
                        
                        if not username.value or not email.value or not password.value:
                            error_label.text = 'Bitte alle Felder ausfüllen'
                            error_label.visible = True
                            return
                        
                        if password.value != password_confirm.value:
                            error_label.text = 'Passwörter stimmen nicht überein'
                            error_label.visible = True
                            return
                        
                        if len(password.value) < 6:
                            error_label.text = 'Passwort muss mindestens 6 Zeichen lang sein'
                            error_label.visible = True
                            return
                        
                        try:
                            user_service.create(
                                username=username.value,
                                email=email.value,
                                password=password.value,
                                role=role.value,
                                active=active.value,
                                created_by=current_user.username
                            )
                            table.rows = load_users()
                            table.update()
                            dialog.close()
                            ui.notify('Benutzer erfolgreich angelegt', type='positive')
                        except Exception as e:
                            error_label.text = f'Fehler: {str(e)}'
                            error_label.visible = True
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close)
                        ui.button('Anlegen', on_click=create_user).props('color=primary')
                
                dialog.open()
            
            def show_edit_dialog(row):
                user = user_service.get_by_id(row['id'])
                
                with ui.dialog() as dialog, ui.card():
                    ui.label(f'Benutzer bearbeiten: {user.username}').classes('text-h6 q-mb-md')
                    
                    username_input = ui.input('Benutzername', value=user.username)
                    email_input = ui.input('E-Mail', value=user.email)
                    
                    role_input = ui.select(
                        label='Rolle',
                        options=User.get_available_roles(),
                        value=user.role
                    )
                    
                    active_input = ui.checkbox('Aktiv', value=user.active)
                    
                    # Warnung anzeigen, wenn letzter Admin betroffen ist
                    warning_label = ui.label('')
                    warning_label.classes('text-warning q-mt-sm')
                    warning_label.visible = False
                    
                    def check_admin_warning():
                        """Prüft, ob der letzte aktive Admin betroffen ist"""
                        # Nur prüfen, wenn User aktuell ein aktiver Admin ist
                        if row['is_admin'] and row['is_active']:
                            active_admins = user_service.count_active_admins()
                            
                            # Prüfe ob Admin inaktiv wird (Rolle bleibt admin, aber Status wird false)
                            will_be_deactivated = (role_input.value == 'admin' and not active_input.value)
                            
                            # Prüfe ob Admin herabgestuft wird (Rolle wird geändert, egal ob aktiv)
                            will_be_demoted = (role_input.value != 'admin')
                            
                            if (will_be_deactivated or will_be_demoted) and active_admins <= 1:
                                warning_label.text = '⚠️ Achtung: Dies ist der letzte aktive Administrator!'
                                warning_label.visible = True
                                save_button.disable()
                            else:
                                warning_label.visible = False
                                save_button.enable()
                        else:
                            warning_label.visible = False
                            save_button.enable()
                    
                    # Überwache Änderungen an Rolle und Status
                    active_input.on('update:model-value', check_admin_warning)
                    role_input.on('update:model-value', check_admin_warning)
                    
                    error_label = ui.label('').classes('text-negative')
                    error_label.visible = False
                    
                    def update_user():
                        error_label.visible = False
                        
                        try:
                            user_service.update(
                                user_id=user.id,
                                username=username_input.value,
                                email=email_input.value,
                                role=role_input.value,
                                active=active_input.value,
                                updated_by=current_user.username,
                                expected_version=row['version']
                            )
                            table.rows = load_users()
                            table.update()
                            dialog.close()
                            ui.notify('Benutzer erfolgreich aktualisiert', type='positive')
                        except ValueError as e:
                            error_label.text = str(e)
                            error_label.visible = True
                        except Exception as e:
                            error_label.text = f'Fehler: {str(e)}'
                            error_label.visible = True
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close)
                        save_button = ui.button('Speichern', on_click=update_user).props('color=primary')
                
                dialog.open()
            
            def show_change_password_dialog(row):
                user = user_service.get_by_id(row['id'])
                
                with ui.dialog() as dialog, ui.card():
                    ui.label(f'Passwort ändern: {user.username}').classes('text-h6 q-mb-md')
                    
                    password = ui.input('Neues Passwort', password=True, password_toggle_button=True).props('autofocus')
                    password_confirm = ui.input('Passwort wiederholen', password=True)
                    
                    error_label = ui.label('').classes('text-negative')
                    error_label.visible = False
                    
                    def change_password():
                        error_label.visible = False
                        
                        if not password.value:
                            error_label.text = 'Bitte Passwort eingeben'
                            error_label.visible = True
                            return
                        
                        if password.value != password_confirm.value:
                            error_label.text = 'Passwörter stimmen nicht überein'
                            error_label.visible = True
                            return
                        
                        if len(password.value) < 6:
                            error_label.text = 'Passwort muss mindestens 6 Zeichen lang sein'
                            error_label.visible = True
                            return
                        
                        try:
                            user_service.change_password(
                                user_id=user.id,
                                new_password=password.value,
                                updated_by=current_user.username
                            )
                            dialog.close()
                            ui.notify('Passwort erfolgreich geändert', type='positive')
                        except Exception as e:
                            error_label.text = f'Fehler: {str(e)}'
                            error_label.visible = True
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close)
                        ui.button('Passwort ändern', on_click=change_password).props('color=primary')
                
                dialog.open()
            
            def show_delete_dialog(row):
                user = user_service.get_by_id(row['id'])
                
                with ui.dialog() as dialog, ui.card():
                    ui.label(f'Benutzer löschen?').classes('text-h6 q-mb-md')
                    ui.label(f'Soll der Benutzer "{user.username}" wirklich gelöscht werden?')
                    ui.label('Gelöschte Benutzer können später wiederhergestellt werden.').classes('text-caption q-mt-sm')
                    
                    def delete_user():
                        try:
                            user_service.delete(user.id, deleted_by=current_user.username)
                            table.rows = load_users()
                            table.update()
                            dialog.close()
                            ui.notify('Benutzer erfolgreich gelöscht', type='positive')
                        except ValueError as e:
                            ui.notify(str(e), type='warning')
                            dialog.close()
                        except Exception as e:
                            ui.notify(f'Fehler: {str(e)}', type='negative')
                            dialog.close()
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close).props('color=secondary')
                        ui.button('Löschen', on_click=delete_user).props('color=negative')
                
                dialog.open()
            
            table.on('edit', lambda e: show_edit_dialog(e.args))
            table.on('change_password', lambda e: show_change_password_dialog(e.args))
            table.on('delete', lambda e: show_delete_dialog(e.args))
            
            ui.button('Neuen Benutzer anlegen', on_click=show_create_dialog, icon='add').props('color=primary')
