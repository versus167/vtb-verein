<template>
  <div>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-subtitle1">Zur Freigabe</div>
      <q-space />
      <q-select v-model="statusFilter" :options="FREIGABE_FILTER_OPTIONEN" emit-value
        map-options dense outlined label="Status" style="min-width:160px"
        @update:model-value="load" />
    </div>

    <div v-if="loading" class="text-center q-py-lg"><q-spinner size="2em" color="primary" /></div>

    <div v-else-if="rechnungen.length === 0" class="text-grey text-center q-py-lg">
      <q-icon name="how_to_reg" size="42px" class="q-mb-sm" />
      <div>Nichts zu tun – keine Rechnungen in diesem Status.</div>
    </div>

    <q-list v-else bordered separator>
      <q-item v-for="r in rechnungen" :key="r.id" clickable @click="oeffne(r)">
        <q-item-section>
          <q-item-label>
            {{ r.kategorie_name }}
            <span v-if="r.abteilung_name" class="text-grey-7">· {{ r.abteilung_name }}</span>
          </q-item-label>
          <q-item-label caption>
            <q-chip dense size="sm" :color="statusChip(r.status).color" text-color="white">
              {{ statusChip(r.status).label }}
            </q-chip>
            <span v-if="r.betrag_cent != null" class="q-mr-xs">{{ fmtBetrag(r.betrag_cent) }}</span>
            <span>· von {{ r.ersteller_name }}</span>
            <span v-if="r.beschreibung">· {{ r.beschreibung }}</span>
          </q-item-label>
          <q-item-label caption>
            <q-icon name="payments" size="xs" /> {{ empfaengerText(r) }}
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-badge v-if="r.anhang_count" color="primary">{{ r.anhang_count }}</q-badge>
        </q-item-section>
      </q-item>
    </q-list>

    <q-dialog v-model="dialogOpen" persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm
        ? 'width:100%;border-radius:16px 16px 0 0'
        : 'min-width:520px;max-width:680px'">
        <q-card-section class="row items-center">
          <div class="text-h6">Rechnung #{{ aktuell?.id }} prüfen</div>
          <q-space />
          <q-chip v-if="aktuell" dense :color="statusChip(aktuell.status).color"
            text-color="white">{{ statusChip(aktuell.status).label }}</q-chip>
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>

        <q-card-section v-if="aktuell" class="q-pt-none">
          <div class="text-body2 q-mb-sm">
            <q-icon name="sell" size="xs" /> {{ aktuell.kategorie_name }}
            <span v-if="aktuell.abteilung_name">· {{ aktuell.abteilung_name }}</span>
            <span v-else>· Vereinsrechnung</span>
            · eingereicht von {{ aktuell.ersteller_name }}
          </div>
          <div class="text-body2 q-mb-sm">
            <span v-if="aktuell.betrag_cent != null" class="text-subtitle2">
              {{ fmtBetrag(aktuell.betrag_cent) }}
            </span>
            <!-- Seit der Betrag Pflicht ist, kann das nur noch bei Altbeständen
                 auftreten oder wenn die Geschäftsstelle ihn wieder geleert hat. -->
            <span v-else class="text-grey-7">Ohne Betragsangabe</span>
            <span v-if="aktuell.rechnungsdatum"> · vom {{ fmtDatum(aktuell.rechnungsdatum) }}</span>
            <span v-if="aktuell.rechnungsnummer"> · Nr. {{ aktuell.rechnungsnummer }}</span>
          </div>
          <div v-if="aktuell.beschreibung" class="text-body2 q-mb-sm">
            {{ aktuell.beschreibung }}
          </div>

          <!-- Wer bekommt das Geld – die eigentliche Entscheidungsgrundlage. -->
          <q-banner dense class="bg-grey-2 q-mb-sm">
            <template #avatar><q-icon name="payments" color="primary" /></template>
            <div class="text-body2">{{ empfaengerText(aktuell) }}</div>
            <div v-if="empfaengerIban(aktuell)" class="text-caption text-grey-7">
              {{ empfaengerIban(aktuell) }}
            </div>
            <div v-else class="text-caption text-grey-7">
              Bankverbindung entnimmt die Buchhaltung dem Beleg.
            </div>
          </q-banner>

          <div class="text-caption text-grey-7 q-mb-xs">Beleg</div>
          <AnhangPanel :anhaenge="anhaenge"
            :upload-url="`/api/rechnungen/${aktuell.id}/anhaenge`"
            :can-upload="false" :can-delete="false" />

          <div v-if="aktuell.status === 'abgelehnt' && aktuell.abgelehnt_grund"
            class="text-negative text-caption q-mt-sm">
            <q-icon name="error" size="xs" /> Abgelehnt: {{ aktuell.abgelehnt_grund }}
          </div>
          <div v-if="error" class="text-negative text-caption q-mt-sm">{{ error }}</div>
        </q-card-section>

        <q-card-actions v-if="aktuell" align="right">
          <template v-if="aktuell.status === 'eingereicht'">
            <q-btn flat color="negative" label="Ablehnen" :loading="busy" @click="ablehnen" />
            <q-btn unelevated color="positive" label="Freigeben" :loading="busy"
              @click="freigeben" />
          </template>
          <q-btn v-else-if="!aktuell.ist_exportiert
            && ['freigegeben', 'abgelehnt'].includes(aktuell.status)"
            flat color="primary" label="Zurücksetzen" :loading="busy" @click="zuruecksetzen" />
          <div v-else-if="aktuell.ist_exportiert" class="text-caption text-grey q-pa-sm">
            Bereits exportiert – zum Ändern zuerst den Export zurücknehmen.
          </div>
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useRoute } from 'vue-router'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'
import AnhangPanel from 'components/AnhangPanel.vue'
import {
  FREIGABE_FILTER_OPTIONEN, statusChip, fmtBetrag, fmtDatum, fehlertext,
  empfaengerText, empfaengerIban,
} from 'src/composables/useRechnungen'

