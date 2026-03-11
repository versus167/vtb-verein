"""
Permission-Verwaltungs-Seite

Ermöglicht Admins, die Permissions einzelner User granular zu verwalten.
Die 13 Permissions sind nach Ressource gruppiert in einer Checkbox-Matrix.
"""
from nicegui import ui
from app.auth.auth_helper import AuthHelper, require_permission
from app.db.datastore import VereinsDB
from app.models.permission import Permission
from app.ui.navigation import create_navigation, set_current_path


# Gruppierung der Permissions nach Ressource für die UI
PERMISSION_GROUPS = [
    {
        'label': 'Mitglieder',
        'icon': 'people',
        'permissions': [
            (Permission.MITGLIEDER_READ,   'Ansehen'),
            (Permission.MITGLIEDER_WRITE,  'Bearbeiten'),
            (Permission.MITGLIEDER_DELETE, 'Löschen'),
        ]
    },
    {
        'label': 'Abteilungen',
        'icon': 'account_tree',
        'permissions': [
            (Permission.ABTEILUNGEN_READ,   'Ansehen'),
            (Permission.ABTEILUNGEN_WRITE,  'Bearbeiten'),
            (Permission.ABTEILUNGEN_DELETE, 'Löschen'),
        ]
    },
    {
        'label': 'Beiträge',
        'icon': 'euro',
        'permissions': [
            (Permission.BEITRAEGE_READ,  'Ansehen'),
            (Permission.BEITRAEGE_WRITE, 'Bearbeiten'),
        ]
    },
    {
        'label': 'Berichte',
        'icon': 'bar_chart',
        'permissions': [
            (Permission.BERICHTE_READ,   'Ansehen'),
            (Permission.BERICHTE_EXPORT, 'Exportieren'),
        ]
    },
    {
        'label': 'Benutzerverwaltung',
        'icon': 'manage_accounts',
        'permissions': [
            (Permission.USERS_READ,   'Ansehen'),
            (Permission.USERS_MANAGE, 'Verwalten'),
        ]
    },
    {
        'label': 'System',
        'icon': 'settings',
        'permissions': [
            (Permission.SYSTEM_CONFIG, 'Konfiguration'),
        ]
    },
]


def create_permission_management_page(db: VereinsDB):
    """Registriert die Permission-Verwaltungsseite als NiceGUI-Route."""

    @ui.page('/users/{user_id}/permissions')
    @require_permission(Permission.USERS_MANAGE)
    def permission_management_page(user_id: int):
        set_current_path('/users')
        create_navigation()

        current_user = AuthHelper.get_current_user()
        user_repo    = db.users
        perm_repo    = db.permissions

        target_user = user_repo.get_by_id(user_id)
        if target_user is None:
            with ui.column().classes('q-ma-md'):
                ui.label('Benutzer nicht gefunden').classes('text-h5 text-negative')
                ui.button('Zurück zur Benutzerverwaltung',
                          on_click=lambda: ui.navigate.to('/users'),
                          icon='arrow_back')
            return

        current_permissions: set[str] = set(target_user.permissions)
        default_permissions: set[str] = Permission.defaults_for_role(target_user.role)
        has_custom = current_permissions != default_permissions

        # Checkbox-Referenzen sammeln: {permission_string: checkbox_element}
        checkboxes: dict[str, ui.checkbox] = {}

        with ui.column().classes('q-ma-md full-width'):

            # --- Header ---
            with ui.row().classes('items-center q-mb-md'):
                ui.button(icon='arrow_back',
                          on_click=lambda: ui.navigate.to('/users')).props('flat round')
                ui.label(f'Permissions: {target_user.username}').classes('text-h5')

            # Rollen-Hinweis
            with ui.row().classes('items-center q-mb-xs'):
                ui.label(f'Rolle: {target_user.role}').classes('text-caption text-grey-7')

            # Warnung bei abweichenden Permissions
            if has_custom:
                with ui.card().classes('bg-orange-1 q-mb-md full-width'):
                    with ui.row().classes('items-center'):
                        ui.icon('warning', color='orange')
                        ui.label(
                            'Die Permissions weichen von den Rollen-Standards ab.'
                        ).classes('q-ml-sm')

            # --- Checkbox-Matrix, gruppiert nach Ressource ---
            with ui.grid(columns=2).classes('full-width q-col-gutter-md q-mb-lg'):
                for group in PERMISSION_GROUPS:
                    with ui.card().classes('full-width'):
                        with ui.row().classes('items-center q-mb-sm'):
                            ui.icon(group['icon'], color='primary')
                            ui.label(group['label']).classes('text-subtitle1 text-weight-bold q-ml-sm')

                        for perm_const, perm_label in group['permissions']:
                            cb = ui.checkbox(
                                perm_label,
                                value=perm_const in current_permissions
                            )
                            # Visueller Hinweis: abweichend von Rollen-Default
                            if perm_const in default_permissions and perm_const not in current_permissions:
                                cb.props('color=orange')
                            elif perm_const not in default_permissions and perm_const in current_permissions:
                                cb.props('color=orange')
                            checkboxes[perm_const] = cb

            # --- Aktionsbuttons ---
            error_label = ui.label('').classes('text-negative')
            error_label.visible = False

            def collect_selected() -> set[str]:
                return {perm for perm, cb in checkboxes.items() if cb.value}

            def reset_to_role_defaults():
                """Setzt alle Checkboxen auf die Rollen-Defaults zurück."""
                for perm, cb in checkboxes.items():
                    cb.set_value(perm in default_permissions)

            def save_permissions():
                error_label.visible = False
                selected = collect_selected()

                # Schutz: letzter Admin darf USERS_MANAGE nicht verlieren
                if target_user.role == 'admin':
                    active_admins = db.count_active_admins()
                    if active_admins <= 1 and Permission.USERS_MANAGE not in selected:
                        error_label.text = (
                            '⚠️ Kann USERS_MANAGE nicht entziehen: '
                            'Dies ist der letzte aktive Administrator.'
                        )
                        error_label.visible = True
                        return

                try:
                    perm_repo.set_permissions_for_user(
                        user_id=target_user.id,
                        permissions=selected,
                        actor=current_user.username,
                    )
                    ui.notify(
                        f'Permissions für {target_user.username} gespeichert',
                        type='positive'
                    )
                    ui.navigate.to('/users')
                except Exception as e:
                    error_label.text = f'Fehler beim Speichern: {e}'
                    error_label.visible = True

            with ui.row().classes('q-gutter-sm'):
                ui.button(
                    'Auf Rollen-Standard zurücksetzen',
                    on_click=reset_to_role_defaults,
                    icon='restart_alt'
                ).props('flat color=secondary')
                ui.button(
                    'Speichern',
                    on_click=save_permissions,
                    icon='save'
                ).props('color=primary')
