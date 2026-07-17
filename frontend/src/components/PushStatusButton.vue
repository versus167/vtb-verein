<template>
  <!-- Push-Status fürs aktuelle Gerät in der Kopfzeile (#108): gelb = aktiv,
       gedimmt = inaktiv/nicht verfügbar. Ein Klick schaltet um bzw. erklärt,
       warum Push hier nicht geht. Immer sichtbar, damit der Zustand „nicht
       aktiv" nicht mit „Symbol fehlt" verwechselt wird. -->
  <q-btn
    flat :dense="$q.screen.gt.sm" round
    :icon="subscribed ? 'notifications_active' : 'notifications_off'"
    :class="subscribed ? 'vtb-push-aktiv' : 'vtb-push-inaktiv'"
    :loading="busy"
    @click="onToggle"
  >
    <q-tooltip>{{ tooltip }}</q-tooltip>
  </q-btn>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useQuasar } from 'quasar'
import { usePush } from 'src/composables/usePush'

const $q = useQuasar()
const push = usePush()

const supported = ref(false)
// null = Serverstatus (noch) unbekannt — Klick versucht es dann einfach.
const configured = ref(null)
const subscribed = ref(false)
const busy = ref(false)

const tooltip = computed(() => {
  if (!supported.value) return 'Push wird von diesem Browser/Gerät nicht unterstützt (HTTPS bzw. localhost nötig)'
  if (configured.value === false) return 'Push ist serverseitig noch nicht konfiguriert'
  return subscribed.value
    ? 'Push auf diesem Gerät aktiv – Klick deaktiviert'
    : 'Push auf diesem Gerät inaktiv – Klick aktiviert'
})

async function refreshState () {
  supported.value = push.isSupported()
  if (!supported.value) return
  try {
    const status = await push.serverStatus()
    configured.value = !!status.configured
    subscribed.value = await push.isSubscribed()
  } catch { /* Status optional – Klick liefert dann die konkrete Meldung */ }
}

// Beim Zurückkehren in die App neu prüfen: die Berechtigung kann inzwischen
// in den Browser-Einstellungen entzogen oder auf einem anderen Weg (Profilseite)
// geändert worden sein.
async function onVisibilityChange () {
  if (document.visibilityState === 'visible' && supported.value) {
    subscribed.value = await push.isSubscribed()
  }
}

async function onToggle () {
  if (!supported.value || configured.value === false) {
    $q.notify({ type: 'warning', message: tooltip.value })
    return
  }
  busy.value = true
  try {
    if (subscribed.value) {
      await push.unsubscribe()
      subscribed.value = false
      $q.notify({ type: 'info', message: 'Push auf diesem Gerät deaktiviert' })
    } else {
      await push.subscribe()
      subscribed.value = true
      $q.notify({ type: 'positive', message: 'Push auf diesem Gerät aktiviert' })
    }
  } catch (e) {
    subscribed.value = await push.isSubscribed()
    $q.notify({ type: 'negative', message: e.message || 'Push konnte nicht geändert werden' })
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  refreshState()
  document.addEventListener('visibilitychange', onVisibilityChange)
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style lang="scss" scoped>
.vtb-push-aktiv {
  color: $vtb-gelb;
}
.vtb-push-inaktiv {
  opacity: 0.6;
}
</style>
