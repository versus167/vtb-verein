import { boot } from 'quasar/wrappers'
import axios from 'axios'

const api = axios.create({ baseURL: '' })

export default boot(({ app }) => {
  // Token aus localStorage wiederherstellen
  const token = localStorage.getItem('vtb_token')
  if (token) {
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`
  }

  // 401 → zur Login-Seite weiterleiten
  api.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response?.status === 401) {
        localStorage.removeItem('vtb_token')
        localStorage.removeItem('vtb_user')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    },
  )

  app.config.globalProperties.$axios = axios
  app.config.globalProperties.$api = api
})

export { api }
