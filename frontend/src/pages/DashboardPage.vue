<template>
  <q-page padding>
    <div class="text-h4 q-mb-md">Willkommen, {{ auth.user?.username }}!</div>
    <div class="text-subtitle1 q-mb-lg text-grey-7">Was möchten Sie tun?</div>

    <div class="row q-gutter-md">
      <q-card
        v-if="auth.hasPermission('abteilungen.read')"
        class="col-auto cursor-pointer dashboard-card"
        @click="router.push({ name: 'abteilungen' })"
      >
        <q-card-section class="text-center" style="min-width: 160px">
          <q-icon name="account_tree" size="3rem" color="primary" />
          <div class="text-h6 q-mt-sm">Abteilungen</div>
          <div class="text-caption text-grey">Abteilungen verwalten</div>
        </q-card-section>
      </q-card>

      <q-card
        v-if="auth.hasPermission('mitglieder.read')"
        class="col-auto cursor-pointer dashboard-card"
        @click="router.push({ name: 'mitglieder' })"
      >
        <q-card-section class="text-center" style="min-width: 160px">
          <q-icon name="group" size="3rem" color="primary" />
          <div class="text-h6 q-mt-sm">Mitglieder</div>
          <div class="text-caption text-grey">Mitglieder verwalten</div>
        </q-card-section>
      </q-card>

      <q-card
        v-if="hatKassenZugriff"
        class="col-auto cursor-pointer dashboard-card"
        @click="router.push({ name: 'kassenbuch' })"
      >
        <q-card-section class="text-center" style="min-width: 160px">
          <q-icon name="account_balance_wallet" size="3rem" color="primary" />
          <div class="text-h6 q-mt-sm">Kassenbuch</div>
          <div class="text-caption text-grey">Buchungen & Berichte</div>
        </q-card-section>
      </q-card>

      <q-card
        class="col-auto cursor-pointer dashboard-card"
        @click="router.push({ name: 'tickets' })"
      >
        <q-card-section class="text-center" style="min-width: 160px">
          <q-icon name="confirmation_number" size="3rem" color="primary" />
          <div class="text-h6 q-mt-sm">Tickets</div>
          <div class="text-caption text-grey">Anfragen & Aufgaben</div>
        </q-card-section>
      </q-card>
    </div>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { api } from 'src/boot/axios'

const router = useRouter()
const auth = useAuthStore()

const hatKassenZugriff = ref(false)

onMounted(async () => {
  try {
    const { data } = await api.get('/api/kassen/')
    hatKassenZugriff.value = data.length > 0
  } catch { /* ignorieren */ }
})
</script>

<style scoped>
.dashboard-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
  transition: all 0.2s ease;
}
</style>
