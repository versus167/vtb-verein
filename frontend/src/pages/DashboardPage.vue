<template>
  <q-page padding>
    <div class="text-h4 q-mb-md">Willkommen, {{ auth.user?.username }}!</div>
    <div class="text-subtitle1 q-mb-lg text-grey-7">Was möchten Sie tun?</div>

    <div class="row q-gutter-md">
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
    </div>
  </q-page>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'

const router = useRouter()
const auth = useAuthStore()
</script>

<style scoped>
.dashboard-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
  transition: all 0.2s ease;
}
</style>
