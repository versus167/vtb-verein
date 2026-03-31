"""
Kassenbuch-Seite

Zeigt Buchungen der zugänglichen Kassen, ermöglicht Anlegen/Bearbeiten/Stornieren
und CSV-Export. Berechtigungen werden pro Kasse geprüft (via KassenbuchService).
"""
from datetime import date, timedelta
from nicegui import ui
from app.db.datastore import VereinsDB
from app.auth.auth_helper import AuthHelper, require_auth
from app.ui.navigation import create_navigation, set_current_path
from app.ui.date_input_helper import DateInputHelper
from app.models.kasse import Kassenbuchung
from app.services.kassenbuch_service import (
    BuchungGesperrtError, NegativerBestandError,
    KeinSchreibzugriffError, KeinExportrechtError,
    DatumAusserhalbBereichError,
)
from app.services.kassenbuch_pdf_service import (
    erstelle_kassenbuch_pdf,
    letzter_vollstaendiger_monat,
)


KATEGORIEN = [
    'Allgemein',
    'Mitgliedsbeiträge',
    'Veranstaltungen',
    'Sportmaterial',
    'Verwaltung',
    'Spenden',
    'Versicherungen',
    'Reisekosten',
    'Sonstiges',
]


def _default_von_datum() -> str:
    """Gibt das Datum von heute minus 90 Tagen als ISO-String zurück."""
    return str(date.today() - timedelta(days=90))


