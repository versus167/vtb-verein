<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Termine</div>
      <q-space />
      <q-btn v-if="darfVerwalten && tab !== 'meine'" color="primary" unelevated
        icon="add" label="Neuer Termin" :round="$q.screen.lt.sm" @click="openCreate" />
    </div>

    <!-- Meine Termine + ein Tab je Mannschaft -->
    <q-tabs v-model="tab" dense align="left" active-color="primary"
      indicator-color="primary" class="text-grey-7" :breakpoint="0">
      <q-tab name="meine" label="Meine Termine" />
      <q-tab v-for="m in teams" :key="m.id" :name="m.id" :label="teamLabel(m)" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <div class="row items-center q-mb-md">
      <q-toggle v-model="vergangene" label="Vergangene anzeigen" dense />
    </div>

    <q-inner-loading :showing="loading" />
    <div v-if="!loading && termine.length === 0" class="text-grey text-center q-py-xl">
      Keine Termine{{ vergangene ? '' : ' ab heute' }}.
    </div>

    <!-- Card-Liste (nach beginn sortiert; Datum steckt in der Card) -->
    <div class="column q-gutter-md">
      <TerminCard v-for="t in termine" :key="t.id" :termin="t"
        :darf-verwalten="kannVerwalten(t)"
        @bearbeiten="openEdit" @absagen="setStatus($event, 'absagen')"
        @reaktivieren="setStatus($event, 'reaktivieren')" @loeschen="confirmDelete"
        @reload="loadTermine" />
    </div>

    <!-- Termin anlegen/bearbeiten -->
    <TerminFormDialog v-model="formOpen" :termin="formTermin" :mannschaft-id="tab"
      @saved="loadTermine" />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import TerminCard from 'components/TerminCard.vue'
import TerminFormDialog from 'components/TerminFormDialog.vue'
import { useTerminAktionen } from 'src/composables/useTermine'

const $q = useQuasar()
const auth = useAuthStore()

const teams = ref([])
const termine = ref([])
const tab = ref('meine')
const vergangene = ref(false)
const loading = ref(false)

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

async function load() {
  try {
    const { data } = await api.get('/api/termine/mannschaften')
    teams.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
    teams.value = []
  }
  await loadTermine()
}
usePageRefresh(load)
onMounted(load)
watch(tab, loadTermine)
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
</script>
