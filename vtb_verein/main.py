#!/usr/bin/env python3
"""
Vereins-Mitgliederverwaltung
Haupteinstiegspunkt für die Anwendung (unter vtb_verein/)
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from nicegui import ui, app as nicegui_app
from fastapi import Request
from fastapi.responses import FileResponse, Response
from app.db.datastore import VereinsDB
from app.ui.login_page import create_login_page
from app.ui.magic_link_page import create_magic_link_page
from app.ui.user_management import create_user_management_page
from app.ui.permission_management import create_permission_management_page
from app.ui.user_profile import create_user_profile_page
from app.ui.abteilung_management import create_abteilung_management_page
from app.ui.mitglied_management import create_mitglied_management_page
from app.ui.kasse_management import create_kasse_management_page
from app.ui.kassenbuch_page import create_kassenbuch_page
from app.ui.ticket_page import create_ticket_pages
from app.ui.navigation import create_navigation, set_current_path
from app.auth.auth_helper import AuthHelper, require_auth
from app.config.email_config import EmailConfig
from app.config.app_info import get_app_version
from app.models.permission import Permission

# .env-Datei laden (muss VOR os.getenv() aufgerufen werden!)
load_dotenv()

# Konfiguration
DB_PATH = os.getenv('VTB_DB_PATH', 'verein.db')
UPLOAD_PATH = os.getenv('VTB_UPLOAD_PATH', 'uploads/')
STORAGE_SECRET = os.getenv('VTB_STORAGE_SECRET', 'CHANGE_ME_IN_PRODUCTION')
HOST = os.getenv('VTB_HOST', '0.0.0.0')
PORT = int(os.getenv('VTB_PORT', '8080'))

print("\n=== Vereinsverwaltung ===")
print(f"Version: {get_app_version()}")
print(f"Datenbank: {DB_PATH}")
print(f"Uploads:   {UPLOAD_PATH}")
print(f"Host: {HOST}:{PORT}")

# E-Mail-Status ausgeben
if EmailConfig.is_configured():
    print(f"E-Mail: \u2705 Konfiguriert ({EmailConfig.get_smtp_server()})")
else:
    print("E-Mail: \u26a0\ufe0f  Nicht konfiguriert - Magic-Link-Login nicht verf\u00fcgbar")

print("=" * 30 + "\n")

# Datenbank initialisieren
db = VereinsDB(DB_PATH, upload_path=UPLOAD_PATH)

_EXT_TO_MIME = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.png': 'image/png', '.gif': 'image/gif',
    '.webp': 'image/webp', '.pdf': 'application/pdf',
}
_NICEGUI_STORAGE_PATH = Path(os.environ.get('NICEGUI_STORAGE_PATH', '.nicegui')).resolve()


@nicegui_app.get('/uploads/{stored_name}')
async def download_anhang(stored_name: str, request: Request) -> Response:
    """Geschützter Download-Endpunkt für Anhänge. Prüft NiceGUI-Session."""
    if '/' in stored_name or '\\' in stored_name or '..' in stored_name:
        return Response(status_code=400, content='Ungültiger Dateiname')

    session_id = request.session.get('id')
    if not session_id:
        return Response(status_code=401, content='Nicht authentifiziert')

    storage_file = _NICEGUI_STORAGE_PATH / f'storage-user-{session_id}.json'
    try:
        session_data = json.loads(storage_file.read_text(encoding='utf-8'))
        if not session_data.get('authenticated'):
            return Response(status_code=401, content='Nicht authentifiziert')
    except Exception:
        return Response(status_code=401, content='Nicht authentifiziert')

    file_path = Path(UPLOAD_PATH) / stored_name
    if not file_path.is_file():
        return Response(status_code=404, content='Datei nicht gefunden')

    media_type = _EXT_TO_MIME.get(file_path.suffix.lower(), 'application/octet-stream')
    headers = {'Content-Disposition': f'inline; filename="{stored_name}"'} \
        if media_type.startswith('image/') else \
        {'Content-Disposition': f'attachment; filename="{stored_name}"'}
    return FileResponse(str(file_path), media_type=media_type, headers=headers)

# Seiten registrieren
create_login_page(db)
create_magic_link_page(db)
create_user_management_page(db)
create_permission_management_page(db)
create_user_profile_page(db)
create_abteilung_management_page(db)
create_mitglied_management_page(db)
create_kasse_management_page(db)
create_kassenbuch_page(db)
create_ticket_pages(db)

# Hauptseite (Dashboard)
@ui.page('/')
@require_auth()
def main_page():
    set_current_path('/')
    create_navigation(db)
    # Permissions bei jedem Seitenaufruf frisch aus der DB laden,
    # damit Admin-Änderungen sofort wirksam sind (ohne Re-Login).
    user = AuthHelper.refresh_permissions(db.permissions)

    with ui.column().classes('q-ma-md'):
        ui.label(f'Willkommen, {user.username}!').classes('text-h4')

        ui.label('Was m\u00f6chten Sie tun?').classes('text-subtitle1 q-mt-md q-mb-md')

        # Dashboard Cards
        with ui.row().classes('q-gutter-md'):
            # Abteilungen – sichtbar ab ABTEILUNGEN_READ
            if user.has_permission(Permission.ABTEILUNGEN_READ):
                with ui.card().classes('cursor-pointer hover-shadow').style('min-width: 200px').on('click', lambda: ui.navigate.to('/abteilungen')):
                    with ui.card_section().classes('text-center'):
                        ui.icon('groups', size='3rem').classes('text-primary')
                        ui.label('Abteilungen').classes('text-h6 q-mt-sm')
                        ui.label('Abteilungen verwalten').classes('text-caption text-grey')

            # Mitgliederverwaltung – sichtbar ab MITGLIEDER_READ
            if user.has_permission(Permission.MITGLIEDER_READ):
                with ui.card().classes('cursor-pointer hover-shadow').style('min-width: 200px').on('click', lambda: ui.navigate.to('/mitglieder')):
                    with ui.card_section().classes('text-center'):
                        ui.icon('group', size='3rem').classes('text-primary')
                        ui.label('Mitglieder').classes('text-h6 q-mt-sm')
                        ui.label('Mitglieder verwalten').classes('text-caption text-grey')

            # Kassenbuch – sichtbar wenn User mind. einer Kasse zugewiesen ist
            # (kassenspezifische Berechtigung, nicht über globale Permissions)
            is_admin = user.can_manage_users()
            kassen = db.kassenbuch.get_kassen_fuer_user(user.id, is_admin=is_admin)
            if kassen:
                with ui.card().classes('cursor-pointer hover-shadow').style('min-width: 200px').on('click', lambda: ui.navigate.to('/kassenbuch')):
                    with ui.card_section().classes('text-center'):
                        ui.icon('menu_book', size='3rem').classes('text-primary')
                        ui.label('Kassenbuch').classes('text-h6 q-mt-sm')
                        ui.label('Buchungen verwalten').classes('text-caption text-grey')

            # Kassenverwaltung – nur echte Admins (USERS_MANAGE)
            if user.has_permission(Permission.USERS_MANAGE):
                with ui.card().classes('cursor-pointer hover-shadow').style('min-width: 200px').on('click', lambda: ui.navigate.to('/kassen')):
                    with ui.card_section().classes('text-center'):
                        ui.icon('account_balance_wallet', size='3rem').classes('text-primary')
                        ui.label('Kassenverwaltung').classes('text-h6 q-mt-sm')
                        ui.label('Kassen und Berechtigungen').classes('text-caption text-grey')

            # Tickets – sichtbar ab TICKETS_ACCESS
            if user.has_permission(Permission.TICKETS_ACCESS):
                with ui.card().classes('cursor-pointer hover-shadow').style('min-width: 200px').on('click', lambda: ui.navigate.to('/tickets')):
                    with ui.card_section().classes('text-center'):
                        ui.icon('confirmation_number', size='3rem').classes('text-primary')
                        ui.label('Tickets').classes('text-h6 q-mt-sm')
                        ui.label('Anfragen und Aufgaben').classes('text-caption text-grey')

            # Benutzerverwaltung – nur echte Admins (USERS_MANAGE)
            if user.has_permission(Permission.USERS_MANAGE):
                with ui.card().classes('cursor-pointer hover-shadow').style('min-width: 200px').on('click', lambda: ui.navigate.to('/users')):
                    with ui.card_section().classes('text-center'):
                        ui.icon('people', size='3rem').classes('text-primary')
                        ui.label('Benutzerverwaltung').classes('text-h6 q-mt-sm')
                        ui.label('Benutzer und Rechte verwalten').classes('text-caption text-grey')

            # Beiträge (Platzhalter) – sichtbar ab BEITRAEGE_READ
            if user.has_permission(Permission.BEITRAEGE_READ):
                with ui.card().classes('cursor-pointer').style('min-width: 200px; opacity: 0.5'):
                    with ui.card_section().classes('text-center'):
                        ui.icon('payments', size='3rem').classes('text-grey')
                        ui.label('Beiträge').classes('text-h6 q-mt-sm text-grey')
                        ui.label('Bald verfügbar').classes('text-caption text-grey')

        ui.label(f'Version {get_app_version()}').classes('text-caption text-grey q-mt-lg')

# Unauthorized-Seite
@ui.page('/unauthorized')
def unauthorized():
    with ui.card().classes('absolute-center'):
        ui.label('Keine Berechtigung').classes('text-h5 text-negative')
        ui.label('Sie haben keine Berechtigung für diese Seite.')
        ui.button('Zurück zur Startseite', on_click=lambda: ui.navigate.to('/')).props('color=primary')

# Multiprocessing-kompatible Main-Guard (wie von NiceGUI empfohlen)
if __name__ in {'__main__', '__mp_main__'}:
    ui.run(
        storage_secret=STORAGE_SECRET,
        host=HOST,
        port=PORT,
        title='Vereinsverwaltung',
        favicon='\U0001f3db\ufe0f',
    )
