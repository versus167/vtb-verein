<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-h5">Zugänge</div>
      <q-space />
      <q-chip dense outline color="primary"
        :label="`${mitZugang} von ${imBlick.length} freigeschaltet`" />
    </div>

    <div class="text-caption text-grey q-mb-md">
      Hier bekommen Mitglieder ihren Login für die App. Freigeschaltet wird einzeln:
      Person suchen, Mailadresse wählen, fertig – die Anmelde-Mail geht sofort raus.
      Ein Passwort ist nicht nötig, das setzt sich jede/r nach dem ersten Login selbst.
      Pro Mailadresse ist ein Zugang möglich; bei einer Familienadresse entscheidet
      die Familie, wer sie nutzt.
    </div>

    <div class="row q-col-gutter-sm q-mb-md">
      <div class="col-12 col-sm">
        <q-input
          v-model="suche" outlined dense clearable debounce="200"
          label="Name suchen" autofocus
        >
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div v-if="mannschaftOptionen.length" class="col-12 col-sm-auto">
        <q-select
          v-model="mannschaftFilter" :options="mannschaftOptionen"
          option-value="id" option-label="label" emit-value map-options
          label="Mannschaft" outlined dense clearable
          style="min-width: 200px"
        >
          <template #prepend><q-icon name="groups" /></template>
        </q-select>
      </div>
      <div class="col-12 col-sm-auto">
        <q-btn-toggle
          v-model="filter" unelevated dense no-caps toggle-color="primary"
          :options="[
            { label: 'Ohne Zugang', value: 'ohne' },
            { label: 'Mit Zugang', value: 'mit' },
            { label: 'Alle', value: 'alle' },
          ]"
        />
      </div>
    </div>

    <q-list bordered separator>
      <q-item v-for="z in sichtbar" :key="z.mitglied_id" clickable @click="oeffne(z)">
        <q-item-section avatar>
          <q-icon :name="statusIcon(z)" :color="statusFarbe(z)" />
        </q-item-section>
        <q-item-section>
          <q-item-label>
            {{ z.nachname }}, {{ z.vorname }}
            <span v-if="z.geburtsjahr" class="text-grey"> · {{ z.geburtsjahr }}</span>
          </q-item-label>
          <q-item-label caption lines="2">
            <span v-if="z.abteilungen">{{ z.abteilungen }}</span>
            <span v-else class="text-grey">keine Abteilung</span>
            <template v-if="z.user_id && !z.zugang_geloescht">
              · {{ z.email }}
              <span v-if="!z.active"> · deaktiviert</span>
              <span v-else-if="!z.last_login && z.einladung_status === 'fehler'" class="text-negative">
                · Einladung nicht versendet</span>
            </template>
            <template v-else-if="z.zugang_geloescht">
              · Konto im Papierkorb
            </template>
            <template v-else-if="!z.mails.length">
              · keine Mailadresse hinterlegt
            </template>
          </q-item-label>
          <q-item-label v-if="z.mannschaften?.length" caption lines="1">
            <q-icon name="groups" size="14px" class="q-mr-xs" />{{ kaderText(z) }}
          </q-item-label>
          <!-- Login ≠ Aktivität: „angemeldet" ist der letzte echte Login, „aktiv"
               der letzte Request. Beim Rollout ist genau das die Frage – hat die
               Person den Zugang je benutzt, und benutzt sie ihn noch? -->
          <q-item-label v-if="z.user_id && !z.zugang_geloescht" caption lines="1">
            <span v-if="z.last_login">
              zuletzt angemeldet {{ formatRelative(z.last_login) }}
              <q-tooltip>{{ formatDateTime(z.last_login) }}</q-tooltip>
            </span>
            <span v-else>noch nicht angemeldet</span>
            <span v-if="z.last_seen">
              · aktiv {{ formatRelative(z.last_seen) }}
              <q-tooltip>{{ formatDateTime(z.last_seen) }}</q-tooltip>
            </span>
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-icon name="chevron_right" color="grey-6" />
        </q-item-section>
      </q-item>

      <q-item v-if="!sichtbar.length && !loading">
        <q-item-section class="text-grey text-center q-py-md">
          {{ suche ? 'Kein Treffer.' : 'Keine Mitglieder in dieser Ansicht.' }}
        </q-item-section>
      </q-item>
    </q-list>

    <div v-if="gefiltert.length > sichtbar.length" class="text-caption text-grey q-mt-sm text-center">
      {{ gefiltert.length - sichtbar.length }} weitere Treffer – bitte die Suche eingrenzen.
    </div>

    <q-dialog v-model="dialogOpen">
      <q-card class="vtb-dialog-karte" style="--vtb-dialog-breite: 340px; max-width: 92vw">
        <!-- no-wrap + col: Ein langer Name soll innerhalb seiner Spalte umbrechen.
             Ohne das rutscht das Schließkreuz unter die Überschrift, statt oben
             rechts zu bleiben (#177). -->
        <q-card-section class="row items-start no-wrap">
          <div class="text-h6 col">{{ aktuell?.vorname }} {{ aktuell?.nachname }}</div>
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>

        <!-- Noch kein Zugang: freischalten -->
        <template v-if="aktuell && !aktuell.user_id">
          <q-card-section class="q-pt-none q-gutter-sm">
            <MailAuswahl v-model="mail" :adressen="mailOptionen"
              label="Mailadresse für den Zugang"
              hint="Für diese Person ist noch keine Adresse hinterlegt – bitte eintippen." />
            <q-banner v-if="belegtVon" dense class="bg-orange-1 text-orange-10 rounded-borders">
              <template #avatar><q-icon name="warning" color="orange-9" /></template>
              Diese Adresse gehört bereits zum Zugang von „{{ belegtVon }}“.
              Pro Adresse ist ein Zugang möglich.
            </q-banner>
            <div class="text-caption text-grey">
              Angelegt wird ein normaler Mitglieds-Zugang ohne Sonderrechte. An die
              Adresse geht eine Mail mit Anmeldelink (7 Tage gültig).
            </div>
            <div v-if="error" class="text-negative text-caption">{{ error }}</div>
          </q-card-section>
          <q-card-actions
            :align="$q.screen.lt.sm ? undefined : 'right'"
            :class="$q.screen.lt.sm ? 'vtb-btn-reihe vtb-btn-reihe--umgekehrt q-px-md q-pb-md' : ''"
          >
            <q-btn flat label="Abbrechen" v-close-popup />
            <q-btn
              unelevated color="primary" label="Freischalten" icon="how_to_reg"
              :loading="busy" :disable="!mailWert || !!belegtVon" @click="freischalten"
            />
          </q-card-actions>
        </template>

        <!-- Zugang vorhanden -->
        <template v-else-if="aktuell">
          <q-card-section class="q-pt-none">
            <div v-if="aktuell.zugang_geloescht" class="text-body2">
              Das Konto dieser Person liegt im Papierkorb. Wiederherstellen kann es
              nur jemand mit Löschrechten über die Personenverwaltung.
            </div>
            <template v-else>
              <div class="text-body2">
                Benutzername <b>{{ aktuell.username }}</b><br>
                Mailadresse <b>{{ aktuell.email }}</b>
              </div>
              <div class="text-caption text-grey q-mt-sm">
                <div v-if="!aktuell.active">Zugang ist deaktiviert.</div>
                <div v-if="aktuell.last_login">
                  Zuletzt angemeldet {{ formatRelative(aktuell.last_login) }}
                  ({{ formatDateTime(aktuell.last_login) }}).
                </div>
                <div v-else>Noch nie angemeldet.</div>
                <div v-if="aktuell.last_seen">
                  Zuletzt aktiv {{ formatRelative(aktuell.last_seen) }}
                  ({{ formatDateTime(aktuell.last_seen) }}).
                </div>
              </div>

              <!-- Versandstand der letzten Einladung: „abgeschickt" ist alles, was
                   die App wissen kann – ein Bounce landet beim Absender, nicht hier. -->
              <div v-if="aktuell.einladung_status === 'fehler'"
                class="text-caption text-negative q-mt-sm">
                <q-icon name="error_outline" size="16px" class="q-mr-xs" />
                Die Einladung vom {{ formatDateTime(aktuell.einladung_zuletzt) }} konnte nicht
                versendet werden. Adresse prüfen und neu einladen.
              </div>
              <div v-else-if="aktuell.einladung_status === 'ok'"
                class="text-caption text-grey q-mt-sm">
                <q-icon name="mark_email_read" size="16px" class="q-mr-xs" />
                Einladung am {{ formatDateTime(aktuell.einladung_zuletzt) }} abgeschickt
                (ob sie ankam, sieht die App nicht).
              </div>
              <div v-else-if="!aktuell.last_login" class="text-caption text-grey q-mt-sm">
                <q-icon name="help_outline" size="16px" class="q-mr-xs" />
                Zum letzten Versand liegt nichts vor.
              </div>

              <!-- Adresswechsel: nur bei einem Zugang, den noch nie jemand benutzt hat.
                   Ab der ersten Anmeldung hieße eine neue Login-Adresse, das Konto zu
                   übernehmen – das bleibt der Benutzerverwaltung vorbehalten. -->
              <div v-if="darfMailWechseln" class="q-mt-md">
                <q-btn
                  v-if="!mailWechsel" flat dense no-caps size="sm" color="primary"
                  icon="edit" label="Andere Mailadresse"
                  @click="starteMailWechsel"
                />
                <div v-else class="q-gutter-sm">
                  <MailAuswahl v-model="mail" :adressen="mailOptionen"
                    label="Neue Mailadresse" :ausser="aktuell.email" />
                  <q-banner v-if="belegtVon" dense class="bg-orange-1 text-orange-10 rounded-borders">
                    <template #avatar><q-icon name="warning" color="orange-9" /></template>
                    Diese Adresse gehört bereits zum Zugang von „{{ belegtVon }}“.
                    Pro Adresse ist ein Zugang möglich.
                  </q-banner>
                  <div class="text-caption text-grey">
                    An die neue Adresse geht sofort eine Einladung. Der bisher
                    verschickte Anmeldelink wird damit ungültig.
                  </div>
                </div>
              </div>
              <div v-if="error" class="text-negative text-caption q-mt-sm">{{ error }}</div>
            </template>
          </q-card-section>
          <q-card-actions
            v-if="!aktuell.zugang_geloescht"
            :align="$q.screen.lt.sm ? undefined : 'right'"
            :class="$q.screen.lt.sm ? 'vtb-btn-reihe vtb-btn-reihe--umgekehrt q-px-md q-pb-md' : ''"
          >
            <template v-if="mailWechsel">
              <q-btn flat label="Abbrechen" :disable="busy" @click="mailWechsel = false" />
              <q-space />
              <q-btn
                unelevated color="primary" icon="forward_to_inbox"
                label="Ändern & einladen" :loading="busy"
                :disable="!mailWert || !!belegtVon" @click="mailAendern"
              />
            </template>
            <template v-else>
              <q-btn
                v-if="aktuell.active" flat color="negative" label="Deaktivieren"
                :loading="busy" @click="deaktivieren"
              />
              <q-space />
              <q-btn flat label="Schließen" v-close-popup />
              <q-btn
                v-if="aktuell.active" unelevated color="primary" icon="mail"
                label="Einladung senden" :loading="busy" @click="einladen"
              />
            </template>
          </q-card-actions>
        </template>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'
import { formatDateTime, formatRelative } from 'src/utils/datetime'
import MailAuswahl from 'components/MailAuswahl.vue'

defineOptions({ name: 'ZugaengePage' })

const $q = useQuasar()

// Die Liste ist vereinsweit (mehrere hundert Zeilen), aber pro Zeile schmal –
// deshalb einmal laden und im Browser filtern statt pro Tastendruck nachzufragen.
const zeilen = ref([])
const loading = ref(false)
const suche = ref('')
const filter = ref('ohne')
const mannschaftFilter = ref(null)
const dialogOpen = ref(false)
const aktuell = ref(null)
const mail = ref(null)
const mailWechsel = ref(false)
const busy = ref(false)
const error = ref('')

// Deckel gegen eine 600-Zeilen-Liste am Handy; wer jemanden sucht, tippt ohnehin.
const MAX_TREFFER = 60

// Auswahl aus den geladenen Zeilen ableiten statt aus /api/mannschaften/: So
// erscheinen nur Mannschaften, in denen wirklich jemand aus dem eigenen Bereich
// steht – der Abteilungs-Scope der Liste gilt damit automatisch auch hier.
const mannschaftOptionen = computed(() => {
  const nachId = new Map()
  const namensZaehler = new Map()
  for (const z of zeilen.value) {
    for (const m of z.mannschaften || []) {
      if (nachId.has(m.id)) continue
      nachId.set(m.id, m)
      namensZaehler.set(m.name, (namensZaehler.get(m.name) || 0) + 1)
    }
  }
  // Mannschaftsnamen sind nur je Abteilung eindeutig („1. Mannschaft" gibt es
  // mehrfach) – bei Dubletten die Abteilung dazuschreiben, sonst nicht.
  return [...nachId.values()]
    .map((m) => ({
      id: m.id,
      label: namensZaehler.get(m.name) > 1 && m.abteilung
        ? `${m.name} · ${m.abteilung}` : m.name,
    }))
    .sort((a, b) => a.label.localeCompare(b.label, 'de'))
})

// Bezugsgröße für den Zähler oben: bei gewählter Mannschaft deren Kader, sonst
// der ganze Verein. „12 von 18 freigeschaltet" ist beim Rollout die Zahl, die zählt.
const imBlick = computed(() => (mannschaftFilter.value == null
  ? zeilen.value
  : zeilen.value.filter((z) => imKader(z))))

const mitZugang = computed(
  () => imBlick.value.filter((z) => z.user_id && !z.zugang_geloescht).length,
)

function imKader(z) {
  return (z.mannschaften || []).some((m) => m.id === mannschaftFilter.value)
}

const kaderText = (z) => (z.mannschaften || []).map((m) => m.name).join(', ')

const gefiltert = computed(() => {
  const q = (suche.value || '').trim().toLowerCase()
  return imBlick.value.filter((z) => {
    const hatZugang = !!z.user_id && !z.zugang_geloescht
    if (filter.value === 'ohne' && hatZugang) return false
    if (filter.value === 'mit' && !hatZugang) return false
    if (!q) return true
    return `${z.vorname} ${z.nachname}`.toLowerCase().includes(q)
      || `${z.nachname} ${z.vorname}`.toLowerCase().includes(q)
  })
})

const sichtbar = computed(() => gefiltert.value.slice(0, MAX_TREFFER))

const mailOptionen = computed(() => aktuell.value?.mails || [])

// Eingetipptes kommt mit Rändern (Handy-Tastaturen hängen gern ein Leerzeichen an).
// Einmal getrimmt an einer Stelle – daran hängen Prüfung, Knopf und Versand.
const mailWert = computed(() => String(mail.value || '').trim())

// Warnung schon vor dem Absenden: dieselbe Adresse kann nur ein Konto tragen.
const belegtVon = computed(() => {
  if (!mailWert.value) return null
  const treffer = (aktuell.value?.mails || [])
    .find((m) => m.wert.toLowerCase() === mailWert.value.toLowerCase())
  return treffer?.belegt_von || null
})

// Adresswechsel nur, solange der Zugang unbenutzt ist: Ab der ersten Anmeldung
// gehört das Konto jemandem, und eine neue Login-Adresse wäre eine Übernahme.
// Das Backend prüft dieselbe Bedingung – hier geht es nur um die Anzeige.
const darfMailWechseln = computed(() => !!aktuell.value?.user_id
  && !aktuell.value.zugang_geloescht
  && aktuell.value.active
  && !aktuell.value.last_login)

function statusIcon(z) {
  if (z.zugang_geloescht) return 'delete_outline'
  if (!z.user_id) return z.mails.length ? 'person_outline' : 'no_accounts'
  if (!z.active) return 'block'
  if (!z.last_login && z.einladung_status === 'fehler') return 'unsubscribe'
  return z.last_login ? 'how_to_reg' : 'mark_email_read'
}

function statusFarbe(z) {
  if (z.zugang_geloescht || !z.user_id) return 'grey-6'
  if (!z.active) return 'negative'
  if (!z.last_login && z.einladung_status === 'fehler') return 'negative'
  return z.last_login ? 'positive' : 'primary'
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/api/personen/freischaltung')
    zeilen.value = data
  } finally {
    loading.value = false
  }
}

