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
                
                # Mitglieder
                if user and user.can_edit():
                    mitgl_btn = ui.button('Mitglieder', on_click=lambda: ui.navigate.to('/mitglieder'), icon='group')
                    if current_path == '/mitglieder':
                        mitgl_btn.props('unelevated').classes('bg-blue-10 text-white')
                    else:
                        mitgl_btn.props('flat').classes('text-white')
                
                # Benutzer
                if user and user.can_manage_users():
                    user_btn = ui.button('Benutzer', on_click=lambda: ui.navigate.to('/users'), icon='people')
                    if current_path == '/users':
                        user_btn.props('unelevated').classes('bg-blue-10 text-white')
                    else:
                        user_btn.props('flat').classes('text-white')
        
        with ui.row().classes('items-center q-gutter-sm'):
            if user:
                # User-Menü (Dropdown)
                with ui.button(icon='account_circle').props('flat round').classes('text-white'):
                    with ui.menu() as menu:
                        with ui.column().classes('q-pa-sm'):
                            # User Info
                            ui.label(f'{user.username}').classes('text-weight-bold')
                            ui.label(f'Rolle: {user.role}').classes('text-caption text-grey-7')
                            ui.separator()
                            
                            # Profil-Link
                            with ui.item(clickable=True, on_click=lambda: (menu.close(), ui.navigate.to('/profile'))):
                                with ui.item_section().props('avatar'):
                                    ui.icon('person')
                                with ui.item_section():
                                    ui.label('Mein Profil')
                            
                            ui.separator()
                            
                            # Logout
                            def handle_logout():
                                menu.close()
                                AuthHelper.logout()
                                ui.navigate.to('/login')
                            
                            with ui.item(clickable=True, on_click=handle_logout):
                                with ui.item_section().props('avatar'):
                                    ui.icon('logout')
                                with ui.item_section():
                                    ui.label('Logout')

def set_current_path(path: str):
    """Setzt den aktuellen Pfad im Storage (für Navigation-Highlighting)"""
    app.storage.user['current_path'] = path