defineOptions({ name: 'RechnungenFreigabePage' })

const $q = useQuasar()
const route = useRoute()

const rechnungen = ref([])
const statusFilter = ref('eingereicht')
const loading = ref(true)

const dialogOpen = ref(false)
const aktuell = ref(null)
const anhaenge = ref([])
const busy = ref(false)
const error = ref('')

async function load() {
  const params = statusFilter.value ? { status: statusFilter.value } : {}
  const { data } = await api.get('/api/rechnungen', { params: { sicht: 'freigabe', ...params } })
  rechnungen.value = data
}

async function oeffne(r) {
  error.value = ''
  aktuell.value = r
  dialogOpen.value = true
  const { data } = await api.get(`/api/rechnungen/${r.id}/anhaenge`)
  anhaenge.value = data
}

async function aktion(pfad, nutzlast, meldung, typ = 'positive') {
  busy.value = true
  error.value = ''
  try {
    await api.post(`/api/rechnungen/${aktuell.value.id}/${pfad}`, nutzlast)
    $q.notify({ type: typ, message: meldung })
    dialogOpen.value = false
    await load()
  } catch (e) {
    error.value = fehlertext(e, 'Aktion fehlgeschlagen')
  } finally {
    busy.value = false
  }
}

function freigeben() {
  return aktion('freigeben', undefined, 'Rechnung freigegeben')
}

function zuruecksetzen() {
  return aktion('zuruecksetzen', undefined, 'Zurückgesetzt', 'info')
}

function ablehnen() {
  $q.dialog({
    title: 'Rechnung ablehnen',
    message: 'Grund der Ablehnung (optional):',
    prompt: { model: '', type: 'text', isValid: () => true },
    cancel: true,
    ok: { label: 'Ablehnen', color: 'negative' },
  }).onOk((grund) => aktion('ablehnen', { grund: grund || null },
    'Rechnung abgelehnt', 'info'))
}

usePageRefresh(load)
onMounted(async () => {
  try {
    await load()
    const id = Number(route.query.rechnung)
    const treffer = id && rechnungen.value.find((r) => r.id === id)
    if (treffer) await oeffne(treffer)
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
})
</script>
