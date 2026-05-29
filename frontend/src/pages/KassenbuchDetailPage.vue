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
          {{ formatEuro(bestandCent) }}
        </div>
        <div class="text-caption text-grey">Bestand</div>
      </div>
    </div>

    <!-- Aktions-Leiste -->
    <div class="row q-gutter-sm q-mb-sm items-center">
      <q-btn
        v-if="$q.screen.lt.sm"
        flat round dense icon="filter_list"
        :color="filterAktiv ? 'primary' : 'grey'"
        @click="filterOpen = !filterOpen"
      >
        <q-badge v-if="filterAktiv" color="primary" floating />
        <q-tooltip>Filter</q-tooltip>
      </q-btn>

      <q-space />

      <template v-if="kannSchreiben">
        <q-btn
          icon="add"
          :label="$q.screen.gt.xs ? 'Einnahme' : undefined"
          color="positive"
          unelevated
          :round="$q.screen.lt.sm"
          @click="openCreateDialog('einnahme')"
        />
        <q-btn
          icon="remove"
          :label="$q.screen.gt.xs ? 'Ausgabe' : undefined"
          color="negative"
          unelevated
          :round="$q.screen.lt.sm"
          @click="openCreateDialog('ausgabe')"
        />
      </template>
      <q-btn
        v-if="kannExportieren"
        icon="download"
        :label="$q.screen.gt.xs ? 'CSV-Export' : undefined"
        color="primary"
        outline
        :round="$q.screen.lt.sm"
        @click="openExportDialog"
      />
      <q-btn
        icon="picture_as_pdf"
        :label="$q.screen.gt.xs ? 'PDF-Bericht' : undefined"
        color="secondary"
        outline
        :round="$q.screen.lt.sm"
        @click="openPdfDialog"
      />
    </div>

    <!-- Filter (Desktop: immer sichtbar; Mobile: einklappbar) -->
    <q-slide-transition>
      <div v-show="$q.screen.gt.xs || filterOpen" class="row q-gutter-sm q-mb-md items-center">
        <q-input v-model="filterVon" type="date" label="Von" outlined dense style="width: 150px" />
        <q-input v-model="filterBis" type="date" label="Bis" outlined dense style="width: 150px" />
        <q-checkbox v-model="showStorniert" label="Stornierte" />
        <q-btn label="Anwenden" outline color="primary" dense @click="applyFilter" />
      </div>
    </q-slide-transition>

    <!-- ── Mobile: Karten-Liste ── -->
    <template v-if="$q.screen.lt.sm">
      <div v-if="loading" class="row justify-center q-py-xl">
        <q-spinner size="40px" color="primary" />
      </div>
      <div v-else-if="buchungenMitBestand.length === 0" class="text-center text-grey q-py-xl">
        Keine Buchungen im gewählten Zeitraum.
      </div>
      <q-card
        v-for="b in buchungenMitBestand"
        :key="b.id"
        flat bordered
        class="q-mb-sm"
        :class="b.deleted_at ? 'bg-grey-1' : ''"
      >
        <q-card-section class="q-py-sm q-px-md">
          <!-- Beleg + Datum -->
          <div class="row items-center q-mb-xs">
            <span class="text-caption text-grey col">
              {{ b.belegnummer }}
              <q-icon v-if="b.exportiert_in_export_id" name="lock" size="xs" color="grey" class="q-ml-xs">
                <q-tooltip>Exportiert – nicht mehr änderbar</q-tooltip>
              </q-icon>
            </span>
            <span class="text-caption text-grey">{{ b.buchungsdatum }}</span>
          </div>

          <!-- Buchungstext + Kategorie -->
          <div class="text-body2" :class="b.deleted_at ? 'text-grey text-strike' : ''">
            {{ b.buchungstext }}
          </div>
          <div v-if="b.kategorie" class="text-caption text-grey q-mb-xs">{{ b.kategorie }}</div>

          <!-- Betrag + laufender Bestand -->
          <div class="row items-end q-mt-xs">
            <div class="col" />
            <div class="text-right">
              <div
                v-if="b.einnahme_cent > 0"
                class="text-subtitle1 text-weight-bold"
                :class="b.deleted_at ? 'text-grey text-strike' : 'text-positive'"
              >+ {{ formatEuro(b.einnahme_cent) }}</div>
              <div
                v-if="b.ausgabe_cent > 0"
                class="text-subtitle1 text-weight-bold"
                :class="b.deleted_at ? 'text-grey text-strike' : 'text-negative'"
              >− {{ formatEuro(b.ausgabe_cent) }}</div>
              <div v-if="b.laufender_bestand_cent !== null" class="text-caption text-grey">
                Bestand {{ formatEuro(b.laufender_bestand_cent) }}
              </div>
            </div>
          </div>
        </q-card-section>

        <q-separator />

        <!-- Aktions-Zeile -->
        <q-card-actions class="q-px-sm q-py-xs">
          <q-btn
            flat round icon="attach_file" color="grey" size="md"
            @click="openAnhangDialog(b)"
          >
            <q-badge v-if="b.anhang_count > 0" color="primary" floating>{{ b.anhang_count }}</q-badge>
            <q-tooltip>Anhänge</q-tooltip>
          </q-btn>
          <q-space />
          <template v-if="kannSchreiben && !b.deleted_at && !b.exportiert_in_export_id">
            <q-btn flat round icon="edit" color="primary" size="md" @click="openEditDialog(b)" />
            <q-btn flat round icon="block" color="negative" size="md" @click="confirmStornieren(b)">
              <q-tooltip>Stornieren</q-tooltip>
            </q-btn>
          </template>
        </q-card-actions>
      </q-card>
    </template>

    <!-- ── Desktop: Tabelle ── -->
    <q-table
      v-else
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
          <q-btn
            flat dense round icon="attach_file" color="grey" size="sm"
            @click="openAnhangDialog(props.row)"
          >
            <q-badge v-if="props.row.anhang_count > 0" color="primary" floating>
              {{ props.row.anhang_count }}
            </q-badge>
            <q-tooltip>Anhänge</q-tooltip>
          </q-btn>
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
    <q-dialog
      v-model="buchungDialogOpen"
      persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 460px'">
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
            inputmode="decimal"
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
    <q-dialog
      v-model="exportDialog"
      persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 520px; max-width: 680px'">
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

    <!-- PDF-Bericht-Dialog -->
    <q-dialog
      v-model="pdfDialog"
      persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 420px'">
        <q-card-section class="text-h6">PDF-Kassenbericht</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="pdfVon" type="date" label="Von *" outlined :max="pdfBis || today" />
          <q-input v-model="pdfBis" type="date" label="Bis *" outlined :min="pdfVon" :max="today" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            label="PDF erstellen"
            icon="picture_as_pdf"
            color="secondary"
            unelevated
            :loading="pdfLoading"
            :disable="!pdfVon || !pdfBis"
            @click="doPdfDownload"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Anhang-Dialog -->
    <q-dialog
      v-model="anhangDialogOpen"
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 460px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Anhänge</div>
          <div v-if="anhangBuchung" class="text-caption text-grey q-ml-sm">
            {{ anhangBuchung.belegnummer }} · {{ anhangBuchung.buchungstext }}
          </div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <anhang-panel
            :anhaenge="anhaenge"
            :upload-url="`/api/kassen/${kasseId}/buchungen/${anhangBuchung?.id}/anhaenge`"
            :can-upload="kannSchreiben && !!anhangBuchung && !anhangBuchung.deleted_at && !anhangBuchung.exportiert_in_export_id"
            :can-delete="kannSchreiben"
            @uploaded="onAnhangUploaded"
            @deleted="onAnhangDeleted"
          />
        </q-card-section>
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
import AnhangPanel from 'src/components/AnhangPanel.vue'

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
const filterOpen = ref(false)

