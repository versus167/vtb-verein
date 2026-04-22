"""
Ticket-System UI

Seiten:
  /tickets                        - Ticketliste (nach Bereichsberechtigung gefiltert)
  /tickets/{ticket_id}            - Ticket-Detail mit Kommentaren
  /tickets/admin                  - Bereiche, Kategorien & Bereichsberechtigungen
  /tickets/{bereich_id}/berechtigungen - Pro-Bereich-Berechtigungen (analog Kasse)

Permission-Logik:
  - Globales TICKETS_READ  → Zugang zur Ticket-Seite überhaupt
  - darf_lesen (Bereich)   → Tickets dieses Bereichs sehen (Admins immer)
  - TICKETS_EDIT ODER darf_bearbeiten (Bereich) → Status ändern, Kommentare hinzufügen (inkl. interne)
  - TICKETS_CLOSE ODER darf_schliessen (Bereich) → Status auf 'erledigt' / 'abgelehnt' setzen
  - TICKETS_CREATE         → Neues Ticket erstellen
  - TICKETS_ASSIGN         → Ticket zuweisen (eigenständige Permission)
  - TICKETS_DELETE         → Ticket soft-löschen
  - TICKETS_INTERN_READ    → Interne Kommentare global (alle Bereiche);
                             alternativ: TICKETS_EDIT oder darf_bearbeiten im Bereich reicht auch
  - TICKETS_BEREICHE_VERWALTEN → Admin-Tab: Bereiche / Kategorien / Berechtigungen

HINWEIS: Globale Permissions (TICKETS_EDIT, TICKETS_CLOSE) erlauben Bearbeitung in allen Bereichen,
in denen der User lesenden Zugriff hat. Bereichsspezifische Rechte sind weiterhin möglich.

WICHTIG: Statische Routen (/tickets/admin) müssen vor parametrisierten
Routen (/tickets/{ticket_id}) registriert werden.

Feldnamen-Referenz (Ticket-Model):
  - gemeldet_von  (nicht reporter_id)
  - zugewiesen_an (nicht assigned_to)
  Kommentar-Model:
  - autor_id      (nicht created_by_id)
  - sichtbarkeit  'intern' | 'oeffentlich' (nicht ist_intern bool)
"""
from nicegui import ui
from app.auth.auth_helper import AuthHelper, require_permission
from app.db.datastore import VereinsDB
from app.models.permission import Permission
from app.models.ticket import (
    Ticket, TicketKommentar, TicketBereich, TicketKategorie, TicketStatus, TicketPrioritaet
)
from app.ui.navigation import create_navigation, set_current_path


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

STATUS_LABELS: dict[str, tuple[str, str]] = {
    TicketStatus.OFFEN:       ('Offen',       'blue'),
    TicketStatus.IN_PRUEFUNG: ('In Prüfung',  'orange'),
    TicketStatus.EINGEPLANT:  ('Eingeplant',  'purple'),
    TicketStatus.RUECKFRAGE:  ('Rückfrage',   'yellow'),
    TicketStatus.ERLEDIGT:    ('Erledigt',    'positive'),
    TicketStatus.ABGELEHNT:   ('Abgelehnt',   'negative'),
}

STATUS_UEBERGAENGE = {
    TicketStatus.OFFEN:       [TicketStatus.IN_PRUEFUNG, TicketStatus.ERLEDIGT, TicketStatus.ABGELEHNT],
    TicketStatus.IN_PRUEFUNG: [TicketStatus.EINGEPLANT, TicketStatus.RUECKFRAGE, TicketStatus.ERLEDIGT, TicketStatus.ABGELEHNT],
    TicketStatus.EINGEPLANT:  [TicketStatus.IN_PRUEFUNG, TicketStatus.ERLEDIGT],
    TicketStatus.RUECKFRAGE:  [TicketStatus.IN_PRUEFUNG, TicketStatus.ABGELEHNT],
    TicketStatus.ERLEDIGT:    [],
    TicketStatus.ABGELEHNT:   [],
}

SCHLIESS_STATUS = {TicketStatus.ERLEDIGT, TicketStatus.ABGELEHNT}

SICHTBARKEIT_INTERN   = 'intern'
SICHTBARKEIT_PUBLIK   = 'oeffentlich'


def _is_admin(user) -> bool:
    return user.role == 'admin'


def _lesbare_bereich_ids(db: VereinsDB, user) -> set[int] | None:
    """None = alle Bereiche (Admin). Ansonsten Set der lesbaren Bereich-IDs."""
    if _is_admin(user):
        return None
    ids = db.ticket_bereich_berechtigungen.get_lesbare_bereich_ids(user.id)
    return set(ids)


