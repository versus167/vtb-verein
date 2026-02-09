"""
Login-Seite für Vereinsverwaltung
"""
from nicegui import ui, app
from app.services.user_service import UserService
from app.auth.auth_helper import AuthHelper
from app.db.datastore import VereinsDB

def create_login_page(db: VereinsDB):
    """Erstellt die Login-Seite"""
    
    @ui.page('/login')
    def login_page():
        # Falls bereits eingeloggt, weiterleiten
        if AuthHelper.is_authenticated():
            ui.navigate.to('/')
            return
        
        user_service = UserService(db)
        
        with ui.card().classes('absolute-center'):
            ui.label('Vereinsverwaltung').classes('text-h4 text-center q-mb-md')
            ui.label('Anmelden').classes('text-h6 text-center q-mb-lg')
            
            username_input = ui.input('Benutzername').props('autofocus')
            password_input = ui.input('Passwort', password=True, password_toggle_button=True)
            
            error_label = ui.label('').classes('text-negative q-mt-sm')
            error_label.visible = False
            
            def do_login():
                error_label.visible = False
                
                username = username_input.value
                password = password_input.value
                
                if not username or not password:
                    error_label.text = 'Bitte Benutzername und Passwort eingeben'
                    error_label.visible = True
                    return
                
                user = user_service.authenticate(username, password)
                
                if user:
                    AuthHelper.set_current_user(user)
                    ui.navigate.to('/')
                else:
                    error_label.text = 'Ungültiger Benutzername oder Passwort'
                    error_label.visible = True
                    password_input.value = ''
            
            password_input.on('keydown.enter', do_login)
            
            with ui.row().classes('w-full'):
                ui.button('Anmelden', on_click=do_login).props('color=primary').classes('flex-1')
