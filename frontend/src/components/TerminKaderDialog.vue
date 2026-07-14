<template>
  <q-dialog v-model="open" @show="load">
    <q-card style="min-width: 340px; max-width: 92vw">
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">Kader &amp; Antworten</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <q-card-section style="min-height: 120px" class="relative-position">
        <q-inner-loading :showing="loading" />
        <div v-if="!loading && kader.length === 0" class="text-grey text-center q-py-md">
          Kein Kader hinterlegt.
        </div>
        <div v-for="grp in gruppen" :key="grp.key" class="q-mb-md">
          <div class="text-caption text-weight-bold text-grey-8 q-mb-xs">
            <q-icon :name="grp.icon" :color="grp.color" size="16px" class="q-mr-xs" />{{ grp.label }} ({{ grp.leute.length }})
          </div>
          <q-list dense separator>
            <q-item v-for="p in grp.leute" :key="p.mitglied_id">
              <q-item-section>
                <q-item-label>{{ p.name }}</q-item-label>
                <q-item-label v-if="p.rollen" caption>{{ p.rollen }}</q-item-label>
              </q-item-section>
              <q-item-section v-if="darfVerwalten" side>
                <div class="row no-wrap q-gutter-xs">
                  <q-btn v-for="a in ANTWORTEN" :key="a.key" flat dense round size="sm"
                    :icon="a.icon" :color="p.antwort === a.key ? a.color : 'grey-5'"
                    :disable="busy" @click="setFuer(p, a.key)">
                    <q-tooltip>{{ a.label }}</q-tooltip>
                  </q-btn>
                </div>
              </q-item-section>
            </q-item>
          </q-list>
        </div>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { ANTWORTEN } from 'src/composables/useTermine'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  terminId: { type: Number, required: true },
  darfVerwalten: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'geaendert'])

const $q = useQuasar()
const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const kader = ref([])
const loading = ref(false)
const busy = ref(false)

// Gruppen in fester Reihenfolge: Zusage, Vielleicht, Absage, dann Offen.
const GRUPPEN = [
  ...ANTWORTEN,
  { key: null, icon: 'radio_button_unchecked', color: 'grey-6', label: 'Offen' },
]
const gruppen = computed(() =>
  GRUPPEN.map(g => ({ ...g, leute: kader.value.filter(p => p.antwort === g.key) }))
    .filter(g => g.leute.length > 0),
)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get(`/api/termine/${props.terminId}/kader`)
    kader.value = data.kader
  } catch {
    $q.notify({ type: 'negative', message: 'Kader konnte nicht geladen werden' })
    kader.value = []
  } finally {
    loading.value = false
  }
}

async function setFuer(p, key) {
  busy.value = true
  try {
    if (p.antwort === key) {
      await api.delete(`/api/termine/${props.terminId}/zusage/${p.mitglied_id}`)
    } else {
      await api.put(`/api/termine/${props.terminId}/zusage/${p.mitglied_id}`, { antwort: key })
    }
    await load()
    emit('geaendert')
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Speichern fehlgeschlagen' })
  } finally {
    busy.value = false
  }
}
</script>