def _kann_bearbeiten(db: VereinsDB, bereich_id: int, user) -> bool:
    """Globale TICKETS_EDIT ODER bereichsspezifisches darf_bearbeiten.
    Admins haben immer Zugriff.
    """
    if _is_admin(user):
        return True
    if AuthHelper.has_permission(Permission.TICKETS_EDIT):
        return True
    return db.ticket_bereich_berechtigungen.user_darf_bearbeiten(bereich_id, user.id)


def _kann_schliessen(db: VereinsDB, bereich_id: int, user) -> bool:
    """Globale TICKETS_CLOSE ODER bereichsspezifisches darf_schliessen.
    Admins haben immer Zugriff.
    """
    if _is_admin(user):
        return True
    if AuthHelper.has_permission(Permission.TICKETS_CLOSE):
        return True
    return db.ticket_bereich_berechtigungen.user_darf_schliessen(bereich_id, user.id)


def _status_badge(status: str):
    label, color = STATUS_LABELS.get(status, (status, 'grey'))
    ui.badge(label, color=color)


# ---------------------------------------------------------------------------
# Seite registrieren
# ---------------------------------------------------------------------------

def create_ticket_pages(db: VereinsDB):

    # -------------------------------------------------------------------
    # /tickets  – Ticketliste
    # -------------------------------------------------------------------
    @ui.page('/tickets')
    @require_permission(Permission.TICKETS_READ)
    def tickets_page():
        set_current_path('/tickets')
        create_navigation()

        user = AuthHelper.get_current_user()
        lesbare_ids = _lesbare_bereich_ids(db, user)
        darf_erstellen = AuthHelper.has_permission(Permission.TICKETS_CREATE)
        darf_verwalten = AuthHelper.has_permission(Permission.TICKETS_BEREICHE_VERWALTEN)

        # Filter-State
        filter_state = {
            'status': None,
            'bereich': None,
            'prioritaet': None,
            'zuweisung': None,
        }

        def refresh():
            liste_container.clear()
            with liste_container:
                _render_ticket_liste(db, user, lesbare_ids, liste_container, filter_state)

        with ui.column().classes('q-ma-md full-width'):
            with ui.row().classes('items-center justify-between full-width q-mb-md'):
                ui.label('Tickets').classes('text-h5')
                with ui.row().classes('q-gutter-sm'):
                    if darf_verwalten:
                        ui.button(
                            'Verwaltung',
                            icon='settings',
                            on_click=lambda: ui.navigate.to('/tickets/admin')
                        ).props('flat color=secondary')
                    if darf_erstellen:
                        ui.button(
                            'Neues Ticket',
                            icon='add',
                            on_click=lambda: _open_ticket_dialog(db, user, lesbare_ids, refresh)
                        ).props('color=primary')

            # Filterleiste
            with ui.card().classes('full-width q-mb-md'):
                with ui.column().classes('full-width q-pa-sm'):
                    ui.label('Filter').classes('text-subtitle2')
                    with ui.row().classes('full-width q-gutter-sm q-mt-sm'):
                        # Status-Filter
                        status_options = {None: 'Alle Status'}
                        status_options.update({s: STATUS_LABELS[s][0] for s in TicketStatus.ALL})
                        ui.select(
                            status_options,
                            label='Status',
                            value=filter_state['status'],
                            on_change=lambda e: [filter_state.update({'status': e.value}), refresh()]
                        ).classes('col')

                        # Bereich-Filter
                        bereiche = db.tickets.get_bereiche()
                        if lesbare_ids is not None:
                            bereiche = [b for b in bereiche if b.id in lesbare_ids]
                        bereich_options = {None: 'Alle Bereiche'}
                        bereich_options.update({b.id: b.name for b in bereiche})
                        ui.select(
                            bereich_options,
                            label='Bereich',
                            value=filter_state['bereich'],
                            on_change=lambda e: [filter_state.update({'bereich': e.value}), refresh()]
                        ).classes('col')

                        # Priorität-Filter
                        prioritaet_options = {None: 'Alle Prioritäten'}
                        prioritaet_options.update({p: TicketPrioritaet.LABELS[p] for p in TicketPrioritaet.ALL})
                        ui.select(
                            prioritaet_options,
                            label='Priorität',
                            value=filter_state['prioritaet'],
                            on_change=lambda e: [filter_state.update({'prioritaet': e.value}), refresh()]
                        ).classes('col')

                        # Zuweisung-Filter
                        alle_user = [u for u in db.users.list_all() if u.active and u.deleted_at is None]
                        zuweisung_options = {None: 'Alle Zuweisungen'}
                        zuweisung_options.update({u.id: u.username for u in alle_user})
                        ui.select(
                            zuweisung_options,
                            label='Zugewiesen an',
                            value=filter_state['zuweisung'],
                            on_change=lambda e: [filter_state.update({'zuweisung': e.value}), refresh()]
                        ).classes('col')

                    with ui.row().classes('justify-end q-mt-sm'):
                        ui.button(
                            'Filter zurücksetzen',
                            icon='refresh',
                            on_click=lambda: [
                                filter_state.update({'status': None}),
                                filter_state.update({'bereich': None}),
                                filter_state.update({'prioritaet': None}),
                                filter_state.update({'zuweisung': None}),
                                refresh()
                            ]
                        ).props('flat color=secondary size=sm')

            liste_container = ui.column().classes('full-width')
            _render_ticket_liste(db, user, lesbare_ids, liste_container, filter_state)

    # -------------------------------------------------------------------
    # /tickets/admin  – Bereiche, Kategorien, Berechtigungen verwalten
    # MUSS vor /tickets/{ticket_id} registriert werden!
    # -------------------------------------------------------------------
    @ui.page('/tickets/admin')
    @require_permission(Permission.TICKETS_BEREICHE_VERWALTEN)
    def tickets_admin_page():
        set_current_path('/tickets')
        create_navigation()

        user = AuthHelper.get_current_user()
        actor = user.username

        with ui.column().classes('q-ma-md full-width'):
            with ui.row().classes('items-center q-mb-md'):
                ui.button(icon='arrow_back',
                          on_click=lambda: ui.navigate.to('/tickets')).props('flat round')
                ui.label('Ticket-Verwaltung').classes('text-h5')

            with ui.tabs().classes('q-mb-md') as tabs:
                tab_bereiche   = ui.tab('Bereiche',   icon='folder')
                tab_kategorien = ui.tab('Kategorien', icon='label')

            with ui.tab_panels(tabs, value=tab_bereiche).classes('full-width'):

                with ui.tab_panel(tab_bereiche):
                    bereiche_container = ui.column().classes('full-width')

                    def refresh_bereiche():
                        bereiche_container.clear()
                        with bereiche_container:
                            _render_bereiche(db, actor, bereiche_container, refresh_bereiche)

                    with ui.row().classes('justify-end full-width q-mb-sm'):
                        ui.button(
                            'Neuer Bereich', icon='add',
                            on_click=lambda: _open_bereich_dialog(db, actor, refresh_bereiche)
                        ).props('color=primary')

                    _render_bereiche(db, actor, bereiche_container, refresh_bereiche)

                with ui.tab_panel(tab_kategorien):
                    kat_container = ui.column().classes('full-width')

                    def refresh_kat():
                        kat_container.clear()
                        with kat_container:
                            _render_kategorien(db, actor, kat_container, refresh_kat)

                    with ui.row().classes('justify-end full-width q-mb-sm'):
                        ui.button(
                            'Neue Kategorie', icon='add',
                            on_click=lambda: _open_kategorie_dialog(db, actor, refresh_kat)
                        ).props('color=primary')

                    _render_kategorien(db, actor, kat_container, refresh_kat)

    # -------------------------------------------------------------------
    # /tickets/{ticket_id}  – Ticket-Detail
    # MUSS nach /tickets/admin registriert werden!
    # -------------------------------------------------------------------
    @ui.page('/tickets/{ticket_id}')
    @require_permission(Permission.TICKETS_READ)
    def ticket_detail_page(ticket_id: int):
        set_current_path('/tickets')
        create_navigation()

        user = AuthHelper.get_current_user()
        actor = user.username

        try:
            ticket = db.tickets.get_ticket(ticket_id)
        except Exception:
            with ui.column().classes('q-ma-md'):
                ui.label('Ticket nicht gefunden.').classes('text-h5 text-negative')
                ui.button('Zurück', icon='arrow_back',
                          on_click=lambda: ui.navigate.to('/tickets'))
            return

        lesbare_ids = _lesbare_bereich_ids(db, user)
        if lesbare_ids is not None and ticket.bereich_id not in lesbare_ids:
            with ui.column().classes('q-ma-md'):
                ui.label('Keine Berechtigung für dieses Ticket.').classes('text-h5 text-negative')
                ui.button('Zurück', icon='arrow_back',
                          on_click=lambda: ui.navigate.to('/tickets'))
            return

        kann_bearbeiten = _kann_bearbeiten(db, ticket.bereich_id, user)
        kann_schliessen = _kann_schliessen(db, ticket.bereich_id, user)
        darf_loeschen   = AuthHelper.has_permission(Permission.TICKETS_DELETE)

        intern_sichtbar = (
            AuthHelper.has_permission(Permission.TICKETS_INTERN_READ)
            or kann_bearbeiten
        )

        bereiche   = {b.id: b for b in db.tickets.get_bereiche()}
        kategorien = {k.id: k for k in db.tickets.get_kategorien()}
        alle_user  = {u.id: u for u in db.users.list_all() if u.active and u.deleted_at is None}

        def page_refresh():
            ui.navigate.to(f'/tickets/{ticket_id}')

        with ui.column().classes('q-ma-md full-width'):
            with ui.row().classes('items-center q-mb-sm'):
                ui.button(icon='arrow_back',
                          on_click=lambda: ui.navigate.to('/tickets')).props('flat round')
                ui.label(f'Ticket #{ticket.id}').classes('text-h5')
                _status_badge(ticket.status)

            with ui.card().classes('full-width q-mb-md'):
                ui.label(ticket.titel).classes('text-subtitle1 text-weight-bold')
                if ticket.beschreibung:
                    ui.label(ticket.beschreibung).classes('q-mt-xs')

                with ui.row().classes('q-mt-sm q-gutter-md text-caption text-grey-7'):
                    bereich_name = bereiche[ticket.bereich_id].name if ticket.bereich_id in bereiche else '—'
                    ui.label(f'Bereich: {bereich_name}')
                    if ticket.kategorie_id and ticket.kategorie_id in kategorien:
                        ui.label(f'Kategorie: {kategorien[ticket.kategorie_id].name}')
                    ui.label(f'Priorität: {TicketPrioritaet.LABELS.get(ticket.prioritaet, ticket.prioritaet)}')
                    if ticket.zugewiesen_an and ticket.zugewiesen_an in alle_user:
                        ui.label(f'Zugewiesen: {alle_user[ticket.zugewiesen_an].username}')
                    ui.label(f'Erstellt: {ticket.created_at[:10] if ticket.created_at else "—"}')

            if kann_bearbeiten or kann_schliessen or darf_loeschen:
                with ui.row().classes('q-gutter-sm q-mb-md'):
                    if kann_bearbeiten:
                        ui.button(
                            'Bearbeiten', icon='edit',
                            on_click=lambda: _open_ticket_bearbeiten_dialog(
                                db, ticket, user, alle_user, bereiche, kategorien,
                                kann_schliessen, page_refresh
                            )
                        ).props('flat color=primary')
                    if darf_loeschen and ticket.status not in {TicketStatus.ERLEDIGT}:
                        ui.button(
                            'Löschen', icon='delete',
                            on_click=lambda: _confirm_ticket_delete(
                                db, ticket, actor, lambda: ui.navigate.to('/tickets')
                            )
                        ).props('flat color=negative')

            ui.label('Kommentare').classes('text-h6 q-mb-sm')

            kommentare = db.tickets.get_kommentare(ticket_id, include_internal=intern_sichtbar)
            if not kommentare:
                ui.label('Noch keine Kommentare.').classes('text-grey q-mb-md')
            else:
                with ui.column().classes('full-width q-gutter-sm q-mb-md'):
                    for k in kommentare:
                        autor = alle_user[k.autor_id].username if k.autor_id in alle_user else str(k.autor_id)
                        with ui.card().classes('full-width'):
                            with ui.row().classes('items-center justify-between q-pa-xs'):
                                with ui.row().classes('items-center q-gutter-xs'):
                                    ui.label(autor).classes('text-weight-bold text-caption')
                                    if k.sichtbarkeit == SICHTBARKEIT_INTERN:
                                        ui.badge('intern', color='orange')
                                ui.label(k.created_at[:16] if k.created_at else '').classes('text-caption text-grey-6')
                            ui.label(k.inhalt).classes('q-pa-xs')

            if kann_bearbeiten:
                with ui.card().classes('full-width q-mt-sm'):
                    ui.label('Kommentar hinzufügen').classes('text-subtitle2 q-mb-sm')
                    inhalt_input = ui.textarea('Kommentar').classes('full-width')
                    intern_cb = None
                    if intern_sichtbar:
                        intern_cb = ui.checkbox('Intern (nicht öffentlich)')

                    def add_kommentar():
                        text = inhalt_input.value.strip()
                        if not text:
                            ui.notify('Kommentar darf nicht leer sein.', type='warning')
                            return
                        sichtbarkeit = SICHTBARKEIT_INTERN if (intern_cb and intern_cb.value) else SICHTBARKEIT_PUBLIK
                        k = TicketKommentar(
                            id=0,
                            ticket_id=ticket_id,
                            inhalt=text,
                            sichtbarkeit=sichtbarkeit,
                            autor_id=user.id,
                        )
                        db.tickets.add_kommentar(k, created_by=actor)
                        ui.notify('Kommentar gespeichert.', type='positive')
                        page_refresh()

                    ui.button('Kommentar speichern', icon='send', on_click=add_kommentar).props('color=primary q-mt-sm')

    # -------------------------------------------------------------------
    # /tickets/{bereich_id}/berechtigungen  – Bereichsberechtigungen
    # -------------------------------------------------------------------
    @ui.page('/tickets/{bereich_id}/berechtigungen')
    @require_permission(Permission.TICKETS_BEREICHE_VERWALTEN)
    def ticket_bereich_berechtigungen_page(bereich_id: int):
        set_current_path('/tickets')
        create_navigation()

        actor = AuthHelper.get_current_user().username
        berechtigung_repo = db.ticket_bereich_berechtigungen
        alle_user = [u for u in db.users.list_all() if u.active and u.deleted_at is None]

        bereiche = {b.id: b for b in db.tickets.get_bereiche()}
        bereich = bereiche.get(bereich_id)
        if bereich is None:
            with ui.column().classes('q-ma-md'):
                ui.label('Bereich nicht gefunden.').classes('text-h5 text-negative')
                ui.button('Zurück', icon='arrow_back',
                          on_click=lambda: ui.navigate.to('/tickets/admin'))
            return

        nicht_admins = [u for u in alle_user if u.role != 'admin']

        with ui.column().classes('q-ma-md full-width'):
            with ui.row().classes('items-center q-mb-md'):
                ui.button(icon='arrow_back',
                          on_click=lambda: ui.navigate.to('/tickets/admin')).props('flat round')
                ui.label(f'Berechtigungen: {bereich.name}').classes('text-h5')

            ui.label(
                'Admins haben immer vollen Zugriff und erscheinen hier nicht.'
            ).classes('text-caption text-grey-7 q-mb-md')

            if not nicht_admins:
                ui.label('Keine weiteren Benutzer vorhanden.').classes('text-grey')
                return

            cbs: dict[int, dict[str, ui.checkbox]] = {}

            with ui.card().classes('full-width'):
                with ui.row().classes('items-center q-pa-sm bg-grey-2 full-width'):
                    ui.label('Benutzer').classes('text-weight-bold').style('min-width:200px')
                    ui.label('Rolle').classes('text-weight-bold').style('min-width:100px')
                    ui.label('Lesen').classes('text-weight-bold text-center').style('min-width:90px')
                    ui.label('Bearbeiten').classes('text-weight-bold text-center').style('min-width:110px')
                    ui.label('Schließen').classes('text-weight-bold text-center').style('min-width:110px')

                ui.separator()

                for u in nicht_admins:
                    b = berechtigung_repo.get_berechtigung(bereich_id, u.id)
                    lesen      = bool(b and b['darf_lesen'])      if b else False
                    bearbeiten = bool(b and b['darf_bearbeiten']) if b else False
                    schliessen = bool(b and b['darf_schliessen']) if b else False

                    with ui.row().classes('items-center q-pa-xs full-width'):
                        ui.label(u.username).style('min-width:200px')
                        ui.label(u.role).classes('text-caption text-grey-7').style('min-width:100px')
                        cb_l = ui.checkbox('', value=lesen).style('min-width:90px')
                        cb_b = ui.checkbox('', value=bearbeiten).style('min-width:110px')
                        cb_s = ui.checkbox('', value=schliessen).style('min-width:110px')

                        def on_bearbeiten(val, uid=u.id):
                            if val and not cbs[uid]['lesen'].value:
                                cbs[uid]['lesen'].set_value(True)

                        def on_schliessen(val, uid=u.id):
                            if val:
                                if not cbs[uid]['lesen'].value:
                                    cbs[uid]['lesen'].set_value(True)
                                if not cbs[uid]['bearbeiten'].value:
                                    cbs[uid]['bearbeiten'].set_value(True)

                        cb_b.on('update:model-value', lambda e, uid=u.id: on_bearbeiten(e.args))
                        cb_s.on('update:model-value', lambda e, uid=u.id: on_schliessen(e.args))

                        cbs[u.id] = {'lesen': cb_l, 'bearbeiten': cb_b, 'schliessen': cb_s}

            error_label = ui.label('').classes('text-negative q-mt-sm')
            error_label.visible = False

            def save_berechtigungen():
                error_label.visible = False
                try:
                    for u in nicht_admins:
                        berechtigung_repo.set_berechtigung(
                            bereich_id=bereich_id,
                            user_id=u.id,
                            darf_lesen=cbs[u.id]['lesen'].value,
                            darf_bearbeiten=cbs[u.id]['bearbeiten'].value,
                            darf_schliessen=cbs[u.id]['schliessen'].value,
                            by=actor,
                        )
                    ui.notify('Berechtigungen gespeichert.', type='positive')
                    ui.navigate.to('/tickets/admin')
                except Exception as exc:
                    error_label.text = f'Fehler: {exc}'
                    error_label.visible = True

            with ui.row().classes('q-mt-md q-gutter-sm'):
                ui.button('Abbrechen',
                          on_click=lambda: ui.navigate.to('/tickets/admin'),
                          icon='close').props('flat color=secondary')
                ui.button('Speichern',
                          on_click=save_berechtigungen,
                          icon='save').props('color=primary')


