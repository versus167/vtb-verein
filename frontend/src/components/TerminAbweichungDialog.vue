<template>
  <q-dialog v-model="open" :maximized="$q.screen.lt.md" @show="load">
    <q-card :class="$q.screen.lt.md ? 'column no-wrap' : ''"
      :style="$q.screen.lt.md ? '' : 'min-width: 420px; max-width: 92vw'">
      <q-card-section class="row items-center q-pb-none"
        :class="$q.screen.lt.md ? 'col-auto' : ''">
        <div class="text-h6">Abweichungen laut DFBnet</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <q-card-section class="q-pb-none" :class="$q.screen.lt.md ? 'col-auto' : ''">
        <div class="text-caption text-grey-7">
          Hier haben sich seit dem letzten Import <b>beide Seiten</b> geändert – der
          Import fasst den Termin deshalb nicht an. Beide Wege sind endgültig: Auch
          „Behalten" merkt sich den DFBnet-Stand, es wird also nicht erneut gefragt.
        </div>
      </q-card-section>

      <!-- Aktueller Ist-Vergleich, unabhängig von offenen Fragen: Nach einem
           „Behalten" oder einer Änderung des Teams steht der Termin dauerhaft
           anders da als die offizielle Ansetzung. Das gehört sichtbar hierher –
           gerade weil der Import bewusst nichts mehr dazu fragt. -->
      <q-card-section v-if="externDiff.length" class="q-pb-none"
        :class="$q.screen.lt.md ? 'col-auto' : ''">
        <q-banner dense class="bg-blue-1 text-blue-10 rounded-borders">
          <template #avatar><q-icon name="sync_alt" /></template>
          <div class="text-weight-medium">Aktuell abweichend vom DFBnet-Stand</div>
          <div v-for="d in externDiff" :key="d.feld" class="text-caption">
            {{ feldLabel(d.feld) }} laut DFBnet: {{ wertText(d.feld, d.dfbnet) }}
          </div>
          <div class="text-caption q-mt-xs">
            Das DFBnet ist die offizielle Ansetzung – steht dort noch der alte Stand,
            gehört die Verlegung dort gemeldet.
          </div>
          <template v-if="darfVerwalten" #action>
            <!-- Ausgeschriebene Beschriftung: Im Dialog stehen mehrere
                 „Übernehmen"-Knöpfe, dieser hier zieht den kompletten
                 DFBnet-Stand nach und nicht eine einzelne Frage. -->
            <q-btn flat dense no-caps color="primary" icon="download_done"
              label="DFBnet-Daten übernehmen"
              :loading="uebernimmt" @click="dfbnetUebernehmen" />
          </template>
        </q-banner>
      </q-card-section>

      <q-card-section style="min-height: 120px" class="relative-position"
        :class="$q.screen.lt.md ? 'col scroll' : 'abweichung-dialog__liste'">
        <q-inner-loading :showing="loading" />
        <div v-if="!loading && abweichungen.length === 0" class="text-grey text-center q-py-md">
          Keine offenen oder früheren Fragen zu diesem Termin.
        </div>

        <q-list separator>
          <q-item v-for="a in abweichungen" :key="a.id" class="q-px-none">
            <q-item-section>
              <q-item-label class="text-weight-medium">
                {{ feldLabel(a.feld) }}
                <q-badge v-if="a.status !== 'offen'" :color="statusFarbe(a.status)"
                  class="q-ml-xs">{{ statusLabel(a.status) }}</q-badge>
              </q-item-label>

              <!-- Absagen kennt das DFBnet praktisch nicht; verschwindet ein Spiel
                   aus dem Auszug, wurde es meist über dessen Zeitraum hinaus
                   verlegt. Der Text nennt deshalb die wahrscheinliche Ursache
                   statt einer Absage. -->
              <q-item-label v-if="a.feld === 'entfallen'" caption>
                Steht in diesem Auszug nicht mehr – meist eine Verlegung über den
                Auszugs-Zeitraum hinaus. Im DFBnet nachsehen, ob es einen neuen
                Termin gibt.
              </q-item-label>
              <q-item-label v-else caption>
                <span class="text-strike">{{ wertText(a.feld, a.wert_app) }}</span>
                <q-icon name="arrow_right_alt" size="18px" class="q-mx-xs" />
                <span class="text-weight-medium">{{ wertText(a.feld, a.wert_extern) }}</span>
                <span v-if="a.spielstaette_name"> ({{ a.spielstaette_name }})</span>
              </q-item-label>

              <q-item-label caption class="text-grey">
                erkannt {{ zeitpunkt(a.erkannt_am) }}
                <template v-if="a.entschieden_von">
                  · entschieden von {{ a.entschieden_von }}
                </template>
              </q-item-label>
            </q-item-section>

            <q-item-section v-if="a.status === 'offen' && darfVerwalten" side>
              <div class="row no-wrap q-gutter-xs">
                <q-btn unelevated dense no-caps color="primary" :disable="busy"
                  :label="a.feld === 'entfallen' ? 'Absagen' : 'Übernehmen'"
                  @click="entscheiden(a, 'uebernommen')" />
                <q-btn flat dense no-caps color="grey-8" :disable="busy"
                  :label="a.feld === 'entfallen' ? 'Findet statt' : 'Behalten'"
                  @click="entscheiden(a, 'verworfen')" />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <!-- Gilt für beide Wege: Entscheiden und das Ziehen auf den DFBnet-Stand -->
      <q-card-section v-if="darfVerwalten && (hatOffene || externDiff.length)" class="q-pt-none"
        :class="$q.screen.lt.md ? 'col-auto' : ''">
        <q-toggle v-model="benachrichtigen" dense
          label="Kader über die Änderung informieren" />
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { abweichungFeldLabel as feldLabel,
         abweichungWert as wertText } from 'src/composables/useTermine'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  terminId: { type: Number, required: true },
  darfVerwalten: { type: Boolean, default: false },
  // [{feld, dfbnet}] – Ist-Vergleich mit dem letzten Importstand, kommt fertig
  // aus der Terminliste (`extern_diff`), damit der Dialog nichts nachladen muss.
  externDiff: { type: Array, default: () => [] },
  terminVersion: { type: Number, default: null },   // für das Übernehmen (Optimistic Locking)
})
const emit = defineEmits(['update:modelValue', 'geaendert'])

