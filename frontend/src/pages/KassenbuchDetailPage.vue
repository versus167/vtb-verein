<template>
  <q-page padding>
    <!-- Header -->
    <div class="row items-center q-mb-sm">
      <q-btn flat round dense icon="arrow_back" :to="{ name: 'kassenbuch' }" class="q-mr-sm" />
      <div class="col">
        <div class="text-h5">{{ kasse?.name ?? 'Kassenbuch' }}</div>
        <div v-if="kasse?.beschreibung" class="text-caption text-grey">{{ kasse.beschreibung }}</div>
      </div>
      <div class="text-right">
        <div class="text-h6" :class="bestandCent < 0 ? 'text-negative' : 'text-positive'">
          Bestand: {{ formatEuro(bestandCent) }}
        </div>
      </div>
    </div>

    <!-- Filter + Aktions-Leiste -->
    <div class="row q-gutter-sm q-mb-md items-center">
      <q-input v-model="filterVon" type="date" label="Von" outlined dense style="width: 160px" />
      <q-input v-model="filterBis" type="date" label="Bis" outlined dense style="width: 160px" />
      <q-checkbox v-model="showStorniert" label="Stornierte einblenden" />
      <q-btn label="Filter anwenden" outline color="primary" dense @click="applyFilter" />
      <q-space />
      <q-btn
        v-if="kannSchreiben"
        label="Einnahme"
        icon="add"
        color="positive"
        unelevated
        @click="openCreateDialog('einnahme')"
      />
      <q-btn
        v-if="kannSchreiben"
        label="Ausgabe"
        icon="remove"
        color="negative"
        unelevated
        @click="openCreateDialog('ausgabe')"
      />
      <q-btn
        v-if="kannExportieren"
        label="CSV-Export"
        icon="download"
        color="primary"
        outline
        @click="openExportDialog"
      />
    </div>

    <!-- Journal-Tabelle -->
    <q-table
      :rows="buchungenMitBestand"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      bordered
      :rows-per-page-options="[25, 50, 100, 0]"
      :row-class="rowClass"
    >
      <template #body-cell-belegnummer="props">
        <q-td :props="props">
          <span :class="props.row.deleted_at ? 'text-strike text-grey' : ''">
            {{ props.row.belegnummer }}
          </span>
          <q-icon
            v-if="props.row.exportiert_in_export_id"
            name="lock"
            size="xs"
            color="grey"
            class="q-ml-xs"
          >
            <q-tooltip>Exportiert – nicht mehr änderbar</q-tooltip>
          </q-icon>
        </q-td>
      </template>

      <template #body-cell-einnahme="props">
        <q-td :props="props" class="text-right">
          <span v-if="props.row.einnahme_cent > 0" :class="props.row.deleted_at ? 'text-grey text-strike' : 'text-positive'">
            {{ formatEuro(props.row.einnahme_cent) }}
          </span>
        </q-td>
      </template>

      <template #body-cell-ausgabe="props">
        <q-td :props="props" class="text-right">
          <span v-if="props.row.ausgabe_cent > 0" :class="props.row.deleted_at ? 'text-grey text-strike' : 'text-negative'">
            {{ formatEuro(props.row.ausgabe_cent) }}
          </span>
        </q-td>
      </template>

      <template #body-cell-bestand="props">
        <q-td :props="props" class="text-right text-weight-bold">
          <span v-if="props.row.laufender_bestand_cent !== null">
            {{ formatEuro(props.row.laufender_bestand_cent) }}
          </span>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs" style="white-space: nowrap">
          <template v-if="kannSchreiben && !props.row.deleted_at && !props.row.exportiert_in_export_id">
            <q-btn flat dense round icon="edit" color="primary" size="sm"
              @click="openEditDialog(props.row)" />
            <q-btn flat dense round icon="block" color="negative" size="sm"
              @click="confirmStornieren(props.row)">
              <q-tooltip>Stornieren</q-tooltip>
            </q-btn>
          </template>
        </q-td>
      </template>
    </q-table>

    <!-- Buchung anlegen / bearbeiten -->
    <q-dialog v-model="buchungDialogOpen" persistent>
      <q-card style="min-width: 460px">
        <q-card-section class="text-h6">
          {{ editingBuchungId ? 'Buchung bearbeiten' : (buchungTyp === 'einnahme' ? 'Neue Einnahme' : 'Neue Ausgabe') }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input
            v-model="buchungForm.buchungsdatum"
            type="date"
            label="Datum *"
            outlined
            :min="datumMin ?? undefined"
            :max="datumMax"
          />
          <q-input v-model="buchungForm.buchungstext" label="Buchungstext *" outlined />
          <q-input v-model="buchungForm.kategorie" label="Kategorie" outlined />
          <q-btn-toggle
            v-model="buchungTyp"
            :options="[{ label: 'Einnahme', value: 'einnahme' }, { label: 'Ausgabe', value: 'ausgabe' }]"
            unelevated
            spread
            :toggle-color="buchungTyp === 'einnahme' ? 'positive' : 'negative'"
          />
          <q-input
            v-model.number="buchungBetragEuro"
            :label="buchungTyp === 'einnahme' ? 'Einnahme (€)' : 'Ausgabe (€)'"
            outlined
            type="number"
            step="0.01"
            min="0"
          />
          <q-input v-model="buchungForm.notiz" label="Notiz" outlined type="textarea" rows="2" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            :label="editingBuchungId ? 'Speichern' : (buchungTyp === 'einnahme' ? 'Einnahme buchen' : 'Ausgabe buchen')"
            :color="buchungTyp === 'einnahme' ? 'positive' : 'negative'"
            unelevated
            :loading="buchungSaving"
            @click="onSaveBuchung"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Export-Dialog -->
    <q-dialog v-model="exportDialog" persistent>
      <q-card style="min-width: 520px; max-width: 680px">
        <q-card-section class="text-h6">CSV-Export</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input
            v-model="exportBisDatum"
            type="date"
            label="Bis-Datum *"
            outlined
            :max="today"
            hint="Alle noch nicht exportierten Buchungen bis einschließlich dieses Datums werden gesperrt."
          />
        </q-card-section>

        <q-separator />

        <q-card-section>
          <div class="text-subtitle2 q-mb-sm">Bisherige Exporte</div>
          <q-table
            :rows="exporte"
            :columns="exportColumns"
            row-key="id"
            :loading="exporteLoading"
            flat
            dense
            hide-bottom
            no-data-label="Noch keine Exporte."
          >
            <template #body-cell-actions="props">
              <q-td :props="props">
                <q-btn flat dense round icon="download" color="primary" size="sm"
                  @click="redownload(props.row)">
                  <q-tooltip>Erneut herunterladen</q-tooltip>
                </q-btn>
              </q-td>
            </template>
          </q-table>
        </q-card-section>

        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            label="Exportieren & sperren"
            color="primary"
            unelevated
            :loading="exportLoading"
            :disable="!exportBisDatum"
            @click="doExport"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

const $q = useQuasar()
const route = useRoute()
const auth = useAuthStore()

const kasseId = computed(() => Number(route.params.kasseId))
const isAdmin = computed(() => auth.user?.role === 'admin')

const kasse = ref(null)
const bestandCent = ref(0)
const buchungen = ref([])
const exporte = ref([])
const loading = ref(false)
const exporteLoading = ref(false)

const today = new Date().toISOString().slice(0, 10)
const vor90Tagen = (() => {
  const d = new Date()
  d.setDate(d.getDate() - 90)
  return d.toISOString().slice(0, 10)
})()

const filterVon = ref(vor90Tagen)
const filterBis = ref('')
const showStorniert = ref(false)

const datumMin = ref(null)
const datumMax = ref('')

const kannSchreiben = computed(() => isAdmin.value || true)
const kannExportieren = computed(() => isAdmin.value || true)

const buchungDialogOpen = ref(false)
const buchungSaving = ref(false)
const editingBuchungId = ref(null)
const editingBuchungVersion = ref(null)
const buchungTyp = ref('einnahme')
const buchungBetragEuro = ref(0)
const buchungForm = ref(emptyBuchungForm())

const exportDialog = ref(false)
const exportLoading = ref(false)
const exportBisDatum = ref(today)

// Laufenden Bestand je Buchung berechnen.
// Strategie: rückwärts vom bekannten Gesamtbestand (bestandCent) — kein Extra-API-Aufruf nötig,
// funktioniert auch wenn der Filter nur einen Ausschnitt zeigt.
const buchungenMitBestand = computed(() => {
  // Neueste zuerst anzeigen → Backend-Liste (älteste zuerst) umkehren
  const neuesteZuerst = [...buchungen.value].reverse()
  let bestand = bestandCent.value
  return neuesteZuerst.map(b => {
    const laufend = b.deleted_at ? null : bestand
    if (!b.deleted_at) {
      // Bestand vor dieser Buchung (rückwärts)
      bestand = bestand - b.einnahme_cent + b.ausgabe_cent
    }
    return { ...b, laufender_bestand_cent: laufend }
  })
})

const columns = [
  { name: 'belegnummer', label: 'Beleg', field: 'belegnummer', align: 'left', style: 'width: 80px' },
  { name: 'buchungsdatum', label: 'Datum', field: 'buchungsdatum', align: 'left' },
  { name: 'buchungstext', label: 'Buchungstext', field: 'buchungstext', align: 'left' },
  { name: 'kategorie', label: 'Kategorie', field: 'kategorie', align: 'left' },
  { name: 'einnahme', label: 'Einnahme', field: 'einnahme_cent', align: 'right' },
  { name: 'ausgabe', label: 'Ausgabe', field: 'ausgabe_cent', align: 'right' },
  { name: 'bestand', label: 'Bestand', field: 'laufender_bestand_cent', align: 'right' },
  { name: 'created_by', label: 'Erfasst von', field: 'created_by', align: 'left' },
  { name: 'actions', label: '', field: 'actions', align: 'right', style: 'width: 80px' },
]

const exportColumns = [
  { name: 'zeitraum', label: 'Zeitraum', field: r => `${r.zeitraum_von} – ${r.zeitraum_bis}`, align: 'left' },
  { name: 'dateiname', label: 'Dateiname', field: 'dateiname', align: 'left' },
  { name: 'anzahl_buchungen', label: 'Buchungen', field: 'anzahl_buchungen', align: 'right' },
  { name: 'actions', label: '', field: 'actions', align: 'right' },
]

function rowClass(row) {
  return row.deleted_at ? 'text-grey' : ''
}

function formatEuro(cent) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(cent / 100)
}

