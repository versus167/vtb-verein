"""
Gemeinsame Navigationsleiste für alle Seiten
"""
from nicegui import ui
from app.auth.auth_helper import AuthHelper

def create_navigation():
    """Erstellt die Navigationsleiste mit dynamischen Menüpunkten basierend auf Benutzerrechten"""
    user = AuthHelper.get_current_user()
    
    with ui.header().classes('items-center justify-between'):
        with ui.row().classes('items-center'):
            ui.label('Vereinsverwaltung').classes('text-h5')
            
            with ui.row().classes('q-ml-lg'):
                ui.button('Home', on_click=lambda: ui.navigate.to('/'), icon='home').props('flat')
                
                if user and user.can_edit():
                    ui.button('Abteilungen', on_click=lambda: ui.navigate.to('/abteilungen'), icon='groups').props('flat')
                
                if user and user.can_manage_users():
                    ui.button('Benutzer', on_click=lambda: ui.navigate.to('/users'), icon='people').props('flat')
        
        with ui.row().classes('items-center'):
            if user:
                ui.label(f'{user.username} ({user.role})').classes('text-caption q-mr-md')
                ui.button('Logout', on_click=lambda: (AuthHelper.logout(), ui.navigate.to('/login')), icon='logout').props('flat')
