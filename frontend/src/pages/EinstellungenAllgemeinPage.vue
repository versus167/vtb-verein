<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Einstellungen</div>

    <div class="row q-col-gutter-md">
      <div v-if="auth.hasPermission('funktionen.verwalten')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="funktionen" icon="badge" title="Funktionen" caption="Funktionen & Rechte" />
      </div>

      <div v-if="auth.hasPermission('abteilungen.read')" class="col-6 col-sm-4 col-md-3">
        <SettingsTile to="abteilungen" icon="account_tree" title="Abteilungen" caption="Abteilungen verwalten" />
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { useAuthStore } from 'src/stores/auth'
import SettingsTile from 'src/components/SettingsTile.vue'

defineOptions({ name: 'EinstellungenAllgemeinPage' })

const auth = useAuthStore()
</script>