# ---------------------------------------------------------------------------
# Render-Helfer
# ---------------------------------------------------------------------------

def _render_ticket_liste(db: VereinsDB, user, lesbare_ids: set[int] | None, container, filter_state: dict):
    alle_tickets = db.tickets.list_tickets()
    bereiche = {b.id: b for b in db.tickets.get_bereiche()}
    alle_user = {u.id: u for u in db.users.list_all() if u.active and u.deleted_at is None}

    if lesbare_ids is not None:
        alle_tickets = [t for t in alle_tickets if t.bereich_id in lesbare_ids]

    # Filter anwenden
    gefilterte_tickets = alle_tickets
    if filter_state['status']:
        gefilterte_tickets = [t for t in gefilterte_tickets if t.status == filter_state['status']]
    if filter_state['bereich']:
        gefilterte_tickets = [t for t in gefilterte_tickets if t.bereich_id == filter_state['bereich']]
    if filter_state['prioritaet']:
        gefilterte_tickets = [t for t in gefilterte_tickets if t.prioritaet == filter_state['prioritaet']]
    if filter_state['zuweisung']:
        gefilterte_tickets = [t for t in gefilterte_tickets if t.zugewiesen_an == filter_state['zuweisung']]

    if not gefilterte_tickets:
        with container:
            ui.label('Keine Tickets gefunden.').classes('text-grey q-mt-md')
        return

    with container:
        for ticket in gefilterte_tickets:
            bereich_name = bereiche[ticket.bereich_id].name if ticket.bereich_id in bereiche else '—'
            zugewiesen_an = alle_user[ticket.zugewiesen_an].username if ticket.zugewiesen_an and ticket.zugewiesen_an in alle_user else '—'
            
            with ui.card().classes('full-width q-mb-sm cursor-pointer').on(
                'click', lambda t=ticket: ui.navigate.to(f'/tickets/{t.id}')
            ):
                with ui.row().classes('items-center justify-between full-width q-pa-sm'):
                    with ui.column().classes('col'):
                        with ui.row().classes('items-center q-gutter-xs'):
                            ui.label(f'#{ticket.id}').classes('text-caption text-grey-6')
                            ui.label(ticket.titel).classes('text-subtitle2 text-weight-bold')
                        ui.label(f'Bereich: {bereich_name}').classes('text-caption text-grey-7')
                        if ticket.zugewiesen_an:
                            ui.label(f'Zugewiesen: {zugewiesen_an}').classes('text-caption text-grey-7')
                        ui.label(f'Priorität: {TicketPrioritaet.LABELS.get(ticket.prioritaet, ticket.prioritaet)}').classes('text-caption text-grey-8')
                    _status_badge(ticket.status)


