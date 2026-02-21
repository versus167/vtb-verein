"""
Tests für den DateInputHelper
"""
import pytest
from app.ui.date_input_helper import DateInputHelper


class TestDateInputHelper:
    """Tests für flexible Datumseingaben"""
    
    def test_iso_format(self):
        """Test: ISO-Format YYYY-MM-DD"""
        assert DateInputHelper.parse_date('2026-02-21') == '2026-02-21'
        assert DateInputHelper.parse_date('2026-2-21') == '2026-02-21'
        assert DateInputHelper.parse_date('2026-12-31') == '2026-12-31'
    
    def test_german_format_full_year(self):
        """Test: Deutsches Format mit 4-stelligem Jahr"""
        assert DateInputHelper.parse_date('21.02.2026') == '2026-02-21'
        assert DateInputHelper.parse_date('21.2.2026') == '2026-02-21'
        assert DateInputHelper.parse_date('1.1.2026') == '2026-01-01'
        assert DateInputHelper.parse_date('31.12.2025') == '2025-12-31'
    
    def test_german_format_short_year(self):
        """Test: Deutsches Format mit 2-stelligem Jahr"""
        assert DateInputHelper.parse_date('21.2.26') == '2026-02-21'
        assert DateInputHelper.parse_date('21.02.26') == '2026-02-21'
        assert DateInputHelper.parse_date('15.3.99') == '1999-03-15'
        assert DateInputHelper.parse_date('15.3.49') == '2049-03-15'
        assert DateInputHelper.parse_date('15.3.50') == '1950-03-15'
    
    def test_slash_format(self):
        """Test: Format mit Schrägstrich"""
        assert DateInputHelper.parse_date('21/2/26') == '2026-02-21'
        assert DateInputHelper.parse_date('21/02/2026') == '2026-02-21'
        assert DateInputHelper.parse_date('1/1/99') == '1999-01-01'
    
    def test_compact_format(self):
        """Test: Kompaktes Format DDMMYY"""
        assert DateInputHelper.parse_date('210226') == '2026-02-21'
        assert DateInputHelper.parse_date('010126') == '2026-01-01'
        assert DateInputHelper.parse_date('311299') == '1999-12-31'
        assert DateInputHelper.parse_date('150349') == '2049-03-15'
        assert DateInputHelper.parse_date('150350') == '1950-03-15'
    
    def test_invalid_dates(self):
        """Test: Ungültige Datumseingaben"""
        assert DateInputHelper.parse_date('32.01.2026') is None
        assert DateInputHelper.parse_date('29.02.2026') is None  # Kein Schaltjahr
        assert DateInputHelper.parse_date('00.01.2026') is None
        assert DateInputHelper.parse_date('15.13.2026') is None
        assert DateInputHelper.parse_date('invalid') is None
        assert DateInputHelper.parse_date('21-02-26') is None  # Falsches Format
    
    def test_empty_input(self):
        """Test: Leere Eingaben"""
        assert DateInputHelper.parse_date(None) is None
        assert DateInputHelper.parse_date('') is None
        assert DateInputHelper.parse_date('   ') is None
    
    def test_format_display(self):
        """Test: Formatierung für Anzeige"""
        assert DateInputHelper.format_date_display('2026-02-21') == '21.02.2026'
        assert DateInputHelper.format_date_display('2026-01-01') == '01.01.2026'
        assert DateInputHelper.format_date_display(None) == ''
        assert DateInputHelper.format_date_display('') == ''
    
    def test_validate_date(self):
        """Test: Validierung mit Rückgabewerten"""
        # Gültige Eingaben
        valid, result = DateInputHelper.validate_date('21.2.26')
        assert valid is True
        assert result == '2026-02-21'
        
        # Leere Eingabe (erlaubt)
        valid, result = DateInputHelper.validate_date('')
        assert valid is True
        assert result is None
        
        # Ungültige Eingabe
        valid, result = DateInputHelper.validate_date('invalid')
        assert valid is False
        assert 'Ungültig' in result
    
    def test_year_boundary(self):
        """Test: Jahresgrenzen für 2-stellige Jahre"""
        # 00-49 → 2000-2049
        assert DateInputHelper.parse_date('01.01.00') == '2000-01-01'
        assert DateInputHelper.parse_date('01.01.49') == '2049-01-01'
        
        # 50-99 → 1950-1999
        assert DateInputHelper.parse_date('01.01.50') == '1950-01-01'
        assert DateInputHelper.parse_date('01.01.99') == '1999-12-31'
    
    def test_leap_year(self):
        """Test: Schaltjahre"""
        assert DateInputHelper.parse_date('29.02.2024') == '2024-02-29'  # Schaltjahr
        assert DateInputHelper.parse_date('29.02.2023') is None  # Kein Schaltjahr
