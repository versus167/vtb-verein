import { Dark } from 'quasar'

export default () => {
  const saved = localStorage.getItem('darkMode')
  if (saved === 'true') Dark.set(true)
  else if (saved === 'false') Dark.set(false)
  else Dark.set('auto')
}