def _render_bereiche(db: VereinsDB, actor: str, container, refresh):
    bereiche = db.tickets.get_bereiche()
    if not bereiche:
        with container:
            ui.label('Noch keine Bereiche vorhanden.').classes('text-grey')
        return
    with container:
        for b in bereiche:
            with ui.card().classes('full-width q-mb-xs'):
                with ui.row().classes('items-center justify-between full-width q-pa-sm'):
                    ui.label(b.name).classes('text-subtitle2')
                    with ui.row().classes('q-gutter-xs'):
                        ui.button(
                            'Berechtigungen', icon='lock',
                            on_click=lambda bid=b.id: ui.navigate.to(f'/tickets/{bid}/berechtigungen')
                        ).props('flat color=primary size=sm')
                        ui.button(
                            icon='edit',
                            on_click=lambda bereich=b: _open_bereich_dialog(db, actor, refresh, bereich)
                        ).props('flat round color=secondary size=sm')
                        ui.button(
                            icon='delete',
                            on_click=lambda bereich=b: _confirm_bereich_delete(db, bereich, actor, refresh)
                        ).props('flat round color=negative size=sm')


def _render_kategorien(db: VereinsDB, actor: str, container, refresh):
    kategorien = db.tickets.get_kategorien()
    if not kategorien:
        with container:
            ui.label('Noch keine Kategorien vorhanden.').classes('text-grey')
        return
    with container:
        for k in kategorien:
            with ui.card().classes('full-width q-mb-xs'):
                with ui.row().classes('items-center justify-between full-width q-pa-sm'):
                    ui.label(k.name).classes('text-subtitle2')
                    with ui.row().classes('q-gutter-xs'):
                        ui.button(
                            icon='edit',
                            on_click=lambda kat=k: _open_kategorie_dialog(db, actor, refresh, kat)
                        ).props('flat round color=secondary size=sm')
                        ui.button(
                            icon='delete',
                            on_click=lambda kat=k: _confirm_kategorie_delete(db, kat, actor, refresh)
                        ).props('flat round color=negative size=sm')


