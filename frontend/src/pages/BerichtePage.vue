<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div>
        <div class="text-h4">Berichte &amp; Statistik</div>
        <div class="text-caption text-grey-7">
          {{ abteilungId ? 'Abteilung: ' + aktuelleAbteilungName : 'Gesamtverein' }}
        </div>
      </div>
      <q-space />
      <q-select
        v-model="abteilungId"
        :options="abteilungSelectOptions"
        option-value="id"
        option-label="name"
        emit-value
        map-options
        dense
        outlined
        options-dense
        label="Abteilung"
        style="min-width: 200px"
        @update:model-value="load"
      />
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
              <div class="text-caption text-grey-7">
                {{ kpi.label }}
                <q-icon v-if="kpi.hint" name="info" size="14px" class="q-ml-xs cursor-pointer text-grey-6">
                  <q-tooltip max-width="280px" anchor="top middle" self="bottom middle" class="text-body2">
                    {{ kpi.hint }}
                  </q-tooltip>
                </q-icon>
              </div>
            </q-card-section>
          </q-card>
        </div>
      </div>

      <div class="row q-col-gutter-md">
        <!-- Mitgliederentwicklung -->
        <div class="col-12 col-md-6">
          <q-card flat bordered class="fit">
            <q-card-section class="row items-center q-gutter-sm">
              <div>
                <div class="text-h6">Mitgliederentwicklung</div>
                <div class="text-caption text-grey-7">
                  Zu- und Abgänge je {{ entwicklungGran === 'monat' ? 'Monat' : 'Jahr' }}
                </div>
              </div>
              <q-space />
              <q-btn-toggle
                v-model="entwicklungGran"
                :dense="$q.screen.gt.sm"
                no-caps
                outline
                :size="$q.screen.lt.md ? 'md' : 'sm'"
                toggle-color="primary"
                :options="[
                  { label: '12 Monate', value: 'monat' },
                  { label: '12 Jahre', value: 'jahr' },
                ]"
              />
            </q-card-section>
            <q-separator />
            <q-card-section>
              <div class="row q-gutter-md q-mb-md text-caption">
                <div><q-badge rounded color="positive" /> Eintritte</div>
                <div><q-badge rounded color="negative" /> Austritte</div>
                <div v-if="hatZukunft" class="text-grey-6">
                  <q-badge rounded color="grey-5" /> Vorschau (geplant)
                </div>
              </div>
              <div class="entwicklung-chart">
                <div
                  v-for="e in entwicklungReihe"
                  :key="e.periode"
                  class="entwicklung-jahr"
                  :class="{ 'ist-zukunft': e.istZukunft }"
                  :title="e.istZukunft ? 'geplant / Vorschau' : undefined"
                >
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
                  <div class="text-caption q-mt-xs" :class="e.istZukunft ? 'text-grey-5' : 'text-grey-7'">{{ e.label }}</div>
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

        <!-- Abteilungsübersicht – nur im Gesamtverein-Modus (bei Filter redundant) -->
        <div class="col-12 col-md-6" v-if="!abteilungId">
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
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import StatBalken from 'src/components/StatBalken.vue'

const $q = useQuasar()
const loading = ref(false)
const data = ref(null)
const entwicklungGran = ref('monat')
const abteilungId = ref(null)
const abteilungOptionen = ref([])

const MONATE_KURZ = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']

const abteilungSelectOptions = computed(() => [
  { id: null, name: 'Gesamtverein' },
  ...abteilungOptionen.value,
])

const aktuelleAbteilungName = computed(
  () => abteilungOptionen.value.find((a) => a.id === abteilungId.value)?.name || '',
)

const kpiCards = computed(() => {
  const k = data.value?.kpis
  if (!k) return []
  return [
    {
      label: 'Mitglieder gesamt', value: k.gesamt, color: 'text-primary',
      hint: 'Aktueller Mitgliederstand heute: alle, die heute Mitglied sind (auch passiv/inaktiv). '
        + 'Bereits Ausgetretene zählen nicht mehr, künftige Eintritte noch nicht.',
    },
    {
      label: 'Aktiv', value: k.aktiv, color: 'text-positive',
      hint: 'Mitglieder mit Status „aktiv" und gültiger Mitgliedschaft; künftige Eintritte zählen mit, '
        + 'abgelaufene Austritte nicht. Kann von „gesamt" abweichen (z. B. gekündigt, aber noch nicht ausgetreten).',
    },
    { label: `Eintritte ${k.jahr}`, value: k.eintritte_jahr, color: 'text-positive' },
    { label: `Austritte ${k.jahr}`, value: k.austritte_jahr, color: 'text-negative' },
    { label: 'Ø Alter', value: k.durchschnittsalter ?? '–', color: 'text-grey-8' },
  ]
})

// Periode-Schlüssel des aktuellen Monats ('YYYY-MM'); Monate danach sind Vorschau.
// Nur die Monatsansicht blickt in die Zukunft (Backend: _MONATS_VORLAUF), die
// Jahresansicht endet im laufenden Jahr – daher dort nie 'istZukunft'.
function istZukunftsperiode(periode) {
  if (entwicklungGran.value !== 'monat') return false
  const now = new Date()
  const key = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  return periode > key
}

const entwicklungReihe = computed(() =>
  (data.value?.entwicklung?.[entwicklungGran.value] || []).map((e) => ({
    ...e,
    istZukunft: istZukunftsperiode(e.periode),
    label: entwicklungGran.value === 'monat'
      ? MONATE_KURZ[Number(e.periode.slice(5, 7)) - 1]
      : e.periode,
  })),
)

const hatZukunft = computed(() => entwicklungReihe.value.some((e) => e.istZukunft))

const entwicklungMax = computed(() =>
  Math.max(1, ...entwicklungReihe.value.flatMap((e) => [e.eintritte, e.austritte])),
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
    const params = abteilungId.value ? { abteilung_id: abteilungId.value } : {}
    const res = await api.get('/api/berichte/statistik', { params })
    data.value = res.data
    abteilungOptionen.value = res.data.abteilung_optionen || []
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der Statistik' })
  } finally {
    loading.value = false
  }
}

usePageRefresh(load)
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
/* Vorschau-Monate (Zukunft): gedimmt + gestrichelte Trennlinie zum "Heute"-Übergang.
   (opacity am Balken vererbt sich auf die Wert-Beschriftung.) */
.entwicklung-jahr.ist-zukunft .entwicklung-bar {
  opacity: 0.4;
}
.entwicklung-jahr.ist-zukunft {
  position: relative;
}
/* Trennlinie nur am ersten Zukunftsmonat (Übergang Gegenwart → Vorschau). */
.entwicklung-jahr:not(.ist-zukunft) + .entwicklung-jahr.ist-zukunft::before {
  content: '';
  position: absolute;
  left: -4px;
  top: 0;
  bottom: 18px;
  border-left: 1px dashed #9e9e9e;
}
</style>
