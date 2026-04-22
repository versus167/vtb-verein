"""
Gemeinsame Navigationsleiste für alle Seiten
"""
from nicegui import ui, app
from app.auth.auth_helper import AuthHelper
from app.models.permission import Permission


def create_navigation(db=None):
    """Erstellt die Navigationsleiste mit dynamischen Menüpunkten basierend auf Benutzerrechten.

    Args:
        db: VereinsDB-Instanz. Wird benötigt um kassenspezifische Berechtigungen zu prüfen
            (Kassenbuch-Button für normale User). Admins sehen den Button immer.
    """
    user = AuthHelper.get_current_user()
    if user and db:
        # Permissions frisch aus DB laden, damit Änderungen durch Admins sofort wirksam werden
        AuthHelper.refresh_permissions(db.permissions)
        user = AuthHelper.get_current_user()  # Aktualisierten User holen
    current_path = app.storage.user.get('current_path', '/')

    # gt-xs: Navigation nur auf Screens >= sm (600px) sichtbar
    # Auf Mobil (lt-sm) wird sie komplett ausgeblendet – stattdessen
    # gibt es auf relevanten Seiten einen floating Home-Button.
    with ui.header().classes('items-center justify-between gt-xs').style('background: linear-gradient(90deg, #1976d2 0%, #1565c0 100%);'):
        with ui.row().classes('items-center'):
            ui.label('\U0001f3db\ufe0f Vereinsverwaltung').classes('text-h5 q-mr-md text-white')

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

                # Kassenbuch für normale User
                if user and db is not None:
                    is_admin = user.can_manage_users()
                    zeige_kassenbuch = False
                    if is_admin:
                        zeige_kassenbuch = len(db.kassenbuch.get_kassen_fuer_user(user.id, is_admin=True)) > 0
                    else:
                        zeige_kassenbuch = len(db.kassenbuch.get_kassen_fuer_user(user.id, is_admin=False)) > 0

                    if zeige_kassenbuch:
                        kb_btn = ui.button('Kassenbuch', on_click=lambda: ui.navigate.to('/kassenbuch'), icon='menu_book')
                        if current_path == '/kassenbuch':
                            kb_btn.props('unelevated').classes('bg-blue-10 text-white')
                        else:
                            kb_btn.props('flat').classes('text-white')

                # Kassenverwaltung (nur Admins)
                if user and user.can_manage_users():
                    kasse_btn = ui.button('Kassen', on_click=lambda: ui.navigate.to('/kassen'), icon='account_balance_wallet')
                    if current_path == '/kassen':
                        kasse_btn.props('unelevated').classes('bg-blue-10 text-white')
                    else:
                        kasse_btn.props('flat').classes('text-white')

                # Tickets – sichtbar ab TICKETS_READ oder wenn User bereichsspezifische Rechte hat
                show_tickets = user and (
                    user.has_permission(Permission.TICKETS_READ) or
                    (db is not None and len(db.ticket_bereich_berechtigungen.get_lesbare_bereich_ids(user.id)) > 0)
                )
                if show_tickets:
                    tickets_btn = ui.button('Tickets', on_click=lambda: ui.navigate.to('/tickets'), icon='confirmation_number')
                    if current_path == '/tickets':
                        tickets_btn.props('unelevated').classes('bg-blue-10 text-white')
                    else:
                        tickets_btn.props('flat').classes('text-white')

                # Benutzer
                if user and user.can_manage_users():
                    user_btn = ui.button('Benutzer', on_click=lambda: ui.navigate.to('/users'), icon='people')
                    if current_path == '/users':
                        user_btn.props('unelevated').classes('bg-blue-10 text-white')
                    else:
                        user_btn.props('flat').classes('text-white')

        with ui.row().classes('items-center q-gutter-sm'):
            if user:
                with ui.button(icon='account_circle').props('flat round').classes('text-white'):
                    with ui.menu() as menu:
                        with ui.column().classes('q-pa-sm'):
                            ui.label(f'{user.username}').classes('text-weight-bold')
                            ui.label(f'Rolle: {user.role}').classes('text-caption text-grey-7')
                            ui.separator()

                            with ui.item().props('clickable').on('click', lambda: (menu.close(), ui.navigate.to('/profile'))):
                                with ui.item_section().props('avatar'):
                                    ui.icon('person')
                                with ui.item_section():
                                    ui.label('Mein Profil')

                            ui.separator()

                            def handle_logout():
                                menu.close()
                                AuthHelper.logout()
                                ui.navigate.to('/login')

                            with ui.item().props('clickable').on('click', handle_logout):
                                with ui.item_section().props('avatar'):
                                    ui.icon('logout')
                                with ui.item_section():
                                    ui.label('Logout')


def set_current_path(path: str):
    """Setzt den aktuellen Pfad im Storage (für Navigation-Highlighting)"""
    app.storage.user['current_path'] = path
