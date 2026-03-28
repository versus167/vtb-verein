"""
Kassenverwaltung

Admins können:
- Kassen anlegen, umbenennen, löschen
- Pro Kasse die Berechtigungen (Lesen / Schreiben / Exportieren) für jeden User verwalten

Nicht-Admins sehen diese Seite nicht (requires USERS_MANAGE).
"""
from nicegui import ui
from app.auth.auth_helper import AuthHelper, require_permission
from app.db.datastore import VereinsDB
from app.models.kasse import Kasse
from app.models.permission import Permission
from app.ui.navigation import create_navigation, set_current_path


def create_kasse_management_page(db: VereinsDB):
    """Registriert die Kassenverwaltungsseite."""

    # -----------------------------------------------------------------
    # Übersichtsseite: alle Kassen
    # -----------------------------------------------------------------
    @ui.page('/kassen')
    @require_permission(Permission.USERS_MANAGE)
    def kassen_page():
        set_current_path('/kassen')
        create_navigation()

        actor = AuthHelper.get_current_user().username
        kasse_repo = db.kassen
        abteilung_repo = db._abteilung_repo

        def refresh():
            kassen_container.clear()
            with kassen_container:
                _render_kassen_liste(db, kassen_container, actor, abteilung_repo, refresh)

        with ui.column().classes('q-ma-md full-width'):
            with ui.row().classes('items-center q-mb-md justify-between full-width'):
                ui.label('Kassenverwaltung').classes('text-h5')
                ui.button(
                    'Neue Kasse',
                    icon='add',
                    on_click=lambda: _open_kasse_dialog(db, actor, abteilung_repo, refresh)
                ).props('color=primary')

            kassen_container = ui.column().classes('full-width')
            _render_kassen_liste(db, kassen_container, actor, abteilung_repo, refresh)

    # -----------------------------------------------------------------
    # Berechtigungsseite für eine einzelne Kasse
    # -----------------------------------------------------------------
    @ui.page('/kassen/{kasse_id}/berechtigungen')
    @require_permission(Permission.USERS_MANAGE)
    def kasse_berechtigungen_page(kasse_id: int):
        set_current_path('/kassen')
        create_navigation()

        actor      = AuthHelper.get_current_user().username
        kasse_repo = db.kassen
        user_repo  = db.users
        bere_repo  = db.kasse_berechtigungen

        kasse = kasse_repo.get_kasse(kasse_id)
        if kasse is None:
            with ui.column().classes('q-ma-md'):
                ui.label('Kasse nicht gefunden').classes('text-h5 text-negative')
                ui.button('Zurück', on_click=lambda: ui.navigate.to('/kassen'), icon='arrow_back')
            return

        alle_user = [u for u in user_repo.list_all() if u.deleted_at is None and u.active]

        with ui.column().classes('q-ma-md full-width'):
            with ui.row().classes('items-center q-mb-md'):
                ui.button(icon='arrow_back',
                          on_click=lambda: ui.navigate.to('/kassen')).props('flat round')
                ui.label(f'Berechtigungen: {kasse.name}').classes('text-h5')

            ui.label(
                'Admins haben immer vollen Zugriff und erscheinen hier nicht.'
            ).classes('text-caption text-grey-7 q-mb-md')

            # Nur Nicht-Admins anzeigen
            nicht_admins = [u for u in alle_user if u.role != 'admin']

            if not nicht_admins:
                ui.label('Keine weiteren Benutzer vorhanden.').classes('text-grey')
                return

            # Checkboxen-Dict: user_id -> {lesen, schreiben, exportieren}
            cbs: dict[int, dict[str, ui.checkbox]] = {}

            with ui.card().classes('full-width'):
                # Tabellenkopf
                with ui.row().classes('items-center q-pa-sm bg-grey-2 full-width'):
                    ui.label('Benutzer').classes('text-weight-bold').style('min-width:200px')
                    ui.label('Rolle').classes('text-weight-bold').style('min-width:100px')
                    ui.label('Lesen').classes('text-weight-bold text-center').style('min-width:90px')
                    ui.label('Schreiben').classes('text-weight-bold text-center').style('min-width:100px')
                    ui.label('Exportieren').classes('text-weight-bold text-center').style('min-width:110px')

                ui.separator()

                for user in nicht_admins:
                    b = bere_repo.get_berechtigung(kasse_id, user.id)
                    lesen      = b.darf_lesen      if b else False
                    schreiben  = b.darf_schreiben  if b else False
                    exportieren = b.darf_exportieren if b else False

                    with ui.row().classes('items-center q-pa-xs full-width'):
                        ui.label(user.username).style('min-width:200px')
                        ui.label(user.role).classes('text-caption text-grey-7').style('min-width:100px')
                        cb_l = ui.checkbox('', value=lesen).style('min-width:90px')
                        cb_s = ui.checkbox('', value=schreiben).style('min-width:100px')
                        cb_e = ui.checkbox('', value=exportieren).style('min-width:110px')

                        # Schreiben impliziert Lesen
                        def on_schreiben_change(val, uid=user.id):
                            if val and not cbs[uid]['lesen'].value:
                                cbs[uid]['lesen'].set_value(True)

                        cb_s.on('update:model-value', lambda e, uid=user.id: on_schreiben_change(e.args))

                        cbs[user.id] = {'lesen': cb_l, 'schreiben': cb_s, 'exportieren': cb_e}

            error_label = ui.label('').classes('text-negative q-mt-sm')
            error_label.visible = False

            def save_berechtigungen():
                error_label.visible = False
                try:
                    for user in nicht_admins:
                        uid = user.id
                        l = cbs[uid]['lesen'].value
                        s = cbs[uid]['schreiben'].value
                        e = cbs[uid]['exportieren'].value
                        if l or s or e:
                            bere_repo.set_berechtigung(
                                kasse_id=kasse_id,
                                user_id=uid,
                                darf_lesen=l,
                                darf_schreiben=s,
                                darf_exportieren=e,
                                actor=actor,
                            )
                        else:
                            # Alle Rechte entziehen
                            bere_repo.revoke_berechtigung(
                                kasse_id=kasse_id,
                                user_id=uid,
                                actor=actor,
                            )
                    ui.notify('Berechtigungen gespeichert', type='positive')
                    ui.navigate.to('/kassen')
                except Exception as exc:
                    error_label.text = f'Fehler: {exc}'
                    error_label.visible = True

            with ui.row().classes('q-mt-md q-gutter-sm'):
                ui.button('Abbrechen',
                          on_click=lambda: ui.navigate.to('/kassen'),
                          icon='close').props('flat color=secondary')
                ui.button('Speichern',
                          on_click=save_berechtigungen,
                          icon='save').props('color=primary')


