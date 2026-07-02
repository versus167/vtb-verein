"""PDF-Service für den Übungsleiter-Stundennachweis (Beleg zur Abrechnung).

Erzeugt einen A4-Quer-Beleg im Stil des bisherigen Papier-Formulars:
Vereins-Kopf + Registrier-Nr., ÜL-Stammdaten, Termine je Wochentag mit
Spaltensummen, Monats-Gesamtstunden, Vergütung/h, Gesamtbetrag und
Unterschriftsfeldern (Übungsleiter / Abteilungsleiter).

Reuse: gleiches reportlab-Fundament wie kassenbuch_pdf_service.py.
"""
from datetime import date, datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

_WOCHENTAGE_KURZ = {1: 'Mo', 2: 'Di', 3: 'Mi', 4: 'Do', 5: 'Fr', 6: 'Sa', 7: 'So'}
_MONATE_KURZ = {1: 'Jan', 2: 'Feb', 3: 'Mär', 4: 'Apr', 5: 'Mai', 6: 'Jun',
                7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Dez'}

_DUNKEL = colors.HexColor('#2c3e50')
_STREIFEN = colors.HexColor('#f5f5f5')

# Feste, knappe Spaltenbreiten der Termin-Tabelle: das Datum ('04.05.26,Mo') ist max.
# 11 Zeichen, die Stunden nur wenige – daher schmal statt auf Tabellenbreite gestreckt.
_DATUM_W = 1.85 * cm
_STD_W = 0.85 * cm


def _fmt_euro(v) -> str:
    if v is None:
        return '–'
    return f"{v:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_std(v) -> str:
    f = float(v)
    return str(int(f)) if f == int(f) else f"{f:.2f}".replace('.', ',')


def _als_date(wert):
    """Wandelt ISO-String oder datetime/date in ein date; None bei Fehlschlag."""
    if isinstance(wert, datetime):
        return wert.date()
    if isinstance(wert, date):
        return wert
    try:
        return date.fromisoformat(str(wert)[:10])
    except (ValueError, TypeError):
        return None


def _fmt_datum(wert) -> str:
    """Formatiert ISO-Strings ODER datetime/date-Objekte (timestamptz liefert datetime)
    einheitlich als TT.MM.JJJJ."""
    if wert is None:
        return ''
    d = _als_date(wert)
    return d.strftime('%d.%m.%Y') if d else str(wert)


def _fmt_datum_kurz_wt(wert) -> str:
    """Kompaktes Termin-Datum mit Wochentagskürzel, z. B. '04.05.26,Mo'."""
    d = _als_date(wert)
    if d is None:
        return _fmt_datum(wert)
    return f"{d.strftime('%d.%m.%y')},{_WOCHENTAGE_KURZ[d.isoweekday()]}"


def _kuerzen(text: str, max_pt: float, font: str = 'Helvetica', size: int = 8) -> str:
    """Kürzt Text auf die verfügbare Spaltenbreite (in pt), damit er einzeilig bleibt –
    hängt '…' an, wenn abgeschnitten wird. So passen auch 3 Monatsspalten auf eine Seite."""
    text = (text or '').strip()
    if not text or stringWidth(text, font, size) <= max_pt:
        return text
    ell = '…'
    while text and stringWidth(text + ell, font, size) > max_pt:
        text = text[:-1]
    return (text.rstrip() + ell) if text else ell


def _monat_label(ym: str) -> str:
    """'2026-05' → 'Mai 26'."""
    try:
        j, m = ym.split('-')
        return f"{_MONATE_KURZ[int(m)]} {j[2:]}"
    except (ValueError, KeyError):
        return ym


def _monat_tabelle(name: str, eintraege: list[dict], style_cell,
                   angebot_breite: float = 0.0, mit_angebot: bool = False) -> Table:
    """Tabelle (Datum | Stunden [| Angebot]) mit Summenfuß für einen Monat.

    Die Termine sind chronologisch gelistet; das Datum trägt das Wochentagskürzel
    ('04.05.26,Mo'), da nicht mehr nach Wochentag gruppiert wird. Datum- und Std-Spalte
    haben eine feste, knappe Breite; nur die optionale Angebot-Spalte bekommt die per
    ``angebot_breite`` vorgegebene Restbreite."""
    last = 2 if mit_angebot else 1
    colWidths = [_DATUM_W, _STD_W] + ([angebot_breite] if mit_angebot else [])
    rows = [[Paragraph(f'<b>{name}</b>', style_cell)] + [''] * last]
    rows.append(['Datum', 'Std.', 'Angebot'][:last + 1])
    summe = 0.0
    for e in eintraege:
        row = [_fmt_datum_kurz_wt(e['datum']), _fmt_std(e['stunden'])]
        if mit_angebot:
            # einzeilig auf die Angebot-Spaltenbreite (minus 3+3 pt Padding) kürzen
            row.append(_kuerzen(e.get('angebot') or '', angebot_breite - 6))
        rows.append(row)
        summe += float(e['stunden'])
    rows.append(['Summe', _fmt_std(summe)] + ([''] if mit_angebot else []))
    # repeatRows: Monats-Kopf + Spaltenüberschrift beim Seitenumbruch wiederholen,
    # damit ein langer Monat sauber über mehrere Seiten laufen kann.
    t = Table(rows, colWidths=colWidths, repeatRows=2)
    t.setStyle(TableStyle([
        ('SPAN', (0, 0), (last, 0)),
        ('BACKGROUND', (0, 0), (last, 0), _DUNKEL),
        ('TEXTCOLOR', (0, 0), (last, 0), colors.white),
        ('BACKGROUND', (0, 1), (last, 1), _STREIFEN),
        ('FONTNAME', (0, 1), (last, 1), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (last, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (last, -1), 0.5, _DUNKEL),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('GRID', (0, 1), (-1, -1), 0.25, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        # knappe Zeilenhöhe: ein voller Monat (31 Termine) passt so in eine Spalte/Seite
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
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
    eingereicht_von: str | None = None,
    eingereicht_am=None,
    bestaetigt_von: str | None = None,
    bestaetigt_am=None,
) -> bytes:
    """Erzeugt den Stundennachweis-Beleg als PDF (bytes).

    :param verein: {'name','strasse','plz_ort','registrier_nr'}
    :param termine: Liste {datum, stunden, wochentag, angebot}
    :param summen: {summe_stunden, verguetung_pro_stunde, gesamtbetrag, monatssummen}
    :param eingereicht_von/_am: Erfasser + Einreich-Zeitpunkt (Nachweis-Block)
    :param bestaetigt_von/_am: Bestätiger + Bestätigungs-Zeitpunkt (Nachweis-Block)
    """
    buffer = BytesIO()
    # A4 hoch: nutzbare Breite = 21,0 − 2×1,5 = 18,0 cm.
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm,
        title=f'Übungsleiter-Stundennachweis {ul_name}',
        author=erstellt_von or 'VTB-Vereinsverwaltung',
    )

    styles = getSampleStyleSheet()
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontName='Helvetica', fontSize=8)
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
    ]], colWidths=[9.5 * cm, 8.5 * cm])
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
    ], colWidths=[4.3 * cm, 4.7 * cm, 4.3 * cm, 4.7 * cm])
    info.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(info)
    story.append(Spacer(1, 0.4 * cm))

    # ── Termine je Monat (nebeneinander) ──
    # Gruppierung nach Monat; Termine chronologisch, Datum mit Wochentagskürzel. Monate
    # stehen nebeneinander (per_row) und brechen bei zu vielen Monaten in die nächste Reihe.
    # Ausnahme: Ein einzelner Monat, der höher als eine Seite ist, wird NICHT verschachtelt,
    # sondern direkt in die Story gelegt, damit er über Seiten umbrechen kann (sonst crasht
    # reportlab an der nicht-teilbaren, verschachtelten Tabelle).
    mit_angebot = any((t.get('angebot') or '').strip() for t in termine)
    nach_monat: dict[str, list[dict]] = {}
    for t in termine:
        nach_monat.setdefault(t['datum'][:7], []).append(t)
    tabellen_daten = [(ym, sorted(eintr, key=lambda e: e['datum']))
                      for ym, eintr in sorted(nach_monat.items())]
    if tabellen_daten:
        usable = 18.0 * cm                               # A4 hoch − Ränder
        if mit_angebot:
            # Monatsbreite so, dass 3 Spalten (3 Monate) nebeneinander auf eine Seite passen;
            # die Angebot-Spalte bekommt den Rest, ihr Text wird auf diese Breite gekürzt.
            breite = 6.0 * cm
            angebot_breite = breite - _DATUM_W - _STD_W
        else:
            breite = _DATUM_W + _STD_W                   # schmale Datum-/Std-Tabelle
            angebot_breite = 0.0
        per_row = max(1, min(len(tabellen_daten), int(usable / breite + 1e-6)))
        seiten_budget = 720                              # pt – A4 hoch bietet ~774 pt Rahmenhöhe

        def _flush(reihe: list) -> None:
            if not reihe:
                return
            if len(reihe) == 1:
                story.append(reihe[0])                   # einzeln → seitenübergreifend umbrechbar
            else:
                grid = Table([reihe], colWidths=[breite] * len(reihe), hAlign='LEFT')
                grid.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ]))
                story.append(grid)
            story.append(Spacer(1, 0.3 * cm))

        reihe: list = []
        for ym, eintr in tabellen_daten:
            t = _monat_tabelle(_monat_label(ym), eintr, cell, angebot_breite, mit_angebot)
            if t.wrap(breite, 1_000_000)[1] > seiten_budget:
                _flush(reihe); reihe = []               # laufende Reihe abschließen
                _flush([t])                             # überlangen Monat einzeln (umbrechbar)
            else:
                reihe.append(t)
                if len(reihe) == per_row:
                    _flush(reihe); reihe = []
        _flush(reihe)
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

    # ── Bestätigungs-Nachweis (ersetzt die physische Unterschrift) ──
    # Es gibt keine handschriftliche Unterschrift mehr; der gedruckte Name + Datum von
    # Einreichung und Bestätigung ist der Freigabe-Nachweis. Bei Entwürfen (noch keine
    # Daten) entfällt der Block ganz.
    def _nachweis(prefix: str, wer: str | None, wann) -> str:
        teile = [t for t in (wer, _fmt_datum(wann) if wann else '') if t]
        return f"{prefix}: {', '.join(teile)}" if teile else ''

    eing_txt = _nachweis('Eingereicht', eingereicht_von, eingereicht_am)
    best_txt = _nachweis('Bestätigt', bestaetigt_von, bestaetigt_am)
    if eing_txt or best_txt:
        story.append(Spacer(1, 0.6 * cm))
        sig = ParagraphStyle('sig', parent=cell, fontSize=9, leading=12)
        nachweis = Table([[Paragraph(eing_txt, sig), Paragraph(best_txt, sig)]],
                         colWidths=[9 * cm, 9 * cm], hAlign='LEFT')
        nachweis.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LINEABOVE', (0, 0), (-1, 0), 0.5, _DUNKEL),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(nachweis)

    doc.build(story)
    return buffer.getvalue()
