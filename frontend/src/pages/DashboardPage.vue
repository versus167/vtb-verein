<template>
  <q-page padding>
    <div class="text-h4 q-mb-md">Willkommen, {{ auth.user?.username }}!</div>
    <div class="text-subtitle1 q-mb-lg text-grey-7">Was möchten Sie tun?</div>

    <div class="row q-col-gutter-md">
      <div
        v-if="auth.hasPermission('personen.read')"
        class="col-6 col-sm-4 col-md-3"
      >
        <q-card class="cursor-pointer dashboard-card fit" @click="router.push({ name: 'personen' })">
          <q-card-section class="text-center">
            <q-icon name="people" size="3rem" color="primary" />
            <div class="text-h6 q-mt-sm">Personen</div>
            <div class="text-caption text-grey">Personen verwalten</div>
          </q-card-section>
        </q-card>
      </div>

      <div
        v-if="auth.hasPermission('mannschaften.read')"
        class="col-6 col-sm-4 col-md-3"
      >
        <q-card class="cursor-pointer dashboard-card fit" @click="router.push({ name: 'mannschaften' })">
          <q-card-section class="text-center">
            <q-icon name="sports_soccer" size="3rem" color="primary" />
            <div class="text-h6 q-mt-sm">Mannschaften</div>
            <div class="text-caption text-grey">Teams & Kader verwalten</div>
          </q-card-section>
        </q-card>
      </div>

      <div v-if="hatKassenZugriff || auth.hasPermission('kassen.verwalten')" class="col-6 col-sm-4 col-md-3">
        <q-card
          class="cursor-pointer dashboard-card fit"
          @click="router.push({ name: auth.hasPermission('kassen.verwalten') ? 'kassenverwaltung' : 'kassenbuch' })"
        >
          <q-card-section class="text-center">
            <q-icon name="account_balance_wallet" size="3rem" color="primary" />
            <div class="text-h6 q-mt-sm">Kassenbuch</div>
            <div class="text-caption text-grey">Buchungen & Berichte</div>
          </q-card-section>
        </q-card>
      </div>

      <div class="col-6 col-sm-4 col-md-3">
        <q-card class="cursor-pointer dashboard-card fit" @click="router.push({ name: 'tickets' })">
          <q-card-section class="text-center">
            <q-icon name="confirmation_number" size="3rem" color="primary" />
            <div class="text-h6 q-mt-sm">Tickets</div>
            <div class="text-caption text-grey">Anfragen & Aufgaben</div>
          </q-card-section>
        </q-card>
      </div>

      <div
        v-if="hatUebungsleiterZugriff"
        class="col-6 col-sm-4 col-md-3"
      >
        <q-card class="cursor-pointer dashboard-card fit" @click="router.push({ name: 'uebungsleiter' })">
          <q-card-section class="text-center">
            <q-icon name="sports" size="3rem" color="primary" />
            <div class="text-h6 q-mt-sm">Übungsleiter</div>
            <div class="text-caption text-grey">Stunden & Vergütung</div>
          </q-card-section>
        </q-card>
      </div>

      <div
        v-if="auth.hasPermission('berichte.read')"
        class="col-6 col-sm-4 col-md-3"
      >
        <q-card class="cursor-pointer dashboard-card fit" @click="router.push({ name: 'berichte' })">
          <q-card-section class="text-center">
            <q-icon name="insights" size="3rem" color="primary" />
            <div class="text-h6 q-mt-sm">Berichte</div>
            <div class="text-caption text-grey">Statistik & Kennzahlen</div>
          </q-card-section>
        </q-card>
      </div>

      <div
        v-if="auth.hasPermission('abteilungen.read')"
        class="col-6 col-sm-4 col-md-3"
      >
        <q-card class="cursor-pointer dashboard-card fit" @click="router.push({ name: 'abteilungen' })">
          <q-card-section class="text-center">
            <q-icon name="account_tree" size="3rem" color="primary" />
            <div class="text-h6 q-mt-sm">Abteilungen</div>
            <div class="text-caption text-grey">Abteilungen verwalten</div>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { api } from 'src/boot/axios'

const router = useRouter()
const auth = useAuthStore()

const hatKassenZugriff = ref(false)

const hatUebungsleiterZugriff = computed(() =>
  auth.hasPermission('ulstunden.erfassen') ||
  auth.hasPermission('ulstunden.erfassen_fremd') ||
  auth.hasPermission('ulstunden.bestaetigen') ||
  auth.hasPermission('ulstunden.verwalten'),
)

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