# -----------------------------------------------------------------
# Hilfsfunktionen
# -----------------------------------------------------------------

def _render_kassen_liste(db, container, actor, abteilung_repo, refresh):
    """Rendert die Liste aller aktiven Kassen als Cards."""
    kassen = db.kassen.list_kassen()
    abteilungen = {a.id: a for a in abteilung_repo.list_abteilungen()}

    if not kassen:
        with container:
            ui.label('Noch keine Kassen vorhanden.').classes('text-grey q-mt-md')
        return

    with container:
        for kasse in kassen:
            abt_name = abteilungen[kasse.abteilung_id].name if kasse.abteilung_id else '—'
            with ui.card().classes('full-width q-mb-sm'):
                with ui.row().classes('items-center justify-between full-width q-pa-sm'):
                    with ui.column().classes('col'):
                        ui.label(kasse.name).classes('text-subtitle1 text-weight-bold')
                        meta_parts = [f'Anfangsbestand: {kasse.anfangsbestand_cent / 100:.2f} €']
                        if kasse.abteilung_id:
                            meta_parts.append(f'Abteilung: {abt_name}')
                        if kasse.beschreibung:
                            meta_parts.append(kasse.beschreibung)
                        ui.label(' • '.join(meta_parts)).classes('text-caption text-grey-7')

                    with ui.row().classes('q-gutter-xs'):
                        ui.button(
                            'Berechtigungen',
                            icon='lock',
                            on_click=lambda k=kasse: ui.navigate.to(f'/kassen/{k.id}/berechtigungen')
                        ).props('flat color=primary size=sm')
                        ui.button(
                            icon='edit',
                            on_click=lambda k=kasse: _open_kasse_dialog(
                                db, actor, abteilung_repo, refresh, kasse=k
                            )
                        ).props('flat round color=secondary size=sm')
                        ui.button(
                            icon='delete',
                            on_click=lambda k=kasse: _confirm_delete(db, k, actor, refresh)
                        ).props('flat round color=negative size=sm')


