"""
Flexibler Datumseingabe-Helper

Unterstützt verschiedene Eingabeformate:
- 21.2.2026 oder 21.02.2026 (deutsches Format)
- 21/2/26 oder 21/02/2026 (mit Schrägstrich)
- 210226 (kompaktes Format: DDMMYY)
- 2026-02-21 (ISO-Format)

Zweistellige Jahreszahlen werden intelligent interpretiert:
- 00-49 → 2000-2049
- 50-99 → 1950-1999
"""
from datetime import datetime
from typing import Optional
import re


class DateInputHelper:
    """Helper-Klasse für flexible Datumseingaben"""
    
    @staticmethod
    def parse_date(date_str: Optional[str]) -> Optional[str]:
        """
        Parst verschiedene Datumsformate und gibt ISO-Format (YYYY-MM-DD) zurück.
        
        Args:
            date_str: Datumseingabe als String
            
        Returns:
            Datum im ISO-Format (YYYY-MM-DD) oder None bei ungültiger Eingabe
        """
        if not date_str or not date_str.strip():
            return None
        
        date_str = date_str.strip()
        
        try:
            # Format: YYYY-MM-DD (ISO - bereits korrekt)
            if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_str):
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                return dt.strftime('%Y-%m-%d')
            
            # Format: DDMMYY (kompakt, z.B. 210226)
            if re.match(r'^\d{6}$', date_str):
                day = int(date_str[0:2])
                month = int(date_str[2:4])
                year = int(date_str[4:6])
                
                # Intelligente Jahresinterpretation
                if year <= 49:
                    year += 2000
                else:
                    year += 1900
                
                dt = datetime(year, month, day)
                return dt.strftime('%Y-%m-%d')
            
            # Format: DD.MM.YYYY oder DD.MM.YY
            if '.' in date_str:
                parts = date_str.split('.')
                if len(parts) == 3:
                    day, month, year = parts
                    return DateInputHelper._parse_dmy(day, month, year)
            
            # Format: DD/MM/YYYY oder DD/MM/YY
            if '/' in date_str:
                parts = date_str.split('/')
                if len(parts) == 3:
                    day, month, year = parts
                    return DateInputHelper._parse_dmy(day, month, year)
            
            # Fallback: Versuche ISO-Format mit verschiedenen Trennzeichen
            for sep in ['-', '.', '/']:
                if sep in date_str:
                    parts = date_str.split(sep)
                    if len(parts) == 3 and len(parts[0]) == 4:
                        # YYYY-MM-DD Format
                        year, month, day = parts
                        dt = datetime(int(year), int(month), int(day))
                        return dt.strftime('%Y-%m-%d')
            
            return None
            
        except (ValueError, IndexError):
            return None
    
    @staticmethod
    def _parse_dmy(day: str, month: str, year: str) -> Optional[str]:
        """
        Parst Tag, Monat, Jahr und gibt ISO-Format zurück.
        
        Args:
            day: Tag als String
            month: Monat als String
            year: Jahr als String (2- oder 4-stellig)
            
        Returns:
            Datum im ISO-Format oder None
        """
        try:
            day = int(day)
            month = int(month)
            year = int(year)
            
            # Zweistellige Jahre interpretieren
            if year < 100:
                if year <= 49:
                    year += 2000
                else:
                    year += 1900
            
            dt = datetime(year, month, day)
            return dt.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def format_date_display(iso_date: Optional[str]) -> str:
        """
        Formatiert ein ISO-Datum für die Anzeige (deutsches Format).
        
        Args:
            iso_date: Datum im ISO-Format (YYYY-MM-DD)
            
        Returns:
            Datum im deutschen Format (DD.MM.YYYY) oder Leerstring
        """
        if not iso_date:
            return ''
        
        try:
            dt = datetime.strptime(iso_date, '%Y-%m-%d')
            return dt.strftime('%d.%m.%Y')
        except ValueError:
            return iso_date
    
    @staticmethod
    def validate_date(date_str: Optional[str]) -> tuple[bool, Optional[str]]:
        """
        Validiert eine Datumseingabe und gibt Status sowie formatiertes Datum zurück.
        
        Args:
            date_str: Datumseingabe als String
            
        Returns:
            Tuple (is_valid, formatted_date_or_error_message)
        """
        if not date_str or not date_str.strip():
            return (True, None)  # Leere Eingabe ist erlaubt
        
        parsed = DateInputHelper.parse_date(date_str)
        if parsed:
            return (True, parsed)
        else:
            return (False, 'Ungültiges Datumsformat. Erlaubt: DD.MM.YYYY, DD/MM/YY, DDMMYY, YYYY-MM-DD')
