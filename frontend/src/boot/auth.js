import { boot } from 'quasar/wrappers'
import { useAuthStore } from 'src/stores/auth'
import { pinia } from 'src/boot/pinia'
import { api } from 'src/boot/axios'

export default boot(async ({ router }) => {
  // useAuthStore() benötigt eine aktive Pinia-Instanz
  const auth = useAuthStore(pinia)

  // Guard ZUERST registrieren – vor jedem await, damit die initiale
  // Navigation nicht ohne Guard durchläuft
  router.beforeEach((to) => {
    if (to.meta.requiresAuth && !auth.isAuthenticated) {
      return { name: 'login' }
    }
    if (to.name === 'login' && auth.isAuthenticated) {
      return { name: 'dashboard' }
    }
    if (to.meta.adminOnly && auth.user?.role !== 'admin') {
      return { name: 'dashboard' }
    }
    if (to.meta.permission && !auth.hasPermission(to.meta.permission) && auth.user?.role !== 'admin') {
      return { name: 'dashboard' }
    }
  })

  // Seitenaufruf-Tracking (Zugriffsprotokoll): nach jeder erfolgreichen Navigation
  // einen page_view loggen. Fire-and-forget, best-effort – darf die Navigation nie
  // blockieren. Nur authentifizierte App-Seiten (requiresAuth); Login/Magic-Link außen vor.
  // Aufeinanderfolgende Duplikate derselben Route werden übersprungen.
  let letzteRoute = null
  router.afterEach((to) => {
    if (!to.meta.requiresAuth || !auth.isAuthenticated) return
    if (to.fullPath === letzteRoute) return
    letzteRoute = to.fullPath
    api.post('/api/protokoll/seitenaufruf', {
      route_name: to.name ?? null,
      path: to.path,
    }).catch(() => {})
  })

  // Permissions nach Guard-Registrierung fresh laden
  if (auth.isAuthenticated) {
    try {
      await auth.loadMe()
    } catch {
      // 401 wird vom Axios-Interceptor behandelt
    }
  }
})
