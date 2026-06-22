import { boot } from 'quasar/wrappers'
import axios from 'axios'
import { pinia } from 'src/boot/pinia'
import { useAuthStore } from 'src/stores/auth'

// withCredentials: das HttpOnly-Session-Cookie (Ticket #48) wird automatisch
// mitgeschickt. Dev (Quasar-Proxy) wie Prod (SPA-Mount) sind same-origin, daher
// genügt das ohne CORS-Sonderfälle. Kein Authorization-Header mehr – das JWT ist
// für JS bewusst unlesbar.
const api = axios.create({ baseURL: '', withCredentials: true })

export default boot(({ app, router }) => {
  // 401 → Store leeren, dann per Router zur Login-Seite
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
