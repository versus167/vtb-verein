// Theme beim Start setzen, bevor die erste Seite gezeichnet wird — sonst
// blitzt kurz das falsche Erscheinungsbild auf. Logik in useTheme.js.
import { initTheme } from 'src/composables/useTheme'

export default () => {
  initTheme()
}
