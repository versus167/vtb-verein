<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h4">Berichte &amp; Statistik</div>
      <q-space />
      <q-btn flat round icon="refresh" :loading="loading" @click="load" />
    </div>

    <div v-if="loading && !data" class="row justify-center q-pa-xl">
      <q-spinner size="3rem" color="primary" />
    </div>

    <template v-else-if="data">
      <!-- Kennzahlen -->
      <div class="row q-col-gutter-md q-mb-lg">
        <div class="col-6 col-sm-4 col-md" v-for="kpi in kpiCards" :key="kpi.label">
          <q-card flat bordered class="fit">
            <q-card-section class="text-center">
              <div class="text-h4 text-weight-bold" :class="kpi.color">{{ kpi.value }}</div>
              <div class="text-caption text-grey-7">{{ kpi.label }}</div>
            </q-card-section>
          </q-card>
        </div>
      </div>

      <div class="row q-col-gutter-md">
        <!-- Mitgliederentwicklung -->
        <div class="col-12 col-md-6">
          <q-card flat bordered class="fit">
            <q-card-section>
              <div class="text-h6">Mitgliederentwicklung</div>
              <div class="text-caption text-grey-7">Zu- und Abgänge je Jahr</div>
            </q-card-section>
            <q-separator />
            <q-card-section>
              <div class="row q-gutter-md q-mb-md text-caption">
                <div><q-badge rounded color="positive" /> Eintritte</div>
                <div><q-badge rounded color="negative" /> Austritte</div>
              </div>
              <div class="entwicklung-chart">
                <div v-for="e in data.entwicklung" :key="e.jahr" class="entwicklung-jahr">
                  <div class="entwicklung-bars">
                    <div
                      class="entwicklung-bar bg-positive"
                      :style="{ height: barHeight(e.eintritte, entwicklungMax) }"
                      :title="`${e.eintritte} Eintritte`"
                    >
                      <span v-if="e.eintritte" class="entwicklung-wert">{{ e.eintritte }}</span>
                    </div>
                    <div
                      class="entwicklung-bar bg-negative"
                      :style="{ height: barHeight(e.austritte, entwicklungMax) }"
                      :title="`${e.austritte} Austritte`"
                    >
                      <span v-if="e.austritte" class="entwicklung-wert">{{ e.austritte }}</span>
                    </div>
                  </div>
                  <div class="text-caption text-grey-7 q-mt-xs">{{ e.jahr }}</div>
                </div>
              </div>
            </q-card-section>
          </q-card>
        </div>

        <!-- Altersstruktur -->
        <div class="col-12 col-md-6">
          <q-card flat bordered class="fit">
            <q-card-section>
              <div class="text-h6">Altersstruktur</div>
              <div class="text-caption text-grey-7">Aktive Mitglieder mit Geburtsdatum</div>
            </q-card-section>
            <q-separator />
            <q-card-section>
              <StatBalken :items="alterItems" color="primary" empty-text="Keine Geburtsdaten erfasst" />
            </q-card-section>
          </q-card>
        </div>

        <!-- Abteilungsübersicht -->
        <div class="col-12 col-md-6">
          <q-card flat bordered class="fit">
            <q-card-section>
              <div class="text-h6">Mitglieder je Abteilung</div>
              <div class="text-caption text-grey-7">Aktive Zuordnungen</div>
            </q-card-section>
            <q-separator />
            <q-card-section>
              <StatBalken :items="abteilungItems" color="teal" empty-text="Keine Abteilungen" />
            </q-card-section>
          </q-card>
        </div>

        <!-- Geschlechterverteilung -->
        <div class="col-12 col-md-6">
          <q-card flat bordered class="fit">
            <q-card-section>
              <div class="text-h6">Geschlechterverteilung</div>
              <div class="text-caption text-grey-7">Aktive Mitglieder</div>
            </q-card-section>
            <q-separator />
            <q-card-section>
              <StatBalken :items="geschlechtItems" color="indigo" empty-text="Keine Daten" />
            </q-card-section>
          </q-card>
        </div>
      </div>
    </template>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import StatBalken from 'src/components/StatBalken.vue'

const $q = useQuasar()
const loading = ref(false)
const data = ref(null)

const kpiCards = computed(() => {
  const k = data.value?.kpis
  if (!k) return []
  return [
    { label: 'Mitglieder gesamt', value: k.gesamt, color: 'text-primary' },
    { label: 'Aktiv', value: k.aktiv, color: 'text-positive' },
    { label: `Eintritte ${k.jahr}`, value: k.eintritte_jahr, color: 'text-positive' },
    { label: `Austritte ${k.jahr}`, value: k.austritte_jahr, color: 'text-negative' },
    { label: 'Ø Alter', value: k.durchschnittsalter ?? '–', color: 'text-grey-8' },
  ]
})

const entwicklungMax = computed(() =>
  Math.max(1, ...(data.value?.entwicklung || []).flatMap((e) => [e.eintritte, e.austritte])),
)

const alterItems = computed(() =>
  (data.value?.altersstruktur || []).map((a) => ({ label: a.gruppe, anzahl: a.anzahl })),
)

const abteilungItems = computed(() =>
  (data.value?.abteilungen || []).map((a) => ({ label: a.name, anzahl: a.anzahl })),
)

const geschlechtItems = computed(() =>
  (data.value?.geschlechter || []).map((g) => ({ label: g.label, anzahl: g.anzahl })),
)

function barHeight(value, max) {
  if (!value) return '2px'
  return `${Math.max(4, (value / max) * 100)}%`
}

async function load() {
  loading.value = true
  try {
    const res = await api.get('/api/berichte/statistik')
    data.value = res.data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der Statistik' })
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.entwicklung-chart {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 220px;
  gap: 8px;
}
.entwicklung-jahr {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  height: 100%;
}
.entwicklung-bars {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 4px;
  flex: 1;
  width: 100%;
}
.entwicklung-bar {
  width: 40%;
  max-width: 28px;
  border-radius: 4px 4px 0 0;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  transition: height 0.3s ease;
}
.entwicklung-wert {
  font-size: 0.7rem;
  color: white;
  padding-top: 2px;
}
</style>