// Nach einem Neuladen zeigt der offene Dialog sonst den Stand von vorhin – nach
// einem fehlgeschlagenen Versand wäre das genau die Auskunft, die man nicht braucht.
function aktualisiereAktuell() {
  if (!aktuell.value) return
  const frisch = zeilen.value.find((z) => z.mitglied_id === aktuell.value.mitglied_id)
  if (frisch) aktuell.value = frisch
}

function oeffne(z) {
  aktuell.value = z
  error.value = ''
  mailWechsel.value = false
  // Primäre Adresse vorbelegen, aber nur wenn sie noch frei ist.
  const frei = (z.mails || []).find((m) => !m.belegt_von)
  mail.value = z.user_id ? null : (frei?.wert || null)
  dialogOpen.value = true
}

async function freischalten() {
  busy.value = true
  error.value = ''
  try {
    await api.post(`/api/personen/mitglied/${aktuell.value.mitglied_id}/zugang`,
      { email: mailWert.value })
    dialogOpen.value = false
    $q.notify({ type: 'positive', message: 'Zugang freigeschaltet, Anmelde-Mail ist unterwegs.' })
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Freischalten fehlgeschlagen'
  } finally {
    busy.value = false
  }
}

async function einladen() {
  busy.value = true
  error.value = ''
  try {
    await api.post(`/api/personen/mitglied/${aktuell.value.mitglied_id}/zugang/einladung`)
    dialogOpen.value = false
    $q.notify({ type: 'positive', message: 'Einladung wurde erneut versendet.' })
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Versand fehlgeschlagen'
    // Der gescheiterte Versand steht jetzt am Konto – im offenen Dialog zeigen.
    await load()
    aktualisiereAktuell()
  } finally {
    busy.value = false
  }
}

