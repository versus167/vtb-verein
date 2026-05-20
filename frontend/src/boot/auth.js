import { boot } from 'quasar/wrappers'
import { useAuthStore } from 'src/stores/auth'
import { pinia } from 'src/boot/pinia'

export default boot(({ router }) => {
  // useAuthStore() benötigt eine aktive Pinia-Instanz
  const auth = useAuthStore(pinia)

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
  })
})
