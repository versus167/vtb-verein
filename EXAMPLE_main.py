"""
Beispiel: Hauptdatei mit User-System Integration
"""
from nicegui import ui, app
from app.db.datastore import VereinsDB
from app.ui.login_page import create_login_page
from app.ui.user_management import create_user_management_page
from app.auth.auth_helper import AuthHelper, require_auth

# Datenbank initialisieren
db = VereinsDB('verein.db')

# Login-Page registrieren
create_login_page(db)

# User-Management registrieren
create_user_management_page(db)

# Beispiel für geschützte Hauptseite
@ui.page('/')
@require_auth()
def main_page():
    user = AuthHelper.get_current_user()
    
    with ui.header():
        ui.label('Vereinsverwaltung').classes('text-h5')
        ui.space()
        ui.label(f'Angemeldet als: {user.username} ({user.role})').classes('text-caption')
        ui.button('Logout', on_click=lambda: (AuthHelper.logout(), ui.navigate.to('/login')))
    
    ui.label(f'Willkommen, {user.username}!').classes('text-h4')
    
    # Navigation
    with ui.row():
        if user.can_manage_users():
            ui.button('Benutzerverwaltung', on_click=lambda: ui.navigate.to('/users'), icon='people')
        
        ui.button('Abteilungen', on_click=lambda: ui.navigate.to('/abteilungen'), icon='groups')

# Unauthorized-Seite
@ui.page('/unauthorized')
def unauthorized():
    with ui.card().classes('absolute-center'):
        ui.label('Keine Berechtigung').classes('text-h5 text-negative')
        ui.label('Sie haben keine Berechtigung für diese Seite.')
        ui.button('Zurück', on_click=lambda: ui.navigate.to('/')).props('color=primary')

ui.run(storage_secret='YOUR_SECRET_KEY_HERE')
