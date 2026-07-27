import { defineStore } from 'pinia'
import { api } from 'src/boot/axios'

// Zahl am App-Symbol der installierten PWA (Badging API).
//
// Bewusst best effort: Firefox kennt die API nicht, Safari/iOS knüpft sie an
// die Benachrichtigungs-Erlaubnis, und im Browser-Tab gibt es überhaupt kein
// Symbol zum Badgen. Wo es nicht geht, passiert einfach nichts – die Zahl an
// Kachel und Nav-Punkt ist die verlässliche Anzeige, das Badge die Zugabe.
function setzeAppBadge(anzahl) {
  if (!('setAppBadge' in navigator)) return
  const erledigt = anzahl > 0 ? navigator.setAppBadge(anzahl) : navigator.clearAppBadge()
  // Auf iOS lehnt die API ohne Benachrichtigungs-Erlaubnis ab – kein Grund,
  // eine unbehandelte Rejection in die Konsole zu schreiben.
  erledigt?.catch?.(() => {})
}

// Offene Aufgaben für die Hinweise an Kacheln und Nav-Punkten (Ticket #133).
//
// Ein Store statt eines Ladevorgangs je Komponente: Nav-Leiste und Dashboard
// zeigen dieselben Zahlen und sind gleichzeitig sichtbar – sie sollen sich
// nicht zwei Antworten auf dieselbe Frage holen und dabei auseinanderlaufen.
// Geladen wird zentral im MainLayout (auch bei jedem Refresh); die Listen-
// seiten stoßen nach einer Entscheidung ein Nachladen an, damit der Hinweis
// sofort verschwindet und nicht erst beim nächsten Refresh.
export const useAufgabenStore = defineStore('aufgaben', {
  state: () => ({
    offen: {},      // { <Routenname>: Anzahl }
    gesamt: 0,
  }),

  getters: {
    // 0 heißt „nichts zu tun" – die Komponenten blenden den Hinweis dann aus.
    anzahl: (state) => (schluessel) => state.offen[schluessel] || 0,
  },

  actions: {
    async laden() {
      try {
        const { data } = await api.get('/api/aufgaben/offen')
        this.offen = data.offen || {}
        this.gesamt = data.gesamt || 0
        setzeAppBadge(this.gesamt)
      } catch {
        // Ein fehlender Hinweis ist harmlos – nichts anzeigen ist besser als
        // eine veraltete Zahl stehen zu lassen.
        this.zuruecksetzen()
      }
    },

    zuruecksetzen() {
      this.offen = {}
      this.gesamt = 0
      // Auch das Badge weg: nach dem Abmelden klebte sonst die Zahl des
      // Vorgängers am App-Symbol.
      setzeAppBadge(0)
    },
  },
})
