<template>
  <div v-if="!items.length" class="text-grey-6 text-center q-pa-md">{{ emptyText }}</div>
  <template v-else>
    <div v-for="item in items" :key="item.label" class="q-mb-sm">
      <div class="row items-center no-wrap q-mb-xs">
        <div class="col text-body2 ellipsis">{{ item.label }}</div>
        <div class="text-weight-medium q-ml-sm">{{ item.anzahl }}</div>
      </div>
      <q-linear-progress
        :value="max ? item.anzahl / max : 0"
        :color="color"
        :track-color="$q.dark.isActive ? 'grey-9' : 'grey-3'"
        size="14px"
        rounded
      />
    </div>
  </template>
</template>

<script setup>
import { computed } from 'vue'
import { useQuasar } from 'quasar'

const props = defineProps({
  items: { type: Array, default: () => [] },
  color: { type: String, default: 'primary' },
  emptyText: { type: String, default: 'Keine Daten' },
})

const $q = useQuasar()
const max = computed(() => Math.max(0, ...props.items.map((i) => i.anzahl)))
</script>
