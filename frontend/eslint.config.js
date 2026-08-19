import globals from 'globals'
import pluginVue from 'eslint-plugin-vue'

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  ...pluginVue.configs['flat/essential'],
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.es2021,
        ...globals.node,
      },
      ecmaVersion: 'latest',
      sourceType: 'module',
    },
    rules: {
      // Ein im Template benutzter, im <script setup> fehlender Name bricht erst
      // zur Laufzeit (der Build bleibt grün) — und dann still: Vue bricht das
      // Rendern ab und lässt den alten DOM stehen. Deshalb hier hart als Fehler.
      'vue/no-undef-properties': 'error',
    },
  },
]
