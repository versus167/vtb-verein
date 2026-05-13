import { defineStore } from 'pinia'
import { api } from 'src/boot/axios'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('vtb_token') || null,
    user: JSON.parse(localStorage.getItem('vtb_user') || 'null'),
  }),

  getters: {
    isAuthenticated: (state) => !!state.token,
    hasPermission: (state) => (permission) => state.user?.permissions?.includes(permission) ?? false,
  },

  actions: {
    async login(username, password) {
      const form = new URLSearchParams()
      form.append('username', username)
      form.append('password', password)
      const { data } = await api.post('/api/auth/login', form)
      this.token = data.access_token
      this.user = { username: data.username, role: data.role, permissions: data.permissions }
      localStorage.setItem('vtb_token', this.token)
      localStorage.setItem('vtb_user', JSON.stringify(this.user))
      api.defaults.headers.common['Authorization'] = `Bearer ${this.token}`
    },

    async loadMe() {
      const { data } = await api.get('/api/auth/me')
      this.user = data
      localStorage.setItem('vtb_user', JSON.stringify(this.user))
    },

    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('vtb_token')
      localStorage.removeItem('vtb_user')
      delete api.defaults.headers.common['Authorization']
    },
  },
})
