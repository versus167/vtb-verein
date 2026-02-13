"""
Gemeinsame Navigationsleiste für alle Seiten
"""
from nicegui import ui, app
from app.auth.auth_helper import AuthHelper

def create_navigation():
    """Erstellt die Navigationsleiste mit dynamischen Menüpunkten basierend auf Benutzerrechten"""
    user = AuthHelper.get_current_user()
    current_path = app.storage.user.get('current_path', '/')
    
    with ui.header().classes('items-center justify-between'):
        with ui.row().classes('items-center'):
            ui.label('🏛️ Vereinsverwaltung').classes('text-h5 q-mr-md')
            
            with ui.row().classes('q-gutter-xs'):
                # Home Button
                home_btn = ui.button('Home', on_click=lambda: ui.navigate.to('/'), icon='home')
                home_btn.props('flat' if current_path != '/' else 'flat outline')
                if current_path == '/':
                    home_btn.classes('text-primary')
                
                # Abteilungen
                if user and user.can_edit():
                    abt_btn = ui.button('Abteilungen', on_click=lambda: ui.navigate.to('/abteilungen'), icon='groups')
                    abt_btn.props('flat' if current_path != '/abteilungen' else 'flat outline')
                    if current_path == '/abteilungen':
                        abt_btn.classes('text-primary')
                
                # Benutzer
                if user and user.can_manage_users():
                    user_btn = ui.button('Benutzer', on_click=lambda: ui.navigate.to('/users'), icon='people')
                    user_btn.props('flat' if current_path != '/users' else 'flat outline')
                    if current_path == '/users':
                        user_btn.classes('text-primary')
        
        with ui.row().classes('items-center q-gutter-sm'):
            if user:
                # User Info Chip
                with ui.chip(icon='account_circle').props('outline color=white'):
                    ui.label(f'{user.username}').classes('text-weight-medium')
                    ui.label(f'({user.role})').classes('text-caption')
                
                # Logout Button
                def handle_logout():
                    AuthHelper.logout()
                    ui.navigate.to('/login')
                
                ui.button('Logout', on_click=handle_logout, icon='logout').props('flat color=white')

def set_current_path(path: str):
    """Setzt den aktuellen Pfad im Storage (für Navigation-Highlighting)"""
    app.storage.user['current_path'] = path
