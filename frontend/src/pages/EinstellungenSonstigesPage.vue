<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Sonstiges</div>

    <div class="row q-col-gutter-md">
      <div v-if="auth.user?.role === 'admin'" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="import" icon="upload_file" title="Datenimport" caption="Daten importieren" />
      </div>

      <div v-if="auth.hasPermission('system.config')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="prune" icon="cleaning_services" title="Datenbereinigung" caption="Papierkorb bereinigen" />
      </div>

      <div v-if="auth.user?.role === 'admin'" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="konsistenz" icon="fact_check" title="Konsistenzprüfung" caption="Beziehungen prüfen" />
      </div>

      <div v-if="auth.hasPermission('fibu.export')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="fibu-export" icon="account_balance" title="Fibu-Export" caption="Buchungen exportieren" />
      </div>

      <div v-if="auth.hasPermission('system.protokoll')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="protokoll" icon="fact_check" title="Protokoll" caption="Zugriffsprotokoll" />
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { useAuthStore } from 'src/stores/auth'
import SettingsTile from 'src/components/SettingsTile.vue'

defineOptions({ name: 'EinstellungenSonstigesPage' })

const auth = useAuthStore()
</script>