function emptyBuchungForm() {
  return { buchungsdatum: today, buchungstext: '', kategorie: '', notiz: '' }
}

async function applyFilter() {
  await Promise.all([loadBuchungen(), loadBestand()])
}

async function loadAll() {
  await Promise.all([loadKasse(), loadBuchungen(), loadBestand(), loadDatumBereich()])
}

async function loadKasse() {
  try {
    const { data } = await api.get('/api/kassen/')
    kasse.value = data.find(k => k.id === kasseId.value) ?? null
  } catch { /* ignorieren */ }
}

async function loadBestand() {
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/bestand`)
    bestandCent.value = data.bestand_cent
  } catch { /* ignorieren */ }
}

async function loadBuchungen() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (filterVon.value) params.append('von', filterVon.value)
    if (filterBis.value) params.append('bis', filterBis.value)
    if (showStorniert.value) params.append('storniert', 'true')
    const { data } = await api.get(`/api/kassen/${kasseId.value}/buchungen?${params}`)
    buchungen.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden.' })
  } finally {
    loading.value = false
  }
}

async function loadExporte() {
  exporteLoading.value = true
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/exporte`)
    exporte.value = data
  } catch { /* ignorieren */ } finally {
    exporteLoading.value = false
  }
}

async function loadDatumBereich() {
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/datum-bereich`)
    datumMin.value = data.min_datum
    datumMax.value = data.max_datum
  } catch { /* ignorieren */ }
}

function openCreateDialog(typ) {
  editingBuchungId.value = null
  editingBuchungVersion.value = null
  buchungTyp.value = typ
  buchungBetragEuro.value = 0
  buchungForm.value = emptyBuchungForm()
  buchungDialogOpen.value = true
}

function openEditDialog(buchung) {
  editingBuchungId.value = buchung.id
  editingBuchungVersion.value = buchung.version
  buchungTyp.value = buchung.einnahme_cent > 0 ? 'einnahme' : 'ausgabe'
  buchungBetragEuro.value = buchung.einnahme_cent > 0
    ? buchung.einnahme_cent / 100
    : buchung.ausgabe_cent / 100
  buchungForm.value = {
    buchungsdatum: buchung.buchungsdatum,
    buchungstext: buchung.buchungstext,
    kategorie: buchung.kategorie || '',
    notiz: buchung.notiz || '',
  }
  buchungDialogOpen.value = true
}

async function onSaveBuchung() {
  if (!buchungForm.value.buchungstext.trim()) {
    $q.notify({ type: 'warning', message: 'Bitte den Buchungstext ausfüllen.' })
    return
  }
  buchungSaving.value = true
  const betragCent = Math.round(buchungBetragEuro.value * 100)
  const payload = {
    buchungsdatum: buchungForm.value.buchungsdatum,
    buchungstext: buchungForm.value.buchungstext.trim(),
    kategorie: buchungForm.value.kategorie.trim(),
    notiz: buchungForm.value.notiz || null,
    einnahme_cent: buchungTyp.value === 'einnahme' ? betragCent : 0,
    ausgabe_cent: buchungTyp.value === 'ausgabe' ? betragCent : 0,
  }
  try {
    if (editingBuchungId.value) {
      await api.put(
        `/api/kassen/${kasseId.value}/buchungen/${editingBuchungId.value}`,
        { ...payload, expected_version: editingBuchungVersion.value },
      )
    } else {
      await api.post(`/api/kassen/${kasseId.value}/buchungen`, payload)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert.' })
    buchungDialogOpen.value = false
    await Promise.all([loadBuchungen(), loadBestand()])
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    buchungSaving.value = false
  }
}

function confirmStornieren(buchung) {
  $q.dialog({
    title: 'Buchung stornieren',
    message: `Buchung Nr. ${buchung.belegnummer} „${buchung.buchungstext}" stornieren?`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/kassen/${kasseId.value}/buchungen/${buchung.id}`)
      $q.notify({ type: 'positive', message: 'Buchung storniert.' })
      await Promise.all([loadBuchungen(), loadBestand()])
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Stornieren.' })
    }
  })
}

