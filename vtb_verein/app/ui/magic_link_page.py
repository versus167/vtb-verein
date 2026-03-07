"""
Magic-Link-Validierungs-Seite
"""
from nicegui import ui
from app.services.user_service import UserService
from app.auth.auth_helper import AuthHelper
from app.db.datastore import VereinsDB

def create_magic_link_page(db: VereinsDB):
    """Erstellt die Magic-Link-Validierungs-Seite"""
    
    @ui.page('/auth/magic-link')
    def magic_link_page(token: str = None):
        """Validiert Magic-Link-Token und loggt User ein"""
        
        user_service = UserService(db)
        
        with ui.card().classes('absolute-center').style('min-width: 400px'):
            ui.label('Login-Link Validierung').classes('text-h5 text-center q-mb-md')
            
            if not token:
                ui.label('❌ Ungültiger Link: Kein Token vorhanden').classes('text-negative text-center')
                ui.label('Bitte verwende den vollständigen Link aus der E-Mail.').classes('text-body2 text-center q-mt-md')
                
                with ui.row().classes('w-full q-mt-lg justify-center'):
                    ui.button('Zurück zum Login', on_click=lambda: ui.navigate.to('/login')).props('color=primary')
                return
            
            # Spinner während Validierung
            spinner = ui.spinner(size='lg').classes('q-mb-md')
            status_label = ui.label('Token wird validiert...').classes('text-center')
            
            # Token validieren
            user = user_service.validate_magic_link(token)
            
            spinner.visible = False
            
            if user:
                # Erfolgreicher Login
                status_label.text = f'✅ Erfolgreich eingeloggt als {user.username}'
                status_label.classes('text-positive text-center text-h6')
                
                # User einloggen mit Remember-Me (Magic-Link impliziert längere Session)
                AuthHelper.set_current_user(user, remember_me=True)
                
                ui.label('Du wirst weitergeleitet...').classes('text-body2 text-center q-mt-md')
                
                # Weiterleitung nach 2 Sekunden
                ui.timer(2.0, lambda: ui.navigate.to('/'), once=True)
                
            else:
                # Token ungültig
                status_label.text = '❌ Login fehlgeschlagen'
                status_label.classes('text-negative text-center text-h6')
                
                with ui.column().classes('w-full q-mt-md'):
                    ui.label('Mögliche Gründe:').classes('text-body2 text-weight-bold')
                    ui.label('• Der Link wurde bereits verwendet').classes('text-body2')
                    ui.label('• Der Link ist abgelaufen (7 Tage Gültigkeit)').classes('text-body2')
                    ui.label('• Der Link ist ungültig').classes('text-body2')
                
                with ui.row().classes('w-full q-mt-lg justify-center'):
                    ui.button('Neuen Link anfordern', on_click=lambda: ui.navigate.to('/login')).props('color=primary')
