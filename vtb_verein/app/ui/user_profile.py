"""
User-Profil-Seite - User können hier ihr eigenes Passwort ändern
"""
from nicegui import ui
from app.services.user_service import UserService
from app.auth.auth_helper import AuthHelper, require_auth
from app.db.datastore import VereinsDB
from app.ui.navigation import create_navigation, set_current_path

def create_user_profile_page(db: VereinsDB):
    """Erstellt die User-Profil-Seite"""
    
    @ui.page('/profile')
    @require_auth()
    def user_profile_page():
        set_current_path('/profile')
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
            ui.label('Mein Profil').classes('text-h4 q-mb-md')
            
            # Profil-Informationen
            with ui.card().classes('q-mb-md'):
                ui.label('Profil-Informationen').classes('text-h6 q-mb-md')
                
                with ui.grid(columns=2).classes('w-full'):
                    ui.label('Benutzername:').classes('text-weight-bold')
                    ui.label(current_user.username)
                    
                    ui.label('E-Mail:').classes('text-weight-bold')
                    ui.label(current_user.email)
                    
                    ui.label('Rolle:').classes('text-weight-bold')
                    ui.label(role_labels.get(current_user.role, current_user.role))
                    
                    ui.label('Letzter Login:').classes('text-weight-bold')
                    ui.label(current_user.last_login or 'Noch nie')
            
            # Passwort ändern
            with ui.card().classes('q-mb-md'):
                ui.label('Passwort ändern').classes('text-h6 q-mb-md')
                
                # Info-Text
                with ui.card().classes('bg-blue-1 q-mb-md'):
                    ui.label('ℹ️ Hinweis').classes('text-weight-bold')
                    ui.label('Du kannst hier dein Passwort setzen oder ändern.').classes('text-caption')
                    ui.label('Alternativ kannst du dich weiterhin per Magic-Link einloggen.').classes('text-caption')
                
                password = ui.input('Neues Passwort', password=True, password_toggle_button=True)
                password_confirm = ui.input('Passwort wiederholen', password=True)
                
                error_label = ui.label('').classes('text-negative')
                error_label.visible = False
                
                success_label = ui.label('').classes('text-positive')
                success_label.visible = False
                
                def change_password():
                    error_label.visible = False
                    success_label.visible = False
                    
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
                            user_id=current_user.id,
                            new_password=password.value,
                            updated_by=current_user.username
                        )
                        
                        # Felder zurücksetzen
                        password.value = ''
                        password_confirm.value = ''
                        
                        success_label.text = '✅ Passwort erfolgreich geändert!'
                        success_label.visible = True
                        
                    except Exception as e:
                        error_label.text = f'Fehler: {str(e)}'
                        error_label.visible = True
                
                ui.button('Passwort ändern', on_click=change_password, icon='vpn_key').props('color=primary')