function openExportDialog() {
  exportBisDatum.value = today
  exportDialog.value = true
  loadExporte()
}

async function doExport() {
  exportLoading.value = true
  try {
    const response = await api.post(
      `/api/kassen/${kasseId.value}/exporte`,
      { bis_datum: exportBisDatum.value },
      { responseType: 'blob' },
    )
    const disposition = response.headers['content-disposition'] || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    const filename = match ? match[1] : `kassenbuch-export-${exportBisDatum.value}.csv`
    const url = URL.createObjectURL(new Blob([response.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    $q.notify({ type: 'positive', message: `Export erstellt: ${filename}` })
    exportDialog.value = false
    await Promise.all([loadBuchungen(), loadExporte(), loadDatumBereich()])
  } catch (e) {
    if (e.response?.data instanceof Blob) {
      const text = await e.response.data.text()
      try { $q.notify({ type: 'negative', message: JSON.parse(text).detail || 'Fehler.' }) }
      catch { $q.notify({ type: 'negative', message: 'Fehler beim Export.' }) }
    } else {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Export.' })
    }
  } finally {
    exportLoading.value = false
  }
}

async function redownload(exportObj) {
  try {
    const response = await api.get(
      `/api/kassen/${kasseId.value}/exporte/${exportObj.id}/download`,
      { responseType: 'blob' },
    )
    const disposition = response.headers['content-disposition'] || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    const filename = match ? match[1] : exportObj.dateiname
    const url = URL.createObjectURL(new Blob([response.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Download.' })
  }
}

onMounted(loadAll)
</script>
