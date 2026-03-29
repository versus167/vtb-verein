"""
Kassenbuch PDF-Berichts-Service

Erzeugt einen PDF-Bericht über alle Buchungen einer Kasse
für einen angegebenen Datumsbereich.

Verwendet reportlab (muss in requirements.txt sein).
"""
from datetime import date, timedelta
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT


def letzter_vollstaendiger_monat() -> tuple[str, str]:
    """Gibt (von_datum_iso, bis_datum_iso) für den letzten kompletten Monat zurück."""
    heute = date.today()
    erster_dieses_monats = heute.replace(day=1)
    letzter_vormonat = erster_dieses_monats - timedelta(days=1)
    erster_vormonat = letzter_vormonat.replace(day=1)
    return erster_vormonat.isoformat(), letzter_vormonat.isoformat()


def _fmt_euro(cent: int) -> str:
    """Formatiert Cent-Betrag als Euro-String (deutsches Format)."""
    return f"{cent / 100:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_datum(iso: str) -> str:
    """Formatiert ISO-Datum als TT.MM.JJJJ."""
    if not iso:
        return ''
    try:
        d = date.fromisoformat(iso)
        return d.strftime('%d.%m.%Y')
    except ValueError:
        return iso


def erstelle_kassenbuch_pdf(
    kasse_name: str,
    von_datum: str,
    bis_datum: str,
    buchungen: list[dict],
    anfangsbestand_cent: int,
    erstellt_von: str = '',
) -> bytes:
    """
    Erstellt einen PDF-Bericht für den Kassenbuch-Zeitraum.

    :param kasse_name: Name der Kasse
    :param von_datum: Startdatum (ISO-Format)
    :param bis_datum: Enddatum (ISO-Format)
    :param buchungen: Liste von Buchungs-Dicts mit Feldern:
                      buchungsdatum, belegnummer, buchungstext, kategorie,
                      einnahme_cent, ausgabe_cent, ist_storniert
    :param anfangsbestand_cent: Bestand zum Beginn des Zeitraums (exkl. erster Tag)
    :param erstellt_von: Benutzername des Erstellers (für Footer)
    :return: PDF als bytes
    """
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2 * cm,
        title=f'Kassenbuch {kasse_name}',
        author=erstellt_von or 'VTB-Vereinsverwaltung',
    )

    styles = getSampleStyleSheet()
    style_normal = styles['Normal']
    style_normal.fontName = 'Helvetica'
    style_normal.fontSize = 9

    style_title = ParagraphStyle(
        'KBTitle',
        fontName='Helvetica-Bold',
        fontSize=16,
        spaceAfter=4,
        textColor=colors.HexColor('#1a1a2e'),
    )
    style_subtitle = ParagraphStyle(
        'KBSubtitle',
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor('#555555'),
        spaceAfter=2,
    )
    style_section = ParagraphStyle(
        'KBSection',
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=colors.HexColor('#1a1a2e'),
        spaceBefore=10,
        spaceAfter=4,
    )
    style_footer = ParagraphStyle(
        'KBFooter',
        fontName='Helvetica',
        fontSize=7,
        textColor=colors.HexColor('#888888'),
        alignment=TA_CENTER,
    )
    style_right = ParagraphStyle(
        'KBRight',
        fontName='Helvetica',
        fontSize=8,
        alignment=TA_RIGHT,
    )
    style_bold_right = ParagraphStyle(
        'KBBoldRight',
        fontName='Helvetica-Bold',
        fontSize=8,
        alignment=TA_RIGHT,
    )

    # Farben
    COL_HEADER_BG = colors.HexColor('#2c3e50')
    COL_HEADER_FG = colors.white
    COL_STRIPE = colors.HexColor('#f5f5f5')
    COL_STORNO = colors.HexColor('#bbbbbb')
    COL_POSITIVE = colors.HexColor('#1a7a3c')
    COL_NEGATIVE = colors.HexColor('#b01020')
    COL_SUMMARY_BG = colors.HexColor('#eaf0fb')

    story = []

    # ------------------------------------------------------------------
    # Kopf
    # ------------------------------------------------------------------
    story.append(Paragraph(f'Kassenbuch – {kasse_name}', style_title))
    story.append(Paragraph(
        f'Zeitraum: {_fmt_datum(von_datum)} bis {_fmt_datum(bis_datum)}',
        style_subtitle
    ))
    erstellungsdatum = date.today().strftime('%d.%m.%Y')
    story.append(Paragraph(
        f'Erstellt am {erstellungsdatum}' + (f' von {erstellt_von}' if erstellt_von else ''),
        style_subtitle
    ))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#cccccc'), spaceAfter=8))

    # ------------------------------------------------------------------
    # Zusammenfassung
    # ------------------------------------------------------------------
    aktive_buchungen = [b for b in buchungen if not b.get('ist_storniert', False)]
    stornierte_buchungen = [b for b in buchungen if b.get('ist_storniert', False)]

    summe_einnahmen = sum(b['einnahme_cent'] for b in aktive_buchungen)
    summe_ausgaben = sum(b['ausgabe_cent'] for b in aktive_buchungen)
    endbestand = anfangsbestand_cent + summe_einnahmen - summe_ausgaben

    story.append(Paragraph('Zusammenfassung', style_section))

    summary_data = [
        ['Anfangsbestand (vor Zeitraum)', _fmt_euro(anfangsbestand_cent)],
        ['Summe Einnahmen', _fmt_euro(summe_einnahmen)],
        ['Summe Ausgaben', _fmt_euro(summe_ausgaben)],
        ['Endbestand', _fmt_euro(endbestand)],
    ]
    if stornierte_buchungen:
        summary_data.append([f'Davon storniert ({len(stornierte_buchungen)} Buchung(en))', '–'])

    summary_table = Table(
        summary_data,
        colWidths=[12 * cm, 4 * cm],
    )
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COL_SUMMARY_BG),
        ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#d0e4ff')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME', (0, 3), (-1, 3), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TEXTCOLOR', (1, 1), (1, 1), COL_POSITIVE),
        ('TEXTCOLOR', (1, 2), (1, 2), COL_NEGATIVE),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 0), (-1, -2), [COL_SUMMARY_BG, colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('LINEABOVE', (0, 3), (-1, 3), 1, colors.HexColor('#4a90d9')),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.4 * cm))

    # ------------------------------------------------------------------
    # Buchungstabelle
    # ------------------------------------------------------------------
    story.append(Paragraph(f'Buchungen ({len(buchungen)} gesamt)', style_section))

    col_widths = [1.5 * cm, 2.3 * cm, 1.5 * cm, 5.8 * cm, 2.8 * cm, 2.0 * cm, 2.0 * cm, 2.5 * cm]

    header_row = ['#', 'Datum', 'Beleg', 'Buchungstext', 'Kategorie', 'Einnahme', 'Ausgabe', 'Bestand']

    table_data = [header_row]

    laufend = anfangsbestand_cent
    row_styles = []

    for i, b in enumerate(buchungen, start=1):
        ist_storniert = b.get('ist_storniert', False)
        if not ist_storniert:
            laufend += b['einnahme_cent'] - b['ausgabe_cent']

        bestand_str = _fmt_euro(laufend) if not ist_storniert else '–'
        einnahme_str = _fmt_euro(b['einnahme_cent']) if b['einnahme_cent'] else ''
        ausgabe_str = _fmt_euro(b['ausgabe_cent']) if b['ausgabe_cent'] else ''
        datum_str = _fmt_datum(b['buchungsdatum'])
        beleg_str = b.get('belegnummer') or ''
        text_str = b['buchungstext']
        if len(text_str) > 40:
            text_str = text_str[:37] + '...'
        kat_str = b.get('kategorie', '')

        row = [str(i), datum_str, beleg_str, text_str, kat_str, einnahme_str, ausgabe_str, bestand_str]
        table_data.append(row)

        data_row_idx = i  # 0 = header
        if ist_storniert:
            row_styles.append(('TEXTCOLOR', (0, data_row_idx), (-1, data_row_idx), COL_STORNO))
        else:
            bg = COL_STRIPE if i % 2 == 0 else colors.white
            row_styles.append(('BACKGROUND', (0, data_row_idx), (-1, data_row_idx), bg))
            if b['einnahme_cent']:
                row_styles.append(('TEXTCOLOR', (5, data_row_idx), (5, data_row_idx), COL_POSITIVE))
            if b['ausgabe_cent']:
                row_styles.append(('TEXTCOLOR', (6, data_row_idx), (6, data_row_idx), COL_NEGATIVE))

    buch_table = Table(table_data, colWidths=col_widths, repeatRows=1)

    base_style = [
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), COL_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), COL_HEADER_FG),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, 0), 5),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        # Daten
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        # Ausrichtung Zahlen
        ('ALIGN', (5, 0), (7, -1), 'RIGHT'),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        # Gitter
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#1a3a5c')),
        # Letzter Saldo fett
        ('FONTNAME', (7, 1), (7, -1), 'Helvetica-Bold'),
    ]

    buch_table.setStyle(TableStyle(base_style + row_styles))
    story.append(buch_table)

    # ------------------------------------------------------------------
    # Footer (via onFirstPage / onLaterPages)
    # ------------------------------------------------------------------
    footer_text = (
        f'Kassenbuch "{kasse_name}" · Zeitraum: {_fmt_datum(von_datum)} – {_fmt_datum(bis_datum)} · '
        f'Erstellt: {erstellungsdatum}'
    )
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cccccc'), spaceAfter=4))
    story.append(Paragraph(footer_text, style_footer))

    doc.build(story)
    return buffer.getvalue()