const filterAktiv = computed(() => !!filterBis.value || showStorniert.value)

const datumMin = ref(null)
const datumMax = ref('')

const kannSchreiben = computed(() => isAdmin.value || !!kasse.value?.darf_schreiben)
const kannExportieren = computed(() => isAdmin.value || !!kasse.value?.darf_exportieren)

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

const pdfDialog = ref(false)
const pdfLoading = ref(false)
const pdfVon = ref(vor90Tagen)
const pdfBis = ref(today)

const anhangDialogOpen = ref(false)
const anhangBuchung = ref(null)
const anhaenge = ref([])

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
  { name: 'actions', label: '', field: 'actions', align: 'right', style: 'width: 120px' },
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
  filterOpen.value = false
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
  const heute = new Date()
  exportBisDatum.value = isoDate(new Date(heute.getFullYear(), heute.getMonth(), 0))
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

async function openAnhangDialog(buchung) {
  anhangBuchung.value = buchung
  anhaenge.value = []
  anhangDialogOpen.value = true
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/buchungen/${buchung.id}/anhaenge`)
    anhaenge.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Anhänge konnten nicht geladen werden.' })
  }
}

function onAnhangUploaded(newAnhang) {
  anhaenge.value = [...anhaenge.value, newAnhang]
  const b = buchungen.value.find(b => b.id === anhangBuchung.value?.id)
  if (b) b.anhang_count = (b.anhang_count || 0) + 1
}

function onAnhangDeleted(anhangId) {
  anhaenge.value = anhaenge.value.filter(a => a.id !== anhangId)
  const b = buchungen.value.find(b => b.id === anhangBuchung.value?.id)
  if (b && b.anhang_count > 0) b.anhang_count--
}

function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function openPdfDialog() {
  const heute = new Date()
  const letzterVormonat = new Date(heute.getFullYear(), heute.getMonth(), 0)
  pdfBis.value = isoDate(letzterVormonat)

  if (exporte.value.length > 0) {
    const letzterExport = [...exporte.value].sort((a, b) =>
      b.zeitraum_bis.localeCompare(a.zeitraum_bis)
    )[0]
    const tagNach = new Date(letzterExport.zeitraum_bis)
    tagNach.setDate(tagNach.getDate() + 1)
    pdfVon.value = isoDate(tagNach)
  } else {
    pdfVon.value = isoDate(new Date(letzterVormonat.getFullYear(), letzterVormonat.getMonth(), 1))
  }

  pdfDialog.value = true
}

async function doPdfDownload() {
  pdfLoading.value = true
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/bericht.pdf`, {
      params: { von: pdfVon.value, bis: pdfBis.value },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(new Blob([data], { type: 'application/pdf' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `kassenbuch_${pdfVon.value}_${pdfBis.value}.pdf`
    a.click()
    URL.revokeObjectURL(url)
    pdfDialog.value = false
  } catch {
    $q.notify({ type: 'negative', message: 'PDF konnte nicht erstellt werden.' })
  } finally {
    pdfLoading.value = false
  }
}

onMounted(loadAll)
</script>
