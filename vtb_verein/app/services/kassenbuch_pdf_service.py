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


def _fmt_zeitstempel(ts: str) -> str:
    """Formatiert einen TEXT-Zeitstempel (z.B. '2026-06-17 14:32:11.123') als TT.MM.JJJJ HH:MM."""
    if not ts:
        return ''
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts).strftime('%d.%m.%Y %H:%M')
    except ValueError:
        return ts


def _stueckelung_label(wert_cent: int) -> str:
    """Beschriftung eines Münz-/Scheinwerts, z.B. 5000 → '50 €', 50 → '50 ct'."""
    if wert_cent >= 100:
        euro = wert_cent / 100
        return f"{euro:g} €"
    return f"{wert_cent} ct"


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
                      einnahme_cent, ausgabe_cent, ist_storniert,
                      exportiert_in_export_id (None = noch offen / nicht endgültig)
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
    style_legend = ParagraphStyle(
        'KBLegend',
        fontName='Helvetica',
        fontSize=7.5,
        textColor=colors.HexColor('#555555'),
        spaceBefore=4,
        spaceAfter=2,
    )

    # Farben
    COL_HEADER_BG = colors.HexColor('#2c3e50')
    COL_HEADER_FG = colors.white
    COL_STRIPE = colors.HexColor('#f5f5f5')
    COL_STORNO = colors.HexColor('#bbbbbb')
    COL_POSITIVE = colors.HexColor('#1a7a3c')
    COL_NEGATIVE = colors.HexColor('#b01020')
    COL_SUMMARY_BG = colors.HexColor('#eaf0fb')
    # Endgültig-exportierte Buchungen: dezentes Blau
    COL_ENDGUELTIG_BG = colors.HexColor('#e8f0fe')
    COL_ENDGUELTIG_BELEG = colors.HexColor('#1a56a0')

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
    endgueltige_buchungen = [b for b in aktive_buchungen if b.get('exportiert_in_export_id') is not None]

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
    extra_rows = 0
    if stornierte_buchungen:
        summary_data.append([f'Davon storniert ({len(stornierte_buchungen)} Buchung(en))', '–'])
        extra_rows += 1
    if endgueltige_buchungen:
        summary_data.append([f'Davon endgültig / exportiert ({len(endgueltige_buchungen)} Buchung(en))', '–'])
        extra_rows += 1

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
        ('ROWBACKGROUNDS', (0, 0), (-1, -1 - extra_rows), [COL_SUMMARY_BG, colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('LINEABOVE', (0, 3), (-1, 3), 1, colors.HexColor('#4a90d9')),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.4 * cm))

    # ------------------------------------------------------------------
    # Buchungstabelle
    # 7 Spalten: Datum | Beleg | Buchungstext | Kategorie | Einnahme | Ausgabe | Bestand
    # ------------------------------------------------------------------
    story.append(Paragraph(f'Buchungen ({len(buchungen)} gesamt)', style_section))

    # Spaltenbreiten: gesamt ~17 cm nutzbar (A4 - 4 cm Rand)
    col_widths = [2.3 * cm, 2.5 * cm, 6.0 * cm, 2.8 * cm, 2.0 * cm, 2.0 * cm, 2.5 * cm]

    header_row = ['Datum', 'Beleg', 'Buchungstext', 'Kategorie', 'Einnahme', 'Ausgabe', 'Bestand']

    table_data = [header_row]

    laufend = anfangsbestand_cent
    row_styles = []

    for i, b in enumerate(buchungen, start=1):
        ist_storniert = b.get('ist_storniert', False)
        ist_endgueltig = b.get('exportiert_in_export_id') is not None

        if not ist_storniert:
            laufend += b['einnahme_cent'] - b['ausgabe_cent']

        bestand_str = _fmt_euro(laufend) if not ist_storniert else '–'
        einnahme_str = _fmt_euro(b['einnahme_cent']) if b['einnahme_cent'] else ''
        ausgabe_str = _fmt_euro(b['ausgabe_cent']) if b['ausgabe_cent'] else ''
        datum_str = _fmt_datum(b['buchungsdatum'])
        beleg_str = b.get('belegnummer') or '–'
        hat_anhang = b.get('anhang_count', 0) > 0
        anhang_suffix = ' ◆' if hat_anhang else ''
        text_str = b['buchungstext']
        if len(text_str) > 45:
            text_str = text_str[:42] + '...'
        kat_str = b.get('kategorie', '')

        data_row_idx = i  # 0 = header

        if ist_storniert:
            row = [datum_str, f'{beleg_str}{anhang_suffix}', text_str, kat_str, einnahme_str, ausgabe_str, bestand_str]
            table_data.append(row)
            row_styles.append(('TEXTCOLOR', (0, data_row_idx), (-1, data_row_idx), COL_STORNO))
        elif ist_endgueltig:
            # Endgültig exportierte Buchung: blaues Beleg-Kürzel + dezenter blauer Hintergrund
            beleg_display = f'[✓] {beleg_str}{anhang_suffix}'
            row = [datum_str, beleg_display, text_str, kat_str, einnahme_str, ausgabe_str, bestand_str]
            table_data.append(row)
            row_styles.append(('BACKGROUND', (0, data_row_idx), (-1, data_row_idx), COL_ENDGUELTIG_BG))
            row_styles.append(('TEXTCOLOR', (1, data_row_idx), (1, data_row_idx), COL_ENDGUELTIG_BELEG))
            row_styles.append(('FONTNAME', (1, data_row_idx), (1, data_row_idx), 'Helvetica-Bold'))
            if b['einnahme_cent']:
                row_styles.append(('TEXTCOLOR', (4, data_row_idx), (4, data_row_idx), COL_POSITIVE))
            if b['ausgabe_cent']:
                row_styles.append(('TEXTCOLOR', (5, data_row_idx), (5, data_row_idx), COL_NEGATIVE))
        else:
            row = [datum_str, f'{beleg_str}{anhang_suffix}', text_str, kat_str, einnahme_str, ausgabe_str, bestand_str]
            table_data.append(row)
            bg = COL_STRIPE if i % 2 == 0 else colors.white
            row_styles.append(('BACKGROUND', (0, data_row_idx), (-1, data_row_idx), bg))
            if b['einnahme_cent']:
                row_styles.append(('TEXTCOLOR', (4, data_row_idx), (4, data_row_idx), COL_POSITIVE))
            if b['ausgabe_cent']:
                row_styles.append(('TEXTCOLOR', (5, data_row_idx), (5, data_row_idx), COL_NEGATIVE))

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
        # Ausrichtung Zahlen (Einnahme=4, Ausgabe=5, Bestand=6)
        ('ALIGN', (4, 0), (6, -1), 'RIGHT'),
        # Gitter
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#1a3a5c')),
        # Letzter Saldo fett
        ('FONTNAME', (6, 1), (6, -1), 'Helvetica-Bold'),
    ]

    buch_table.setStyle(TableStyle(base_style + row_styles))
    story.append(buch_table)

    # ------------------------------------------------------------------
    # Legende
    # ------------------------------------------------------------------
    story.append(Paragraph(
        '[✓] Beleg = endgültig / bereits exportiert  ·  '
        '◆ = Anhänge vorhanden  ·  '
        'Grau = storniert (wird im Endbestand nicht berücksichtigt)',
        style_legend,
    ))

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    footer_text = (
        f'Kassenbuch "{kasse_name}" · Zeitraum: {_fmt_datum(von_datum)} – {_fmt_datum(bis_datum)} · '
        f'Erstellt: {erstellungsdatum}'
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cccccc'), spaceAfter=4))
    story.append(Paragraph(footer_text, style_footer))

    doc.build(story)
    return buffer.getvalue()


def erstelle_zaehlprotokoll_pdf(
    kasse_name: str,
    stueckelung: dict,
    ist_cent: int,
    soll_cent: int,
    differenz_cent: int,
    gezaehlt_am: str = '',
    gezaehlt_von: str = '',
    belegnummer: str = '',
    notiz: str = '',
) -> bytes:
    """Erstellt das Zählprotokoll-PDF (Stückelung + Soll-/Ist-Abgleich) einer Kassenzählung.

    :param stueckelung: {wert_cent (str|int): anzahl} – z.B. {"5000": 2, "200": 13}
    :return: PDF als bytes
    """
    from app.models.kasse import EURO_STUECKELUNG_CENT

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.5 * cm, bottomMargin=2 * cm,
        title=f'Zählprotokoll {kasse_name}',
        author=gezaehlt_von or 'VTB-Vereinsverwaltung',
    )

    style_title = ParagraphStyle('ZPTitle', fontName='Helvetica-Bold', fontSize=16,
                                 spaceAfter=4, textColor=colors.HexColor('#1a1a2e'))
    style_subtitle = ParagraphStyle('ZPSubtitle', fontName='Helvetica', fontSize=10,
                                    textColor=colors.HexColor('#555555'), spaceAfter=2)
    style_section = ParagraphStyle('ZPSection', fontName='Helvetica-Bold', fontSize=10,
                                   textColor=colors.HexColor('#1a1a2e'), spaceBefore=10, spaceAfter=4)
    style_footer = ParagraphStyle('ZPFooter', fontName='Helvetica', fontSize=7,
                                  textColor=colors.HexColor('#888888'), alignment=TA_CENTER)

    COL_HEADER_BG = colors.HexColor('#2c3e50')
    COL_SUMMARY_BG = colors.HexColor('#eaf0fb')
    COL_POSITIVE = colors.HexColor('#1a7a3c')
    COL_NEGATIVE = colors.HexColor('#b01020')

    # Stückelung normalisieren: Cent-Wert (int) → Anzahl, nur Werte > 0
    norm: dict[int, int] = {}
    for wert, anzahl in (stueckelung or {}).items():
        try:
            w, a = int(wert), int(anzahl)
        except (TypeError, ValueError):
            continue
        if a > 0:
            norm[w] = a

    story = []
    story.append(Paragraph(f'Zählprotokoll – {kasse_name}', style_title))
    story.append(Paragraph(f'Gezählt am {_fmt_zeitstempel(gezaehlt_am)}'
                           + (f' von {gezaehlt_von}' if gezaehlt_von else ''), style_subtitle))
    if belegnummer:
        story.append(Paragraph(f'Zugehörige Buchung: Beleg-Nr. {belegnummer}', style_subtitle))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#cccccc'), spaceAfter=8))

    # ------------------------------------------------------------------
    # Stückelungstabelle
    # ------------------------------------------------------------------
    story.append(Paragraph('Stückelung', style_section))
    table_data = [['Wert', 'Anzahl', 'Summe']]
    for wert in EURO_STUECKELUNG_CENT:
        anzahl = norm.get(wert, 0)
        if anzahl == 0:
            continue
        table_data.append([_stueckelung_label(wert), str(anzahl), _fmt_euro(wert * anzahl)])
    table_data.append(['Gezählt (Ist)', '', _fmt_euro(ist_cent)])

    stueck_table = Table(table_data, colWidths=[6 * cm, 4 * cm, 4 * cm])
    stueck_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COL_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('BACKGROUND', (0, -1), (-1, -1), COL_SUMMARY_BG),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#4a90d9')),
    ]))
    story.append(stueck_table)
    story.append(Spacer(1, 0.4 * cm))

    # ------------------------------------------------------------------
    # Soll-/Ist-Abgleich
    # ------------------------------------------------------------------
    story.append(Paragraph('Soll-/Ist-Abgleich', style_section))
    differenz_label = 'stimmt überein' if differenz_cent == 0 else (
        'Überschuss' if differenz_cent > 0 else 'Fehlbetrag')
    abgleich_data = [
        ['Soll (Buchbestand)', _fmt_euro(soll_cent)],
        ['Ist (gezählt)', _fmt_euro(ist_cent)],
        [f'Differenz ({differenz_label})', _fmt_euro(differenz_cent)],
    ]
    abgleich_table = Table(abgleich_data, colWidths=[10 * cm, 4 * cm])
    diff_color = COL_POSITIVE if differenz_cent >= 0 else COL_NEGATIVE
    abgleich_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COL_SUMMARY_BG),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TEXTCOLOR', (1, -1), (1, -1), diff_color),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor('#4a90d9')),
    ]))
    story.append(abgleich_table)

    if notiz:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph('Notiz', style_section))
        story.append(Paragraph(notiz, style_subtitle))

    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cccccc'), spaceAfter=4))
    story.append(Paragraph(
        f'Zählprotokoll "{kasse_name}" · Gezählt: {_fmt_zeitstempel(gezaehlt_am)}'
        + (f' von {gezaehlt_von}' if gezaehlt_von else ''),
        style_footer,
    ))

    doc.build(story)
    return buffer.getvalue()
