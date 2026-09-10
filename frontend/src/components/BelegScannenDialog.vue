<template>
  <!--
    Beleg scannen (Ticket #197) — Rahmen um ein eigenständiges Dokument.

    Der Scanner selbst liegt in frontend/public/beleg-scanner.html und läuft
    NICHT als Teil dieser App. Grund ist die Sicherheitsrichtlinie: OpenCV.js
    braucht 'unsafe-eval' und `connect-src data:` (gemessen, s.
    backend/main.py). Diese Lockerung soll an der Kante dieses Rahmens enden
    und nicht für die Seiten mit Mitglieder-, Kassen- und Tresordaten gelten.

    Vollbild-Dialog statt eigener Route, damit der Rechnungs-Dialog darunter
    stehen bleibt: Über eine Route wären das eingetippte Formular und die schon
    gewählten Belege weg, sobald man scannt.

    `persistent`, weil ein Fingertipp neben den Dialog sonst mitten im Scannen
    alles verwirft. Zu geht es über die Knöpfe im Dokument, das dafür eine
    Nachricht schickt.
  -->
  <q-dialog v-model="offen" persistent maximized transition-show="fade" transition-hide="fade">
    <!-- v-if statt v-show: Beim Schließen soll das Dokument wirklich
         verschwinden. Das beendet den Kamerastream zuverlässiger als jedes
         Aufräumen von Hand — der Browser reißt beim Entladen alles ab. -->
    <iframe
      v-if="modelValue"
      ref="rahmen"
      class="beleg-scanner-rahmen"
      :src="quelle"
      title="Beleg scannen"
      allow="camera; fullscreen"
    />
  </q-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { appInfo, ladeAppInfo } from 'src/composables/useAppInfo'
import { BELEG_MAX_MB } from 'src/composables/useRechnungen'

defineOptions({ name: 'BelegScannenDialog' })

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'fertig'])

const offen = computed({
  get: () => props.modelValue,
  set: (wert) => emit('update:modelValue', wert),
})

// Zwei Werte wandern über die Adresse ins Dokument, weil es als statische Datei
// weder Build noch Store kennt:
//   v   – die App-Version, die es an die OpenCV-Bibliothek weiterreicht, damit
//         ein Austausch trotz unveränderlichem Cache eine neue Adresse ergibt.
//   max – die Anhang-Grenze in MB. So bleibt sie EINE Konstante (BELEG_MAX_MB)
//         statt einer zweiten, die im statischen Dokument still veraltet. Der
//         Scanner warnt damit vor dem Hochladen statt danach.
const quelle = computed(() => {
  const p = new URLSearchParams()
  if (appInfo.value.version) p.set('v', appInfo.value.version)
  p.set('max', String(BELEG_MAX_MB))
  return `/beleg-scanner.html?${p}`
})

/**
 * Nachrichten aus dem Rahmen.
 *
 * Die Herkunft wird geprüft, obwohl das Dokument von uns selbst kommt: Ein
 * `message`-Ereignis kann jede Seite schicken, die ein Fenster auf uns hat.
 * Ohne die Prüfung nähme der Rechnungs-Dialog eine Datei von irgendwoher an.
 */
function aufNachricht (e) {
  if (e.origin !== window.location.origin) return
  const daten = e.data
  if (!daten || typeof daten !== 'object') return
  if (daten.typ === 'vtb-beleg-scan' && daten.datei) {
    emit('fertig', daten.datei)
  } else if (daten.typ === 'vtb-beleg-scan-schliessen') {
    offen.value = false
  }
}

onMounted(() => {
  ladeAppInfo()
  window.addEventListener('message', aufNachricht)
})

onBeforeUnmount(() => {
  window.removeEventListener('message', aufNachricht)
})
</script>

<style scoped>
/* Der Dialog gibt die volle Fläche her; das Dokument darin bringt sein eigenes
   Layout mit (position: fixed, inset: 0). */
.beleg-scanner-rahmen {
  width: 100vw;
  height: 100vh;
  border: 0;
  display: block;
  background: #0e0e0e;
}
</style>
