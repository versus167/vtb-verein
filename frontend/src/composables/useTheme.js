// Erscheinungsbild der App (#131): drei Themes statt nur hell/dunkel.
//
//   vtb     Vereinsfarben als Fläche — Gelb als Seitengrund, Wappenblau für
//           Karten und Tabellen (der bisherige Hellmodus, unverändert)
//   hell    neutrale Arbeitsfläche — weiße Karten auf hellem Grau, dunkle
//           Schrift; blau-gelb nur noch als Akzent (Kopfzeile, Aktivmarken)
//   dunkel  Navy (der bisherige Dark Mode, unverändert)
//
// Quasar kennt nur den Schalter hell/dunkel. Das Theme steht deshalb zusätzlich
// als Klasse `vtb-theme--<name>` am <body>; die Stylesheets hängen daran. Für
// den Dark Mode bleiben die Regeln auf Quasars `body--dark` — die Klasse setzt
// Quasar selbst, sie kann nicht mit unserer auseinanderlaufen.
//
// Die Wahl gilt pro Gerät (localStorage): Handy abends dunkel, Desktop hell.
import { Dark } from 'quasar'
import { computed, ref } from 'vue'

const SCHLUESSEL = 'vtbTheme'
const SCHLUESSEL_ALT = 'darkMode' // vor #131: 'true' | 'false' | 'auto'

// Reihenfolge = Reihenfolge im Menü.
export const THEME_AUSWAHL = [
  { wert: 'vtb', label: 'VTB', icon: 'palette' },
  { wert: 'hell', label: 'Hell', icon: 'light_mode' },
  { wert: 'dunkel', label: 'Dunkel', icon: 'dark_mode' },
  { wert: 'auto', label: 'Automatisch', icon: 'brightness_auto' },
]

const ERLAUBT = new Set(THEME_AUSWAHL.map((t) => t.wert))

// Was der Nutzer gewählt hat — inkl. 'auto'.
const wahl = ref('vtb')

// Was tatsächlich angezeigt wird. Bei 'auto' entscheidet die Systemeinstellung:
// dunkel → 'dunkel', sonst 'vtb'. Damit ändert sich für niemanden etwas, der
// bisher auf „Automatisch" stand; wer es neutral will, wählt „Hell" bewusst.
export const aktivesTheme = computed(() =>
  wahl.value === 'auto' ? (Dark.isActive ? 'dunkel' : 'vtb') : wahl.value,
)

export const themeWahl = computed(() => wahl.value)

export const themeIcon = computed(
  () => THEME_AUSWAHL.find((t) => t.wert === wahl.value)?.icon || 'palette',
)

export const themeLabel = computed(
  () => THEME_AUSWAHL.find((t) => t.wert === wahl.value)?.label || 'VTB',
)

// Gespeicherte Wahl lesen — inklusive Übernahme der alten Dark-Mode-Einstellung.
function gespeicherteWahl() {
  const neu = localStorage.getItem(SCHLUESSEL)
  if (neu && ERLAUBT.has(neu)) return neu

  const alt = localStorage.getItem(SCHLUESSEL_ALT)
  if (alt === 'true') return 'dunkel'
  if (alt === 'false') return 'vtb' // der alte Hellmodus war der VTB-Look
  if (alt === 'auto') return 'auto'
  return 'vtb'
}

// Body-Klasse nachziehen. Bei 'auto' hängt das Ergebnis am System, deshalb nach
// jedem Wechsel von Dark erneut aufrufen (Quasar meldet Systemwechsel über
// seinen Media-Listener, der `Dark.set('auto')` erneut auslöst).
function klasseSetzen() {
  const klassen = document.body.classList
  for (const t of THEME_AUSWAHL) {
    if (t.wert !== 'auto') klassen.remove(`vtb-theme--${t.wert}`)
  }
  klassen.add(`vtb-theme--${aktivesTheme.value}`)
}

export function setTheme(wert) {
  if (!ERLAUBT.has(wert)) return
  wahl.value = wert
  localStorage.setItem(SCHLUESSEL, wert)
  Dark.set(wert === 'auto' ? 'auto' : wert === 'dunkel')
  klasseSetzen()
}

// Die Farbe der Browser-Leiste (Handy) trägt in der index.html den VTB-Wert.
// Sie muss der Akzentfarbe dieser Instanz folgen, sonst rahmt ein fremder Verein
// seine App in Vereinsgelb. Der Wert kommt aus derselben Custom Property, die
// das Backend ausliefert — steht keine da, bleibt der Wert aus dem Dokument.
function browserleisteFaerben() {
  const akzent = getComputedStyle(document.documentElement)
    .getPropertyValue('--vtb-akzent')
    .trim()
  if (!akzent) return
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', akzent)
}

// Beim Start: gespeicherte Wahl anwenden und auf Systemwechsel horchen. Quasars
// eigener Listener setzt nur `body--dark` um — die Theme-Klasse müssen wir
// selbst nachziehen, sonst bliebe bei 'auto' die alte am Body stehen.
export function initTheme() {
  setTheme(gespeicherteWahl())
  browserleisteFaerben()
  window
    .matchMedia('(prefers-color-scheme: dark)')
    .addEventListener('change', () => {
      if (wahl.value === 'auto') klasseSetzen()
    })
}
