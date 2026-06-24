<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Stundenerfassung</div>
      <q-space />
      <q-btn color="primary" unelevated icon="add" label="Neue Abrechnung" @click="openCreate" />
    </div>

    <q-list bordered separator>
      <q-item v-for="a in abrechnungen" :key="a.id" clickable @click="openDetail(a)">
        <q-item-section>
          <q-item-label>
            {{ a.abteilung_name }}
            <span class="text-grey-7">· {{ a.zeitraum_von }} – {{ a.zeitraum_bis }}</span>
          </q-item-label>
          <q-item-label caption>
            <q-chip dense size="sm" :color="statusChip(a.status).color" text-color="white">
              {{ statusChip(a.status).label }}
            </q-chip>
            <span class="q-mx-xs">{{ a.summen.summe_stunden }} Std.</span>
            <span v-if="a.summen.gesamtbetrag != null">· {{ fmtEuro(a.summen.gesamtbetrag) }}</span>
            <q-chip dense size="sm" outline :color="a.lizenz_klassifikation === 'mit_lizenz' ? 'green-8' : 'blue-grey'">
              {{ a.lizenz_klassifikation === 'mit_lizenz' ? 'mit Lizenz' : 'ohne Lizenz' }}
            </q-chip>
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-icon name="chevron_right" color="grey-6" />
        </q-item-section>
      </q-item>
    </q-list>
    <div v-if="abrechnungen.length === 0" class="text-grey text-center q-py-lg">
      Noch keine Abrechnungen. Lege deine erste an.
    </div>

    <!-- ════════════ Neue Abrechnung ════════════ -->
    <q-dialog v-model="createOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">Neue Abrechnung</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-select v-model="cForm.abteilung_id" :options="abteilungen" option-value="id" option-label="name"
            emit-value map-options label="Abteilung *" outlined dense />
          <div class="row q-gutter-sm">
            <q-input v-model="cForm.zeitraum_von" label="Von *" outlined dense type="date" class="col" />
            <q-input v-model="cForm.zeitraum_bis" label="Bis *" outlined dense type="date" class="col" />
          </div>
          <q-select v-model="cForm.lizenz_klassifikation" :options="lizenzOptionen" emit-value map-options
            label="Lizenz" outlined dense />
          <q-select v-model="cForm.foerder_klassifikation" :options="foerderOptionen" emit-value map-options
            clearable label="Sportförderung (optional)" outlined dense />
          <div v-if="cError" class="text-negative text-caption">{{ cError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Anlegen" :loading="cSaving" @click="saveCreate" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ════════════ Detail / Bearbeiten ════════════ -->
    <q-dialog v-model="detailOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:560px;max-width:680px'">
        <q-card-section class="row items-center">
          <div class="text-h6">Abrechnung</div>
          <q-space />
          <q-chip v-if="detail" dense :color="statusChip(detail.status).color" text-color="white">
            {{ statusChip(detail.status).label }}
          </q-chip>
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>

        <q-card-section v-if="detail" class="q-pt-none">
          <div class="text-body2 q-mb-sm">
            <q-icon name="account_tree" size="xs" /> {{ detail.abteilung_name }}
            · {{ detail.zeitraum_von }} – {{ detail.zeitraum_bis }}
            · {{ detail.lizenz_klassifikation === 'mit_lizenz' ? 'mit Lizenz' : 'ohne Lizenz' }}
          </div>
          <div v-if="detail.status === 'abgelehnt' && detail.abgelehnt_grund"
            class="text-negative text-caption q-mb-sm">
            <q-icon name="error" size="xs" /> Abgelehnt: {{ detail.abgelehnt_grund }}
          </div>

          <!-- Termine -->
          <q-markup-table flat bordered dense class="q-mb-sm">
            <thead>
              <tr><th class="text-left">Datum</th><th class="text-left">Wo.</th>
                <th class="text-right">Stunden</th><th class="text-left">Angebot</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="s in detail.stunden" :key="s.id">
                <td>{{ s.datum }}</td>
                <td>{{ wochentagKurz(s.wochentag) }}</td>
                <td class="text-right">{{ s.stunden }}</td>
                <td>{{ s.angebot || '' }}</td>
                <td class="text-right">
                  <q-btn v-if="isEntwurf" flat dense round size="sm" icon="delete" color="negative"
                    @click="deleteTermin(s)" />
                </td>
              </tr>
              <tr v-if="detail.stunden.length === 0">
                <td colspan="5" class="text-grey text-center">Noch keine Termine erfasst.</td>
              </tr>
            </tbody>
          </q-markup-table>

          <!-- Termin hinzufügen (nur im Entwurf) -->
          <div v-if="isEntwurf" class="row q-gutter-sm items-end q-mb-sm">
            <q-input v-model="tForm.datum" label="Datum" outlined dense type="date" class="col"
              :min="detail.zeitraum_von" :max="detail.zeitraum_bis" />
            <q-input v-model.number="tForm.stunden" label="Std." outlined dense type="number" step="0.25"
              style="width:90px" />
            <q-input v-model="tForm.angebot" label="Angebot" outlined dense class="col" />
            <q-btn color="primary" unelevated icon="add" :loading="tSaving" @click="addTermin" />
          </div>

          <div class="row items-center q-mt-sm">
            <div class="text-subtitle2">
              Summe: {{ detail.summen.summe_stunden }} Std.
              <span v-if="detail.summen.gesamtbetrag != null">
                · {{ fmtEuro(detail.summen.gesamtbetrag) }}
                <span class="text-grey-7">({{ fmtEuro(detail.summen.verguetung_pro_stunde) }}/h)</span>
              </span>
              <span v-else-if="detail.status !== 'entwurf'" class="text-orange">
                · kein Vergütungssatz hinterlegt
              </span>
            </div>
          </div>
          <div v-if="dError" class="text-negative text-caption q-mt-xs">{{ dError }}</div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn v-if="isEntwurf" flat color="negative" label="Löschen" @click="deleteAbrechnung" />
          <q-btn v-if="detail && detail.stunden.length > 0" flat color="primary"
            icon="picture_as_pdf" label="Beleg" @click="downloadBeleg" />
          <q-space />
          <q-btn v-if="detail && detail.status === 'abgelehnt'" flat color="primary"
            label="Erneut bearbeiten" :loading="dBusy" @click="zuruecksetzen" />
          <q-btn v-if="isEntwurf" unelevated color="primary" label="Einreichen"
            :loading="dBusy" @click="einreichen" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

defineOptions({ name: 'UlStundenPage' })

const $q = useQuasar()

const abrechnungen = ref([])
const abteilungen = ref([])

const lizenzOptionen = [
  { label: 'mit Lizenz', value: 'mit_lizenz' },
  { label: 'ohne Lizenz', value: 'ohne_lizenz' },
]
const foerderOptionen = [
  { label: 'LSBS', value: 'LSBS' },
  { label: 'Spofö 3.3', value: 'Spofoe_3_3' },
]

function statusChip(status) {
  return {
    entwurf: { label: 'Entwurf', color: 'blue-grey' },
    eingereicht: { label: 'Eingereicht', color: 'orange' },
    bestaetigt: { label: 'Bestätigt', color: 'green' },
    abgelehnt: { label: 'Abgelehnt', color: 'red' },
  }[status] || { label: status, color: 'grey' }
}

function fmtEuro(v) {
  if (v == null) return ''
  return Number(v).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' })
}
function wochentagKurz(w) {
  return ['', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][w] || ''
}

async function loadAbrechnungen() {
  const { data } = await api.get('/api/ul-stunden/meine')
  abrechnungen.value = data
}
async function loadAbteilungen() {
  const { data } = await api.get('/api/abteilungen/')
  abteilungen.value = data
}
usePageRefresh(loadAbrechnungen)
onMounted(async () => {
  try { await Promise.all([loadAbrechnungen(), loadAbteilungen()]) }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})

// ── Neue Abrechnung ────────────────────────────────────────
const createOpen = ref(false)
const cSaving = ref(false)
const cError = ref('')
const cForm = ref({})
function openCreate() {
  cError.value = ''
  const heute = new Date().toISOString().slice(0, 10)
  cForm.value = {
    abteilung_id: null, zeitraum_von: heute, zeitraum_bis: heute,
    lizenz_klassifikation: 'ohne_lizenz', foerder_klassifikation: null,
  }
  createOpen.value = true
}
async function saveCreate() {
  if (!cForm.value.abteilung_id || !cForm.value.zeitraum_von || !cForm.value.zeitraum_bis) {
    cError.value = 'Abteilung und Zeitraum sind erforderlich.'; return
  }
  cSaving.value = true; cError.value = ''
  try {
    const { data } = await api.post('/api/ul-stunden', cForm.value)
    createOpen.value = false
    await loadAbrechnungen()
    openDetail(data)
  } catch (e) {
    cError.value = e.response?.data?.detail || 'Fehler beim Anlegen'
  } finally {
    cSaving.value = false
  }
}

// ── Detail / Termine ───────────────────────────────────────
const detailOpen = ref(false)
const detail = ref(null)
const dError = ref('')
const dBusy = ref(false)
const tForm = ref({ datum: '', stunden: null, angebot: '' })
const tSaving = ref(false)

const isEntwurf = computed(() => detail.value?.status === 'entwurf')

async function openDetail(a) {
  dError.value = ''
  detailOpen.value = true
  await reloadDetail(a.id)
  tForm.value = {
    datum: detail.value?.erfassbar_ab && detail.value.erfassbar_ab > detail.value.zeitraum_von
      ? detail.value.erfassbar_ab : detail.value?.zeitraum_von || '',
    stunden: null, angebot: '',
  }
}
async function reloadDetail(id) {
  const { data } = await api.get(`/api/ul-stunden/${id}`)
  detail.value = data
}
function setDetail(data) {
  detail.value = data
  const idx = abrechnungen.value.findIndex(a => a.id === data.id)
  if (idx >= 0) abrechnungen.value[idx] = data
}

async function addTermin() {
  if (!tForm.value.datum || !tForm.value.stunden) {
    dError.value = 'Datum und Stunden sind erforderlich.'; return
  }
  tSaving.value = true; dError.value = ''
  try {
    const { data } = await api.post(`/api/ul-stunden/${detail.value.id}/stunden`, {
      datum: tForm.value.datum, stunden: Number(tForm.value.stunden),
      angebot: tForm.value.angebot || null,
    })
    setDetail(data)
    tForm.value.stunden = null; tForm.value.angebot = ''
  } catch (e) {
    dError.value = e.response?.data?.detail || 'Fehler'
  } finally {
    tSaving.value = false
  }
}
async function deleteTermin(s) {
  try {
    const { data } = await api.delete(`/api/ul-stunden/${detail.value.id}/stunden/${s.id}`)
    setDetail(data)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

async function einreichen() {
  dBusy.value = true; dError.value = ''
  try {
    const { data } = await api.post(`/api/ul-stunden/${detail.value.id}/einreichen`)
    setDetail(data)
    $q.notify({ type: 'positive', message: 'Eingereicht – zur Bestätigung durch den Abteilungsleiter' })
    detailOpen.value = false
    await loadAbrechnungen()
  } catch (e) {
    dError.value = e.response?.data?.detail || 'Einreichen fehlgeschlagen'
  } finally {
    dBusy.value = false
  }
}
async function zuruecksetzen() {
  dBusy.value = true
  try {
    const { data } = await api.post(`/api/ul-stunden/${detail.value.id}/zuruecksetzen`)
    setDetail(data)
    await loadAbrechnungen()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    dBusy.value = false
  }
}
async function downloadBeleg() {
  try {
    const res = await api.get(`/api/ul-stunden/${detail.value.id}/beleg.pdf`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `Stundennachweis_${detail.value.mitglied_nachname || 'UL'}_${detail.value.zeitraum_von}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Beleg konnte nicht erstellt werden' })
  }
}
function deleteAbrechnung() {
  $q.dialog({ title: 'Abrechnung löschen', message: 'Diese Abrechnung wirklich löschen?', cancel: true })
    .onOk(async () => {
      try {
        await api.delete(`/api/ul-stunden/${detail.value.id}`)
        detailOpen.value = false
        await loadAbrechnungen()
      } catch (e) {
        $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
      }
    })
}
</script>
