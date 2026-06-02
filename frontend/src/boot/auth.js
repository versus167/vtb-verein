import { boot } from 'quasar/wrappers'
import { useAuthStore } from 'src/stores/auth'
import { pinia } from 'src/boot/pinia'

export default boot(async ({ router }) => {
  // useAuthStore() benötigt eine aktive Pinia-Instanz
  const auth = useAuthStore(pinia)

  // Permissions beim App-Start einmal fresh vom Server laden
  if (auth.isAuthenticated) {
    try {
      await auth.loadMe()
    } catch {
      // Token abgelaufen o.ä. – Router-Guard leitet weiter
    }
  }

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
})
