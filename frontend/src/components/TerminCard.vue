<template>
  <q-card flat bordered class="termin-card" :class="{ 'termin-card--abgesagt': abgesagt }">
    <!-- Kopf: farbiger Balken mit Datumsblock, Titel, Status/Menü -->
    <div class="termin-card__kopf row items-center no-wrap"
      :class="abgesagt ? 'bg-negative' : 'bg-primary'"
      :style="klickbar ? 'cursor:pointer' : ''" @click="onKopfClick">
      <div class="termin-card__datum column items-center justify-center text-white">
        <div class="text-caption text-weight-medium" style="line-height:1">{{ wochentag(datumIso) }}</div>
        <div class="text-weight-bold" style="line-height:1.2">{{ tagMonat(datumIso) }}</div>
      </div>
      <div class="col termin-card__titel text-white">
        <div class="text-subtitle1 text-weight-bold ellipsis">{{ terminTitel(termin) }}</div>
        <div v-if="termin.mannschaft_name" class="text-caption ellipsis" style="opacity:.85">
          {{ termin.mannschaft_name }}
        </div>
      </div>
      <q-badge v-if="abgesagt" color="white" text-color="negative"
        class="q-mr-sm text-weight-bold">ABGESAGT</q-badge>
      <q-btn v-if="darfVerwalten && !kompakt" flat round dense icon="more_vert" color="white"
        @click.stop>
        <q-menu auto-close>
          <q-list dense style="min-width: 170px">
            <q-item clickable @click="emit('bearbeiten', termin)">
              <q-item-section avatar><q-icon name="edit" size="xs" /></q-item-section>
              <q-item-section>Bearbeiten</q-item-section>
            </q-item>
            <q-item v-if="!abgesagt" clickable @click="emit('absagen', termin)">
              <q-item-section avatar><q-icon name="event_busy" size="xs" /></q-item-section>
              <q-item-section>Absagen</q-item-section>
            </q-item>
            <q-item v-else clickable @click="emit('reaktivieren', termin)">
              <q-item-section avatar><q-icon name="event_available" size="xs" /></q-item-section>
              <q-item-section>Reaktivieren</q-item-section>
            </q-item>
            <q-item clickable @click="emit('loeschen', termin)">
              <q-item-section avatar><q-icon name="delete" size="xs" color="negative" /></q-item-section>
              <q-item-section class="text-negative">Löschen</q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
      <q-icon v-else-if="kompakt" name="chevron_right" color="white" class="q-mr-sm" />
    </div>

    <!-- Zeiten -->
    <div class="row items-center termin-card__zeiten text-center">
      <div class="col">
        <span class="text-grey-7 text-caption">Treffen </span>
        <span class="text-weight-medium">{{ treffen }}</span>
      </div>
      <q-separator vertical />
      <div class="col">
        <span class="text-grey-7 text-caption">Beginn </span>
        <span class="text-weight-medium">{{ beginn }}</span>
      </div>
      <q-separator vertical />
      <div class="col">
        <span class="text-grey-7 text-caption">Ende </span>
        <span class="text-weight-medium">{{ ende }}</span>
      </div>
    </div>

    <div v-if="!kompakt && metaText" class="termin-card__meta text-caption text-grey-7 ellipsis">
      <q-icon name="place" size="14px" /> {{ metaText }}
    </div>

    <q-separator />

    <!-- Zu-/Absagen -->
    <div class="row items-center termin-card__rsvp no-wrap">
      <q-btn v-for="a in ANTWORTEN" :key="a.key" class="col"
        :flat="termin.meine_antwort !== a.key" :unelevated="termin.meine_antwort === a.key"
        :color="termin.meine_antwort === a.key ? a.color : 'grey-7'"
        :text-color="termin.meine_antwort === a.key ? 'white' : undefined"
        dense no-caps square :disable="!termin.kann_zusagen || busy" @click="toggle(a.key)">
        <q-icon :name="a.icon" size="20px" />
        <span class="q-ml-xs text-weight-medium">{{ zaehler(a.key) }}</span>
        <q-tooltip>{{ a.label }}</q-tooltip>
      </q-btn>
      <q-separator vertical />
      <q-btn class="col-auto q-px-md" flat dense icon="groups" color="grey-8"
        @click="kaderOffen = true">
        <q-tooltip>Kader &amp; Antworten</q-tooltip>
      </q-btn>
    </div>

    <TerminKaderDialog v-model="kaderOffen" :termin-id="termin.id"
      :darf-verwalten="darfVerwalten" @geaendert="emit('reload')" />
  </q-card>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import TerminKaderDialog from 'components/TerminKaderDialog.vue'
import { ANTWORTEN, terminTitel, uhrzeit, wochentag, tagMonat } from 'src/composables/useTermine'

const props = defineProps({
  termin: { type: Object, required: true },
  darfVerwalten: { type: Boolean, default: false },
  kompakt: { type: Boolean, default: false },   // Dashboard-Variante: kein Menü, Kopf klickbar
})
const emit = defineEmits(['bearbeiten', 'absagen', 'reaktivieren', 'loeschen', 'reload', 'oeffnen'])

const $q = useQuasar()
const busy = ref(false)
const kaderOffen = ref(false)

const abgesagt = computed(() => props.termin.status === 'abgesagt')
const datumIso = computed(() => (props.termin.beginn ?? '').slice(0, 10))
const treffen = computed(() => props.termin.treffpunkt_zeit || '--:--')
const beginn = computed(() => uhrzeit(props.termin.beginn) || '--:--')
const ende = computed(() => uhrzeit(props.termin.ende) || '--:--')
const klickbar = computed(() => props.kompakt)
const metaText = computed(() => {
  const t = props.termin
  return [t.ort, t.treffpunkt ? `Treffpunkt: ${t.treffpunkt}` : null].filter(Boolean).join(' · ')
})

function zaehler(key) {
  return props.termin.zusagen?.[key] ?? 0
}
function onKopfClick() {
  if (props.kompakt) emit('oeffnen', props.termin)
}

async function toggle(key) {
  busy.value = true
  try {
    if (props.termin.meine_antwort === key) {
      await api.delete(`/api/termine/${props.termin.id}/zusage`)
    } else {
      await api.put(`/api/termine/${props.termin.id}/zusage`, { antwort: key })
    }
    emit('reload')
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Speichern fehlgeschlagen' })
  } finally {
    busy.value = false
  }
}
</script>

<style lang="scss" scoped>
.termin-card {
  border-radius: 12px;
  overflow: hidden;
}
.termin-card--abgesagt .termin-card__titel .text-subtitle1 {
  text-decoration: line-through;
}
.termin-card__kopf {
  min-height: 56px;
  gap: 12px;
  padding-right: 6px;
}
.termin-card__datum {
  min-width: 58px;
  align-self: stretch;
  padding: 6px 8px;
  background: rgba(0, 0, 0, 0.12);
}
.termin-card__zeiten {
  padding: 10px 8px;
}
.termin-card__meta {
  padding: 0 12px 8px;
}
.termin-card__rsvp {
  min-height: 44px;
}
</style>
