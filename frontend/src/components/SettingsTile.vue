<template>
  <q-card class="cursor-pointer settings-tile fit" @click="go">
    <q-card-section class="settings-tile__inhalt">
      <div class="settings-tile__icon">
        <q-icon :name="icon" size="26px" color="primary" />
      </div>
      <div class="text-subtitle1 text-weight-bold">{{ title }}</div>
      <div v-if="caption" class="text-caption text-grey">{{ caption }}</div>
      <q-icon name="chevron_right" class="settings-tile__pfeil" />
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

<style lang="scss" scoped>
.settings-tile {
  border-radius: 14px;
}
.settings-tile:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
  transition: all 0.2s ease;
}
.settings-tile__inhalt {
  position: relative;
  /* Platz für den Pfeil rechts */
  padding-right: 40px;
}
.settings-tile__icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba($vtb-blau, 0.08);
  margin-bottom: 10px;
}
.settings-tile__pfeil {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 22px;
  color: rgba(0, 0, 0, 0.35);
}
</style>
