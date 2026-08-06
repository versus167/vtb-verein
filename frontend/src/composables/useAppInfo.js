// App-Metadaten aus /api/app-info: Version, Quellcode-Link (AGPL §13) und das
// Vereinskürzel für Mannschaftsnamen. Einmal je Sitzung geladen und geteilt –
// Login-Seite, Drawer-Fußzeile und die Termin-Titel brauchen dieselben Werte,
// und der Endpunkt liefert Stammdaten, die sich im Betrieb nicht ändern.
import { computed, ref } from 'vue'
import { api } from 'src/boot/axios'

export const appInfo = ref({ name: '', version: '', source_url: '', verein_kurz: '', verein_name: '' })

// Vereinsname für die Login-Seite. Solange nichts geladen ist, bleibt die Zeile
// leer – lieber kurz kein Name als der eines fremden Vereins.
export const vereinName = computed(() => (appInfo.value.verein_name || '').trim())

// „v.2026.08.04.162" – Anzeigeform; leer, solange nichts geladen ist.
export const versionLabel = computed(() =>
  appInfo.value.version ? `v.${appInfo.value.version}` : '')

let laufend = null

// Mehrfach aufrufbar: Der erste Aufruf lädt, alle weiteren hängen sich an. Ein
// Fehlschlag wird nicht zementiert – der nächste Aufruf versucht es erneut.
export function ladeAppInfo() {
  if (!laufend) {
    laufend = api.get('/api/app-info')
      .then(({ data }) => { appInfo.value = { ...appInfo.value, ...data } })
      .catch(() => { laufend = null })
  }
  return laufend
}

// „AH" → „VTB AH". Das Kürzel ist Stammdatum (VTB_VEREIN_KURZ), damit die App
// auch für einen anderen Verein läuft. Trägt der Mannschaftsname das Kürzel
// schon, bleibt er, wie er ist – sonst stünde da „VTB VTB Chemnitz 2".
export function eigenesTeam(mannschaftName) {
  const name = (mannschaftName || '').trim()
  const kurz = (appInfo.value.verein_kurz || '').trim()
  if (!name || !kurz || name.toLowerCase().startsWith(kurz.toLowerCase())) return name
  return `${kurz} ${name}`
}