def _open_kasse_dialog(db, actor, abteilung_repo, refresh, kasse=None):
    """Dialog zum Anlegen oder Bearbeiten einer Kasse."""
    is_new = kasse is None
    abteilungen = abteilung_repo.list_abteilungen()

    with ui.dialog() as dialog, ui.card().style('min-width: 420px'):
        ui.label('Neue Kasse' if is_new else 'Kasse bearbeiten').classes('text-h6 q-mb-md')

        name_input = ui.input(
            'Name *',
            value='' if is_new else kasse.name
        ).classes('full-width')

        beschreibung_input = ui.input(
            'Beschreibung',
            value='' if is_new else (kasse.beschreibung or '')
        ).classes('full-width')

        anfang_input = ui.number(
            'Anfangsbestand (€)',
            value=0 if is_new else round(kasse.anfangsbestand_cent / 100, 2),
            format='%.2f',
            step=0.01,
        ).classes('full-width')

        abt_options = {None: '(keine Abteilung)'}
        abt_options.update({a.id: a.name for a in abteilungen})

        abt_select = ui.select(
            abt_options,
            label='Abteilung',
            value=None if is_new else kasse.abteilung_id
        ).classes('full-width')

        error_label = ui.label('').classes('text-negative')
        error_label.visible = False

        def save():
            error_label.visible = False
            name = name_input.value.strip()
            if not name:
                error_label.text = 'Name darf nicht leer sein.'
                error_label.visible = True
                return

            try:
                anfang_cent = round((anfang_input.value or 0) * 100)
                abt_id = abt_select.value  # None oder int

                if is_new:
                    neue_kasse = Kasse(
                        name=name,
                        beschreibung=beschreibung_input.value.strip() or None,
                        anfangsbestand_cent=anfang_cent,
                        abteilung_id=abt_id,
                    )
                    gespeicherte_kasse = db.kassen.create_kasse(neue_kasse, created_by=actor)
                    # Admins automatisch berechtigen
                    admins = [u for u in db.users.list_all()
                              if u.role == 'admin' and u.active and u.deleted_at is None]
                    for adm in admins:
                        db.kasse_berechtigungen.set_berechtigung(
                            kasse_id=gespeicherte_kasse.id,
                            user_id=adm.id,
                            darf_lesen=True,
                            darf_schreiben=True,
                            darf_exportieren=True,
                            actor=actor,
                        )
                else:
                    kasse.name = name
                    kasse.beschreibung = beschreibung_input.value.strip() or None
                    kasse.anfangsbestand_cent = anfang_cent
                    kasse.abteilung_id = abt_id
                    db.kassen.update_kasse(kasse, updated_by=actor)

                # notify VOR close() – sonst ist der Slot-Kontext bereits zerstört
                ui.notify(
                    'Kasse erstellt' if is_new else 'Kasse aktualisiert',
                    type='positive'
                )
                dialog.close()
                refresh()
            except Exception as exc:
                error_label.text = f'Fehler: {exc}'
                error_label.visible = True

        with ui.row().classes('q-mt-md q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat color=secondary')
            ui.button('Speichern', on_click=save, icon='save').props('color=primary')

    dialog.open()


def _confirm_delete(db, kasse, actor, refresh):
    """Bestätigungsdialog zum Soft-Delete einer Kasse."""
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Kasse \u201e{kasse.name}\u201c löschen?').classes('text-h6')
        ui.label(
            'Die Kasse und alle zugehörigen Buchungen bleiben in der History erhalten.'
        ).classes('text-caption text-grey-7 q-mb-md')

        def confirm():
            db.kasse_berechtigungen.revoke_alle_berechtigungen_fuer_kasse(kasse.id, actor)
            db.kassen.mark_kasse_deleted(kasse.id, actor)
            # notify VOR close() – sonst ist der Slot-Kontext bereits zerstört
            ui.notify(f'Kasse \u201e{kasse.name}\u201c gelöscht', type='warning')
            dialog.close()
            refresh()

        with ui.row().classes('q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat')
            ui.button('Löschen', on_click=confirm, icon='delete').props('color=negative')

    dialog.open()
