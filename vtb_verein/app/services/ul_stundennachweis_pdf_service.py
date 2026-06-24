"""PDF-Service für den Übungsleiter-Stundennachweis (Beleg zur Abrechnung).

Erzeugt einen A4-Quer-Beleg im Stil des bisherigen Papier-Formulars:
Vereins-Kopf + Registrier-Nr., ÜL-Stammdaten, Termine je Wochentag mit
Spaltensummen, Monats-Gesamtstunden, Vergütung/h, Gesamtbetrag und
Unterschriftsfeldern (Übungsleiter / Abteilungsleiter).

Reuse: gleiches reportlab-Fundament wie kassenbuch_pdf_service.py.
"""
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

_WOCHENTAGE = {1: 'Montag', 2: 'Dienstag', 3: 'Mittwoch', 4: 'Donnerstag',
               5: 'Freitag', 6: 'Samstag', 7: 'Sonntag'}
_MONATE_KURZ = {1: 'Jan', 2: 'Feb', 3: 'Mär', 4: 'Apr', 5: 'Mai', 6: 'Jun',
                7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Dez'}

_DUNKEL = colors.HexColor('#2c3e50')
_STREIFEN = colors.HexColor('#f5f5f5')


def _fmt_euro(v) -> str:
    if v is None:
        return '–'
    return f"{v:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_std(v) -> str:
    f = float(v)
    return str(int(f)) if f == int(f) else f"{f:.2f}".replace('.', ',')


def _fmt_datum(iso: str) -> str:
    try:
        return date.fromisoformat(iso[:10]).strftime('%d.%m.%Y')
    except (ValueError, TypeError):
        return iso or ''


def _monat_label(ym: str) -> str:
    """'2026-05' → 'Mai 26'."""
    try:
        j, m = ym.split('-')
        return f"{_MONATE_KURZ[int(m)]} {j[2:]}"
    except (ValueError, KeyError):
        return ym


def _wochentag_tabelle(name: str, eintraege: list[dict], style_cell) -> Table:
    """Kleine Tabelle (Datum | Stunden) mit Summenfuß für einen Wochentag."""
    rows = [[Paragraph(f'<b>{name}</b>', style_cell), '']]
    rows.append(['Datum', 'Std.'])
    summe = 0.0
    for e in eintraege:
        rows.append([_fmt_datum(e['datum']), _fmt_std(e['stunden'])])
        summe += float(e['stunden'])
    rows.append(['Summe', _fmt_std(summe)])
    t = Table(rows, colWidths=[3.2 * cm, 1.6 * cm])
    t.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BACKGROUND', (0, 0), (1, 0), _DUNKEL),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.white),
        ('BACKGROUND', (0, 1), (1, 1), _STREIFEN),
        ('FONTNAME', (0, 1), (1, 1), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (1, -1), 0.5, _DUNKEL),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('GRID', (0, 1), (-1, -1), 0.25, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    return t


def erstelle_stundennachweis_pdf(
    *,
    verein: dict,
    ul_name: str,
    sportart: str,
    iban: str | None,
    trainerlizenz_nr: str | None,
    qualifikation: str | None,
    lizenz_klassifikation: str,
    foerder_klassifikation: str | None,
    zeitraum_von: str,
    zeitraum_bis: str,
    termine: list[dict],
    summen: dict,
    erstellt_von: str = '',
) -> bytes:
    """Erzeugt den Stundennachweis-Beleg als PDF (bytes).

    :param verein: {'name','strasse','plz_ort','registrier_nr'}
    :param termine: Liste {datum, stunden, wochentag, angebot}
    :param summen: {summe_stunden, verguetung_pro_stunde, gesamtbetrag, monatssummen}
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm,
        title=f'Übungsleiter-Stundennachweis {ul_name}',
        author=erstellt_von or 'VTB-Vereinsverwaltung',
    )

    styles = getSampleStyleSheet()
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontName='Helvetica', fontSize=8)
    h_left = ParagraphStyle('hl', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11)
    h_addr = ParagraphStyle('ha', parent=styles['Normal'], fontName='Helvetica', fontSize=8)
    h_title = ParagraphStyle('ht', parent=styles['Normal'], fontName='Helvetica-Bold',
                             fontSize=14, alignment=2, spaceAfter=5)
    h_sub = ParagraphStyle('hs', parent=styles['Normal'], fontName='Helvetica', fontSize=8,
                           alignment=2)

    story = []

    # ── Kopf: Verein links, Titel rechts ──
    kopf = Table([[
        Paragraph(
            f"{verein.get('name', '')}<br/>{verein.get('strasse', '')}<br/>{verein.get('plz_ort', '')}",
            ParagraphStyle('hbox', parent=h_addr, leading=12, fontSize=9),
        ),
        [Paragraph('Übungsleiter-Stundennachweis', h_title),
         Paragraph(f"{verein.get('name', '')} – Registrier-Nr. {verein.get('registrier_nr', '')}", h_sub)],
    ]], colWidths=[13 * cm, 12.5 * cm])
    kopf.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(kopf)
    story.append(Spacer(1, 0.4 * cm))

    # ── Stammdaten-Block ──
    lizenz_label = 'mit Lizenz' if lizenz_klassifikation == 'mit_lizenz' else 'ohne Lizenz'
    info = Table([
        [Paragraph('<b>Name des Übungsleiters:</b>', cell), Paragraph(ul_name or '', cell),
         Paragraph('<b>Sportart / Abteilung:</b>', cell), Paragraph(sportart or '', cell)],
        [Paragraph('<b>Konto-Nr. / IBAN:</b>', cell), Paragraph(iban or '', cell),
         Paragraph('<b>Klassifikation:</b>', cell),
         Paragraph(lizenz_label + (f" · {foerder_klassifikation}" if foerder_klassifikation else ''), cell)],
        [Paragraph('<b>Qualifikation / Trainerlizenz (Nr.):</b>', cell),
         Paragraph(' / '.join(x for x in [qualifikation, trainerlizenz_nr] if x), cell),
         Paragraph('<b>Zeitraum:</b>', cell),
         Paragraph(f"{_fmt_datum(zeitraum_von)} – {_fmt_datum(zeitraum_bis)}", cell)],
    ], colWidths=[5 * cm, 8 * cm, 4.5 * cm, 8 * cm])
    info.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(info)
    story.append(Spacer(1, 0.4 * cm))

    # ── Termine je Wochentag (nebeneinander, max. 4 pro Reihe) ──
    nach_wochentag: dict[int, list[dict]] = {}
    for t in termine:
        wt = t.get('wochentag') or (date.fromisoformat(t['datum'][:10]).isoweekday())
        nach_wochentag.setdefault(wt, []).append(t)
    weekday_tables = [
        _wochentag_tabelle(_WOCHENTAGE.get(wt, str(wt)),
                           sorted(eintr, key=lambda e: e['datum']), cell)
        for wt, eintr in sorted(nach_wochentag.items())
    ]
    if weekday_tables:
        per_row = 4
        for i in range(0, len(weekday_tables), per_row):
            chunk = weekday_tables[i:i + per_row]
            grid = Table([chunk], colWidths=[6.2 * cm] * len(chunk))
            grid.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(grid)
            story.append(Spacer(1, 0.2 * cm))
    else:
        story.append(Paragraph('<i>Keine Termine erfasst.</i>', cell))

    story.append(Spacer(1, 0.3 * cm))

    # ── Zusammenfassung ──
    monats_rows = [[_monat_label(ym), _fmt_std(std)]
                   for ym, std in sorted(summen.get('monatssummen', {}).items())]
    zus_rows = [['Gesamtstunden', _fmt_std(summen.get('summe_stunden', 0))]]
    zus_rows += monats_rows
    zus_rows.append(['Vergütung / h', _fmt_euro(summen.get('verguetung_pro_stunde'))])
    zus_rows.append(['Gesamtbetrag', _fmt_euro(summen.get('gesamtbetrag'))])
    zus = Table(zus_rows, colWidths=[5 * cm, 3.5 * cm], hAlign='RIGHT')
    zus.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BACKGROUND', (0, 0), (-1, 0), _STREIFEN),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), _STREIFEN),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(zus)
    story.append(Spacer(1, 1.0 * cm))

    # ── Unterschriften ──
    sign = Table([
        ['', ''],
        [Paragraph('Übungsleiter', cell), Paragraph('Abteilungsleiter', cell)],
    ], colWidths=[12 * cm, 12 * cm])
    sign.setStyle(TableStyle([
        ('LINEABOVE', (0, 1), (0, 1), 0.5, colors.black),
        ('LINEABOVE', (1, 1), (1, 1), 0.5, colors.black),
        ('TOPPADDING', (0, 1), (-1, 1), 2),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    story.append(sign)

    doc.build(story)
    return buffer.getvalue()