function starteMailWechsel() {
  // Nicht mit der bisherigen Adresse vorbelegen: Die ist ja gerade der Grund für den
  // Wechsel. Eine andere hinterlegte Adresse, die noch frei ist, ist der bessere Start.
  const frei = (aktuell.value.mails || [])
    .find((m) => !m.belegt_von && m.wert.toLowerCase() !== (aktuell.value.email || '').toLowerCase())
  mail.value = frei?.wert || null
  error.value = ''
  mailWechsel.value = true
}

async function mailAendern() {
  busy.value = true
  error.value = ''
  try {
    await api.put(`/api/personen/mitglied/${aktuell.value.mitglied_id}/zugang/mailadresse`,
      { email: mailWert.value })
    dialogOpen.value = false
    mailWechsel.value = false
    $q.notify({ type: 'positive',
      message: 'Adresse geändert, neue Einladung ist unterwegs. Der alte Link gilt nicht mehr.' })
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Ändern fehlgeschlagen'
    // Bei 502 ist die Adresse geändert, nur der Versand hat gehakt – die Liste
    // und der offene Dialog müssen den neuen Stand trotzdem zeigen.
    await load()
    aktualisiereAktuell()
  } finally {
    busy.value = false
  }
}

function deaktivieren() {
  const name = `${aktuell.value.vorname} ${aktuell.value.nachname}`
  $q.dialog({
    title: 'Zugang deaktivieren',
    message: `Zugang von ${name} abschalten? Die Anmeldung ist danach nicht mehr `
      + 'möglich. Gelöscht wird nichts – das Konto lässt sich später wieder aktivieren.',
    cancel: true,
    ok: { label: 'Deaktivieren', color: 'negative' },
  }).onOk(async () => {
    busy.value = true
    error.value = ''
    try {
      await api.post(`/api/personen/mitglied/${aktuell.value.mitglied_id}/zugang/deaktivieren`)
      dialogOpen.value = false
      $q.notify({ type: 'positive', message: 'Zugang deaktiviert.' })
      await load()
    } catch (e) {
      error.value = e.response?.data?.detail || 'Deaktivieren fehlgeschlagen'
    } finally {
      busy.value = false
    }
  })
}

usePageRefresh(load)
onMounted(async () => {
  try { await load() } catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})
</script>