def create_kassenbuch_page(db: VereinsDB):
    """Registriert die Kassenbuch-Seite als NiceGUI-Route."""

    @ui.page('/kassenbuch')
    @require_auth()
    def kassenbuch_page():
        set_current_path('/kassenbuch')
        create_navigation(db)

        current_user = AuthHelper.get_current_user()
        is_admin = current_user.can_manage_users()

        kassen = db.kassenbuch.get_kassen_fuer_user(current_user.id, is_admin=is_admin)

        if not kassen:
            with ui.column().classes('q-ma-md'):
                ui.label('Kassenbuch').classes('text-h4 q-mb-md')
                with ui.card().classes('bg-warning q-pa-md'):
                    ui.label('⚠️ Du hast keinen Zugriff auf eine Kasse.')
                    ui.label('Bitte einen Administrator um Kassenzugang.').classes('text-caption')
            return

        ui.label('Kassenbuch').classes('text-h4 q-ma-md')

        # Floating Home-Button (nur Mobil, links unten)
        ui.button(
            icon='home',
            on_click=lambda: ui.navigate.to('/')
        ).props('fab color=primary').classes('lt-sm fixed').style(
            'bottom: 16px; left: 16px; z-index: 2000;'
        )

        # State – von_datum startet standardmäßig 90 Tage in der Vergangenheit
        state = {
            'kasse': kassen[0],
            'von_datum': _default_von_datum(),
            'bis_datum': None,
            'include_storniert': False,
            'show_history': False,
        }

        # ------------------------------------------------------------------
        # Hilfsfunktionen
        # ------------------------------------------------------------------

        def fmt_euro(cent: int) -> str:
            return f"{cent / 100:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')

        def hat_schreibzugriff() -> bool:
            if is_admin:
                return True
            b = db.kasse_berechtigungen.get_berechtigung(state['kasse'].id, current_user.id)
            return b is not None and b.darf_schreiben

        def hat_exportrecht() -> bool:
            if is_admin:
                return True
            b = db.kasse_berechtigungen.get_berechtigung(state['kasse'].id, current_user.id)
            return b is not None and b.darf_exportieren

        # ------------------------------------------------------------------
        # Kassen-Header: Tabs + Bestand
        # ------------------------------------------------------------------
        with ui.row().classes('w-full items-center q-px-md q-mb-sm').style('gap: 0'):
            kasse_tabs = ui.tabs().classes('q-mr-auto').props('scrollable')
            with kasse_tabs:
                tab_refs = {}
                for k in kassen:
                    tab_refs[k.id] = ui.tab(str(k.id), label=k.name)

            bestand_label = ui.label('').classes('text-h6 text-right q-px-md')

        # ------------------------------------------------------------------
        # Inhaltsbereich (wird bei Tab-Wechsel neu gerendert)
        # Desktop bekommt seitliches Padding, Mobil keins (Liste geht bis zum Rand)
        # align-items: stretch sorgt dafür, dass Kinder die volle Breite bekommen
        # ------------------------------------------------------------------
        content_area = ui.column().classes('w-full gt-xs:q-px-md').style(
            'width: 100%; align-items: stretch;'
        )

        def refresh_bestand():
            cent = db.kassen.get_bestand_cent(state['kasse'].id)
            farbe = 'text-positive' if cent >= 0 else 'text-negative'
            bestand_label.text = f'Bestand: {fmt_euro(cent)}'
            bestand_label.classes(replace=f'text-h6 text-right q-px-md {farbe}')

        def load_buchungen() -> list[dict]:
            buchungen = db.kassenbuch._buchung.list_kassenbuchungen(
                kasse_id=state['kasse'].id,
                von_datum=state['von_datum'],
                bis_datum=state['bis_datum'],
                include_storniert=state['include_storniert'],
            )
            if state['von_datum']:
                laufend = db.kassen.get_bestand_zum_datum_cent(
                    state['kasse'].id,
                    _tag_vor(state['von_datum'])
                )
            else:
                laufend = state['kasse'].anfangsbestand_cent

            rows = []
            for b in buchungen:
                if not b.ist_storniert:
                    laufend += b.einnahme_cent - b.ausgabe_cent
                rows.append({
                    'id': b.id,
                    'datum': DateInputHelper.format_date_display(b.buchungsdatum),
                    'belegnummer': b.belegnummer or '',
                    'buchungstext': b.buchungstext,
                    'kategorie': b.kategorie,
                    'einnahme': fmt_euro(b.einnahme_cent) if b.einnahme_cent else '',
                    'ausgabe': fmt_euro(b.ausgabe_cent) if b.ausgabe_cent else '',
                    'bestand': fmt_euro(laufend) if not b.ist_storniert else '—',
                    'storniert': b.ist_storniert,
                    'exportiert': b.ist_exportiert,
                    'version': b.version,
                })
            # Neueste Buchung zuerst
            rows.reverse()
            return rows

        def _tag_vor(datum_iso: str) -> str:
            return str(date.fromisoformat(datum_iso) - timedelta(days=1))

        def render_content():
            content_area.clear()
            history_cache: dict[int, list[dict]] = {}

            with content_area:
                refresh_bestand()

                # ----------------------------------------------------------
                # [1] Filter-Accordion
                # ----------------------------------------------------------

                # Desktop-Filterzeile (nur gt-xs sichtbar)
                with ui.row().classes('items-center q-gutter-sm q-mb-sm gt-xs') as _desktop_filter:
                    von_input_d = ui.input(
                        'Von',
                        value=DateInputHelper.format_date_display(state['von_datum']) if state['von_datum'] else '',
                        placeholder='TT.MM.JJJJ'
                    ).classes('w-32')
                    bis_input_d = ui.input(
                        'Bis',
                        value=DateInputHelper.format_date_display(state['bis_datum']) if state['bis_datum'] else '',
                        placeholder='TT.MM.JJJJ'
                    ).classes('w-32')

                    def on_storniert_change_d(e):
                        state['include_storniert'] = e.value
                        render_content()

                    ui.checkbox(
                        'Stornierte einblenden',
                        value=state['include_storniert'],
                        on_change=on_storniert_change_d
                    )

                    def apply_filter_d():
                        von_raw = von_input_d.value.strip()
                        bis_raw = bis_input_d.value.strip()
                        state['von_datum'] = DateInputHelper.parse_date(von_raw) if von_raw else None
                        state['bis_datum'] = DateInputHelper.parse_date(bis_raw) if bis_raw else None
                        render_content()

                    ui.button('Filter anwenden', on_click=apply_filter_d, icon='filter_list').props('outline dense')

                    ui.separator().props('vertical')

                    def on_history_toggle_d(e):
                        state['show_history'] = e.value
                        render_content()

                    ui.checkbox(
                        'Änderungshistorie anzeigen',
                        value=state['show_history'],
                        on_change=on_history_toggle_d,
                    ).props('dense')

                    ui.separator().props('vertical')

                    if hat_schreibzugriff():
                        ui.button('Einnahme', on_click=lambda: show_buchung_dialog('einnahme'), icon='add').props('color=positive dense')
                        ui.button('Ausgabe', on_click=lambda: show_buchung_dialog('ausgabe'), icon='remove').props('color=negative dense')

                    if hat_exportrecht():
                        ui.button('CSV-Export', on_click=show_export_dialog, icon='download').props('color=primary dense outline')
                        ui.button('PDF-Bericht', on_click=show_pdf_dialog, icon='picture_as_pdf').props('color=deep-orange dense outline')

                # Mobile Filter-Accordion (nur lt-sm sichtbar)
                with ui.expansion('Filter & Aktionen', icon='filter_list').classes('lt-sm q-mb-sm').style('width: 100%;') as _mobile_filter:
                    with ui.column().classes('q-gutter-sm q-pa-sm'):
                        von_input_m = ui.input(
                            'Von',
                            value=DateInputHelper.format_date_display(state['von_datum']) if state['von_datum'] else '',
                            placeholder='TT.MM.JJJJ'
                        ).classes('w-full')
                        bis_input_m = ui.input(
                            'Bis',
                            value=DateInputHelper.format_date_display(state['bis_datum']) if state['bis_datum'] else '',
                            placeholder='TT.MM.JJJJ'
                        ).classes('w-full')

                        def on_storniert_change_m(e):
                            state['include_storniert'] = e.value
                            render_content()

                        ui.checkbox(
                            'Stornierte einblenden',
                            value=state['include_storniert'],
                            on_change=on_storniert_change_m
                        )

                        def apply_filter_m():
                            von_raw = von_input_m.value.strip()
                            bis_raw = bis_input_m.value.strip()
                            state['von_datum'] = DateInputHelper.parse_date(von_raw) if von_raw else None
                            state['bis_datum'] = DateInputHelper.parse_date(bis_raw) if bis_raw else None
                            render_content()

                        ui.button('Filter anwenden', on_click=apply_filter_m, icon='filter_list').props('outline dense').classes('w-full')

                        def on_history_toggle_m(e):
                            state['show_history'] = e.value
                            render_content()

                        ui.checkbox(
                            'Änderungshistorie anzeigen',
                            value=state['show_history'],
                            on_change=on_history_toggle_m,
                        ).props('dense')

                        if hat_exportrecht():
                            with ui.row().classes('q-gutter-sm'):
                                ui.button('CSV-Export', on_click=show_export_dialog, icon='download').props('color=primary dense outline')
                                ui.button('PDF-Bericht', on_click=show_pdf_dialog, icon='picture_as_pdf').props('color=deep-orange dense outline')

                # ----------------------------------------------------------
                # FAB Speed-Dial – Einnahme/Ausgabe (rechts unten, nur Mobil)
                # ----------------------------------------------------------
                if hat_schreibzugriff():
                    with ui.element('q-fab').props(
                        'icon=add direction=up color=primary'
                    ).classes('lt-sm fixed').style('bottom: 80px; right: 16px; z-index: 2000;'):
                        ui.element('q-fab-action').props(
                            'icon=add color=positive label=Einnahme'
                        ).on('click', lambda: show_buchung_dialog('einnahme'))
                        ui.element('q-fab-action').props(
                            'icon=remove color=negative label=Ausgabe'
                        ).on('click', lambda: show_buchung_dialog('ausgabe'))

                rows = load_buchungen()
                show_history_col = state['show_history']

                # ----------------------------------------------------------
                # [2a] Mobile Buchungsliste – Swipe-Zeilen mit Tagesgruppen
                # Swipe-Links  → Stornieren (rot)
                # Swipe-Rechts → Bearbeiten (blau)
                # ----------------------------------------------------------

                # CSS einmalig injizieren (idempotent durch id)
                ui.add_head_html('''
                <style id="kasse-mobile-list-style">
                  .kasse-day-header {
                    display: flex;
                    align-items: center;
                    width: 100%;
                    padding: 4px 12px;
                    background: #2c2c2c;
                    color: #ffffff;
                    font-size: 13px;
                    font-weight: 600;
                    letter-spacing: 0.01em;
                    box-sizing: border-box;
                  }
                  .kasse-day-saldo {
                    margin-left: auto;
                    font-size: 13px;
                    font-weight: 700;
                  }
                  .kasse-day-saldo.positiv { color: #69f0ae; }
                  .kasse-day-saldo.negativ { color: #ff5252; }
                  .kasse-buchung-zeile {
                    display: flex;
                    align-items: center;
                    width: 100%;
                    min-height: 48px;
                    padding: 6px 12px;
                    border-bottom: 1px solid #f0f0f0;
                    gap: 8px;
                    background: #ffffff;
                    box-sizing: border-box;
                  }
                  .kasse-buchung-zeile.storniert {
                    background: #fafafa;
                    opacity: 0.6;
                  }
                  .kasse-buchung-text {
                    flex: 1;
                    min-width: 0;
                    overflow: hidden;
                  }
                  .kasse-buchung-title {
                    font-size: 14px;
                    font-weight: 500;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    line-height: 1.3;
                  }
                  .kasse-buchung-title.storniert {
                    text-decoration: line-through;
                    color: #9e9e9e;
                  }
                  .kasse-buchung-sub {
                    font-size: 11px;
                    color: #9e9e9e;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    line-height: 1.2;
                  }
                  .kasse-buchung-betrag {
                    text-align: right;
                    white-space: nowrap;
                    flex-shrink: 0;
                  }
                  .kasse-buchung-betrag .betrag {
                    font-size: 14px;
                    font-weight: 600;
                    display: block;
                    line-height: 1.3;
                  }
                  .kasse-buchung-betrag .positiv { color: #2e7d32; }
                  .kasse-buchung-betrag .negativ { color: #c62828; }
                  .kasse-slide-left {
                    background: #d32f2f;
                    color: white;
                    display: flex;
                    align-items: center;
                    padding: 0 20px;
                    font-size: 13px;
                    gap: 6px;
                  }
                  .kasse-slide-right {
                    background: #1565c0;
                    color: white;
                    display: flex;
                    align-items: center;
                    padding: 0 20px;
                    font-size: 13px;
                    gap: 6px;
                  }
                </style>
                ''')

                # Buchungen nach Datum gruppieren (Reihenfolge bereits neueste zuerst)
                gruppen: dict[str, list[dict]] = {}
                for row in rows:
                    gruppen.setdefault(row['datum'], []).append(row)

                schreibzugriff = hat_schreibzugriff()

                with ui.element('div').classes('lt-sm').style(
                    'width: 100%; display: block; border-top: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0;'
                ):
                    if not rows:
                        with ui.element('div').classes('kasse-buchung-zeile'):
                            ui.label('Keine Buchungen vorhanden.').style('color: #9e9e9e; font-size: 14px;')
                    else:
                        for datum, gruppe in gruppen.items():
                            # Tagessaldo = Bestand der ersten (neuesten) nicht-stornierten Buchung des Tages
                            tages_bestand = next(
                                (r['bestand'] for r in gruppe if r['bestand'] != '—'),
                                gruppe[0]['bestand']
                            )
                            saldo_positiv = not tages_bestand.startswith('-') and tages_bestand != '—'
                            saldo_cls = 'positiv' if saldo_positiv else 'negativ'

                            # Tages-Trennzeile
                            with ui.element('div').classes('kasse-day-header'):
                                ui.html(f'<span>{datum}</span>')
                                ui.html(f'<span class="kasse-day-saldo {saldo_cls}">Saldo&nbsp;&nbsp;{tages_bestand}</span>')

                            # Buchungszeilen des Tages
                            for row in gruppe:
                                row_id = row['id']
                                storniert = row['storniert']
                                exportiert = row['exportiert']
                                kann_bearbeiten = schreibzugriff and not storniert and not exportiert

                                betrag_txt = f"+{row['einnahme']}" if row['einnahme'] else f"-{row['ausgabe']}"
                                betrag_cls = 'positiv' if row['einnahme'] else 'negativ'

                                meta_parts = []
                                if row['belegnummer']:
                                    meta_parts.append(f"#{row['belegnummer']}")
                                meta_parts.append(row['kategorie'])
                                if exportiert:
                                    meta_parts.append('🔒')
                                meta_str = '  ·  '.join(meta_parts)

                                title_cls = 'kasse-buchung-title storniert' if storniert else 'kasse-buchung-title'
                                zeile_cls = 'kasse-buchung-zeile storniert' if storniert else 'kasse-buchung-zeile'

                                if kann_bearbeiten:
                                    # q-slide-item: Swipe-Rechts = Bearbeiten, Swipe-Links = Stornieren
                                    slide = ui.element('q-slide-item').style('display: block; width: 100%;')

                                    # Swipe-Rechts-Slot (Bearbeiten)
                                    slide.add_slot('right', f'''
                                        <div class="kasse-slide-right">
                                            <q-icon name="edit" />
                                            <span>Bearbeiten</span>
                                        </div>
                                    ''')

                                    # Swipe-Links-Slot (Stornieren)
                                    slide.add_slot('left', f'''
                                        <div class="kasse-slide-left">
                                            <q-icon name="block" />
                                            <span>Stornieren</span>
                                        </div>
                                    ''')

                                    with slide:
                                        with ui.element('div').classes(zeile_cls):
                                            with ui.element('div').classes('kasse-buchung-text'):
                                                ui.html(f'<div class="{title_cls}">{row["buchungstext"]}</div>')
                                                ui.html(f'<div class="kasse-buchung-sub">{meta_str}</div>')
                                            with ui.element('div').classes('kasse-buchung-betrag'):
                                                ui.html(f'<span class="betrag {betrag_cls}">{betrag_txt}</span>')

                                    # Swipe-Events auf q-slide-item
                                    slide.on('right', lambda rid=row_id, s=slide: (
                                        s.run_method('reset'),
                                        show_buchung_dialog('edit', buchung_id=rid),
                                    ))
                                    slide.on('left', lambda r=row, s=slide: (
                                        s.run_method('reset'),
                                        show_storno_dialog(r),
                                    ))

                                else:
                                    # Kein Swipe für stornierte / exportierte Buchungen
                                    with ui.element('div').classes(zeile_cls):
                                        with ui.element('div').classes('kasse-buchung-text'):
                                            ui.html(f'<div class="{title_cls}">{row["buchungstext"]}</div>')
                                            ui.html(f'<div class="kasse-buchung-sub">{meta_str}</div>')
                                        with ui.element('div').classes('kasse-buchung-betrag'):
                                            ui.html(f'<span class="betrag {betrag_cls}">{betrag_txt}</span>')

                # ----------------------------------------------------------
                # [2b] Desktop Buchungstabelle – q-table (gt-xs)
                # ----------------------------------------------------------
                columns = [
                    {'name': 'belegnummer', 'label': 'Beleg', 'field': 'belegnummer', 'align': 'left', 'sortable': True},
                    {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'align': 'left', 'sortable': True},
                    {'name': 'buchungstext', 'label': 'Buchungstext', 'field': 'buchungstext', 'align': 'left'},
                    {'name': 'kategorie', 'label': 'Kategorie', 'field': 'kategorie', 'align': 'left'},
                    {'name': 'einnahme', 'label': 'Einnahme', 'field': 'einnahme', 'align': 'right'},
                    {'name': 'ausgabe', 'label': 'Ausgabe', 'field': 'ausgabe', 'align': 'right'},
                    {'name': 'bestand', 'label': 'Bestand', 'field': 'bestand', 'align': 'right'},
                    {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'center'},
                ]

                with ui.element('div').classes('gt-xs w-full'):
                    table = ui.table(
                        columns=columns,
                        rows=rows,
                        row_key='id',
                    ).classes('w-full')

                    body_slot = r'''
                        <q-tr :props="props"
                              :class="props.row.storniert ? 'text-strike text-grey-5' : ''">
                            <q-td key="belegnummer" :props="props">
                                <span>{{ props.row.belegnummer }}</span>
                                <q-icon v-if="props.row.exportiert" name="lock" size="xs"
                                        class="q-ml-xs text-grey-5" title="exportiert" />
                            </q-td>
                            <q-td key="datum" :props="props">{{ props.row.datum }}</q-td>
                            <q-td key="buchungstext" :props="props">{{ props.row.buchungstext }}</q-td>
                            <q-td key="kategorie" :props="props">{{ props.row.kategorie }}</q-td>
                            <q-td key="einnahme" :props="props" class="text-positive text-right">
                                {{ props.row.einnahme }}
                            </q-td>
                            <q-td key="ausgabe" :props="props" class="text-negative text-right">
                                {{ props.row.ausgabe }}
                            </q-td>
                            <q-td key="bestand" :props="props" class="text-right text-weight-bold">
                                {{ props.row.bestand }}
                            </q-td>
                            <q-td key="actions" :props="props">
                    '''

                    if show_history_col:
                        body_slot += r'''
                                    <q-btn v-if="props.row.version > 1"
                                           flat dense round
                                           :icon="props.row._hist_open ? 'expand_less' : 'history'"
                                           size="sm" color="grey"
                                           :title="props.row._hist_open ? 'Historie schließen' : 'Änderungshistorie'"
                                           @click="$parent.$emit('load_history', props.row.id)" />
                        '''

                    body_slot += r'''
                                <q-btn v-if="!props.row.storniert && !props.row.exportiert"
                                       flat dense icon="edit" size="sm"
                                       @click="$parent.$emit('edit', props.row.id)" />
                                <q-btn v-if="!props.row.storniert && !props.row.exportiert"
                                       flat dense icon="block" size="sm" color="negative"
                                       @click="$parent.$emit('stornieren', props.row)" />
                            </q-td>
                        </q-tr>
                    '''

                    if show_history_col:
                        body_slot += r'''
                        <template v-if="props.row._hist_open && props.row._hist_rows">
                            <q-tr v-for="h in props.row._hist_rows"
                                  :key="'h_' + props.row.id + '_' + h.version"
                                  class="text-grey-6 bg-grey-1">
                                <q-td class="text-caption text-grey">v{{ h.version }}</q-td>
                                <q-td class="text-caption">{{ h.datum }}</q-td>
                                <q-td class="text-caption">{{ h.buchungstext }}</q-td>
                                <q-td class="text-caption">{{ h.kategorie }}</q-td>
                                <q-td class="text-caption text-right">{{ h.einnahme }}</q-td>
                                <q-td class="text-caption text-right">{{ h.ausgabe }}</q-td>
                                <q-td class="text-caption text-right text-grey-5">—</q-td>
                                <q-td></q-td>
                            </q-tr>
                        </template>
                        '''

                    table.add_slot('body', body_slot)

                    if hat_schreibzugriff():
                        table.on('edit', lambda e: show_buchung_dialog('edit', buchung_id=int(e.args)))
                        table.on('stornieren', lambda e: show_storno_dialog(e.args))

                    if show_history_col:
                        def on_load_history(e):
                            buchung_id = int(e.args)
                            if buchung_id not in history_cache:
                                raw = db.kassenbuch._buchung.get_history(buchung_id)
                                history_cache[buchung_id] = [
                                    {
                                        'version': h['version'],
                                        'datum': DateInputHelper.format_date_display(h['buchungsdatum']),
                                        'buchungstext': h['buchungstext'],
                                        'kategorie': h['kategorie'],
                                        'einnahme': fmt_euro(h['einnahme_cent']) if h['einnahme_cent'] else '',
                                        'ausgabe': fmt_euro(h['ausgabe_cent']) if h['ausgabe_cent'] else '',
                                    }
                                    for h in raw
                                ]
                            hist_rows = history_cache[buchung_id]
                            for row in table.rows:
                                if row['id'] == buchung_id:
                                    row['_hist_open'] = not row.get('_hist_open', False)
                                    row['_hist_rows'] = hist_rows
                                    break
                            table.update()

                        table.on('load_history', on_load_history)

                    if not rows:
                        ui.label('Keine Buchungen vorhanden.').classes('text-grey q-mt-md gt-xs')

        # ------------------------------------------------------------------
        # Dialog: Buchung anlegen / bearbeiten
        # ------------------------------------------------------------------

        def show_buchung_dialog(modus: str, buchung_id: int = None):
            ist_neu = modus in ('einnahme', 'ausgabe')

            buchung: Kassenbuchung | None = None
            if not ist_neu:
                try:
                    buchung = db.kassenbuch._buchung.get_kassenbuchung(buchung_id)
                except KeyError:
                    ui.notify('Buchung nicht gefunden', type='negative')
                    return

            titel = {
                'einnahme': 'Neue Einnahme',
                'ausgabe': 'Neue Ausgabe',
                'edit': f'Buchung bearbeiten: {buchung.belegnummer}' if buchung else 'Buchung bearbeiten',
            }[modus]

            modus_eff = modus if ist_neu else ('einnahme' if buchung.einnahme_cent > 0 else 'ausgabe')

            min_datum_iso, max_datum_iso = db.kassenbuch.get_datum_bereich(state['kasse'].id)

            with ui.dialog() as dialog, ui.card().style('min-width: min(480px, 95vw)'):
                ui.label(titel).classes('text-h6 q-mb-md')

                datum_input = ui.input(
                    'Datum *',
                    value=DateInputHelper.format_date_display(
                        buchung.buchungsdatum if buchung else date.today().isoformat()
                    ),
                    placeholder='z.B. 28.3.26'
                ).classes('w-full')
                datum_state = {
                    'value': buchung.buchungsdatum if buchung else date.today().isoformat()
                }

                datum_fehler_label = ui.label('').classes('text-negative text-caption q-mt-xs')
                datum_fehler_label.visible = False

                def _datum_bereich_hinweis() -> str:
                    min_fmt = DateInputHelper.format_date_display(min_datum_iso) if min_datum_iso else None
                    max_fmt = DateInputHelper.format_date_display(max_datum_iso)
                    if min_fmt:
                        return f'Erlaubter Bereich: {min_fmt} – {max_fmt}'
                    return f'Datum darf nicht nach {max_fmt} liegen'

                def _prüfe_datum_live(datum_iso: str | None) -> bool:
                    if datum_iso is None:
                        datum_fehler_label.text = 'Ungültiges Datum'
                        datum_fehler_label.visible = True
                        return False
                    if datum_iso > max_datum_iso:
                        datum_fehler_label.text = _datum_bereich_hinweis()
                        datum_fehler_label.visible = True
                        return False
                    if min_datum_iso is not None and datum_iso < min_datum_iso:
                        datum_fehler_label.text = _datum_bereich_hinweis()
                        datum_fehler_label.visible = True
                        return False
                    datum_fehler_label.visible = False
                    return True

                def on_datum_change(e):
                    parsed = DateInputHelper.parse_date(datum_input.value)
                    if parsed:
                        datum_state['value'] = parsed
                        _prüfe_datum_live(parsed)
                    else:
                        datum_state['value'] = None
                        if datum_input.value.strip():
                            datum_fehler_label.text = 'Ungültiges Datum'
                            datum_fehler_label.visible = True
                        else:
                            datum_fehler_label.visible = False

                def on_datum_blur(e):
                    parsed = DateInputHelper.parse_date(datum_input.value)
                    if parsed:
                        datum_state['value'] = parsed
                        datum_input.value = DateInputHelper.format_date_display(parsed)
                        _prüfe_datum_live(parsed)
                    else:
                        datum_state['value'] = None
                        datum_input.error = 'Ungültiges Datum'

                datum_input.on('update:model-value', on_datum_change)
                datum_input.on('blur', on_datum_blur)
                _prüfe_datum_live(datum_state['value'])

                buchungstext_input = ui.input(
                    'Buchungstext *',
                    value=buchung.buchungstext if buchung else ''
                ).classes('w-full')

                kategorie_input = ui.select(
                    label='Kategorie *',
                    options=KATEGORIEN,
                    value=buchung.kategorie if buchung else 'Allgemein'
                ).classes('w-full')

                betrag_label = 'Einnahme (€) *' if modus_eff == 'einnahme' else 'Ausgabe (€) *'
                init_betrag = ''
                if buchung:
                    cent = buchung.einnahme_cent if modus_eff == 'einnahme' else buchung.ausgabe_cent
                    init_betrag = f'{cent / 100:.2f}'
                betrag_input = ui.input(
                    betrag_label,
                    value=init_betrag,
                    placeholder='0,00'
                ).classes('w-full')

                notiz_input = ui.textarea(
                    'Notiz',
                    value=buchung.notiz or '' if buchung else ''
                ).classes('w-full').props('rows=2')

                error_label = ui.label('').classes('text-negative')
                error_label.visible = False

                def save():
                    error_label.visible = False

                    if not datum_state['value']:
                        error_label.text = 'Bitte gültiges Datum eingeben'
                        error_label.visible = True
                        return

                    if not _prüfe_datum_live(datum_state['value']):
                        error_label.text = _datum_bereich_hinweis()
                        error_label.visible = True
                        return

                    if not buchungstext_input.value.strip():
                        error_label.text = 'Buchungstext ist erforderlich'
                        error_label.visible = True
                        return

                    betrag_str = betrag_input.value.strip().replace(',', '.')
                    try:
                        betrag_euro = float(betrag_str)
                        if betrag_euro <= 0:
                            raise ValueError
                        betrag_cent = round(betrag_euro * 100)
                    except ValueError:
                        error_label.text = 'Bitte gültigen Betrag eingeben (z.B. 12,50)'
                        error_label.visible = True
                        return

                    einnahme_cent = betrag_cent if modus_eff == 'einnahme' else 0
                    ausgabe_cent = betrag_cent if modus_eff == 'ausgabe' else 0

                    try:
                        if ist_neu:
                            neue_buchung = Kassenbuchung(
                                kasse_id=state['kasse'].id,
                                buchungsdatum=datum_state['value'],
                                buchungstext=buchungstext_input.value.strip(),
                                kategorie=kategorie_input.value,
                                einnahme_cent=einnahme_cent,
                                ausgabe_cent=ausgabe_cent,
                                notiz=notiz_input.value.strip() or None,
                            )
                            db.kassenbuch.create_buchung(
                                neue_buchung,
                                created_by=current_user.username,
                                user_id=current_user.id,
                                is_admin=is_admin,
                            )
                            ui.notify('Buchung erfolgreich angelegt', type='positive')
                        else:
                            buchung.buchungsdatum = datum_state['value']
                            buchung.buchungstext = buchungstext_input.value.strip()
                            buchung.kategorie = kategorie_input.value
                            buchung.einnahme_cent = einnahme_cent
                            buchung.ausgabe_cent = ausgabe_cent
                            buchung.notiz = notiz_input.value.strip() or None
                            db.kassenbuch.update_buchung(
                                buchung,
                                updated_by=current_user.username,
                                user_id=current_user.id,
                                is_admin=is_admin,
                            )
                            ui.notify('Buchung erfolgreich aktualisiert', type='positive')

                        dialog.close()
                        render_content()

                    except DatumAusserhalbBereichError as e:
                        datum_fehler_label.text = _datum_bereich_hinweis()
                        datum_fehler_label.visible = True
                        error_label.text = str(e)
                        error_label.visible = True
                    except NegativerBestandError as e:
                        error_label.text = str(e)
                        error_label.visible = True
                    except (BuchungGesperrtError, KeinSchreibzugriffError) as e:
                        error_label.text = str(e)
                        error_label.visible = True
                    except Exception as e:
                        error_label.text = f'Fehler: {e}'
                        error_label.visible = True

                with ui.row().classes('w-full q-mt-md'):
                    ui.button('Abbrechen', on_click=dialog.close)
                    ui.button(
                        'Anlegen' if ist_neu else 'Speichern',
                        on_click=save
                    ).props('color=primary')

            dialog.open()

        # ------------------------------------------------------------------
        # Dialog: Buchung stornieren
        # ------------------------------------------------------------------

        def show_storno_dialog(row: dict):
            buchung_id = int(row['id'])
            belegnummer = row.get('belegnummer', '')
            buchungstext = row.get('buchungstext', '')

            with ui.dialog() as dialog, ui.card():
                ui.label('Buchung stornieren?').classes('text-h6 q-mb-md')
                ui.label(f'Beleg {belegnummer}: {buchungstext}')
                ui.label('Die Buchung wird als storniert markiert und bleibt in der History.').classes(
                    'text-caption text-grey q-mt-sm'
                )

                def do_storno():
                    try:
                        db.kassenbuch.storniere_buchung(
                            buchung_id,
                            deleted_by=current_user.username,
                            user_id=current_user.id,
                            is_admin=is_admin,
                        )
                        ui.notify('Buchung storniert', type='warning')
                        dialog.close()
                        render_content()
                    except (BuchungGesperrtError, KeinSchreibzugriffError) as e:
                        ui.notify(str(e), type='negative')
                        dialog.close()
                    except Exception as e:
                        ui.notify(f'Fehler: {e}', type='negative')
                        dialog.close()

                with ui.row().classes('w-full q-mt-md'):
                    ui.button('Abbrechen', on_click=dialog.close).props('color=secondary')
                    ui.button('Stornieren', on_click=do_storno).props('color=negative')

            dialog.open()

        # ------------------------------------------------------------------
        # Dialog: CSV-Export
        # ------------------------------------------------------------------

        def show_export_dialog():
            with ui.dialog() as dialog, ui.card().style('min-width: min(520px, 95vw)'):
                ui.label('CSV-Export').classes('text-h6 q-mb-md')

                bis_input = ui.input(
                    'Bis-Datum *',
                    value=DateInputHelper.format_date_display(date.today().isoformat()),
                    placeholder='TT.MM.JJJJ'
                ).classes('w-full')
                bis_state = {'value': date.today().isoformat()}

                vorschau_container = ui.column().classes('w-full q-mt-sm q-mb-sm')

                def lade_vorschau():
                    vorschau_container.clear()
                    with vorschau_container:
                        if not bis_state['value']:
                            return
                        buchungen = db.kassenbuch._export.get_nicht_exportierte_buchungen(
                            state['kasse'].id, bis_state['value']
                        )
                        if not buchungen:
                            ui.label('Keine exportierbaren Buchungen in diesem Zeitraum.').classes(
                                'text-caption text-grey'
                            )
                            return
                        summe_einnahmen = sum(b['einnahme_cent'] for b in buchungen)
                        summe_ausgaben = sum(b['ausgabe_cent'] for b in buchungen)
                        with ui.card().classes('bg-blue-1 q-pa-sm w-full'):
                            ui.label(f'📋 {len(buchungen)} Buchung(en) werden exportiert').classes(
                                'text-caption text-weight-bold'
                            )
                            with ui.row().classes('q-gutter-md q-mt-xs'):
                                ui.label(f'Einnahmen: {fmt_euro(summe_einnahmen)}').classes(
                                    'text-caption text-positive'
                                )
                                ui.label(f'Ausgaben: {fmt_euro(summe_ausgaben)}').classes(
                                    'text-caption text-negative'
                                )

                def on_bis_blur(e):
                    parsed = DateInputHelper.parse_date(bis_input.value)
                    if parsed:
                        bis_state['value'] = parsed
                        bis_input.value = DateInputHelper.format_date_display(parsed)
                        bis_input.error = None
                        lade_vorschau()
                    else:
                        bis_input.error = 'Ungültiges Datum'
                bis_input.on('blur', on_bis_blur)

                lade_vorschau()

                error_label = ui.label('').classes('text-negative')
                error_label.visible = False

                ui.separator().classes('q-mt-md q-mb-sm')
                ui.label('Bisherige Exporte').classes('text-subtitle2 text-grey-7')
                exporte = db.kassenbuch._export.list_exporte(state['kasse'].id)
                if not exporte:
                    ui.label('Noch keine Exporte für diese Kasse.').classes('text-caption text-grey')
                else:
                    verlauf_cols = [
                        {'name': 'zeitraum', 'label': 'Zeitraum', 'field': 'zeitraum', 'align': 'left'},
                        {'name': 'dateiname', 'label': 'Dateiname', 'field': 'dateiname', 'align': 'left'},
                        {'name': 'anzahl', 'label': 'Buchungen', 'field': 'anzahl', 'align': 'right'},
                        {'name': 'exportiert_von', 'label': 'Von', 'field': 'exportiert_von', 'align': 'left'},
                        {'name': 'exportiert_am', 'label': 'Am', 'field': 'exportiert_am', 'align': 'left'},
                        {'name': 'reexport', 'label': '', 'field': 'reexport', 'align': 'center'},
                    ]
                    verlauf_rows = []
                    for ex in exporte:
                        von_str = DateInputHelper.format_date_display(ex.zeitraum_von) if ex.zeitraum_von else '?'
                        bis_str = DateInputHelper.format_date_display(ex.zeitraum_bis) if ex.zeitraum_bis else '?'
                        am_str = ''
                        if ex.exportiert_am:
                            am_str = str(ex.exportiert_am)[:10]
                            am_str = DateInputHelper.format_date_display(am_str)
                        verlauf_rows.append({
                            'export_id': ex.id,
                            'zeitraum': f'{von_str} – {bis_str}',
                            'dateiname': ex.dateiname,
                            'anzahl': ex.anzahl_buchungen,
                            'exportiert_von': ex.exportiert_von or '',
                            'exportiert_am': am_str,
                        })

                    verlauf_table = ui.table(
                        columns=verlauf_cols,
                        rows=verlauf_rows,
                        row_key='export_id'
                    ).classes('w-full').props('dense flat')

                    verlauf_table.add_slot('body-cell-reexport', r'''
                        <q-td :props="props">
                            <q-btn flat dense round icon="download" size="sm" color="primary"
                                   title="Erneut herunterladen"
                                   @click="$parent.$emit('reexport', props.row.export_id)" />
                        </q-td>
                    ''')

                    def on_reexport(e):
                        export_id = int(e.args)
                        try:
                            dateiname, csv_bytes = db.kassenbuch.reexportiere_csv(
                                export_id=export_id,
                                user_id=current_user.id,
                                is_admin=is_admin,
                            )
                            ui.notify(f'Download gestartet: {dateiname}', type='positive')
                            ui.download(csv_bytes, dateiname)
                        except KeinExportrechtError as e:
                            ui.notify(str(e), type='negative')
                        except Exception as e:
                            ui.notify(f'Fehler beim Re-Export: {e}', type='negative')

                    verlauf_table.on('reexport', on_reexport)

                def do_export():
                    error_label.visible = False
                    if not bis_state['value']:
                        error_label.text = 'Bitte Bis-Datum eingeben'
                        error_label.visible = True
                        return
                    try:
                        dateiname, csv_bytes = db.kassenbuch.exportiere_csv(
                            kasse_id=state['kasse'].id,
                            bis_datum=bis_state['value'],
                            exported_by=current_user.username,
                            user_id=current_user.id,
                            is_admin=is_admin,
                        )
                        ui.notify(f'Export erstellt: {dateiname}', type='positive')
                        ui.download(csv_bytes, dateiname)
                        dialog.close()
                        render_content()
                    except ValueError as e:
                        error_label.text = str(e)
                        error_label.visible = True
                    except KeinExportrechtError as e:
                        error_label.text = str(e)
                        error_label.visible = True
                    except Exception as e:
                        error_label.text = f'Fehler: {e}'
                        error_label.visible = True

                with ui.row().classes('w-full q-mt-md'):
                    ui.button('Abbrechen', on_click=dialog.close)
                    ui.button('Exportieren', on_click=do_export).props('color=primary')

            dialog.open()

        # ------------------------------------------------------------------
        # Dialog: PDF-Bericht
        # ------------------------------------------------------------------

        def show_pdf_dialog():
            von_default, bis_default = letzter_vollstaendiger_monat()

            with ui.dialog() as dialog, ui.card().style('min-width: min(480px, 95vw)'):
                ui.label('PDF-Bericht').classes('text-h6 q-mb-md')

                ui.label(
                    'Standardmäßig ist der letzte komplette Monat vorausgewählt. '
                    'Der Zeitraum kann beliebig angepasst werden.'
                ).classes('text-caption text-grey-7 q-mb-sm')

                pdf_state = {
                    'von': von_default,
                    'bis': bis_default,
                    'include_storniert': False,
                }

                with ui.row().classes('q-gutter-sm'):
                    von_input = ui.input(
                        'Von *',
                        value=DateInputHelper.format_date_display(von_default),
                        placeholder='TT.MM.JJJJ'
                    ).classes('w-36')

                    bis_input = ui.input(
                        'Bis *',
                        value=DateInputHelper.format_date_display(bis_default),
                        placeholder='TT.MM.JJJJ'
                    ).classes('w-36')

                def on_von_blur(e):
                    parsed = DateInputHelper.parse_date(von_input.value)
                    if parsed:
                        pdf_state['von'] = parsed
                        von_input.value = DateInputHelper.format_date_display(parsed)
                        von_input.error = None
                    else:
                        von_input.error = 'Ungültiges Datum'

                def on_bis_blur(e):
                    parsed = DateInputHelper.parse_date(bis_input.value)
                    if parsed:
                        pdf_state['bis'] = parsed
                        bis_input.value = DateInputHelper.format_date_display(parsed)
                        bis_input.error = None
                    else:
                        bis_input.error = 'Ungültiges Datum'

                von_input.on('blur', on_von_blur)
                bis_input.on('blur', on_bis_blur)

                def on_storniert_pdf_change(e):
                    pdf_state['include_storniert'] = e.value

                ui.checkbox(
                    'Stornierte Buchungen mit ausgeben',
                    value=False,
                    on_change=on_storniert_pdf_change,
                ).classes('q-mt-sm')

                error_label = ui.label('').classes('text-negative q-mt-sm')
                error_label.visible = False

                def do_pdf():
                    error_label.visible = False

                    if not pdf_state['von'] or not pdf_state['bis']:
                        error_label.text = 'Bitte Von- und Bis-Datum eingeben'
                        error_label.visible = True
                        return

                    if pdf_state['von'] > pdf_state['bis']:
                        error_label.text = 'Von-Datum muss vor dem Bis-Datum liegen'
                        error_label.visible = True
                        return

                    try:
                        buchungen_raw = db.kassenbuch._buchung.list_kassenbuchungen(
                            kasse_id=state['kasse'].id,
                            von_datum=pdf_state['von'],
                            bis_datum=pdf_state['bis'],
                            include_storniert=pdf_state['include_storniert'],
                        )

                        tag_vor_von = str(
                            date.fromisoformat(pdf_state['von']) - timedelta(days=1)
                        )
                        anfangsbestand = db.kassen.get_bestand_zum_datum_cent(
                            state['kasse'].id,
                            tag_vor_von,
                        )

                        buchungen_dicts = [
                            {
                                'buchungsdatum': b.buchungsdatum,
                                'belegnummer': b.belegnummer,
                                'buchungstext': b.buchungstext,
                                'kategorie': b.kategorie,
                                'einnahme_cent': b.einnahme_cent,
                                'ausgabe_cent': b.ausgabe_cent,
                                'ist_storniert': b.ist_storniert,
                                'exportiert_in_export_id': b.exportiert_in_export_id,
                            }
                            for b in buchungen_raw
                        ]

                        pdf_bytes = erstelle_kassenbuch_pdf(
                            kasse_name=state['kasse'].name,
                            von_datum=pdf_state['von'],
                            bis_datum=pdf_state['bis'],
                            buchungen=buchungen_dicts,
                            anfangsbestand_cent=anfangsbestand,
                            erstellt_von=current_user.username,
                        )

                        von_fmt = pdf_state['von'].replace('-', '')
                        bis_fmt = pdf_state['bis'].replace('-', '')
                        dateiname = (
                            f"kassenbuch_{state['kasse'].name.replace(' ', '_')}"
                            f"_{von_fmt}_{bis_fmt}.pdf"
                        )

                        ui.notify(f'PDF erstellt: {dateiname}', type='positive')
                        ui.download(pdf_bytes, dateiname)
                        dialog.close()

                    except Exception as e:
                        error_label.text = f'Fehler beim PDF-Export: {e}'
                        error_label.visible = True

                with ui.row().classes('w-full q-mt-md'):
                    ui.button('Abbrechen', on_click=dialog.close)
                    ui.button('PDF erstellen', on_click=do_pdf, icon='picture_as_pdf').props('color=deep-orange')

            dialog.open()

        # ------------------------------------------------------------------
        # Tab-Wechsel
        # ------------------------------------------------------------------
        def on_tab_change(e):
            kasse_id = int(e.value)
            state['kasse'] = next(k for k in kassen if k.id == kasse_id)
            state['von_datum'] = _default_von_datum()
            state['bis_datum'] = None
            state['include_storniert'] = False
            state['show_history'] = False
            render_content()

        kasse_tabs.on('update:model-value', on_tab_change)
        kasse_tabs.set_value(str(kassen[0].id))

        # Initiales Rendering
        render_content()
