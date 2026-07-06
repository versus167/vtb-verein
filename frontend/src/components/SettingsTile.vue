<template>
  <q-card class="cursor-pointer settings-tile fit" @click="go">
    <q-card-section class="text-center">
      <q-icon :name="icon" size="3rem" color="primary" />
      <div class="text-h6 q-mt-sm">{{ title }}</div>
      <div v-if="caption" class="text-caption text-grey">{{ caption }}</div>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { useRouter } from 'vue-router'

const props = defineProps({
  to: { type: String, required: true },
  icon: { type: String, required: true },
  title: { type: String, required: true },
  caption: { type: String, default: '' },
})

const router = useRouter()
function go() {
  router.push({ name: props.to })
}
</script>

<style scoped>
.settings-tile:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
  transition: all 0.2s ease;
}
</style>
