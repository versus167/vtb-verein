<template>
  <q-page class="q-pa-md">
    <q-tabs
      v-model="tab"
      dense
      align="left"
      class="text-grey-8 q-mb-sm"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab v-if="kannErfassen" name="erfassung" icon="schedule" label="Erfassung" />
      <q-tab v-if="kannBestaetigen" name="bestaetigung" icon="how_to_reg" label="Bestätigung" />
      <q-tab v-if="kannVerwalten" name="saetze" icon="payments" label="Vergütungssätze" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <UlStundenPage v-if="tab === 'erfassung' && kannErfassen" />
    <UlBestaetigungPage v-else-if="tab === 'bestaetigung' && kannBestaetigen" />
    <UlSaetzePage v-else-if="tab === 'saetze' && kannVerwalten" />
  </q-page>
</template>

<script setup>
import { ref } from 'vue'
import { useAuthStore } from 'src/stores/auth'
import UlStundenPage from 'pages/UlStundenPage.vue'
import UlBestaetigungPage from 'pages/UlBestaetigungPage.vue'
import UlSaetzePage from 'pages/UlSaetzePage.vue'

defineOptions({ name: 'UebungsleiterPage' })

const auth = useAuthStore()

// Rechte sind während der Session stabil → einmalig auswerten.
const kannErfassen =
  auth.hasPermission('ulstunden.erfassen') || auth.hasPermission('ulstunden.erfassen_fremd')
const kannBestaetigen = auth.hasPermission('ulstunden.bestaetigen')
const kannVerwalten = auth.hasPermission('ulstunden.verwalten')

// Start auf dem ersten Tab, den der Nutzer sehen darf.
const tab = ref(kannErfassen ? 'erfassung' : kannBestaetigen ? 'bestaetigung' : 'saetze')
</script>
