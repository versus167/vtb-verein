"""
User-Profil-Seite - User können hier ihr eigenes Passwort ändern
"""
from nicegui import ui
from app.services.user_service import UserService
from app.auth.auth_helper import AuthHelper, require_auth
from app.db.datastore import VereinsDB
from app.ui.navigation import create_navigation, set_current_path

def create_user_profile_page(db: VereinsDB):
    """Erstellt die User-Profil-Seite"""
    
    @ui.page('/profile')
    @require_auth()
    def user_profile_page():
        set_current_path('/profile')
        create_navigation(db)
        user_service = UserService(db)
        current_user = AuthHelper.get_current_user()
        is_admin = current_user.role == 'admin'
        
        # Rollen-Mapping für Anzeige
        role_labels = {
            'admin': 'Administrator',
            'user': 'Bearbeiter',
            'readonly': 'Nur Lesen',
            'special': 'Spezielle Funktion'
        }
        
        with ui.column().classes('q-ma-md'):
            ui.label('Mein Profil').classes('text-h4 q-mb-md')
            
            # Profil-Informationen
            with ui.card().classes('q-mb-md'):
                ui.label('Profil-Informationen').classes('text-h6 q-mb-md')
                
                # Hinweis für Non-Admins
                if not is_admin:
                    with ui.card().classes('bg-blue-1 q-mb-md'):
                        ui.label('\u2139\ufe0f Hinweis').classes('text-weight-bold text-caption')
                        ui.label('Username und E-Mail können nur von Administratoren geändert werden.').classes('text-caption')
                
                with ui.grid(columns=2).classes('w-full'):
                    ui.label('Benutzername:').classes('text-weight-bold')
                    ui.label(current_user.username)
                    
                    ui.label('E-Mail:').classes('text-weight-bold')
                    if is_admin:
                        # Admin kann E-Mail ändern
                        email_container = ui.row().classes('items-center')
                        with email_container:
                            email_label = ui.label(current_user.email)
                            ui.button(icon='edit', on_click=lambda: show_edit_email_dialog()).props('flat dense size=sm')
                    else:
                        # Normaler User sieht nur E-Mail
                        ui.label(current_user.email)
                    
                    ui.label('Rolle:').classes('text-weight-bold')
                    ui.label(role_labels.get(current_user.role, current_user.role))
                    
                    ui.label('Letzter Login:').classes('text-weight-bold')
                    ui.label(current_user.last_login or 'Noch nie')
            
            # E-Mail ändern (nur für Admins)
            def show_edit_email_dialog():
                with ui.dialog() as dialog, ui.card():
                    ui.label('E-Mail-Adresse ändern').classes('text-h6 q-mb-md')
                    
                    new_email = ui.input('Neue E-Mail-Adresse', value=current_user.email).props('autofocus')
                    
                    error_label = ui.label('').classes('text-negative')
                    error_label.visible = False
                    
                    def update_email():
                        error_label.visible = False
                        
                        if not new_email.value or '@' not in new_email.value:
                            error_label.text = 'Bitte gültige E-Mail-Adresse eingeben'
                            error_label.visible = True
                            return
                        
                        try:
                            user_service.update(
                                user_id=current_user.id,
                                username=current_user.username,
                                email=new_email.value,
                                role=current_user.role,
                                active=current_user.active,
                                updated_by=current_user.username,
                                expected_version=current_user.version
                            )
                            
                            # User-Objekt in Session aktualisieren
                            updated_user = user_service.get_by_id(current_user.id)
                            AuthHelper.set_current_user(updated_user, remember_me=True)
                            
                            dialog.close()
                            ui.notify('E-Mail-Adresse erfolgreich geändert', type='positive')
                            
                            # Seite neu laden um geänderte E-Mail anzuzeigen
                            ui.navigate.to('/profile', reload=True)
                            
                        except Exception as e:
                            error_label.text = f'Fehler: {str(e)}'
                            error_label.visible = True
                    
                    with ui.row().classes('w-full'):
                        ui.button('Abbrechen', on_click=dialog.close)
                        ui.button('Speichern', on_click=update_email).props('color=primary')
                
                dialog.open()
            
            # Passwort ändern
            with ui.card().classes('q-mb-md'):
                ui.label('Passwort ändern').classes('text-h6 q-mb-md')
                
                # Info-Text
                with ui.card().classes('bg-blue-1 q-mb-md'):
                    ui.label('\u2139\ufe0f Hinweis').classes('text-weight-bold')
                    ui.label('Du kannst hier dein Passwort setzen oder ändern.').classes('text-caption')
                    ui.label('Alternativ kannst du dich weiterhin per Magic-Link einloggen.').classes('text-caption')
                
                password = ui.input('Neues Passwort', password=True, password_toggle_button=True)
                password_confirm = ui.input('Passwort wiederholen', password=True)
                
                error_label = ui.label('').classes('text-negative')
                error_label.visible = False
                
                success_label = ui.label('').classes('text-positive')
                success_label.visible = False
                
                def change_password():
                    error_label.visible = False
                    success_label.visible = False
                    
                    if not password.value:
                        error_label.text = 'Bitte Passwort eingeben'
                        error_label.visible = True
                        return
                    
                    if password.value != password_confirm.value:
                        error_label.text = 'Passwörter stimmen nicht überein'
                        error_label.visible = True
                        return
                    
                    if len(password.value) < 6:
                        error_label.text = 'Passwort muss mindestens 6 Zeichen lang sein'
                        error_label.visible = True
                        return
                    
                    try:
                        user_service.change_password(
                            user_id=current_user.id,
                            new_password=password.value,
                            updated_by=current_user.username
                        )
                        
                        # Felder zurücksetzen
                        password.value = ''
                        password_confirm.value = ''
                        
                        success_label.text = '✅ Passwort erfolgreich geändert!'
                        success_label.visible = True
                        
                    except Exception as e:
                        error_label.text = f'Fehler: {str(e)}'
                        error_label.visible = True
                
                ui.button('Passwort ändern', on_click=change_password, icon='vpn_key').props('color=primary')
            
            # Multi-Channel Notifications (Phase 2)
            with ui.card().classes('q-mb-md'):
                ui.label('Benachrichtigungskanäle').classes('text-h6 q-mb-md')
                
                # Info-Text
                with ui.card().classes('bg-blue-1 q-mb-md'):
                    ui.label('📢 Benachrichtigungskanäle konfigurieren').classes('text-weight-bold')
                    ui.label('Wähle deine bevorzugten Kanäle für Benachrichtigungen aus.').classes('text-caption')
                    ui.label('Wenn dein bevorzugter Kanal nicht verfügbar ist, wird automatisch auf E-Mail ausgewichen.').classes('text-caption')
                
                with ui.grid(columns=2).classes('w-full gap-md'):
                    # Telegram
                    ui.label('Telegram:').classes('text-weight-bold col-span-2')
                    telegram_input = ui.input(
                        'Telegram @username oder Chat-ID',
                        value=current_user.telegram_id or ''
                    ).classes('col-span-2').props('outlined')
                    telegram_help = ui.label('z.B. @myusername oder 123456789').classes('text-caption text-grey col-span-2')
                    
                    # Matrix
                    ui.label('Matrix:').classes('text-weight-bold col-span-2')
                    matrix_input = ui.input(
                        'Matrix-ID',
                        value=current_user.matrix_id or ''
                    ).classes('col-span-2').props('outlined')
                    matrix_help = ui.label('z.B. @user:matrix.org').classes('text-caption text-grey col-span-2')
                    
                    # Bevorzugter Kanal
                    ui.label('Bevorzugter Kanal:').classes('text-weight-bold col-span-2')
                    channel_select = ui.select(
                        options=['email', 'telegram', 'matrix'],
                        value=current_user.preferred_contact,
                        label='Kanal wählen'
                    ).classes('col-span-2').props('outlined')
                
                # Error/Success Messages
                error_label = ui.label('').classes('text-negative')
                error_label.visible = False
                
                success_label = ui.label('').classes('text-positive')
                success_label.visible = False
                
                # Buttons
                def save_contact_preferences():
                    error_label.visible = False
                    success_label.visible = False
                    
                    telegram_val = telegram_input.value.strip() if telegram_input.value else None
                    matrix_val = matrix_input.value.strip() if matrix_input.value else None
                    channel_val = channel_select.value
                    
                    try:
                        # Validierung: Wenn Telegram/Matrix als bevorzugter Kanal, dann erforderlich
                        if channel_val == 'telegram' and not telegram_val:
                            error_label.text = '❌ Telegram-ID erforderlich wenn Telegram als Kanal gewählt'
                            error_label.visible = True
                            return
                        
                        if channel_val == 'matrix' and not matrix_val:
                            error_label.text = '❌ Matrix-ID erforderlich wenn Matrix als Kanal gewählt'
                            error_label.visible = True
                            return
                        
                        # Update durchführen
                        updated_user = user_service.update_contact_preferences(
                            user_id=current_user.id,
                            telegram_id=telegram_val,
                            matrix_id=matrix_val,
                            preferred_contact=channel_val,
                            updated_by=current_user.username,
                            expected_version=current_user.version
                        )
                        
                        # User in Session aktualisieren
                        AuthHelper.set_current_user(updated_user, remember_me=True)
                        
                        success_label.text = '✅ Benachrichtigungseinstellungen gespeichert!'
                        success_label.visible = True
                        
                        # Seite aktualisieren um neue Werte anzuzeigen
                        ui.timer(1.0, lambda: ui.navigate.to('/profile'), once=True)
                        
                    except ValueError as e:
                        error_label.text = f'❌ {str(e)}'
                        error_label.visible = True
                    except Exception as e:
                        error_label.text = f'❌ Fehler: {str(e)}'
                        error_label.visible = True
                
                def send_test_message():
                    error_label.visible = False
                    success_label.visible = False
                    
                    channel_val = channel_select.value
                    
                    if channel_val == 'telegram' and not current_user.telegram_id:
                        error_label.text = '❌ Keine Telegram-ID konfiguriert'
                        error_label.visible = True
                        return
                    
                    if channel_val == 'matrix' and not current_user.matrix_id:
                        error_label.text = '❌ Keine Matrix-ID konfiguriert'
                        error_label.visible = True
                        return
                    
                    try:
                        from app.services.notification_service import NotificationService
                        
                        result = NotificationService.send_notification(
                            current_user,
                            title='🧪 Test-Nachricht',
                            message='Dies ist eine Test-Benachrichtigung von der VTB-Vereinsverwaltung.'
                        )
                        
                        if result:
                            success_label.text = '✅ Test-Nachricht versendet!'
                            success_label.visible = True
                        else:
                            error_label.text = '❌ Test-Nachricht konnte nicht versendet werden'
                            error_label.visible = True
                            
                    except Exception as e:
                        error_label.text = f'❌ Fehler beim Test-Versand: {str(e)}'
                        error_label.visible = True
                
                with ui.row().classes('w-full gap-md'):
                    ui.button('Speichern', on_click=save_contact_preferences).props('color=primary')
                    ui.button('Test-Nachricht', on_click=send_test_message).props('color=primary outline')
