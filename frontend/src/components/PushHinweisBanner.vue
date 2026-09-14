<template>
  <!-- Push-Hinweis in der installierten App. Gegenstück zum Installations-Banner im
       MainLayout (das nur im Browser erscheint): Links aus Mails öffnen am Handy
       oft im Browser der Mail-App statt in der App, auf dem iPhone sogar immer.
       Zuverlässig in die App führt nur der Tipp auf eine Push-Nachricht. -->
  <q-banner
    v-if="sichtbar"
    dense
    class="bg-primary text-white fixed-bottom"
    style="z-index: 9999"
  >
    <template #avatar>
      <q-icon name="notifications_active" color="white" />
    </template>
    Push einschalten? Ein Tipp auf die Benachrichtigung öffnet dann direkt den Termin
    oder das Ticket hier in der App.
    <template #action>
      <q-btn flat dense label="Einschalten" :loading="busy" @click="einschalten" />
      <q-btn flat dense label="Nein danke" @click="ausblenden" />
    </template>
  </q-banner>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { usePush } from 'src/composables/usePush'

// Je Gerät: Wer ablehnt, wird hier nicht mehr gefragt — die Glocke auf der
// Übersicht und das Profil bleiben als Weg zum Einschalten.
const AUS_KEY = 'vtb_push_hinweis_aus'

const $q = useQuasar()
const push = usePush()

const sichtbar = ref(false)
const busy = ref(false)

function istInstalliert () {
  return window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true
}

function abgelehnt () {
  try {
    return !!localStorage.getItem(AUS_KEY)
  } catch {
    return false
  }
}

onMounted(async () => {
  // Im Browser gibt es das Installations-Banner; dort wäre das hier ein zweites.
  // Blockierte Benachrichtigungen kann nur der Nutzer in den Einstellungen lösen –
  // ein Knopf, der dann bloß eine Fehlermeldung zeigt, hilft niemandem.
  if (!istInstalliert() || abgelehnt() || !push.isSupported()
      || Notification.permission === 'denied') return
  try {
    const status = await push.serverStatus()
    if (!status.configured) return
    sichtbar.value = !(await push.isSubscribed())
  } catch { /* Status unbekannt – dann lieber nichts anzeigen */ }
})

async function einschalten () {
  busy.value = true
  try {
    await push.subscribe()
    sichtbar.value = false
    $q.notify({ type: 'positive', message: 'Push auf diesem Gerät aktiviert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || 'Push konnte nicht aktiviert werden' })
  } finally {
    busy.value = false
  }
}

function ausblenden () {
  sichtbar.value = false
  try {
    localStorage.setItem(AUS_KEY, '1')
  } catch { /* dann eben beim nächsten Start noch einmal */ }
}
</script>
