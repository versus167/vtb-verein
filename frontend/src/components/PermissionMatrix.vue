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
          <div v-for="perm in group.permissions" :key="perm.key">
            <q-checkbox
              :model-value="selectedSet.has(perm.key)"
              :label="perm.label"
              :disable="readonly"
              :color="highlightKeys.includes(perm.key) ? 'orange' : 'primary'"
              @update:model-value="val => toggle(perm.key, val)"
            />
          </div>
        </q-card-section>
      </q-card>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

// Wiederverwendbare Berechtigungs-Matrix (Checkbox-Raster nach Gruppen).
// Genutzt vom persönlichen Berechtigungsscreen (UserPermissionsPage) und vom
// Funktions-Berechtigungs-Dialog (EinstellungenPage). v-model ist ein Array von
// Permission-Keys; highlightKeys hebt abweichende Einträge orange hervor.
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  groups: { type: Array, default: () => [] },
  readonly: { type: Boolean, default: false },
  highlightKeys: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

const selectedSet = computed(() => new Set(props.modelValue))

function toggle(key, val) {
  const set = new Set(props.modelValue)
  if (val) set.add(key)
  else set.delete(key)
  emit('update:modelValue', [...set])
}
</script>
