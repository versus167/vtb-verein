<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-h5">Stunden bestätigen</div>
      <q-space />
      <q-select v-model="statusFilter" :options="statusFilterOptionen" emit-value map-options
        dense outlined label="Status" style="min-width:160px" @update:model-value="load" />
    </div>

    <q-list bordered separator>
      <q-item v-for="a in abrechnungen" :key="a.id" clickable @click="openDetail(a)">
        <q-item-section>
          <q-item-label>
            {{ a.mitglied_nachname }}, {{ a.mitglied_vorname }}
            <span class="text-grey-7">· {{ a.abteilung_name }}</span>
          </q-item-label>
          <q-item-label caption>
            {{ a.zeitraum_von }} – {{ a.zeitraum_bis }}
            <q-chip dense size="sm" :color="statusChip(a.status).color" text-color="white">
              {{ statusChip(a.status).label }}
            </q-chip>
            <span class="q-mx-xs">{{ a.summen.summe_stunden }} Std.</span>
            <span v-if="a.summen.gesamtbetrag != null">· {{ fmtEuro(a.summen.gesamtbetrag) }}</span>
          </q-item-label>
        </q-item-section>
        <q-item-section side><q-icon name="chevron_right" color="grey-6" /></q-item-section>
      </q-item>
    </q-list>
    <div v-if="abrechnungen.length === 0" class="text-grey text-center q-py-lg">
      Keine Abrechnungen in diesem Status.
    </div>

    <!-- Detail -->
    <q-dialog v-model="detailOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:560px;max-width:680px'">
        <q-card-section class="row items-center">
          <div class="text-h6">Abrechnung prüfen</div>
          <q-space />
          <q-chip v-if="detail" dense :color="statusChip(detail.status).color" text-color="white">
            {{ statusChip(detail.status).label }}
          </q-chip>
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>

        <q-card-section v-if="detail" class="q-pt-none">
          <div class="text-body2 q-mb-sm">
            <q-icon name="person" size="xs" /> {{ detail.mitglied_nachname }}, {{ detail.mitglied_vorname }}
            · {{ detail.abteilung_name }}
            · {{ detail.zeitraum_von }} – {{ detail.zeitraum_bis }}
            · {{ detail.lizenz_klassifikation === 'mit_lizenz' ? 'mit Lizenz' : 'ohne Lizenz' }}
          </div>

          <!-- Erfasste Termine: Kalender (Standard) oder Liste -->
          <div class="row items-center q-mb-xs">
            <div class="text-caption text-grey-7">Erfasste Stunden</div>
            <q-space />
            <q-btn-toggle v-model="ansicht" dense no-caps unelevated size="sm"
              toggle-color="primary" color="grey-3" text-color="grey-8"
              :options="[{ label: 'Kalender', value: 'kalender', icon: 'calendar_month' },
                         { label: 'Liste', value: 'liste', icon: 'list' }]" />
          </div>

          <!-- Kalender: Tage mit Einträgen zeigen die Stunden als umkreiste Zahl (nur lesen) -->
          <StundenKalender v-if="ansicht === 'kalender'" class="q-mb-sm"
            :termine="detail.stunden" :von="detail.zeitraum_von" :bis="detail.zeitraum_bis" />
          <div v-if="ansicht === 'kalender' && detail.stunden.length === 0"
            class="text-grey text-center q-pb-sm">Keine Termine.</div>

          <q-markup-table v-if="ansicht === 'liste'" flat bordered dense class="q-mb-sm">
            <thead>
              <tr><th class="text-left">Datum</th><th class="text-left">Wo.</th>
                <th class="text-right">Stunden</th><th class="text-left">Angebot</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in detail.stunden" :key="s.id">
                <td>{{ s.datum }}</td><td>{{ wochentagKurz(s.wochentag) }}</td>
                <td class="text-right">{{ s.stunden }}</td><td>{{ s.angebot || '' }}</td>
              </tr>
              <tr v-if="detail.stunden.length === 0">
                <td colspan="4" class="text-grey text-center">Keine Termine.</td>
              </tr>
            </tbody>
          </q-markup-table>

          <div class="text-subtitle2">
            Summe: {{ detail.summen.summe_stunden }} Std.
            <span v-if="detail.summen.gesamtbetrag != null">
              · {{ fmtEuro(detail.summen.gesamtbetrag) }}
              <span class="text-grey-7">({{ fmtEuro(detail.summen.verguetung_pro_stunde) }}/h)</span>
            </span>
            <span v-else class="text-orange">· kein Vergütungssatz hinterlegt</span>
          </div>
          <div v-if="detail.status === 'abgelehnt' && detail.abgelehnt_grund"
            class="text-negative text-caption q-mt-xs">
            <q-icon name="error" size="xs" /> Abgelehnt: {{ detail.abgelehnt_grund }}
          </div>
          <div v-if="dError" class="text-negative text-caption q-mt-xs">{{ dError }}</div>
        </q-card-section>

        <q-card-actions v-if="detail" align="right">
          <q-btn v-if="detail.stunden.length > 0" flat color="primary"
            icon="picture_as_pdf" label="Beleg" @click="downloadBeleg" />
          <q-space />
          <template v-if="detail.status === 'eingereicht'">
            <q-btn flat color="negative" label="Ablehnen" :loading="dBusy" @click="ablehnen" />
            <q-btn unelevated color="green" label="Bestätigen" :loading="dBusy" @click="bestaetigen" />
          </template>
          <q-btn v-else-if="detail.status === 'bestaetigt'" flat color="primary"
            label="Zurücksetzen" :loading="dBusy" @click="zuruecksetzen" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import StundenKalender from 'src/components/StundenKalender.vue'

