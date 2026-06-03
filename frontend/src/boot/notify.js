import { boot } from 'quasar/wrappers'
import { Notify } from 'quasar'

export default boot(() => {
  Notify.setDefaults({
    position: 'top-right',
    timeout: 4000,
    actions: [{ icon: 'close', color: 'white', dense: true, round: true }],
  })
})
