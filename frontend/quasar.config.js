/* eslint-env node */
import { configure } from 'quasar/wrappers'

export default configure(function (/* ctx */) {
  return {
    boot: ['pinia', 'axios', 'auth'],

    css: ['app.scss'],

    extras: [
      'roboto-font',
      'material-icons',
    ],

    build: {
      target: {
        browser: ['es2019', 'edge88', 'firefox78', 'chrome87', 'safari13.1'],
        node: 'node22',
      },
      vueRouterMode: 'history',
      vitePlugins: [],
    },

    devServer: {
      open: false,
      port: 9000,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },

    framework: {
      config: {
        notify: {
          position: 'top-right',
          timeout: 3000,
        },
      },
      iconSet: 'material-icons',
      lang: 'de',
      plugins: [
        'Notify',
        'Dialog',
        'Loading',
        'LocalStorage',
      ],
    },

    animations: [],

    pwa: {
      workboxMode: 'GenerateSW',
      injectPwaMetaTags: true,
      swFilename: 'sw.js',
      manifestFilename: 'manifest.json',
      useCredentialsForManifestTag: false,
    },
  }
})
