"""
Mitgliederverwaltungs-Seite
"""
from nicegui import ui
from app.db.datastore import VereinsDB
from app.models.mitglied import Mitglied
from app.auth.auth_helper import AuthHelper, require_role
from app.ui.navigation import create_navigation, set_current_path

def create_mitglied_management_page(db: VereinsDB):
    """Erstellt die Mitgliederverwaltungs-Seite"""
    
    @ui.page('/mitglieder')
    @require_role('user')
    def mitglied_management_page():
        set_current_path('/mitglieder')
        create_navigation()
        current_user = AuthHelper.get_current_user()
        
        ui.label('Mitgliederverwaltung').classes('text-h4 q-mb-md q-mt-md q-ml-md')
        
        columns = [
            {'name': 'mitgliedsnummer', 'label': 'Nr.', 'field': 'mitgliedsnummer', 'align': 'left', 'sortable': True},
            {'name': 'vorname', 'label': 'Vorname', 'field': 'vorname', 'align': 'left', 'sortable': True},
            {'name': 'nachname', 'label': 'Nachname', 'field': 'nachname', 'align': 'left', 'sortable': True},
            {'name': 'geburtsdatum', 'label': 'Geburtsdatum', 'field': 'geburtsdatum', 'align': 'left'},
            {'name': 'ort', 'label': 'Ort', 'field': 'ort', 'align': 'left'},
            {'name': 'email', 'label': 'E-Mail', 'field': 'email', 'align': 'left'},
            {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'left'},
            {'name': 'actions', 'label': 'Aktionen', 'field': 'actions', 'align': 'center'},
        ]
        
        def load_mitglieder():
            mitglieder = db.list_mitglieder()
            return [
                {
                    'id': m.id,
                    'mitgliedsnummer': m.mitgliedsnummer or '',
                    'vorname': m.vorname,
                    'nachname': m.nachname,
                    'geburtsdatum': m.geburtsdatum or '',
                    'ort': m.ort or '',
                    'email': m.email or '',
                    'status': m.status,
                    'version': m.version,
                }
                for m in mitglieder
            ]
        
        with ui.card().classes('w-full q-ma-md'):
            table = ui.table(columns=columns, rows=load_mitglieder(), row_key='id').classes('w-full')
            table.add_slot('body-cell-actions', '''
                <q-td :props="props">
                    <q-btn flat dense icon="edit" @click="$parent.$emit('edit', props.row)" />
                    <q-btn flat dense icon="delete" @click="$parent.$emit('delete', props.row)" />
                </q-td>
            ''')
            
            def show_create_dialog():
                with ui.dialog() as dialog, ui.card().style('min-width: 700px; max-height: 80vh; overflow-y: auto'):
                    ui.label('Neues Mitglied anlegen').classes('text-h6 q-mb-md')
                    
                    # Mitgliedsdaten
                    ui.label('Mitgliedsdaten').classes('text-subtitle2 q-mt-md q-mb-sm')
                    next_nummer = db.get_next_mitgliedsnummer()
                    mitgliedsnummer = ui.number('Mitgliedsnummer', value=next_nummer, format='%.0f').props('autofocus')
                    
                    # Persönliche Daten
                    ui.label('Persönliche Daten').classes('text-subtitle2 q-mt-md q-mb-sm')
                    vorname = ui.input('Vorname *').classes('w-full')
                    nachname = ui.input('Nachname *').classes('w-full')
                    geburtsdatum = ui.input('Geburtsdatum (YYYY-MM-DD)')
                    
                    # Kontaktdaten
                    ui.label('Kontakt').classes('text-subtitle2 q-mt-md q-mb-sm')
                    email = ui.input('E-Mail')
                    telefon = ui.input('Telefon')
                    
                    # Adresse
                    ui.label('Adresse').classes('text-subtitle2 q-mt-md q-mb-sm')
                    strasse = ui.input('Straße')
                    with ui.row().classes('w-full'):
                        plz = ui.input('PLZ').classes('w-1/4')
                        ort = ui.input('Ort').classes('w-3/4')
                    land = ui.input('Land', value='Deutschland')
                    
                    # Vereinsdaten
                    ui.label('Vereinsdaten').classes('text-subtitle2 q-mt-md q-mb-sm')
                    eintrittsdatum = ui.input('Eintrittsdatum (YYYY-MM-DD)')
                    austrittsdatum = ui.input('Austrittsdatum (YYYY-MM-DD)')
                    
                    # Zahlungsdaten
                    ui.label('Zahlung').classes('text-subtitle2 q-mt-md q-mb-sm')
                    zahlungsart = ui.select(
                        'Zahlungsart *',
                        options=['Lastschrift', 'Rechnung', 'Bar'],
                        value='Lastschrift'
                    )
                    iban = ui.input('IBAN')
                    bic = ui.input('BIC')
                    kontoinhaber = ui.input('Kontoinhaber')
                    abgerechnet_bis = ui.input('Abgerechnet bis (YYYY-MM-DD)')
                    
                    error_label = ui.label('').classes('text-negative')
                    error_label.visible = False
                    
                    def create_mitglied():
                        error_label.visible = False
                        
                        # Validierung
                        if not vorname.value or not nachname.value:
                            error_label.text = 'Vorname und Nachname sind Pflichtfelder'
                            error_label.visible = True
                            return
                        
                        if not zahlungsart.value:
                            error_label.text = 'Zahlungsart ist ein Pflichtfeld'
                            error_label.visible = True
                            return
                        
                        # Prüfe Mitgliedsnummer
                        nummer = int(mitgliedsnummer.value) if mitgliedsnummer.value else None
                        if nummer and not db.is_mitgliedsnummer_available(nummer):
                            error_label.text = f'Mitgliedsnummer {nummer} ist bereits vergeben'
                            error_label.visible = True
                            return
                        
                        try:
                            m = Mitglied(
                                mitgliedsnummer=nummer,
                                vorname=vorname.value,
                                nachname=nachname.value,
                                geburtsdatum=geburtsdatum.value or None,
                                strasse=strasse.value or None,
                                plz=plz.value or None,
                                ort=ort.value or None,
                                land=land.value or None,
                                email=email.value or None,
                                telefon=telefon.value or None,
                                eintrittsdatum=eintrittsdatum.value or None,
                                austrittsdatum=austrittsdatum.value or None,
                                status='aktiv',
                                zahlungsart=zahlungsart.value,
                                iban=iban.value or None,
                                bic=bic.value or None,
                                kontoinhaber=kontoinhaber.value or None,
                                abgerechnet_bis=abgerechnet_bis.value or None,
                            )
                            db.create_mitglied(m, created_by=current_user.username)
                            table.rows = load_mitglieder()
                            table.update()
                            dialog.close()
                            ui.notify('Mitglied erfolgreich angelegt', type='positive')
                        except Exception as e:
                            error_label.text = f'Fehler: {str(e)}'
                            error_label.visible = True
                    
                    with ui.row().classes('w-full q-mt-md'):
                        ui.button('Abbrechen', on_click=dialog.close)
                        ui.button('Anlegen', on_click=create_mitglied).props('color=primary')
                
                dialog.open()
            
            def show_edit_dialog(row):
                m = db.get_mitglied(row['id'])
                
                with ui.dialog() as dialog, ui.card().style('min-width: 700px; max-height: 80vh; overflow-y: auto'):
                    ui.label(f'Mitglied bearbeiten: {m.vorname} {m.nachname}').classes('text-h6 q-mb-md')
                    
                    # Mitgliedsdaten
                    ui.label('Mitgliedsdaten').classes('text-subtitle2 q-mt-md q-mb-sm')
                    mitgliedsnummer = ui.number('Mitgliedsnummer', value=m.mitgliedsnummer, format='%.0f')
                    
                    # Persönliche Daten
                    ui.label('Persönliche Daten').classes('text-subtitle2 q-mt-md q-mb-sm')
                    vorname = ui.input('Vorname *', value=m.vorname)
                    nachname = ui.input('Nachname *', value=m.nachname)
                    geburtsdatum = ui.input('Geburtsdatum (YYYY-MM-DD)', value=m.geburtsdatum or '')
                    
                    # Kontaktdaten
                    ui.label('Kontakt').classes('text-subtitle2 q-mt-md q-mb-sm')
                    email = ui.input('E-Mail', value=m.email or '')
                    telefon = ui.input('Telefon', value=m.telefon or '')
                    
                    # Adresse
                    ui.label('Adresse').classes('text-subtitle2 q-mt-md q-mb-sm')
                    strasse = ui.input('Straße', value=m.strasse or '')
                    with ui.row().classes('w-full'):
                        plz = ui.input('PLZ', value=m.plz or '').classes('w-1/4')
                        ort = ui.input('Ort', value=m.ort or '').classes('w-3/4')
                    land = ui.input('Land', value=m.land or '')
                    
                    # Vereinsdaten
                    ui.label('Vereinsdaten').classes('text-subtitle2 q-mt-md q-mb-sm')
                    eintrittsdatum = ui.input('Eintrittsdatum (YYYY-MM-DD)', value=m.eintrittsdatum or '')
                    austrittsdatum = ui.input('Austrittsdatum (YYYY-MM-DD)', value=m.austrittsdatum or '')
                    
                    # Zahlungsdaten
                    ui.label('Zahlung').classes('text-subtitle2 q-mt-md q-mb-sm')
                    zahlungsart = ui.select(
                        'Zahlungsart *',
                        options=['Lastschrift', 'Rechnung', 'Bar'],
                        value=m.zahlungsart
                    )
                    iban = ui.input('IBAN', value=m.iban or '')
                    bic = ui.input('BIC', value=m.bic or '')
                    kontoinhaber = ui.input('Kontoinhaber', value=m.kontoinhaber or '')
                    abgerechnet_bis = ui.input('Abgerechnet bis (YYYY-MM-DD)', value=m.abgerechnet_bis or '')
                    
                    error_label = ui.label('').classes('text-negative')
                    error_label.visible = False
                    
                    def update_mitglied():
                        error_label.visible = False
                        
                        # Validierung
                        if not vorname.value or not nachname.value:
                            error_label.text = 'Vorname und Nachname sind Pflichtfelder'
                            error_label.visible = True
                            return
                        
                        if not zahlungsart.value:
                            error_label.text = 'Zahlungsart ist ein Pflichtfeld'
                            error_label.visible = True
                            return
                        
                        # Prüfe Mitgliedsnummer
                        nummer = int(mitgliedsnummer.value) if mitgliedsnummer.value else None
                        if nummer and not db.is_mitgliedsnummer_available(nummer, exclude_id=m.id):
                            error_label.text = f'Mitgliedsnummer {nummer} ist bereits vergeben'
                            error_label.visible = True
                            return
                        
                        try:
                            m.mitgliedsnummer = nummer
                            m.vorname = vorname.value
                            m.nachname = nachname.value
                            m.geburtsdatum = geburtsdatum.value or None
                            m.strasse = strasse.value or None
                            m.plz = plz.value or None
                            m.ort = ort.value or None
                            m.land = land.value or None
                            m.email = email.value or None
                            m.telefon = telefon.value or None
                            m.eintrittsdatum = eintrittsdatum.value or None
                            m.austrittsdatum = austrittsdatum.value or None
                            m.zahlungsart = zahlungsart.value
                            m.iban = iban.value or None
                            m.bic = bic.value or None
                            m.kontoinhaber = kontoinhaber.value or None
                            m.abgerechnet_bis = abgerechnet_bis.value or None
                            
                            success = db.update_mitglied(m, updated_by=current_user.username)
                            if not success:
                                error_label.text = 'Update fehlgeschlagen - Versionkonflikt'
                                error_label.visible = True
                                return
                            
                            table.rows = load_mitglieder()
                            table.update()
                            dialog.close()
                            ui.notify('Mitglied erfolgreich aktualisiert', type='positive')
                        except Exception as e:
                            error_label.text = f'Fehler: {str(e)}'
                            error_label.visible = True
                    
                    with ui.row().classes('w-full q-mt-md'):
                        ui.button('Abbrechen', on_click=dialog.close)
                        ui.button('Speichern', on_click=update_mitglied).props('color=primary')
                
                dialog.open()
            
            def show_delete_dialog(row):
                m = db.get_mitglied(row['id'])
                
                with ui.dialog() as dialog, ui.card():
                    ui.label('Mitglied löschen?').classes('text-h6 q-mb-md')
                    ui.label(f'Soll das Mitglied "{m.vorname} {m.nachname}" (Nr. {m.mitgliedsnummer}) wirklich gelöscht werden?')
                    
                    def delete_mitglied():
                        try:
                            success = db.delete_mitglied(m.id, deleted_by=current_user.username)
                            if success:
                                table.rows = load_mitglieder()
                                table.update()
                                dialog.close()
                                ui.notify('Mitglied erfolgreich gelöscht', type='positive')
                            else:
                                ui.notify('Mitglied konnte nicht gelöscht werden', type='negative')
                                dialog.close()
                        except Exception as e:
                            ui.notify(f'Fehler: {str(e)}', type='negative')
                            dialog.close()
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close).props('color=secondary')
                        ui.button('Löschen', on_click=delete_mitglied).props('color=negative')
                
                dialog.open()
            
            table.on('edit', lambda e: show_edit_dialog(e.args))
            table.on('delete', lambda e: show_delete_dialog(e.args))
            
            ui.button('Neues Mitglied anlegen', on_click=show_create_dialog, icon='add').props('color=primary')