# ---------------------------------------------------------------------------
# Dialoge
# ---------------------------------------------------------------------------

def _open_ticket_dialog(db: VereinsDB, user, lesbare_ids: set[int] | None, refresh):
    actor = user.username
    bereiche = db.tickets.get_bereiche()
    if lesbare_ids is not None:
        bereiche = [b for b in bereiche if b.id in lesbare_ids]
    kategorien = db.tickets.get_kategorien()
    alle_user = [u for u in db.users.list_all() if u.active and u.deleted_at is None]

    if not bereiche:
        ui.notify('Keine zugänglichen Bereiche vorhanden.', type='warning')
        return

    with ui.dialog() as dialog, ui.card().style('min-width: 480px'):
        ui.label('Neues Ticket').classes('text-h6 q-mb-md')

        titel_input        = ui.input('Titel *').classes('full-width')
        beschreibung_input = ui.textarea('Beschreibung').classes('full-width')

        bereich_options = {b.id: b.name for b in bereiche}
        bereich_select  = ui.select(bereich_options, label='Bereich *').classes('full-width')

        kat_options = {None: '(keine Kategorie)'}
        kat_options.update({k.id: k.name for k in kategorien})
        kat_select = ui.select(kat_options, label='Kategorie', value=None).classes('full-width')

        prioritaet_options = {p: TicketPrioritaet.LABELS[p] for p in TicketPrioritaet.ALL}
        prioritaet_select = ui.select(
            prioritaet_options, label='Priorität', value=TicketPrioritaet.NORMAL
        ).classes('full-width')

        assign_options = {None: '(nicht zugewiesen)'}
        assign_options.update({u.id: u.username for u in alle_user})
        assign_select = ui.select(assign_options, label='Zuweisen an', value=None).classes('full-width')

        error_label = ui.label('').classes('text-negative')
        error_label.visible = False

        def save():
            error_label.visible = False
            titel = titel_input.value.strip()
            bereich_id = bereich_select.value
            if not titel:
                error_label.text = 'Titel darf nicht leer sein.'
                error_label.visible = True
                return
            if not bereich_id:
                error_label.text = 'Bitte einen Bereich wählen.'
                error_label.visible = True
                return
            try:
                neues_ticket = Ticket(
                    id=0,
                    titel=titel,
                    beschreibung=beschreibung_input.value.strip() or '',
                    status=TicketStatus.OFFEN,
                    prioritaet=prioritaet_select.value,
                    bereich_id=bereich_id,
                    kategorie_id=kat_select.value,
                    gemeldet_von=user.id,
                    zugewiesen_an=assign_select.value,
                )
                db.tickets.create_ticket(neues_ticket, created_by=actor)
                ui.notify('Ticket erstellt.', type='positive')
                dialog.close()
                refresh()
            except Exception as exc:
                error_label.text = f'Fehler: {exc}'
                error_label.visible = True

        with ui.row().classes('q-mt-md q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat color=secondary')
            ui.button('Erstellen', on_click=save, icon='add').props('color=primary')

    dialog.open()


