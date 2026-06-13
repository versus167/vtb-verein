<template>
  <div class="row q-col-gutter-md">
    <div
      v-for="group in groups"
      :key="group.label"
      class="col-12 col-sm-6 col-md-4"
    >
      <q-card flat bordered>
        <q-card-section>
          <div class="row items-center q-mb-sm">
            <q-icon :name="group.icon" color="primary" size="sm" />
            <span class="text-subtitle2 text-weight-bold q-ml-sm">{{ group.label }}</span>
          </div>

          <!-- ── Einfacher Modus: Checkbox je Recht ── -->
          <template v-if="mode === 'simple'">
            <div v-for="perm in group.permissions" :key="perm.key">
              <q-checkbox
                :model-value="selectedSet.has(perm.key)"
                :label="perm.label"
                :disable="readonly"
                :color="highlightKeys.includes(perm.key) ? 'orange' : 'primary'"
                @update:model-value="val => toggle(perm.key, val)"
              />
            </div>
          </template>

          <!-- ── Tri-State-Modus: geerbt / individuell + / individuell − ── -->
          <template v-else>
            <div v-for="perm in group.permissions" :key="perm.key" class="q-mb-sm">
              <div class="row items-center no-wrap">
                <q-icon
                  :name="isEffective(perm.key) ? 'check_circle' : 'cancel'"
                  :color="isEffective(perm.key) ? 'positive' : 'grey-5'"
                  size="xs" class="q-mr-xs"
                />
                <div class="col">{{ perm.label }}</div>
                <q-btn-toggle
                  :model-value="stateOf(perm.key)"
                  :options="tristateOptions"
                  :disable="readonly"
                  dense unelevated no-caps size="sm"
                  toggle-color="primary" color="grey-3" text-color="grey-8"
                  @update:model-value="v => setState(perm.key, v)"
                />
              </div>
              <div class="text-caption text-grey-6 q-ml-lg">
                <template v-if="inheritChips(perm.key).length">
                  geerbt:
                  <q-badge
                    v-for="(c, i) in inheritChips(perm.key)" :key="i"
                    color="teal-1" text-color="teal-9" class="q-ml-xs"
                  >{{ c }}</q-badge>
                </template>
                <span v-else-if="stateOf(perm.key) === 'grant'">individuell gewährt</span>
                <span v-else-if="stateOf(perm.key) === 'deny'" class="text-negative">individuell entzogen</span>
                <span v-else>nicht geerbt</span>
              </div>
            </div>
          </template>
        </q-card-section>
      </q-card>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

// Wiederverwendbare Berechtigungs-Matrix.
//  - mode='simple'  : Checkbox-Raster, v-model = Array von Keys (Funktions-Matrix).
//  - mode='tristate': geerbt / individuell+ / individuell−, v-model:grants + v-model:denies
//    plus inherited (Set) und sources (Herkunft) für die Anzeige (persönlicher Screen).
const props = defineProps({
  groups: { type: Array, default: () => [] },
  readonly: { type: Boolean, default: false },
  mode: { type: String, default: 'simple' }, // 'simple' | 'tristate'
  // simple
  modelValue: { type: Array, default: () => [] },
  highlightKeys: { type: Array, default: () => [] },
  // tristate
  grants: { type: Array, default: () => [] },
  denies: { type: Array, default: () => [] },
  inherited: { type: Array, default: () => [] },
  sources: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'update:grants', 'update:denies'])

// ── simple ──
const selectedSet = computed(() => new Set(props.modelValue))
function toggle(key, val) {
  const set = new Set(props.modelValue)
  if (val) set.add(key)
  else set.delete(key)
  emit('update:modelValue', [...set])
}

// ── tristate ──
const tristateOptions = [
  { label: 'Standard', value: 'auto' },
  { label: '+', value: 'grant' },
  { label: '−', value: 'deny' },
]
const grantsSet = computed(() => new Set(props.grants))
const deniesSet = computed(() => new Set(props.denies))
const inheritedSet = computed(() => new Set(props.inherited))

function stateOf(key) {
  if (deniesSet.value.has(key)) return 'deny'
  if (grantsSet.value.has(key)) return 'grant'
  return 'auto'
}
function isEffective(key) {
  const s = stateOf(key)
  if (s === 'deny') return false
  if (s === 'grant') return true
  return inheritedSet.value.has(key)
}
function setState(key, state) {
  const g = new Set(props.grants)
  const d = new Set(props.denies)
  g.delete(key); d.delete(key)
  if (state === 'grant') g.add(key)
  else if (state === 'deny') d.add(key)
  emit('update:grants', [...g])
  emit('update:denies', [...d])
}
function inheritChips(key) {
  return (props.sources[key] || [])
    .filter(s => s.typ === 'sockel' || s.typ === 'funktion')
    .map(s => {
      if (s.typ === 'sockel') return 'Sockel'
      return s.abteilung_name ? `${s.funktion_name} (${s.abteilung_name})` : s.funktion_name
    })
}
</script>