defineOptions({ name: 'UlBestaetigungPage' })

const $q = useQuasar()

const abrechnungen = ref([])
const statusFilter = ref('eingereicht')
const statusFilterOptionen = [
  { label: 'Zu bestätigen', value: 'eingereicht' },
  { label: 'Bestätigt', value: 'bestaetigt' },
  { label: 'Abgelehnt', value: 'abgelehnt' },
  { label: 'Alle', value: '' },
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

async function load() {
  const params = statusFilter.value ? { status_filter: statusFilter.value } : {}
  const { data } = await api.get('/api/ul-stunden/zu-bestaetigen', { params })
  abrechnungen.value = data
}
usePageRefresh(load)
onMounted(async () => {
  try { await load() }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})

const detailOpen = ref(false)
const detail = ref(null)
const dError = ref('')
const dBusy = ref(false)
const ansicht = ref('kalender')   // 'kalender' (Standard) | 'liste'

async function openDetail(a) {
  dError.value = ''
  detailOpen.value = true
  const { data } = await api.get(`/api/ul-stunden/${a.id}`)
  detail.value = data
}

async function bestaetigen() {
  dBusy.value = true; dError.value = ''
  try {
    await api.post(`/api/ul-stunden/${detail.value.id}/bestaetigen`)
    $q.notify({ type: 'positive', message: 'Abrechnung bestätigt' })
    detailOpen.value = false
    await load()
  } catch (e) {
    dError.value = e.response?.data?.detail || 'Bestätigen fehlgeschlagen'
  } finally {
    dBusy.value = false
  }
}

function ablehnen() {
  $q.dialog({
    title: 'Abrechnung ablehnen',
    message: 'Grund der Ablehnung (optional):',
    prompt: { model: '', type: 'text', isValid: () => true },
    cancel: true,
    ok: { label: 'Ablehnen', color: 'negative' },
  }).onOk(async (grund) => {
    dBusy.value = true; dError.value = ''
    try {
      await api.post(`/api/ul-stunden/${detail.value.id}/ablehnen`, { grund: grund || null })
      $q.notify({ type: 'info', message: 'Abrechnung abgelehnt' })
      detailOpen.value = false
      await load()
    } catch (e) {
      dError.value = e.response?.data?.detail || 'Ablehnen fehlgeschlagen'
    } finally {
      dBusy.value = false
    }
  })
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
async function zuruecksetzen() {
  dBusy.value = true; dError.value = ''
  try {
    await api.post(`/api/ul-stunden/${detail.value.id}/zuruecksetzen`)
    $q.notify({ type: 'info', message: 'Zurückgesetzt – ÜL kann erneut bearbeiten' })
    detailOpen.value = false
    await load()
  } catch (e) {
    dError.value = e.response?.data?.detail || 'Fehler'
  } finally {
    dBusy.value = false
  }
}
</script>
