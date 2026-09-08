import { boot } from 'quasar/wrappers'

// Zurück-Geste am Handy: Ein offener Dialog ist gefühlt eine eigene Seite —
// „zurück" soll ihn schließen und nicht die ganze Seite verlassen (#193). Ohne
// das landet man aus einem Bearbeiten-Dialog heraus wieder auf dem Dashboard,
// obwohl man nur eine Ebene hoch wollte.
//
// Quasar kann das von Haus aus nur in Cordova-/Capacitor-Builds: Sein
// History-Plugin (plugins/private.history) hängt sich dort ans native
// backbutton-Event, und QDialog/QDrawer tragen sich bei ihm ein. Im Browser
// bzw. der PWA — also in unserem Fall — installiert es sich gar nicht erst,
// und die Zurück-Geste geht direkt an den Router.
//
// Nachbau fürs Web:
//   * Öffnet ein Dialog, schieben wir einen History-Eintrag auf dieselbe URL
//     nach. Die Zurück-Geste hat damit etwas zu verbrauchen.
//   * Beim popstate schließen wir so viele Dialoge, bis der Stapel wieder so
//     tief ist wie im History-State vermerkt (`vtbOverlay`). Über die Tiefe
//     statt über einen Zähler, weil das idempotent ist: verschluckte oder
//     zusammengefasste popstate-Events bringen es nicht aus dem Tritt.
//   * Schließt ein Dialog anders (Button, ESC, Backdrop), räumen wir seinen
//     Eintrag per history.back() selbst weg — sonst müsste man einmal ins Leere
//     zurückdrücken.
//
// Angehängt wird das per globalem Mixin an QDialog statt über Quasars
// History-Plugin: Dessen Modul ist privat und liegt im Dev-Server (dort ohne
// Treeshaking, Import aus dem dist-Bundle) in einer anderen Instanz als im
// Build — ein Patch dort würde nur in Produktion greifen. Der Mixin nutzt
// dagegen nur öffentliche API (Prop `modelValue`, Methode `hide()`) und
// verhält sich in beiden Modi gleich.
//
// Fallstrick für Seiten mit Deeplink: Solange ein Dialog offen ist, ist der
// oberste History-Eintrag unserer, nicht der der Seite. Ein `router.replace`
// (z. B. um `?ticket=NN` nach dem Öffnen aus der URL zu putzen) trifft dann den
// falschen Eintrag — der Seiten-Eintrag behält die Query, und jedes Zurück
// zieht den Deeplink erneut auf. Deshalb gilt: erst die URL aufräumen, dann den
// Dialog öffnen (siehe TicketsPage.vue::openTicketFromQuery).
//
// Bewusst nicht dabei:
//   * QDrawer — am Desktop ist die Navigationsleiste dauerhaft offen, dort
//     wären History-Einträge fürs Auf-/Zuklappen nur störend.
//   * Wer mit offenem Dialog wegnavigiert, lässt dessen Einträge im Verlauf
//     zurück; zurück führt dann erst auf dieselbe Seite, bevor es weitergeht.
//     Selten (der Dialog verdeckt die Navigation) und harmlos.

const OFFEN_KEY = Symbol('vtb-zurueck')

// Offene Dialoge, oberster zuletzt.
const stapel = []

function tiefeImVerlauf() {
  return window.history.state?.vtbOverlay ?? 0
}

function eintragen(eintrag) {
  stapel.push(eintrag)
  const alt = window.history.state ?? {}
  // Zustand des Routers mitnehmen (position/scroll), damit vue-router beim
  // Zurückspringen weiter saubere Deltas rechnet. Kein zweites Argument für
  // die URL: Der Eintrag zeigt bewusst auf dieselbe Adresse.
  window.history.pushState(
    {
      ...alt,
      back: alt.current ?? null,
      forward: null,
      position: (alt.position ?? 0) + 1,
      vtbOverlay: stapel.length,
    },
    '',
  )
}

function austragen(eintrag) {
  const index = stapel.lastIndexOf(eintrag)
  if (index === -1) return
  stapel.splice(index, 1)
  // Nur zurückspringen, wenn oben auch wirklich noch ein eigener Eintrag liegt.
  // Beim Routenwechsel schließt Quasar offene Dialoge selbst — ein back() würde
  // dann die gerade begonnene Navigation wieder zurücknehmen.
  if (tiefeImVerlauf() > stapel.length) window.history.back()
}

function beiPopstate() {
  const tiefe = tiefeImVerlauf()
  // pop() vor hide(): Das Schließen löst den modelValue-Watcher aus, der sonst
  // seinerseits ein history.back() auslösen würde.
  while (stapel.length > tiefe) stapel.pop().schliessen()
}

const zurueckMixin = {
  mounted() {
    if (this.$options.name !== 'QDialog') return

    const eintrag = { schliessen: () => this.hide() }
    this[OFFEN_KEY] = eintrag

    if (this.modelValue === true) eintragen(eintrag)

    this.$watch('modelValue', (offen) => {
      if (offen === true) eintragen(eintrag)
      else austragen(eintrag)
    })
  },

  unmounted() {
    if (this.$options.name !== 'QDialog') return
    const eintrag = this[OFFEN_KEY]
    if (eintrag !== undefined) austragen(eintrag)
  },
}

export default boot(({ app }) => {
  app.mixin(zurueckMixin)
  window.addEventListener('popstate', beiPopstate)
})
