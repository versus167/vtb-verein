"""
Widget für flexible Datumseingabe

Kombiniert NiceGUI Date-Picker mit intelligentem Parser
"""
from nicegui import ui
from typing import Optional, Callable
from app.ui.date_input_helper import DateInputHelper


class DateInput:
    """
    Flexibles Datumseingabe-Widget
    
    Kombiniert einen Date-Picker mit einem Textfeld, das verschiedene
    Eingabeformate akzeptiert und automatisch konvertiert.
    """
    
    def __init__(
        self,
        label: str,
        value: Optional[str] = None,
        on_change: Optional[Callable] = None,
        required: bool = False
    ):
        """
        Erstellt ein flexibles Datumseingabe-Widget.
        
        Args:
            label: Label für das Eingabefeld
            value: Initialer Wert im ISO-Format (YYYY-MM-DD)
            on_change: Callback-Funktion bei Änderungen
            required: Ob das Feld ein Pflichtfeld ist
        """
        self.label = label
        self._value = value
        self._on_change = on_change
        self._required = required
        self._error_message = ''
        
        # UI-Elemente
        self._input: Optional[ui.input] = None
        self._date_picker: Optional[ui.date] = None
        self._error_label: Optional[ui.label] = None
        
        self._create_ui()
    
    def _create_ui(self):
        """Erstellt die UI-Elemente"""
        with ui.column().classes('w-full'):
            with ui.row().classes('w-full gap-2'):
                # Texteingabe mit Auto-Format-Erkennung
                display_value = DateInputHelper.format_date_display(self._value) if self._value else ''
                
                self._input = ui.input(
                    label=self.label + (' *' if self._required else ''),
                    value=display_value,
                    placeholder='DD.MM.YYYY, DD/MM/YY, DDMMYY'
                ).classes('flex-grow').props('clearable')
                
                self._input.on('blur', self._on_input_blur)
                
                # Date-Picker-Button
                with ui.button(icon='calendar_today', on_click=self._open_date_picker).props('flat dense'):
                    pass
            
            # Fehleranzeige
            self._error_label = ui.label('').classes('text-negative text-xs')
            self._error_label.visible = False
            
            # Versteckter Date-Picker
            self._date_picker = ui.date(
                value=self._value,
                on_change=self._on_date_picker_change
            )
            self._date_picker.visible = False
    
    def _on_input_blur(self, e):
        """Handler für Fokus-Verlust des Eingabefeldes"""
        input_value = self._input.value
        
        if not input_value or not input_value.strip():
            if self._required:
                self._show_error('Dieses Feld ist erforderlich')
            else:
                self._value = None
                self._error_label.visible = False
                if self._on_change:
                    self._on_change(None)
            return
        
        # Parse und validiere
        parsed = DateInputHelper.parse_date(input_value)
        
        if parsed:
            self._value = parsed
            self._input.value = DateInputHelper.format_date_display(parsed)
            self._date_picker.value = parsed
            self._error_label.visible = False
            
            if self._on_change:
                self._on_change(parsed)
        else:
            self._show_error('Ungültiges Datum. Format: DD.MM.YYYY, DD/MM/YY, DDMMYY')
    
    def _open_date_picker(self):
        """Öffnet den Date-Picker Dialog"""
        with ui.dialog() as dialog, ui.card():
            ui.label(self.label).classes('text-h6 q-mb-md')
            
            temp_date = ui.date(
                value=self._value
            ).classes('w-full')
            
            with ui.row().classes('w-full q-mt-md'):
                ui.button('Abbrechen', on_click=dialog.close)
                
                def select_date():
                    if temp_date.value:
                        self._value = temp_date.value
                        self._input.value = DateInputHelper.format_date_display(temp_date.value)
                        self._date_picker.value = temp_date.value
                        self._error_label.visible = False
                        
                        if self._on_change:
                            self._on_change(temp_date.value)
                    
                    dialog.close()
                
                ui.button('Übernehmen', on_click=select_date).props('color=primary')
        
        dialog.open()
    
    def _on_date_picker_change(self, e):
        """Handler für Änderungen im Date-Picker"""
        if self._date_picker.value:
            self._value = self._date_picker.value
            self._input.value = DateInputHelper.format_date_display(self._date_picker.value)
            self._error_label.visible = False
            
            if self._on_change:
                self._on_change(self._date_picker.value)
    
    def _show_error(self, message: str):
        """Zeigt eine Fehlermeldung an"""
        self._error_message = message
        self._error_label.text = message
        self._error_label.visible = True
    
    @property
    def value(self) -> Optional[str]:
        """Gibt den aktuellen Wert im ISO-Format zurück"""
        return self._value
    
    @value.setter
    def value(self, new_value: Optional[str]):
        """Setzt einen neuen Wert (ISO-Format)"""
        self._value = new_value
        if self._input:
            self._input.value = DateInputHelper.format_date_display(new_value) if new_value else ''
        if self._date_picker:
            self._date_picker.value = new_value
    
    def is_valid(self) -> bool:
        """Prüft, ob die aktuelle Eingabe valid ist"""
        if self._required and not self._value:
            return False
        return not self._error_label.visible
