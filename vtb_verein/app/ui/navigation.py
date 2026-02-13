"""
Gemeinsame Navigationsleiste für alle Seiten
"""
from nicegui import ui, app
from app.auth.auth_helper import AuthHelper

def create_navigation():
    """Erstellt die Navigationsleiste mit dynamischen Menüpunkten basierend auf Benutzerrechten"""
    user = AuthHelper.get_current_user()
    current_path = app.storage.user.get('current_path', '/')
    
    with ui.header().classes('items-center justify-between').style('background: linear-gradient(90deg, #1976d2 0%, #1565c0 100%);'):
        with ui.row().classes('items-center'):
            ui.label('🏛️ Vereinsverwaltung').classes('text-h5 q-mr-md text-white')
            
            with ui.row().classes('q-gutter-xs'):
                # Home Button
                home_btn = ui.button('Home', on_click=lambda: ui.navigate.to('/'), icon='home')
                if current_path == '/':
                    home_btn.props('unelevated').classes('bg-blue-10 text-white')
                else:
                    home_btn.props('flat').classes('text-white')
                
                # Abteilungen
                if user and user.can_edit():
                    abt_btn = ui.button('Abteilungen', on_click=lambda: ui.navigate.to('/abteilungen'), icon='groups')
                    if current_path == '/abteilungen':
                        abt_btn.props('unelevated').classes('bg-blue-10 text-white')
                    else:
                        abt_btn.props('flat').classes('text-white')
                
                # Benutzer
                if user and user.can_manage_users():
                    user_btn = ui.button('Benutzer', on_click=lambda: ui.navigate.to('/users'), icon='people')
                    if current_path == '/users':
                        user_btn.props('unelevated').classes('bg-blue-10 text-white')
                    else:
                        user_btn.props('flat').classes('text-white')
        
        with ui.row().classes('items-center q-gutter-sm'):
            if user:
                # User Info Chip
                with ui.chip(icon='account_circle').props('color=white text-color=primary'):
                    ui.label(f'{user.username}').classes('text-weight-medium')
                    ui.label(f'({user.role})').classes('text-caption')
                
                # Logout Button
                def handle_logout():
                    AuthHelper.logout()
                    ui.navigate.to('/login')
                
                ui.button('Logout', on_click=handle_logout, icon='logout').props('flat').classes('text-white')

def set_current_path(path: str):
    """Setzt den aktuellen Pfad im Storage (für Navigation-Highlighting)"""
    app.storage.user['current_path'] = path
