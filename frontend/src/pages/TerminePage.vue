<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Termine</div>
      <!-- Von wann ist der Spielplan? Steht klein neben der Überschrift, weil es
           die Termine als Ganzes einordnet – nicht einen einzelnen davon (#171). -->
      <div v-if="dfbnetStand" class="text-caption text-grey-7 q-ml-sm">
        DFBnet-Stand {{ dfbnetStand }}
        <q-tooltip>{{ dfbnetStandDetail }}</q-tooltip>
      </div>
      <q-space />
      <q-btn v-if="darfVerwalten && tab !== 'meine'" flat color="primary"
        icon="repeat" label="Serien" class="q-mr-sm" @click="serienOffen = true" />
      <!-- Vorlauf der Erinnerungen gilt vereinsweit, hängt also am globalen Recht
           und nicht an der Kader-Rolle des gerade offenen Tabs. -->
      <q-btn v-if="auth.hasPermission('termine.verwalten')" flat color="primary"
        icon="notifications_active" label="Erinnerungen" class="q-mr-sm"
        @click="erinnerungOffen = true" />
      <q-btn v-if="darfVerwalten && tab !== 'meine'" color="primary" unelevated
        icon="add" label="Neuer Termin" :round="$q.screen.lt.sm" @click="openCreate" />
    </div>

    <!-- Meine Termine + ein Tab je Mannschaft -->
    <q-tabs v-model="tab" dense align="left" active-color="primary"
      indicator-color="primary" class="text-grey-7" :breakpoint="0">
      <q-tab name="meine" label="Meine Termine" />
      <q-tab v-for="m in sichtbareTeams" :key="m.id" :name="m.id" :label="teamLabel(m)" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <div class="row items-center q-gutter-md q-mb-md">
      <q-toggle v-model="vergangene" label="Vergangene anzeigen" dense />
      <q-toggle v-if="hatFremdeTeams" v-model="nurMeine" label="Nur meine Teams" dense />
    </div>

    <q-inner-loading :showing="loading" />
    <div v-if="!loading && termine.length === 0" class="text-grey text-center q-py-xl">
      Keine Termine{{ vergangene ? '' : ' ab heute' }}.
    </div>

    <!-- Card-Liste (nach beginn sortiert; Datum steckt in der Card) -->
    <div class="column q-gutter-md">
      <TerminCard v-for="t in termine" :key="t.id" :termin="t"
        :id="`termin-${t.id}`"
        :class="{ 'termin--hervorgehoben': hervorgehoben === t.id }"
        :darf-verwalten="kannVerwalten(t)"
        @bearbeiten="openEdit" @absagen="setStatus($event, 'absagen')"
        @reaktivieren="setStatus($event, 'reaktivieren')" @loeschen="confirmDelete"
        @reload="loadTermine" />
    </div>

    <!-- Termin anlegen/bearbeiten -->
    <TerminFormDialog v-model="formOpen" :termin="formTermin" :mannschaft-id="tab"
      @saved="loadTermine" />

    <!-- Vorlauf der Termin-Erinnerungen (vereinsweit) -->
    <TerminErinnerungDialog v-model="erinnerungOffen" />

    <!-- Terminserien verwalten (nur im Team-Tab) -->
    <TerminSerienDialog v-if="tab !== 'meine'" v-model="serienOffen"
      :mannschaft-id="tab" @geaendert="loadTermine" />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import TerminCard from 'components/TerminCard.vue'
import TerminFormDialog from 'components/TerminFormDialog.vue'
import TerminSerienDialog from 'components/TerminSerienDialog.vue'
import TerminErinnerungDialog from 'components/TerminErinnerungDialog.vue'
import { useTerminAktionen } from 'src/composables/useTermine'

const $q = useQuasar()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const teams = ref([])
const termine = ref([])
const tab = ref('meine')
const vergangene = ref(false)
const loading = ref(false)
// Standardansicht wie bei den Tickets: erst die eigenen Mannschaften. Bewusst
// nicht gemerkt – wer fremde Termine prüfen will, schaltet für den Moment um.
const nurMeine = ref(true)

// Mannschaften, die nur über termine.verwalten/Admin dazukommen. Gibt es keine,
// bleibt der Haken aus – er hätte dann nichts zu filtern.
const hatFremdeTeams = computed(() => teams.value.some(m => !m.eigen))
const sichtbareTeams = computed(
  () => nurMeine.value ? teams.value.filter(m => m.eigen) : teams.value)

const darfVerwalten = computed(() => {
  if (auth.hasPermission('termine.verwalten')) return true
  const team = teams.value.find(m => m.id === tab.value)
  return team?.zugriff === 'verwalten'
})

function teamLabel(m) {
  return m.saison ? `${m.name} (${m.saison})` : m.name
}

function kannVerwalten(t) {
  if (auth.hasPermission('termine.verwalten')) return true
  if (tab.value === 'meine') return t.zugriff === 'verwalten'
  return darfVerwalten.value
}

function vonFilter() {
  const heute = new Date()
  if (!vergangene.value) return heute.toISOString().slice(0, 10)
  heute.setDate(heute.getDate() - 90)
  return heute.toISOString().slice(0, 10)
}

async function loadTermine() {
  loading.value = true
  try {
    if (tab.value === 'meine') {
      const { data } = await api.get('/api/termine/meine', { params: { von: vonFilter() } })
      termine.value = data
    } else {
      const { data } = await api.get(`/api/termine/mannschaften/${tab.value}`,
        { params: { von: vonFilter() } })
      termine.value = data.termine
    }
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Termine' })
    termine.value = []
  } finally {
    loading.value = false
  }
}

// ── Deep-Link aus einer Benachrichtigung: /termine?termin=NN (#158) ──
// Kein eigener Dialog: Die Zusage-Knöpfe sitzen in der Card selbst. Es genügt
// also, zur richtigen Card zu springen und sie kurz zu markieren – dann steht
// der Finger direkt über „Zusage"/„Absage".
const hervorgehoben = ref(null)

async function zeigeTerminAusQuery() {
  const id = Number(route.query.termin)
  if (!id) return
  // Query in jedem Fall entfernen: Sonst springt jeder Reload erneut – und die
  // Meldung unten käme bei jedem Auto-Refresh wieder.
  const rest = { ...route.query }
  delete rest.termin
  router.replace({ query: rest })

  if (!termine.value.some(t => t.id === id)) {
    // Kann passieren, wenn der Termin inzwischen vorbei ist (Filter „ab heute")
    // oder zu einem Team gehört, dessen Tab gerade nicht offen ist.
    $q.notify({ type: 'info', message: 'Der Termin steht nicht in dieser Liste – '
      + 'ggf. „Vergangene anzeigen" einschalten oder das Team-Tab wechseln.' })
    return
  }
  hervorgehoben.value = id
  await nextTick()
  document.getElementById(`termin-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  // Die Markierung ist ein Hinweis, kein Zustand – nach ein paar Sekunden weg.
  setTimeout(() => { if (hervorgehoben.value === id) hervorgehoben.value = null }, 4000)
}

watch(() => route.query.termin, (v) => { if (v) zeigeTerminAusQuery() })

// ── Stand des Spielplan-Imports (#171) ──
// Angezeigt wird das Dateidatum – der Stand, den der Anwender meint. Fehlt es
// (Import von vor dieser Anzeige oder Browser ohne lastModified), tritt der
// Zeitpunkt des Einlesens ein; ganz ohne Import bleibt die Zeile weg.
const importStand = ref(null)
const dfbnetStand = computed(() => {
  const s = importStand.value
  const wann = s?.datei_datum || s?.importiert_am
  return wann ? fmtDatum(wann) : ''
})
const dfbnetStandDetail = computed(() => {
  const s = importStand.value
  if (!s) return ''
  const teile = []
  if (s.datei_datum) teile.push(`Datei vom ${fmtDatumZeit(s.datei_datum)}`)
  if (s.dateiname) teile.push(s.dateiname)
  if (s.importiert_am) {
    teile.push(`eingelesen ${fmtDatumZeit(s.importiert_am)}`
      + (s.importiert_von ? ` von ${s.importiert_von}` : ''))
  }
  return teile.join(' · ')
})

function fmtDatum(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('de-DE')
}
function fmtDatumZeit(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('de-DE',
    { dateStyle: 'short', timeStyle: 'short' })
}

async function loadImportStand() {
  try {
    const { data } = await api.get('/api/import/dfbnet/stand')
    importStand.value = (data && (data.datei_datum || data.importiert_am)) ? data : null
  } catch { importStand.value = null }
}

async function load() {
  await loadImportStand()
  try {
    const { data } = await api.get('/api/termine/mannschaften')
    teams.value = data
    // Wer gar keinen eigenen Kader hat (reiner Verwalter), säße sonst vor einer
    // leeren Tab-Leiste – für den ist „alle" die einzig sinnvolle Ansicht.
    if (!data.some(m => m.eigen)) nurMeine.value = false
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
    teams.value = []
  }
  await loadTermine()
}
usePageRefresh(load)
// Der Deep-Link wird genau einmal ausgewertet – nach dem ersten Laden. Über
// usePageRefresh liefe er sonst bei jedem Auto-Refresh erneut.
onMounted(async () => {
  await load()
  await zeigeTerminAusQuery()
})
watch(tab, loadTermine)
// Wird der Haken gesetzt, während ein fremdes Team offen ist, verschwindet dessen
// Tab – ohne Rücksprung bliebe eine Liste stehen, zu der kein Tab mehr gehört.
watch(nurMeine, () => {
  if (tab.value !== 'meine' && !sichtbareTeams.value.some(m => m.id === tab.value)) {
    tab.value = 'meine'
  }
})
watch(vergangene, loadTermine)

// ── Termin anlegen/bearbeiten (Formular in TerminFormDialog) ──
const formOpen = ref(false)
const formTermin = ref(null)   // null = Anlegen

function openCreate() {
  formTermin.value = null
  formOpen.value = true
}
function openEdit(t) {
  formTermin.value = t
  formOpen.value = true
}

const { setStatus, confirmDelete } = useTerminAktionen(loadTermine)

// ── Terminserien ──────────────────────────────────────────
const serienOffen = ref(false)

// ── Erinnerungen (vereinsweiter Vorlauf) ──────────────────
const erinnerungOffen = ref(false)
</script>

<style lang="scss" scoped>
/* Ziel eines Deep-Links aus einer Benachrichtigung (#158): kurz sichtbar machen,
   welche Card gemeint ist. Der Akzentton trägt in allen drei Themes (er ist die
   Vereinsfarbe, nicht themenabhängig); die Animation läuft aus, damit die
   Markierung ein Hinweis bleibt und kein Dauerzustand wird. */
.termin--hervorgehoben {
  animation: termin-blick 4s ease-out;
}

@keyframes termin-blick {
  0%, 60% {
    box-shadow: 0 0 0 3px rgba($akzent-rgb, 1);
  }
  100% {
    box-shadow: 0 0 0 3px rgba($akzent-rgb, 0);
  }
}
</style>
