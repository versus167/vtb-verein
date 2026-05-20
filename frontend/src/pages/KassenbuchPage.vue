<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Kassenbuch</div>

    <div v-if="loading" class="row justify-center q-py-xl">
      <q-spinner size="40px" color="primary" />
    </div>

    <div v-else-if="kassen.length === 0" class="text-center text-grey q-py-xl">
      <q-icon name="account_balance_wallet" size="48px" class="q-mb-sm" />
      <div>Keine Kassen verfügbar.</div>
      <div class="text-caption">Ein Administrator muss Ihnen Zugriff gewähren.</div>
    </div>

    <div v-else class="row q-gutter-md">
      <q-card
        v-for="k in kassen"
        :key="k.id"
        class="col-12 col-sm-5 col-md-3"
        bordered
        flat
      >
        <q-card-section>
          <div class="text-h6">{{ k.name }}</div>
          <div v-if="k.beschreibung" class="text-caption text-grey q-mt-xs">{{ k.beschreibung }}</div>
          <div class="text-subtitle1 q-mt-sm" :class="k.bestand_cent < 0 ? 'text-negative' : 'text-positive'">
            {{ formatEuro(k.bestand_cent) }}
          </div>
          <div class="text-caption text-grey">Aktueller Bestand</div>
        </q-card-section>

        <q-separator />

        <q-card-actions>
          <q-btn
            flat
            label="Buchungen"
            color="primary"
            :to="{ name: 'kassenbuch-detail', params: { kasseId: k.id } }"
          />
        </q-card-actions>
      </q-card>
    </div>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()

const kassen = ref([])
const loading = ref(false)

function formatEuro(cent) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(cent / 100)
}

async function loadKassen() {
  loading.value = true
  try {
    const { data } = await api.get('/api/kassen/')
    kassen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Kassen.' })
  } finally {
    loading.value = false
  }
}

onMounted(loadKassen)
</script>
