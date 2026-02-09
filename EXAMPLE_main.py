"""
Beispiel: Hauptdatei mit User-System Integration
"""
from nicegui import ui, app
from app.db.datastore import VereinsDB
from app.ui.login_page import create_login_page
from app.ui.user_management import create_user_management_page
from app.ui.abteilung_management import create_abteilung_management_page
from app.ui.navigation import create_navigation
from app.auth.auth_helper import AuthHelper, require_auth

# Datenbank initialisieren
db = VereinsDB('verein.db')

# Login-Page registrieren
create_login_page(db)

# User-Management registrieren
create_user_management_page(db)

# Abteilungs-Management registrieren
create_abteilung_management_page(db)

# Beispiel für geschützte Hauptseite
@ui.page('/')
@require_auth()
def main_page():
    create_navigation()
    user = AuthHelper.get_current_user()
    
    with ui.column().classes('q-ma-md'):
        ui.label(f'Willkommen, {user.username}!').classes('text-h4')
        
        ui.label('Was möchten Sie tun?').classes('text-subtitle1 q-mt-md')
        
        # Dashboard Cards
        with ui.row().classes('q-mt-md'):
            if user.can_edit():
                with ui.card().classes('cursor-pointer').on('click', lambda: ui.navigate.to('/abteilungen')):
                    with ui.card_section():
                        ui.icon('groups', size='xl').classes('text-primary')
                        ui.label('Abteilungen').classes('text-h6')
                        ui.label('Abteilungen verwalten').classes('text-caption')
            
            if user.can_manage_users():
                with ui.card().classes('cursor-pointer').on('click', lambda: ui.navigate.to('/users')):
                    with ui.card_section():
                        ui.icon('people', size='xl').classes('text-primary')
                        ui.label('Benutzerverwaltung').classes('text-h6')
                        ui.label('Benutzer und Rechte verwalten').classes('text-caption')

# Unauthorized-Seite
@ui.page('/unauthorized')
def unauthorized():
    with ui.card().classes('absolute-center'):
        ui.label('Keine Berechtigung').classes('text-h5 text-negative')
        ui.label('Sie haben keine Berechtigung für diese Seite.')
        ui.button('Zurück', on_click=lambda: ui.navigate.to('/')).props('color=primary')

ui.run(storage_secret='YOUR_SECRET_KEY_HERE')
