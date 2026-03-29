"""
Kassenbuch-Seite

Zeigt Buchungen der zugänglichen Kassen, ermöglicht Anlegen/Bearbeiten/Stornieren
und CSV-Export. Berechtigungen werden pro Kasse geprüft (via KassenbuchService).
"""
from datetime import date
from nicegui import ui
from app.db.datastore import VereinsDB
from app.auth.auth_helper import AuthHelper, require_auth
from app.ui.navigation import create_navigation, set_current_path
from app.ui.date_input_helper import DateInputHelper
from app.models.kasse import Kassenbuchung
from app.services.kassenbuch_service import (
    BuchungGesperrtError, NegativerBestandError,
    KeinSchreibzugriffError, KeinExportrechtError,
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

        # State
        state = {
            'kasse': kassen[0],
            'von_datum': None,
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
            kasse_tabs = ui.tabs().classes('q-mr-auto')
            with kasse_tabs:
                tab_refs = {}
                for k in kassen:
                    tab_refs[k.id] = ui.tab(str(k.id), label=k.name)

            bestand_label = ui.label('').classes('text-h6 text-right q-px-md')

        # ------------------------------------------------------------------
        # Inhaltsbereich (wird bei Tab-Wechsel neu gerendert)
        # ------------------------------------------------------------------
        content_area = ui.column().classes('w-full q-px-md')

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
            return rows

        def _tag_vor(datum_iso: str) -> str:
            from datetime import timedelta
            return str(date.fromisoformat(datum_iso) - timedelta(days=1))

        def render_content():
            content_area.clear()
            # Cache für bereits geladene History-Daten (buchung_id -> list[dict])
            history_cache: dict[int, list[dict]] = {}

            with content_area:
                refresh_bestand()

                # ---------- Filterzeile ----------
                with ui.row().classes('items-center q-gutter-sm q-mb-sm'):
                    von_input = ui.input(
                        'Von',
                        value=DateInputHelper.format_date_display(state['von_datum']) if state['von_datum'] else '',
                        placeholder='TT.MM.JJJJ'
                    ).classes('w-32')
                    bis_input = ui.input(
                        'Bis',
                        value=DateInputHelper.format_date_display(state['bis_datum']) if state['bis_datum'] else '',
                        placeholder='TT.MM.JJJJ'
                    ).classes('w-32')

                    def on_storniert_change(e):
                        state['include_storniert'] = e.value
                        render_content()

                    ui.checkbox(
                        'Stornierte einblenden',
                        value=state['include_storniert'],
                        on_change=on_storniert_change
                    )

                    def apply_filter():
                        von_raw = von_input.value.strip()
                        bis_raw = bis_input.value.strip()
                        state['von_datum'] = DateInputHelper.parse_date(von_raw) if von_raw else None
                        state['bis_datum'] = DateInputHelper.parse_date(bis_raw) if bis_raw else None
                        render_content()

                    ui.button('Filter anwenden', on_click=apply_filter, icon='filter_list').props('outline dense')

                    ui.separator().props('vertical')

                    def on_history_toggle(e):
                        state['show_history'] = e.value
                        render_content()

                    ui.checkbox(
                        'Änderungshistorie anzeigen',
                        value=state['show_history'],
                        on_change=on_history_toggle,
                    ).props('dense')

                    ui.separator().props('vertical')

                    if hat_schreibzugriff():
                        ui.button('Einnahme', on_click=lambda: show_buchung_dialog('einnahme'), icon='add').props('color=positive dense')
                        ui.button('Ausgabe', on_click=lambda: show_buchung_dialog('ausgabe'), icon='remove').props('color=negative dense')

                    if hat_exportrecht():
                        ui.button('CSV-Export', on_click=show_export_dialog, icon='download').props('color=primary dense outline')

                # ---------- Buchungstabelle ----------
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

                rows = load_buchungen()
                show_history_col = state['show_history']
                table = ui.table(columns=columns, rows=rows, row_key='id').classes('w-full')

                # Der NiceGUI body-Slot bekommt 'props' als einzelnes Objekt pro Zeile
                # (NICHT props_list). History-Zeilen direkt nach </q-tr> einfügen.
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
                    ui.label('Keine Buchungen vorhanden.').classes('text-grey q-mt-md')

        # ------------------------------------------------------------------
        # Dialog: Buchung anlegen / bearbeiten
        # ------------------------------------------------------------------

        def show_buchung_dialog(modus: str, buchung_id: int = None):
            """
            modus: 'einnahme' | 'ausgabe' | 'edit'
            buchung_id: Nur bei modus='edit' übergeben; Buchung wird frisch aus DB geladen.
            """
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

            with ui.dialog() as dialog, ui.card().style('min-width: 480px'):
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

                def on_datum_blur(e):
                    parsed = DateInputHelper.parse_date(datum_input.value)
                    if parsed:
                        datum_state['value'] = parsed
                        datum_input.value = DateInputHelper.format_date_display(parsed)
                        datum_input.error = None
                    else:
                        datum_input.error = 'Ungültiges Datum'
                datum_input.on('blur', on_datum_blur)

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
            """row ist das plain dict aus dem Vue-Event (JSON-serialisiert)."""
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
            with ui.dialog() as dialog, ui.card().style('min-width: 480px'):
                ui.label('CSV-Export').classes('text-h6 q-mb-md')

                # Bis-Datum-Eingabe
                bis_input = ui.input(
                    'Bis-Datum *',
                    value=DateInputHelper.format_date_display(date.today().isoformat()),
                    placeholder='TT.MM.JJJJ'
                ).classes('w-full')
                bis_state = {'value': date.today().isoformat()}

                # Vorschau-Bereich
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

                # Initiale Vorschau laden
                lade_vorschau()

                error_label = ui.label('').classes('text-negative')
                error_label.visible = False

                # Export-Verlauf
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
                            'zeitraum': f'{von_str} – {bis_str}',
                            'dateiname': ex.dateiname,
                            'anzahl': ex.anzahl_buchungen,
                            'exportiert_von': ex.exportiert_von or '',
                            'exportiert_am': am_str,
                        })
                    ui.table(
                        columns=verlauf_cols,
                        rows=verlauf_rows,
                        row_key='dateiname'
                    ).classes('w-full').props('dense flat')

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
        # Tab-Wechsel
        # ------------------------------------------------------------------
        def on_tab_change(e):
            kasse_id = int(e.value)
            state['kasse'] = next(k for k in kassen if k.id == kasse_id)
            state['von_datum'] = None
            state['bis_datum'] = None
            state['include_storniert'] = False
            state['show_history'] = False
            render_content()

        kasse_tabs.on('update:model-value', on_tab_change)
        kasse_tabs.set_value(str(kassen[0].id))

        # Initiales Rendering
        render_content()
