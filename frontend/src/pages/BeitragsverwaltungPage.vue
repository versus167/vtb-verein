<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Beitragsverwaltung</div>

    <q-tabs v-model="tab" dense align="left" class="q-mb-md">
      <q-tab name="regeln"       label="Regeln"        icon="rule" />
      <q-tab name="abrechnung"   label="Abrechnung"    icon="calculate" />
      <q-tab name="sollstellungen" label="Sollstellungen" icon="list_alt" />
    </q-tabs>

    <!-- ════════════════════════════════════════════════
         Tab: Beitragsregeln
         ════════════════════════════════════════════════ -->
    <q-tab-panels v-model="tab" animated>
      <q-tab-panel name="regeln" class="q-pa-none">
        <div class="row items-center q-mb-md">
          <q-select v-model="filterAbteilung" :options="abteilungFilterOptions"
            emit-value map-options clearable dense outlined
            label="Abteilung filtern" style="min-width: 240px" />
          <q-space />
          <q-btn v-if="kannSchreiben" icon="add" label="Neue Regel" color="primary"
            unelevated @click="openRegelDialog()" />
        </div>
        <div v-if="regelnLoading" class="row justify-center q-py-xl">
          <q-spinner size="40px" color="primary" />
        </div>
        <q-list bordered separator v-else>
          <q-item v-for="r in gefilterteRegeln" :key="r.id">
            <q-item-section>
              <q-item-label class="text-weight-medium">{{ r.name }}</q-item-label>
              <q-item-label caption>
                {{ r.betrag_pro_monat.toFixed(2) }} €/Monat
                · {{ r.betrag_pro_einzug.toFixed(2) }} €/{{ turnusLabel(r.einzug_turnus) }}
                · ab {{ r.gueltig_ab }}
                <span v-if="r.gueltig_bis"> bis {{ r.gueltig_bis }}</span>
              </q-item-label>
              <q-item-label caption class="q-mt-xs">
                <q-chip v-if="r.abteilung_name" dense size="sm" color="purple" text-color="white">
                  {{ r.abteilung_name }}
                </q-chip>
                <q-chip v-else dense size="sm" color="primary" text-color="white">
                  Alle Mitglieder
                </q-chip>
                <q-chip v-if="r.bedingung_abteilung_status" dense size="sm" color="orange" text-color="white">
                  Status: {{ r.bedingung_abteilung_status }}
                </q-chip>
                <q-chip v-if="r.bedingung_funktion" dense size="sm" color="indigo" text-color="white">
                  Funktion: {{ funktionLabel(r.bedingung_funktion) }}{{ r.bedingung_funktion_abteilung_id ? ` (${abteilungOptions.find(a=>a.id===r.bedingung_funktion_abteilung_id)?.name ?? '?'})` : '' }}
                </q-chip>
                <q-chip v-if="r.ausnahme_funktion" dense size="sm" color="deep-orange" text-color="white">
                  Ausnahme: {{ funktionLabel(r.ausnahme_funktion) }}{{ r.ausnahme_funktion_abteilung_id ? ` (${abteilungOptions.find(a=>a.id===r.ausnahme_funktion_abteilung_id)?.name ?? '?'})` : '' }}
                </q-chip>
                <q-chip v-if="r.bedingung_alter_min != null || r.bedingung_alter_max != null" dense size="sm" color="blue-grey" text-color="white">
                  Alter {{ r.bedingung_alter_min ?? 0 }}–{{ r.bedingung_alter_max ?? '∞' }} J.
                </q-chip>
                <q-chip v-if="r.zahler_typ === 'abteilung'" dense size="sm" color="teal" text-color="white">
                  Zahlung: {{ r.abteilung_name ?? 'Abteilung' }}
                </q-chip>
              </q-item-label>
            </q-item-section>
            <q-item-section side v-if="kannSchreiben">
              <div class="row q-gutter-xs">
                <q-btn flat dense round icon="edit" color="primary" @click="openRegelDialog(r)" />
                <q-btn flat dense round icon="delete" color="negative" @click="deleteRegel(r)" />
              </div>
            </q-item-section>
          </q-item>
          <q-item v-if="gefilterteRegeln.length === 0">
            <q-item-section class="text-grey text-center q-py-md">
              {{ regeln.length === 0 ? 'Noch keine Beitragsregeln angelegt.' : 'Keine Regeln für diese Abteilung.' }}
            </q-item-section>
          </q-item>
        </q-list>
      </q-tab-panel>

      <!-- ════════════════════════════════════════════════
           Tab: Abrechnung
           ════════════════════════════════════════════════ -->
      <q-tab-panel name="abrechnung" class="q-pa-none">
        <q-card flat bordered class="q-mb-md" style="max-width: 480px">
          <q-card-section>
            <div class="text-subtitle1 text-weight-bold q-mb-sm">Abrechnung starten</div>
            <div class="text-caption text-grey-7 q-mb-md">
              Das System berechnet alle fälligen Beiträge zum gewählten Stichtag.
              Bitte erst Vorschau prüfen, dann bestätigen.
            </div>
            <q-input v-model="stichtag" type="date" label="Stichtag *" outlined dense
              :max="heute" class="q-mb-sm" />
            <div class="row q-gutter-sm">
              <q-btn label="Vorschau berechnen" outline color="primary" :loading="vorschauLoading"
                :disable="!stichtag" @click="ladeVorschau" />
            </div>
          </q-card-section>
        </q-card>

        <!-- Vorschau-Tabelle -->
        <template v-if="vorschau.length > 0">
          <div class="row q-gutter-sm q-mb-sm items-center">
            <q-input v-model="vorschauFilterName" dense outlined clearable
              label="Nach Name suchen" style="min-width: 200px" />
            <q-select v-model="vorschauFilterAbteilung" :options="vorschauAbteilungOptionen"
              emit-value map-options clearable dense outlined
              label="Abteilung filtern" style="min-width: 200px" />
            <div class="text-subtitle2 col-auto">
              {{ gefilterteVorschau.filter(p => !p.bereits_vorhanden).length }} neu,
              {{ gefilterteVorschau.filter(p => p.bereits_vorhanden).length }} vorhanden
              <span v-if="vorschauFilterName || vorschauFilterAbteilung" class="text-grey-6">
                (von {{ vorschauNeu.length + vorschauDuplikate.length }} gesamt)
              </span>
            </div>
          </div>
          <q-table :rows="gefilterteVorschau" :columns="vorschauColumns" :row-key="vorschauRowKey"
            flat bordered dense :rows-per-page-options="[0]" hide-bottom>
            <template #body-cell-status="props">
              <q-td :props="props">
                <q-chip dense size="sm"
                  :color="props.row.bereits_vorhanden ? 'grey' : 'positive'"
                  text-color="white">
                  {{ props.row.bereits_vorhanden ? 'vorhanden' : 'neu' }}
                </q-chip>
              </q-td>
            </template>
            <template #body-cell-zahler="props">
              <q-td :props="props">
                <q-chip dense size="sm"
                  :color="props.row.zahler_typ === 'abteilung' ? 'teal' : 'primary'"
                  text-color="white">
                  {{ props.row.zahler_typ === 'abteilung' ? 'Abteilung' : 'SEPA' }}
                </q-chip>
              </q-td>
            </template>
          </q-table>
          <div class="q-mt-md">
            <q-btn v-if="kannAbrechnen && vorschauNeu.length > 0"
              label="Abrechnung bestätigen" color="primary" unelevated
              :loading="abrechnungLoading" @click="confirmAbrechnung" />
          </div>
        </template>

        <!-- Ergebnis -->
        <q-banner v-if="abrechnungErgebnis" class="bg-positive text-white q-mt-md" rounded>
          <template #avatar><q-icon name="check_circle" /></template>
          <strong>{{ abrechnungErgebnis.zeitraum }}</strong> abgerechnet:
          {{ abrechnungErgebnis.angelegt }} Sollstellungen angelegt
          ({{ abrechnungErgebnis.uebersprungen }} übersprungen).
        </q-banner>
      </q-tab-panel>

      <!-- ════════════════════════════════════════════════
           Tab: Sollstellungen
           ════════════════════════════════════════════════ -->
      <q-tab-panel name="sollstellungen" class="q-pa-none">
        <div class="row q-gutter-sm q-mb-md items-center">
          <q-input v-model="filterZeitraum" label="Zeitraum" outlined dense clearable
            placeholder="z.B. 2026-Q4" style="min-width: 160px" />
          <q-btn label="Laden" color="primary" outline dense @click="ladeSollstellungen" />
          <q-btn v-if="kannAbrechnen && filterZeitraum && sollstellungen.some(s => s.status === 'offen' && s.zahler_typ === 'mitglied')"
            icon="download" label="SEPA-Export" color="secondary" outline dense
            @click="sepaExport" />
        </div>

        <q-table :rows="sollstellungen" :columns="sollColumns" row-key="id"
          flat bordered :loading="sollLoading" :rows-per-page-options="[25, 50, 0]">
          <template #body-cell-status="props">
            <q-td :props="props">
              <q-chip dense size="sm" :color="statusColor(props.row.status)" text-color="white">
                {{ props.row.status }}
              </q-chip>
            </q-td>
          </template>
          <template #body-cell-actions="props">
            <q-td :props="props" v-if="kannAbrechnen && props.row.status === 'offen'">
              <q-btn flat dense round icon="check_circle" color="positive" size="sm"
                @click="markBezahlt(props.row)">
                <q-tooltip>Als bezahlt markieren</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="block" color="negative" size="sm"
                @click="markStorniert(props.row)">
                <q-tooltip>Stornieren</q-tooltip>
              </q-btn>
            </q-td>
            <q-td :props="props" v-else />
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>

    <!-- Regel-Dialog -->
    <q-dialog v-model="regelDialogOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:500px'">
        <q-card-section class="text-h6">{{ editingRegel?.id ? 'Regel bearbeiten' : 'Neue Beitragsregel' }}</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="regelForm.name" label="Name *" outlined dense />
          <q-select v-model="regelForm.abteilung_id" :options="abteilungOptions"
            option-value="id" option-label="name" emit-value map-options
            label="Abteilung (leer = Vereinsbeitrag)" outlined dense clearable />
          <div class="row q-gutter-sm">
            <q-input v-model.number="regelForm.betrag_pro_monat" label="Betrag/Monat (€) *"
              outlined dense type="number" step="0.01" class="col" />
            <q-select v-model="regelForm.einzug_turnus"
              :options="turnusOptions" emit-value map-options
              label="Einzug-Turnus" outlined dense class="col" />
          </div>
          <div class="row q-gutter-sm">
            <q-input v-model="regelForm.gueltig_ab" label="Gültig ab *" outlined dense type="date" class="col" />
            <q-input v-model="regelForm.gueltig_bis" label="Gültig bis" outlined dense type="date" class="col" />
          </div>
          <q-input v-model="regelForm.bedingung_abteilung_status"
            label="Nur für Abteilungs-Status (kommagetrennt, leer = alle)"
            outlined dense />
          <q-select
            v-model="regelForm.bedingung_funktion"
            :options="funktionOptionen" emit-value map-options
            label="Bedingung: Nur für Funktion (leer = alle)"
            outlined dense clearable />
          <q-select
            v-if="regelForm.bedingung_funktion"
            v-model="regelForm.bedingung_funktion_abteilung_id"
            :options="abteilungOptions" option-value="id" option-label="name"
            emit-value map-options
            label="Bedingung gilt für Abteilung (leer = alle)"
            outlined dense clearable />
          <q-select
            v-model="regelForm.ausnahme_funktion"
            :options="funktionOptionen" emit-value map-options
            label="Ausnahme: Funktion ausschließen (leer = keine)"
            outlined dense clearable />
          <q-select
            v-if="regelForm.ausnahme_funktion"
            v-model="regelForm.ausnahme_funktion_abteilung_id"
            :options="abteilungOptions" option-value="id" option-label="name"
            emit-value map-options
            label="Ausnahme gilt für Abteilung (leer = alle)"
            outlined dense clearable />
          <div class="row q-gutter-sm">
            <q-input v-model.number="regelForm.bedingung_alter_min" label="Alter von (Jahre)"
              outlined dense type="number" min="0" clearable class="col" />
            <q-input v-model.number="regelForm.bedingung_alter_max" label="Alter bis (Jahre)"
              outlined dense type="number" min="0" clearable class="col" />
          </div>
          <div class="text-caption text-grey-6 q-mb-xs">
            Alter am Abrechnungs-Stichtag. Mitglieder ohne gültiges Geburtsdatum werden bei
            gesetzter Altersbedingung nicht berücksichtigt.
          </div>
          <q-select v-model="regelForm.zahler_typ"
            :options="[{label:'Mitglied zahlt selbst (SEPA)',value:'mitglied'},{label:'Abteilung zahlt',value:'abteilung'}]"
            emit-value map-options label="Zahler" outlined dense />
          <div v-if="regelError" class="text-negative text-caption">{{ regelError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="regelSaving" @click="saveRegel" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

const $q = useQuasar()
const auth = useAuthStore()

const tab = ref('regeln')
const heute = new Date().toISOString().slice(0, 10)

const kannSchreiben    = computed(() => auth.hasPermission('beitraege.write'))
const kannAbrechnen    = computed(() => auth.hasPermission('beitraege.abrechnen'))

// ── Optionen ───────────────────────────────────────────────
const abteilungOptions = ref([])
const funktionOptionen = ref([])

async function loadFunktionOptionen() {
  try {
    const { data } = await api.get('/api/funktionen')
    funktionOptionen.value = data.map(f => ({ label: f.name, value: f.key }))
  } catch {
    funktionOptionen.value = []
  }
}

function funktionLabel(f) {
  return funktionOptionen.value.find(o => o.value === f)?.label ?? f
}
const turnusOptions = [
  { label: 'Monatlich',     value: 'monat' },
  { label: 'Vierteljährlich', value: 'quartal' },
  { label: 'Halbjährlich',  value: 'halbjahr' },
  { label: 'Jährlich',      value: 'jahr' },
]
function turnusLabel(t) {
  return { monat: 'Monat', quartal: 'Quartal', halbjahr: 'Halbjahr', jahr: 'Jahr' }[t] ?? t
}
function statusColor(s) {
  return { offen: 'warning', bezahlt: 'positive', storniert: 'negative' }[s] ?? 'grey'
}

// ── Regeln ─────────────────────────────────────────────────
const regeln = ref([])
const regelnLoading = ref(false)

// Filter nach Abteilung: null = alle, 'verein' = Vereinsbeitrag (ohne Abteilung), sonst abteilung_id
const filterAbteilung = ref(null)
const abteilungFilterOptions = computed(() => [
  { label: 'Verein (alle Mitglieder)', value: 'verein' },
  ...abteilungOptions.value.map(a => ({ label: a.name, value: a.id })),
])
const gefilterteRegeln = computed(() => {
  if (filterAbteilung.value === null) return regeln.value
  if (filterAbteilung.value === 'verein') return regeln.value.filter(r => r.abteilung_id == null)
  // Alle Regeln, die diese Abteilung betreffen: eigene Abteilung, Bedingung auf die
  // Abteilung (Einschluss) oder Ausnahme auf die Abteilung (Ausschluss)
  return regeln.value.filter(r =>
    r.abteilung_id === filterAbteilung.value ||
    r.bedingung_funktion_abteilung_id === filterAbteilung.value ||
    r.ausnahme_funktion_abteilung_id === filterAbteilung.value
  )
})
const regelDialogOpen = ref(false)
const regelSaving = ref(false)
const regelError = ref('')
const editingRegel = ref(null)
const regelForm = ref({})

async function loadRegeln() {
  regelnLoading.value = true
  try {
    const { data } = await api.get('/api/beitraege/regeln')
    regeln.value = data
  } finally {
    regelnLoading.value = false
  }
}

function openRegelDialog(r = null) {
  editingRegel.value = r
  regelError.value = ''
  regelForm.value = r ? {
    name: r.name, abteilung_id: r.abteilung_id,
    betrag_pro_monat: r.betrag_pro_monat, einzug_turnus: r.einzug_turnus,
    gueltig_ab: r.gueltig_ab, gueltig_bis: r.gueltig_bis ?? '',
    bedingung_abteilung_status: r.bedingung_abteilung_status ?? '',
    bedingung_funktion: r.bedingung_funktion ?? null,
    bedingung_funktion_abteilung_id: r.bedingung_funktion_abteilung_id ?? null,
    ausnahme_funktion: r.ausnahme_funktion ?? null,
    ausnahme_funktion_abteilung_id: r.ausnahme_funktion_abteilung_id ?? null,
    bedingung_alter_min: r.bedingung_alter_min ?? null,
    bedingung_alter_max: r.bedingung_alter_max ?? null,
    zahler_typ: r.zahler_typ,
    expected_version: r.version,
  } : {
    name: '', abteilung_id: null,
    betrag_pro_monat: 0, einzug_turnus: 'quartal',
    gueltig_ab: heute, gueltig_bis: '',
    bedingung_abteilung_status: '',
    bedingung_funktion: null,
    bedingung_funktion_abteilung_id: null,
    ausnahme_funktion: null,
    ausnahme_funktion_abteilung_id: null,
    bedingung_alter_min: null,
    bedingung_alter_max: null,
    zahler_typ: 'mitglied',
  }
  regelDialogOpen.value = true
}

async function saveRegel() {
  regelSaving.value = true
  regelError.value = ''
  try {
    const payload = {
      ...regelForm.value,
      betrag_pro_monat: Number(regelForm.value.betrag_pro_monat),
      gueltig_bis: regelForm.value.gueltig_bis || null,
      bedingung_abteilung_status: regelForm.value.bedingung_abteilung_status || null,
      bedingung_funktion: regelForm.value.bedingung_funktion || null,
      ausnahme_funktion: regelForm.value.ausnahme_funktion || null,
      ausnahme_funktion_abteilung_id: regelForm.value.ausnahme_funktion_abteilung_id || null,
      bedingung_alter_min: regelForm.value.bedingung_alter_min === '' || regelForm.value.bedingung_alter_min == null ? null : Number(regelForm.value.bedingung_alter_min),
      bedingung_alter_max: regelForm.value.bedingung_alter_max === '' || regelForm.value.bedingung_alter_max == null ? null : Number(regelForm.value.bedingung_alter_max),
    }
    if (editingRegel.value?.id) {
      await api.put(`/api/beitraege/regeln/${editingRegel.value.id}`, payload)
    } else {
      await api.post('/api/beitraege/regeln', payload)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    regelDialogOpen.value = false
    await loadRegeln()
  } catch (e) {
    regelError.value = e.response?.data?.detail || 'Fehler'
  } finally {
    regelSaving.value = false
  }
}

async function deleteRegel(r) {
  $q.dialog({ title: 'Regel löschen', message: `„${r.name}" wirklich löschen?`, cancel: true })
    .onOk(async () => {
      await api.delete(`/api/beitraege/regeln/${r.id}`)
      await loadRegeln()
    })
}

// ── Abrechnung ─────────────────────────────────────────────
const stichtag = ref(heute)
const vorschau = ref([])
const vorschauLoading = ref(false)
const abrechnungLoading = ref(false)
const abrechnungErgebnis = ref(null)
const vorschauFilterName = ref('')
const vorschauFilterAbteilung = ref(null)

const vorschauNeu = computed(() => vorschau.value.filter(p => !p.bereits_vorhanden))
const vorschauDuplikate = computed(() => vorschau.value.filter(p => p.bereits_vorhanden))

// Eindeutiger Zeilen-Key: ein Mitglied kann mehrere Beiträge haben (Vereins- +
// Abteilungsbeitrag), daher reicht mitglied_id allein nicht – sonst rendert
// q-table beim Filtern doppelte/veraltete Zeilen.
function vorschauRowKey(row) {
  return `${row.mitglied_id}-${row.beitragsregel_id}-${row.zeitraum}`
}

// Abteilungs-Optionen aus den Mitgliedschaften der Vorschau-Mitglieder ableiten.
const vorschauAbteilungOptionen = computed(() => {
  const ids = new Set()
  for (const p of vorschau.value) {
    for (const aid of (p.mitglied_abteilung_ids || [])) ids.add(aid)
  }
  const nameById = new Map(abteilungOptions.value.map(a => [a.id, a.name]))
  return [...ids]
    .map(id => ({ label: nameById.get(id) ?? `Abteilung ${id}`, value: id }))
    .sort((a, b) => (a.label > b.label ? 1 : -1))
})

const gefilterteVorschau = computed(() => {
  let rows = vorschau.value
  if (vorschauFilterName.value) {
    const q = vorschauFilterName.value.toLowerCase()
    rows = rows.filter(p => p.mitglied_name.toLowerCase().includes(q))
  }
  // Abteilungsfilter: alle Beiträge von Mitgliedern, die der Abteilung angehören
  // (egal ob Vereins-, eigener oder fremder Abteilungsbeitrag).
  if (vorschauFilterAbteilung.value != null) {
    rows = rows.filter(p => (p.mitglied_abteilung_ids || []).includes(vorschauFilterAbteilung.value))
  }
  return rows
})

const vorschauColumns = [
  { name: 'mitglied_name',     label: 'Mitglied',     field: 'mitglied_name',     align: 'left' },
  { name: 'beitragsregel_name',label: 'Regel',        field: 'beitragsregel_name',align: 'left' },
  { name: 'betrag',            label: 'Betrag',       field: r => r.betrag.toFixed(2) + ' €', align: 'right' },
  { name: 'zeitraum',          label: 'Zeitraum',     field: 'zeitraum',           align: 'left' },
  { name: 'zahler',            label: 'Zahler',       field: 'zahler_typ',         align: 'left' },
  { name: 'status',            label: 'Status',       field: 'bereits_vorhanden',  align: 'left' },
]

async function ladeVorschau() {
  vorschauLoading.value = true
  abrechnungErgebnis.value = null
  try {
    const { data } = await api.post('/api/beitraege/vorschau', { stichtag: stichtag.value })
    vorschau.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    vorschauLoading.value = false
  }
}

async function confirmAbrechnung() {
  $q.dialog({
    title: 'Abrechnung bestätigen',
    message: `${vorschauNeu.value.length} Sollstellungen anlegen?`,
    cancel: true, persistent: true,
  }).onOk(async () => {
    abrechnungLoading.value = true
    try {
      const { data } = await api.post('/api/beitraege/abrechnen', { stichtag: stichtag.value })
      abrechnungErgebnis.value = data
      vorschau.value = []
      vorschauFilterName.value = ''
      vorschauFilterAbteilung.value = null
      $q.notify({ type: 'positive', message: `Abrechnung ${data.zeitraum} abgeschlossen` })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
    } finally {
      abrechnungLoading.value = false
    }
  })
}

// ── Sollstellungen ─────────────────────────────────────────
const sollstellungen = ref([])
const sollLoading = ref(false)
const filterZeitraum = ref('')

const sollColumns = [
  { name: 'mitglied_name',     label: 'Mitglied',    field: 'mitglied_name',     align: 'left' },
  { name: 'beitragsregel_name',label: 'Regel',       field: 'beitragsregel_name',align: 'left' },
  { name: 'betrag_soll',       label: 'Betrag',      field: r => r.betrag_soll.toFixed(2) + ' €', align: 'right' },
  { name: 'faelligkeitsdatum', label: 'Fällig',      field: 'faelligkeitsdatum', align: 'left' },
  { name: 'status',            label: 'Status',      field: 'status',            align: 'left' },
  { name: 'bezahlt_am',        label: 'Bezahlt am',  field: 'bezahlt_am',        align: 'left' },
  { name: 'actions',           label: '',            field: 'actions',           align: 'right' },
]

async function ladeSollstellungen() {
  if (!filterZeitraum.value) return
  sollLoading.value = true
  try {
    const { data } = await api.get('/api/beitraege/sollstellungen', { params: { zeitraum: filterZeitraum.value } })
    sollstellungen.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    sollLoading.value = false
  }
}

async function markBezahlt(s) {
  const heute = new Date().toISOString().slice(0, 10)
  await api.patch(`/api/beitraege/sollstellungen/${s.id}`, { bezahlt_am: heute })
  await ladeSollstellungen()
}

async function markStorniert(s) {
  $q.dialog({ title: 'Stornieren?', message: `Sollstellung für ${s.mitglied_name} stornieren?`, cancel: true })
    .onOk(async () => {
      await api.patch(`/api/beitraege/sollstellungen/${s.id}`, { bezahlt_am: null })
      await ladeSollstellungen()
    })
}

async function sepaExport() {
  const url = `/api/beitraege/sepa-export/${filterZeitraum.value}`
  const response = await api.get(url, { responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(response.data)
  link.download = `sepa_${filterZeitraum.value}.csv`
  link.click()
}

async function loadOptionen() {
  const { data: ab } = await api.get('/api/abteilungen/')
  abteilungOptions.value = ab
}

onMounted(async () => {
  await Promise.all([loadRegeln(), loadOptionen(), loadFunktionOptionen()])
})
</script>
