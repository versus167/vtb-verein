#!/usr/bin/env python3
"""
Vereins-Mitgliederverwaltung
Haupteinstiegspunkt für die Anwendung (unter vtb_verein/)
"""
import os
from nicegui import ui
from app.db.datastore import VereinsDB
from app.ui.login_page import create_login_page
from app.ui.user_management import create_user_management_page
from app.ui.abteilung_management import create_abteilung_management_page
from app.ui.navigation import create_navigation
from app.auth.auth_helper import AuthHelper, require_auth

# Konfiguration
DB_PATH = os.getenv('VTB_DB_PATH', 'verein.db')
STORAGE_SECRET = os.getenv('VTB_STORAGE_SECRET', 'CHANGE_ME_IN_PRODUCTION')
HOST = os.getenv('VTB_HOST', '0.0.0.0')
PORT = int(os.getenv('VTB_PORT', '8080'))

print("\n=== Vereinsverwaltung ===")
print(f"Datenbank: {DB_PATH}")
print(f"Host: {HOST}:{PORT}")
print("=" * 30 + "\n")

# Datenbank initialisieren
db = VereinsDB(DB_PATH)

# Seiten registrieren
create_login_page(db)
create_user_management_page(db)
create_abteilung_management_page(db)

# Hauptseite (Dashboard)
@ui.page('/')
@require_auth()
def main_page():
    create_navigation()
    user = AuthHelper.get_current_user()

    with ui.column().classes('q-ma-md'):
        ui.label(f'Willkommen, {user.username}!').classes('text-h4')

        ui.label('Was möchten Sie tun?').classes('text-subtitle1 q-mt-md q-mb-md')

        # Dashboard Cards
        with ui.row().classes('q-gutter-md'):
            # Abteilungen
            if user.can_edit():
                with ui.card().classes('cursor-pointer hover-shadow').style('min-width: 200px').on('click', lambda: ui.navigate.to('/abteilungen')):
                    with ui.card_section().classes('text-center'):
                        ui.icon('groups', size='3rem').classes('text-primary')
                        ui.label('Abteilungen').classes('text-h6 q-mt-sm')
                        ui.label('Abteilungen verwalten').classes('text-caption text-grey')

            # Benutzerverwaltung
            if user.can_manage_users():
                with ui.card().classes('cursor-pointer hover-shadow').style('min-width: 200px').on('click', lambda: ui.navigate.to('/users')):
                    with ui.card_section().classes('text-center'):
                        ui.icon('people', size='3rem').classes('text-primary')
                        ui.label('Benutzerverwaltung').classes('text-h6 q-mt-sm')
                        ui.label('Benutzer und Rechte verwalten').classes('text-caption text-grey')

            # Platzhalter für zukünftige Module
            if user.can_edit():
                with ui.card().classes('cursor-pointer').style('min-width: 200px; opacity: 0.5'):
                    with ui.card_section().classes('text-center'):
                        ui.icon('group', size='3rem').classes('text-grey')
                        ui.label('Mitglieder').classes('text-h6 q-mt-sm text-grey')
                        ui.label('Bald verfügbar').classes('text-caption text-grey')

                with ui.card().classes('cursor-pointer').style('min-width: 200px; opacity: 0.5'):
                    with ui.card_section().classes('text-center'):
                        ui.icon('payments', size='3rem').classes('text-grey')
                        ui.label('Beiträge').classes('text-h6 q-mt-sm text-grey')
                        ui.label('Bald verfügbar').classes('text-caption text-grey')

# Unauthorized-Seite
@ui.page('/unauthorized')
def unauthorized():
    with ui.card().classes('absolute-center'):
        ui.label('Keine Berechtigung').classes('text-h5 text-negative')
        ui.label('Sie haben keine Berechtigung für diese Seite.')
        ui.button('Zurück zur Startseite', on_click=lambda: ui.navigate.to('/')).props('color=primary')

# Multiprocessing-kompatible Main-Guard (wie von NiceGUI empfohlen)
if __name__ in {'__main__', '__mp_main__'}:
    # Starte die Anwendung
    ui.run(
        storage_secret=STORAGE_SECRET,
        host=HOST,
        port=PORT,
        title='Vereinsverwaltung',
        favicon='🏛️',
    )
