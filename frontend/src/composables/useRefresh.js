// Zentrale Refresh-Steuerung für Listen-/Daten-Seiten.
//
// Jede Seite registriert über usePageRefresh(handler) ihre Reload-Funktion.
// Da immer nur eine Seite aktiv ist (router-view), gibt es genau einen
// aktiven Handler. Der Refresh-Button im Header sowie das automatische
// Nachladen beim Zurückkehren zur App rufen diesen Handler auf.
import { ref, computed, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'

// () => Promise|void – Reload der aktuell sichtbaren Seite, oder null.
const currentHandler = ref(null)
const refreshing = ref(false)
let lastRefreshAt = 0

// Nicht öfter automatisch nachladen als alle 30 s (gegen Fokus-Flackern).
const AUTO_REFRESH_MIN_INTERVAL = 30_000

async function triggerRefresh() {
  if (!currentHandler.value || refreshing.value) return
  refreshing.value = true
  try {
    await currentHandler.value()
    lastRefreshAt = Date.now()
  } catch { /* Fehler meldet die Seite selbst */ } finally {
    refreshing.value = false
  }
}

// Für den Header (MainLayout): Status + Auslöser des Refresh-Buttons.
export function useRefreshControl() {
  return {
    refreshing,
    hasHandler: computed(() => currentHandler.value !== null),
    triggerRefresh,
  }
}

// Auto-Refresh beim Zurückkehren zur App/zum Tab. Einmalig global
// installieren (im MainLayout). Gedrosselt über AUTO_REFRESH_MIN_INTERVAL.
let autoInstalled = false
function onAppVisible() {
  if (document.visibilityState === 'hidden') return
  if (Date.now() - lastRefreshAt < AUTO_REFRESH_MIN_INTERVAL) return
  triggerRefresh()
}
export function installAutoRefresh() {
  if (autoInstalled) return
  autoInstalled = true
  document.addEventListener('visibilitychange', onAppVisible)
  window.addEventListener('focus', onAppVisible)
}

// Pro Seite aufrufen: registriert handler als aktiven Reload, solange die
// Seite sichtbar ist. Funktioniert auch mit <keep-alive> (PersonenPage) über
// onActivated/onDeactivated. Der Guard verhindert, dass eine ausscheidende
// Seite den Handler einer bereits gemounteten Folgeseite überschreibt.
export function usePageRefresh(handler) {
  const register = () => { currentHandler.value = handler }
  const unregister = () => { if (currentHandler.value === handler) currentHandler.value = null }
  onMounted(register)
  onActivated(register)
  onDeactivated(unregister)
  onUnmounted(unregister)
}
