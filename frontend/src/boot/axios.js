import { boot } from 'quasar/wrappers'
import axios from 'axios'
import { pinia } from 'src/boot/pinia'
import { useAuthStore } from 'src/stores/auth'

const api = axios.create({ baseURL: '' })

export default boot(({ app, router }) => {
  // Token aus localStorage wiederherstellen
  const token = localStorage.getItem('vtb_token')
  if (token) {
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`
  }

  // 401 → Store + localStorage leeren, dann per Router zur Login-Seite
  api.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response?.status === 401) {
        const auth = useAuthStore(pinia)
        auth.logout()
        router.push({ name: 'login' }).catch(() => {})
      }
      return Promise.reject(error)
    },
  )

  app.config.globalProperties.$axios = axios
  app.config.globalProperties.$api = api
})

export { api }