def _open_ticket_bearbeiten_dialog(
    db: VereinsDB, ticket: Ticket, user, alle_user: dict,
    bereiche: dict, kategorien: dict, kann_schliessen: bool, refresh
):
    actor = user.username
    erlaubte_status = list(STATUS_UEBERGAENGE.get(ticket.status, []))
    if not kann_schliessen and not _is_admin(user):
        erlaubte_status = [s for s in erlaubte_status if s not in SCHLIESS_STATUS]

    with ui.dialog() as dialog, ui.card().style('min-width: 420px'):
        ui.label(f'Ticket #{ticket.id} bearbeiten').classes('text-h6 q-mb-md')

        assign_options = {None: '(nicht zugewiesen)'}
        assign_options.update({uid: u.username for uid, u in alle_user.items()})
        assign_select = ui.select(
            assign_options, label='Zuweisen an', value=ticket.zugewiesen_an
        ).classes('full-width')

        status_select = None
        if erlaubte_status:
            status_options = {s: STATUS_LABELS[s][0] for s in erlaubte_status}
            status_select = ui.select(
                status_options, label='Status ändern auf', value=None
            ).classes('full-width')
        else:
            ui.label('Keine weiteren Statuswechsel möglich.').classes('text-caption text-grey-7')

        error_label = ui.label('').classes('text-negative')
        error_label.visible = False

        def save():
            error_label.visible = False
            try:
                if assign_select.value != ticket.zugewiesen_an:
                    ticket.zugewiesen_an = assign_select.value
                    db.tickets.update_ticket(ticket, updated_by=actor)

                if status_select and status_select.value:
                    db.tickets.change_status(
                        ticket.id, status_select.value, actor, ticket.version
                    )

                ui.notify('Ticket aktualisiert.', type='positive')
                dialog.close()
                refresh()
            except Exception as exc:
                error_label.text = f'Fehler: {exc}'
                error_label.visible = True

        with ui.row().classes('q-mt-md q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat color=secondary')
            ui.button('Speichern', on_click=save, icon='save').props('color=primary')

    dialog.open()