const $q = useQuasar()
const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const abweichungen = ref([])
const loading = ref(false)
const busy = ref(false)
const uebernimmt = ref(false)
const benachrichtigen = ref(true)

const hatOffene = computed(() => abweichungen.value.some(a => a.status === 'offen'))

const STATUS = {
  uebernommen: { label: 'übernommen', farbe: 'positive' },
  verworfen: { label: 'behalten', farbe: 'grey-7' },
  hinfaellig: { label: 'erledigt', farbe: 'grey-6' },
}

function statusLabel(status) {
  return STATUS[status]?.label ?? status
}
function statusFarbe(status) {
  return STATUS[status]?.farbe ?? 'grey'
}

// erkannt_am/entschieden_am sind echte Zeitstempel (TIMESTAMPTZ), keine Wandzeit.
function zeitpunkt(wert) {
  if (!wert) return ''
  const d = new Date(wert)
  return Number.isNaN(d.getTime())
    ? wert
    : d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get(`/api/termine/${props.terminId}/abweichungen`)
    abweichungen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Abweichungen konnten nicht geladen werden' })
    abweichungen.value = []
  } finally {
    loading.value = false
  }
}

// Termin auf den DFBnet-Stand ziehen, ohne dass eine offene Frage dazu existiert
// (verworfen oder vom Team geändert). Der Kader wird nur mit gesetztem Haken
// informiert – dieselbe Opt-in-Regel wie beim Entscheiden.
async function dfbnetUebernehmen() {
  uebernimmt.value = true
  try {
    const { data } = await api.post(`/api/termine/${props.terminId}/dfbnet-uebernehmen`, {
      expected_version: props.terminVersion,
      benachrichtigen: benachrichtigen.value,
    })
    if (data.ausgelassen?.length) {
      $q.notify({ type: 'warning', timeout: 8000,
        message: 'Der Ort wurde nicht übernommen – im letzten Importstand fehlt '
          + 'die Spielstätte. Bitte den Platz im Termin von Hand setzen.' })
    } else {
      $q.notify({ type: 'positive', message: 'Termin steht jetzt auf dem DFBnet-Stand' })
    }
    emit('geaendert')
    open.value = false
  } catch (e) {
    $q.notify({ type: 'negative',
      message: e.response?.data?.detail || 'Übernehmen fehlgeschlagen' })
  } finally {
    uebernimmt.value = false
  }
}

async function entscheiden(a, entscheidung) {
  busy.value = true
  try {
    await api.post(`/api/termine/abweichungen/${a.id}/entscheiden`, {
      entscheidung,
      expected_version: a.version,
      benachrichtigen: benachrichtigen.value,
    })
    await load()
    emit('geaendert')
    $q.notify({
      type: 'positive',
      message: entscheidung === 'uebernommen' ? 'Termin angepasst' : 'Termin bleibt wie er ist',
    })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Speichern fehlgeschlagen' })
  } finally {
    busy.value = false
  }
}
</script>

<style lang="scss" scoped>
// Desktop: nur die Liste scrollt, Kopf und Hinweis bleiben stehen
.abweichung-dialog__liste {
  max-height: 60vh;
  overflow-y: auto;
}
</style>
