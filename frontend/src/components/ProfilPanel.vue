<template>
  <q-card flat bordered class="vtb-karte profil-panel">
    <q-expansion-item
      expand-separator
      :duration="180"
      header-class="profil-panel__kopf"
      expand-icon-class="profil-panel__pfeil"
    >
      <template #header>
        <q-item-section avatar class="profil-panel__scheibe">
          <div class="vtb-icon vtb-icon--klein">
            <q-icon :name="icon" size="20px" />
          </div>
        </q-item-section>
        <q-item-section>
          <q-item-label class="text-weight-bold">{{ titel }}</q-item-label>
          <q-item-label v-if="info" caption lines="1">{{ info }}</q-item-label>
        </q-item-section>
      </template>

      <q-card-section>
        <slot />
      </q-card-section>
    </q-expansion-item>
  </q-card>
</template>

<script setup>
defineProps({
  icon: { type: String, required: true },
  titel: { type: String, required: true },
  // Kurzfassung im Kopf, damit man zugeklappt schon sieht, was drinsteckt.
  info: { type: String, default: '' },
})
</script>

<style scoped lang="scss">
.profil-panel {
  overflow: hidden;

  // Die Icon-Scheibe färbt ihr Icon selbst (Gelb auf Blau, Hellblau im Dark
  // Mode). Ohne das hier gewinnt die globale Regel für Icons in q-items auf
  // blauen Karten und macht es weiß.
  :deep(.vtb-icon .q-icon) {
    color: inherit;
  }

  :deep(.profil-panel__scheibe) {
    min-width: 0;
    padding-right: 12px;
  }

  // Aufklappbarkeit sichtbar machen: der ganze Kopf reagiert auf Hover, der
  // Pfeil sitzt in einer Scheibe und dreht sich beim Öffnen (Quasar-Default).
  :deep(.profil-panel__kopf) {
    transition: background 0.15s ease;
  }
  :deep(.profil-panel__kopf:hover) {
    background: rgba(255, 255, 255, 0.06);
  }
  :deep(.profil-panel__pfeil) {
    padding: 4px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.1);
    transition: background 0.15s ease;
  }
  :deep(.profil-panel__kopf:hover .profil-panel__pfeil) {
    background: rgba(255, 255, 255, 0.2);
  }
}
</style>
