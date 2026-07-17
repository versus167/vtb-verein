<template>
  <q-page padding>
    <div class="text-h6 q-mb-lg dashboard-gruss">Willkommen, {{ auth.user?.display_name || auth.user?.username }}!</div>

    <!-- Nächste Termine (die nächsten Termine der eigenen Teams als Cards) -->
    <div v-if="naechsteTermine.length" class="q-mb-lg">
      <div class="row items-center q-mb-sm">
        <div class="text-subtitle1 text-weight-bold">Nächste Termine</div>
        <q-space />
        <q-btn flat dense no-caps color="primary" label="Alle anzeigen"
          @click="router.push({ name: 'termine' })" />
      </div>
      <div class="row q-col-gutter-md">
        <div v-for="t in naechsteTermine" :key="t.id" class="col-12 col-md-6">
          <TerminCard :termin="t" kompakt :darf-verwalten="darfTerminVerwalten(t)"
            @reload="ladeNaechsteTermine" @oeffnen="router.push({ name: 'termine' })"
            @bearbeiten="openEdit" @absagen="setStatus($event, 'absagen')"
            @reaktivieren="setStatus($event, 'reaktivieren')" @loeschen="confirmDelete" />
        </div>
      </div>
    </div>

    <!-- Termin bearbeiten (Verwalter, direkt vom Dashboard) -->
    <TerminFormDialog v-model="editOpen" :termin="editTermin" @saved="ladeNaechsteTermine" />

    <div class="row q-col-gutter-md">
      <div v-if="auth.hasPermission('personen.read')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="personen" icon="people" title="Personen" caption="Personen verwalten" />
      </div>

      <div v-if="auth.hasPermission('mannschaften.read')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="mannschaften" icon="sports_soccer" title="Mannschaften" caption="Teams & Kader verwalten" />
      </div>

      <div v-if="hatTermineZugriff || auth.hasPermission('termine.verwalten')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="termine" icon="event" title="Termine" caption="Training & Spiele" />
      </div>

      <div v-if="hatKassenZugriff || auth.hasPermission('kassen.verwalten')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile :to="kassenZiel" icon="account_balance_wallet" title="Kassenbuch" caption="Buchungen & Berichte" />
      </div>

      <div v-if="auth.hasPermission('schliessanlage.read')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="schliessanlage" icon="lock" title="Schließanlage" caption="Zutritt & Schlösser" />
      </div>

      <div v-if="hatTresorZugriff || auth.hasPermission('tresor.verwalten')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="tresor" icon="vpn_key" title="Passwörter/Kontakte" caption="Vereins-Tresor" />
      </div>

      <div class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="tickets" icon="confirmation_number" title="Tickets" caption="Anfragen & Aufgaben" />
      </div>

      <div v-if="hatUebungsleiterZugriff" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="uebungsleiter" icon="sports" title="Übungsleiter" caption="Stunden & Vergütung" />
      </div>

      <div v-if="auth.hasPermission('berichte.read')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="berichte" icon="insights" title="Berichte" caption="Statistik & Kennzahlen" />
      </div>

      <div v-if="auth.hasPermission('abteilungen.read')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="abteilungen" icon="account_tree" title="Abteilungen" caption="Abteilungen verwalten" />
      </div>

      <div v-if="zeigeEinstellungen" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="einstellungen" icon="tune" title="Einstellungen" caption="Funktionen, Abteilungen" />
      </div>

      <div v-if="zeigeSonstiges" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="sonstiges" icon="more_horiz" title="Sonstiges" caption="Import, Bereinigen, Fibu, Protokoll" />
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { api } from 'src/boot/axios'
import SettingsTile from 'src/components/SettingsTile.vue'
import TerminCard from 'components/TerminCard.vue'
import TerminFormDialog from 'components/TerminFormDialog.vue'
import { useTerminAktionen } from 'src/composables/useTermine'

const auth = useAuthStore()
const router = useRouter()

const hatKassenZugriff = ref(false)
const hatTresorZugriff = ref(false)
const hatTermineZugriff = ref(false)
const naechsteTermine = ref([])

const kassenZiel = computed(() =>
  auth.hasPermission('kassen.verwalten') ? 'kassenverwaltung' : 'kassenbuch',
)

const hatUebungsleiterZugriff = computed(() =>
  auth.hasPermission('ulstunden.erfassen') ||
  auth.hasPermission('ulstunden.erfassen_fremd') ||
  auth.hasPermission('ulstunden.bestaetigen') ||
  auth.hasPermission('ulstunden.verwalten'),
)

const zeigeEinstellungen = computed(() =>
  auth.user?.role === 'admin' ||
  auth.hasPermission('funktionen.verwalten') ||
  auth.hasPermission('abteilungen.read'),
)
const zeigeSonstiges = computed(() =>
  auth.user?.role === 'admin' ||
  auth.hasPermission('system.config') ||
  auth.hasPermission('fibu.export') ||
  auth.hasPermission('system.protokoll'),
)

onMounted(async () => {
  try {
    const { data } = await api.get('/api/kassen/')
    hatKassenZugriff.value = data.length > 0
  } catch { /* ignorieren */ }
  try {
    const { data } = await api.get('/api/tresor')
    hatTresorZugriff.value = data.length > 0
  } catch { /* ignorieren */ }
  try {
    const { data } = await api.get('/api/termine/mannschaften')
    hatTermineZugriff.value = data.length > 0
  } catch { /* ignorieren */ }
  await ladeNaechsteTermine()
})

async function ladeNaechsteTermine() {
  try {
    const von = new Date().toISOString().slice(0, 10)
    const { data } = await api.get('/api/termine/meine', { params: { von } })
    naechsteTermine.value = data.slice(0, 3)
  } catch { /* ignorieren */ }
}

// Verwalter editieren direkt vom Dashboard (zugriff kommt je Termin aus /meine)
function darfTerminVerwalten(t) {
  return auth.hasPermission('termine.verwalten') || t.zugriff === 'verwalten'
}

const editOpen = ref(false)
const editTermin = ref(null)
function openEdit(t) {
  editTermin.value = t
  editOpen.value = true
}
const { setStatus, confirmDelete } = useTerminAktionen(ladeNaechsteTermine)
</script>
