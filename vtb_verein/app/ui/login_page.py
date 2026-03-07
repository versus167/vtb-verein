"""
Login-Seite für Vereinsverwaltung mit Password und Magic-Link Support
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
        
        with ui.card().classes('absolute-center').style('min-width: 400px'):
            ui.label('Vereinsverwaltung').classes('text-h4 text-center q-mb-md')
            ui.label('Anmelden').classes('text-h6 text-center q-mb-lg')
            
            # Tabs für Password und Magic-Link Login
            with ui.tabs().classes('w-full') as tabs:
                tab_password = ui.tab('Passwort')
                tab_magic = ui.tab('Login-Link')
            
            with ui.tab_panels(tabs, value=tab_password).classes('w-full'):
                # ============================================
                # Tab 1: Password-Login
                # ============================================
                with ui.tab_panel(tab_password):
                    username_input = ui.input('Benutzername').props('autofocus').classes('w-full')
                    password_input = ui.input('Passwort', password=True, password_toggle_button=True).classes('w-full')
                    
                    remember_me_checkbox = ui.checkbox('Angemeldet bleiben (bis zu 30 Tage)', value=False)
                    
                    error_label = ui.label('').classes('text-negative q-mt-sm')
                    error_label.visible = False
                    
                    def do_login():
                        error_label.visible = False
                        
                        username = username_input.value
                        password = password_input.value
                        remember_me = remember_me_checkbox.value
                        
                        if not username or not password:
                            error_label.text = 'Bitte Benutzername und Passwort eingeben'
                            error_label.visible = True
                            return
                        
                        user = user_service.authenticate(username, password)
                        
                        if user:
                            # Session mit Remember-Me setzen
                            AuthHelper.set_current_user(user, remember_me=remember_me)
                            ui.navigate.to('/')
                        else:
                            error_label.text = 'Ungültiger Benutzername oder Passwort'
                            error_label.visible = True
                            password_input.value = ''
                    
                    password_input.on('keydown.enter', do_login)
                    
                    with ui.row().classes('w-full q-mt-md'):
                        ui.button('Anmelden', on_click=do_login).props('color=primary').classes('flex-1')
                
                # ============================================
                # Tab 2: Magic-Link anfordern
                # ============================================
                with ui.tab_panel(tab_magic):
                    ui.label('Erhalte einen Login-Link per E-Mail').classes('text-body2 q-mb-md')
                    
                    email_input = ui.input('E-Mail-Adresse').classes('w-full').props('type=email')
                    
                    magic_success = ui.label('').classes('text-positive q-mt-sm')
                    magic_success.visible = False
                    
                    magic_error = ui.label('').classes('text-negative q-mt-sm')
                    magic_error.visible = False
                    
                    def request_magic_link():
                        magic_success.visible = False
                        magic_error.visible = False
                        
                        email = email_input.value
                        
                        if not email:
                            magic_error.text = 'Bitte E-Mail-Adresse eingeben'
                            magic_error.visible = True
                            return
                        
                        # Magic-Link anfordern
                        success = user_service.send_magic_link(email)
                        
                        if success:
                            magic_success.text = f'Login-Link wurde an {email} gesendet. Bitte überprüfe dein Postfach.'
                            magic_success.visible = True
                            email_input.value = ''
                        else:
                            magic_error.text = 'E-Mail-Adresse nicht gefunden oder E-Mail-Versand fehlgeschlagen.'
                            magic_error.visible = True
                    
                    email_input.on('keydown.enter', request_magic_link)
                    
                    with ui.row().classes('w-full q-mt-md'):
                        ui.button('Login-Link anfordern', on_click=request_magic_link).props('color=secondary').classes('flex-1')
                    
                    ui.label('Der Link ist 7 Tage gültig und kann nur einmal verwendet werden.').classes('text-caption text-grey q-mt-md')
