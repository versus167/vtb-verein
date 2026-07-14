<template>
  <q-page padding>
    <div class="text-h6 q-mb-lg dashboard-gruss">Willkommen, {{ auth.user?.username }}!</div>

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
        <SettingsTile to="tresor" icon="vpn_key" title="Passwörter" caption="Vereins-Tresor" />
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
import { useAuthStore } from 'src/stores/auth'
import { api } from 'src/boot/axios'
import SettingsTile from 'src/components/SettingsTile.vue'

const auth = useAuthStore()

const hatKassenZugriff = ref(false)
const hatTresorZugriff = ref(false)
const hatTermineZugriff = ref(false)

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
})
</script>