def _confirm_ticket_delete(db: VereinsDB, ticket: Ticket, actor: str, refresh):
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Ticket #{ticket.id} löschen?').classes('text-h6')
        ui.label('Das Ticket bleibt in der History erhalten.').classes('text-caption text-grey-7 q-mb-md')

        def confirm():
            db.tickets.mark_ticket_deleted(ticket.id, actor)
            ui.notify(f'Ticket #{ticket.id} gelöscht.', type='warning')
            dialog.close()
            refresh()

        with ui.row().classes('q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat')
            ui.button('Löschen', on_click=confirm, icon='delete').props('color=negative')

    dialog.open()


def _open_bereich_dialog(db: VereinsDB, actor: str, refresh, bereich: TicketBereich = None):
    is_new = bereich is None
    with ui.dialog() as dialog, ui.card().style('min-width: 360px'):
        ui.label('Neuer Bereich' if is_new else 'Bereich bearbeiten').classes('text-h6 q-mb-md')
        name_input   = ui.input('Name *', value='' if is_new else bereich.name).classes('full-width')
        beschr_input = ui.input(
            'Beschreibung', value='' if is_new else (bereich.beschreibung or '')
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
                if is_new:
                    neuer = TicketBereich(id=0, name=name, beschreibung=beschr_input.value.strip() or None)
                    db.tickets.create_bereich(neuer, created_by=actor)
                else:
                    bereich.name = name
                    bereich.beschreibung = beschr_input.value.strip() or None
                    db.tickets.update_bereich(bereich, updated_by=actor)
                ui.notify('Bereich gespeichert.', type='positive')
                dialog.close()
                refresh()
            except Exception as exc:
                error_label.text = f'Fehler: {exc}'
                error_label.visible = True

        with ui.row().classes('q-mt-md q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat color=secondary')
            ui.button('Speichern', on_click=save, icon='save').props('color=primary')

    dialog.open()


def _confirm_bereich_delete(db: VereinsDB, bereich: TicketBereich, actor: str, refresh):
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Bereich „{bereich.name}" löschen?').classes('text-h6')
        ui.label(
            'Alle Berechtigungen für diesen Bereich werden ebenfalls entfernt.'
        ).classes('text-caption text-grey-7 q-mb-md')

        def confirm():
            db.ticket_bereich_berechtigungen.mark_alle_berechtigungen_fuer_bereich_deleted(
                bereich.id, actor
            )
            db.tickets.mark_bereich_deleted(bereich.id, actor)
            ui.notify(f'Bereich „{bereich.name}" gelöscht.', type='warning')
            dialog.close()
            refresh()

        with ui.row().classes('q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat')
            ui.button('Löschen', on_click=confirm, icon='delete').props('color=negative')

    dialog.open()


def _open_kategorie_dialog(db: VereinsDB, actor: str, refresh, kategorie: TicketKategorie = None):
    is_new = kategorie is None
    with ui.dialog() as dialog, ui.card().style('min-width: 360px'):
        ui.label('Neue Kategorie' if is_new else 'Kategorie bearbeiten').classes('text-h6 q-mb-md')
        name_input   = ui.input('Name *', value='' if is_new else kategorie.name).classes('full-width')
        beschr_input = ui.input(
            'Beschreibung', value='' if is_new else (kategorie.beschreibung or '')
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
                if is_new:
                    neue = TicketKategorie(id=0, name=name, beschreibung=beschr_input.value.strip() or None)
                    db.tickets.create_kategorie(neue, created_by=actor)
                else:
                    kategorie.name = name
                    kategorie.beschreibung = beschr_input.value.strip() or None
                    db.tickets.update_kategorie(kategorie, updated_by=actor)
                ui.notify('Kategorie gespeichert.', type='positive')
                dialog.close()
                refresh()
            except Exception as exc:
                error_label.text = f'Fehler: {exc}'
                error_label.visible = True

        with ui.row().classes('q-mt-md q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat color=secondary')
            ui.button('Speichern', on_click=save, icon='save').props('color=primary')

    dialog.open()


def _confirm_kategorie_delete(db: VereinsDB, kategorie: TicketKategorie, actor: str, refresh):
    with ui.dialog() as dialog, ui.card():
        ui.label(f'Kategorie „{kategorie.name}" löschen?').classes('text-h6')

        def confirm():
            db.tickets.mark_kategorie_deleted(kategorie.id, actor)
            ui.notify(f'Kategorie „{kategorie.name}" gelöscht.', type='warning')
            dialog.close()
            refresh()

        with ui.row().classes('q-gutter-sm justify-end full-width'):
            ui.button('Abbrechen', on_click=dialog.close).props('flat')
            ui.button('Löschen', on_click=confirm, icon='delete').props('color=negative')

    dialog.open()
