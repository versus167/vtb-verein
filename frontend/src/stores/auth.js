import { defineStore } from 'pinia'
import { api } from 'src/boot/axios'

export const useAuthStore = defineStore('auth', {
  // Das JWT liegt seit Ticket #48 im HttpOnly-Cookie (für JS unlesbar). Der Store
  // kennt nur noch das (unkritische) User-Objekt: es dient ausschließlich dem
  // UI-Gating, durchgesetzt wird die Berechtigung serverseitig je Request. Der
  // localStorage-Cache erlaubt „eingeloggt bleiben“ über Reloads; Quelle der
  // Wahrheit ist die Cookie-validierte /me-Antwort beim Bootstrap.
  state: () => ({
    user: JSON.parse(localStorage.getItem('vtb_user') || 'null'),
  }),

  getters: {
    isAuthenticated: (state) => !!state.user,
    hasPermission: (state) => (permission) => state.user?.role === 'admin' || state.user?.permissions?.includes(permission) || false,
  },

  actions: {
    async login(username, password, rememberMe = false) {
      const form = new URLSearchParams()
      form.append('username', username)
      form.append('password', password)
      const { data } = await api.post(`/api/auth/login?remember_me=${rememberMe}`, form)
      this._applyUser(data)
    },

    async loginWithMagicToken(token, remember = false) {
      const { data } = await api.post('/api/auth/magic-link/validate', { token, remember })
      this._applyUser(data)
    },

    _applyUser(data) {
      // Server setzt das Session-Cookie; hier nur die User-Infos übernehmen.
      this.user = { id: data.id, username: data.username, role: data.role, permissions: data.permissions }
      localStorage.setItem('vtb_user', JSON.stringify(this.user))
    },

    async loadMe() {
      const { data } = await api.get('/api/auth/me')
      this.user = data
      localStorage.setItem('vtb_user', JSON.stringify(this.user))
    },

    logout() {
      this.user = null
      localStorage.removeItem('vtb_user')
      localStorage.removeItem('vtb_token') // Altlast aus der localStorage-Token-Ära
    },

    // Vom Nutzer ausgelöster Logout: zuerst die Server-Session widerrufen
    // (damit das Gerät nicht in der Geräteliste verbleibt), dann lokal leeren.
    // Best effort – ein Fehler darf das lokale Abmelden nicht verhindern.
    async logoutServer() {
      try {
        await api.post('/api/auth/logout')
      } catch { /* Session evtl. schon ungültig – egal */ }
      this.logout()
    },
  },
})
