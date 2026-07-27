import { defineStore } from 'pinia'
import { api } from 'src/boot/axios'

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
      } catch {
        // Ein fehlender Hinweis ist harmlos – nichts anzeigen ist besser als
        // eine veraltete Zahl stehen zu lassen.
        this.zuruecksetzen()
      }
    },

    zuruecksetzen() {
      this.offen = {}
      this.gesamt = 0
    },
  },
})
