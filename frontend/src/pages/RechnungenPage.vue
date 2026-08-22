<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Rechnungen</div>

    <q-tabs v-model="tab" dense align="left" class="text-grey-8 q-mb-sm"
      active-color="primary" indicator-color="primary">
      <q-tab v-if="kannEinreichen" name="meine" icon="receipt_long" label="Meine Rechnungen" />
      <q-tab v-if="kannFreigeben" name="freigabe" icon="how_to_reg" label="Freigabe" />
      <q-tab v-if="kannVerwalten" name="export" icon="download" label="Export" />
      <q-tab v-if="kannVerwalten" name="kategorien" icon="sell" label="Kategorien" />
      <q-tab v-if="kannVerwalten" name="einstellungen" icon="settings" label="Einstellungen" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <RechnungenMeinePage v-if="tab === 'meine' && kannEinreichen" />
    <RechnungenFreigabePage v-else-if="tab === 'freigabe' && kannFreigeben" />
    <RechnungenExportPage v-else-if="tab === 'export' && kannVerwalten" />
    <RechnungenKategorienPage v-else-if="tab === 'kategorien' && kannVerwalten" />
    <RechnungenEinstellungenPage v-else-if="tab === 'einstellungen' && kannVerwalten" />
  </q-page>
</template>

<script setup>
import { ref } from 'vue'
import { useAuthStore } from 'stores/auth'
import RechnungenMeinePage from 'pages/RechnungenMeinePage.vue'
import RechnungenFreigabePage from 'pages/RechnungenFreigabePage.vue'
import RechnungenExportPage from 'pages/RechnungenExportPage.vue'
import RechnungenKategorienPage from 'pages/RechnungenKategorienPage.vue'
import RechnungenEinstellungenPage from 'pages/RechnungenEinstellungenPage.vue'

defineOptions({ name: 'RechnungenPage' })

const auth = useAuthStore()

// Rechte sind während der Session stabil → einmalig auswerten (wie UebungsleiterPage).
const kannEinreichen = auth.hasPermission('rechnungen.einreichen')
const kannFreigeben = auth.hasPermission('rechnungen.freigeben')
const kannVerwalten = auth.hasPermission('rechnungen.verwalten')

const tab = ref(
  kannEinreichen ? 'meine' : kannFreigeben ? 'freigabe' : 'export',
)
</script>
