<template>
  <div>
    <div class="row items-center q-mb-md q-gutter-sm">
      <q-btn unelevated color="primary" icon="add" label="Rechnung einreichen"
        @click="neu" />
      <q-space />
      <q-select v-model="statusFilter" :options="STATUS_FILTER_OPTIONEN" emit-value
        map-options dense outlined label="Status" style="min-width:160px"
        @update:model-value="load" />
    </div>

    <div v-if="loading" class="text-center q-py-lg"><q-spinner size="2em" color="primary" /></div>

    <div v-else-if="rechnungen.length === 0" class="text-grey text-center q-py-lg">
      <q-icon name="receipt_long" size="42px" class="q-mb-sm" />
      <div>Noch keine Rechnungen eingereicht.</div>
    </div>

    <q-list v-else bordered separator>
      <q-item v-for="r in rechnungen" :key="r.id" clickable @click="oeffne(r)">
        <q-item-section>
          <q-item-label>
            {{ r.kategorie_name }}
            <span v-if="r.abteilung_name" class="text-grey-7">· {{ r.abteilung_name }}</span>
          </q-item-label>
          <q-item-label caption>
            <q-chip dense size="sm" :color="statusChip(r.status).color" text-color="white">
              {{ statusChip(r.status).label }}
            </q-chip>
            <span v-if="r.betrag_cent != null" class="q-mr-xs">{{ fmtBetrag(r.betrag_cent) }}</span>
            <span>· {{ empfaengerText(r) }}</span>
            <span v-if="r.beschreibung">· {{ r.beschreibung }}</span>
            <span v-if="r.anhang_count" class="q-ml-xs">
              <q-icon name="attach_file" size="xs" />{{ r.anhang_count }}
            </span>
          </q-item-label>
          <q-item-label v-if="r.status === 'abgelehnt' && r.abgelehnt_grund"
            caption class="text-negative">
            <q-icon name="error" size="xs" /> {{ r.abgelehnt_grund }}
          </q-item-label>
        </q-item-section>
        <q-item-section side><q-icon name="chevron_right" color="grey-6" /></q-item-section>
      </q-item>
    </q-list>

    <!-- Anlegen / Detail -->
    <q-dialog v-model="dialogOpen" persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm
        ? 'width:100%;border-radius:16px 16px 0 0'
        : 'min-width:520px;max-width:640px'">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ aktuell?.id ? `Rechnung #${aktuell.id}` : 'Rechnung einreichen' }}</div>
          <q-space />
          <q-chip v-if="aktuell?.id" dense :color="statusChip(aktuell.status).color"
            text-color="white">{{ statusChip(aktuell.status).label }}</q-chip>
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>

        <q-card-section class="q-pt-none">
          <!-- Pflicht: Kategorie. Alles andere macht die Buchhaltung. -->
          <q-select v-model="form.kategorie_id" :options="kategorien" option-value="id"
            option-label="name" emit-value map-options outlined dense
            label="Kategorie *" :disable="!istEntwurf" class="q-mb-sm" />

          <!-- Abteilung nur zeigen, wenn es überhaupt etwas zu wählen gibt -->
          <q-select v-if="abteilungen.length > 1" v-model="form.abteilung_id"
            :options="abteilungsOptionen" option-value="id" option-label="name"
            emit-value map-options outlined dense label="Abteilung"
            :disable="!istEntwurf" class="q-mb-sm" />
          <div v-else-if="abteilungen.length === 1" class="text-caption text-grey q-mb-sm">
            Abteilung: {{ abteilungen[0].name }}
          </div>
          <div v-else class="text-caption text-grey q-mb-sm">
            Ohne Abteilung – die Geschäftsstelle gibt diese Rechnung frei.
          </div>

          <q-input v-model="form.beschreibung" outlined dense label="Wofür? (optional)"
            :disable="!istEntwurf" class="q-mb-sm" />

          <!-- Kernfrage der Freigabe: an wen fließt das Geld? -->
          <div class="text-caption text-grey-7">An wen wird gezahlt? *</div>
          <q-option-group v-model="form.empfaenger_typ" :options="EMPFAENGER_OPTIONEN"
            color="primary" dense :disable="!istEntwurf" class="q-mb-xs" />
          <q-input v-if="form.empfaenger_typ === 'extern'" v-model="form.empfaenger_name"
            outlined dense label="Rechnungsaussteller *" :disable="!istEntwurf"
            class="q-mb-sm" />

          <q-expansion-item dense-toggle label="Zusatzangaben (optional)"
            header-class="text-grey-7" class="q-mb-sm">
            <div class="q-pt-sm q-gutter-sm">
              <q-input v-model="form.betrag" outlined dense label="Betrag (€)"
                inputmode="decimal" :disable="!istEntwurf" />
              <q-input v-model="form.rechnungsdatum" outlined dense type="date"
                label="Rechnungsdatum" stack-label :disable="!istEntwurf" />
              <q-input v-model="form.rechnungsnummer" outlined dense
                label="Rechnungsnummer" :disable="!istEntwurf" />
              <!-- Bei Erstattung an ein Mitglied kommt die IBAN aus dem
                   Mitgliedsstamm – hier nur für externe Aussteller nötig. -->
              <q-input v-if="form.empfaenger_typ === 'extern'" v-model="form.empfaenger_iban"
                outlined dense label="IBAN des Ausstellers" :disable="!istEntwurf" />
            </div>
          </q-expansion-item>

          <div class="text-caption text-grey-7 q-mb-xs">Beleg *</div>

          <!-- Bestehende Rechnung: Upload läuft direkt gegen die ID. -->
          <AnhangPanel v-if="aktuell?.id" :anhaenge="anhaenge"
            :upload-url="`/api/rechnungen/${aktuell.id}/anhaenge`"
            :can-upload="istEntwurf" :can-delete="istEntwurf"
            @uploaded="onUploaded" @deleted="onDeleted" />

          <!-- Neue Rechnung: Datei bis zum Klick vorhalten, damit Anlegen,
               Hochladen und Einreichen ein einziger Schritt bleiben. -->
          <div v-else>
            <q-list v-if="neueDateien.length" bordered separator class="q-mb-sm">
              <q-item v-for="(d, i) in neueDateien" :key="i" dense>
                <q-item-section avatar>
                  <q-icon :name="d.type === 'application/pdf' ? 'picture_as_pdf' : 'image'"
                    :color="d.type === 'application/pdf' ? 'negative' : 'primary'" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ d.name }}</q-item-label>
                  <q-item-label caption>{{ (d.size / 1024).toFixed(0) }} KB</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-btn flat dense round icon="delete" color="negative" size="sm"
                    @click="neueDateien.splice(i, 1)" />
                </q-item-section>
              </q-item>
            </q-list>
            <input ref="dateiInput" type="file" multiple :accept="BELEG_ACCEPT"
              style="display: none" @change="dateienGewaehlt" />
            <q-btn outline color="primary" icon="attach_file" label="Beleg wählen"
              size="sm" @click="dateiInput.click()" />
            <span class="text-caption text-grey q-ml-sm">{{ BELEG_HINWEIS }}</span>
          </div>

          <div v-if="error" class="text-negative text-caption q-mt-sm">{{ error }}</div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn v-if="aktuell?.id && istEntwurf" flat color="negative" label="Löschen"
            :loading="busy" @click="loeschen" />
          <q-space />
          <q-btn v-if="istEntwurf" flat color="primary" label="Als Entwurf speichern"
            :loading="busy" @click="speichern" />
          <q-btn v-if="istEntwurf" unelevated color="primary" label="Einreichen"
            :loading="busy" :disable="!kannEinreichen" @click="einreichen" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useRoute } from 'vue-router'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'
import AnhangPanel from 'components/AnhangPanel.vue'
import {
  STATUS_FILTER_OPTIONEN, statusChip, fmtBetrag, parseBetrag, fehlertext,
  BELEG_ACCEPT, BELEG_HINWEIS, belegFehler, EMPFAENGER_OPTIONEN, empfaengerText,
} from 'src/composables/useRechnungen'

defineOptions({ name: 'RechnungenMeinePage' })

const $q = useQuasar()
const route = useRoute()

const rechnungen = ref([])
const kategorien = ref([])
const abteilungen = ref([])
const statusFilter = ref('')
const loading = ref(true)

const dialogOpen = ref(false)
const aktuell = ref(null)
const anhaenge = ref([])
const busy = ref(false)
const error = ref('')

// Belege einer noch nicht angelegten Rechnung – werden erst beim Einreichen
// (bzw. beim Speichern) hochgeladen, sobald es eine ID gibt.
const neueDateien = ref([])
const dateiInput = ref(null)

const form = ref(leeresFormular())

const istEntwurf = computed(() => !aktuell.value?.id || aktuell.value.status === 'entwurf')
// Einreichen braucht Kategorie, Empfänger und mindestens einen Beleg – egal ob
// der schon hochgeladen ist oder noch im Dialog wartet.
const kannEinreichen = computed(() =>
  !!form.value.kategorie_id
  && (form.value.empfaenger_typ !== 'extern' || !!form.value.empfaenger_name?.trim())
  && (aktuell.value?.id ? anhaenge.value.length > 0 : neueDateien.value.length > 0),
)
// „Keine Abteilung" muss wählbar bleiben: Vereinsrechnungen gehen an die Geschäftsstelle.
const abteilungsOptionen = computed(() => [
  { id: null, name: 'Ohne Abteilung (Verein)' }, ...abteilungen.value,
])

function leeresFormular() {
  return {
    kategorie_id: null,
    abteilung_id: null,
    beschreibung: '',
    // Häufigster Fall: jemand hat ausgelegt und will es zurück. Bewusst
    // vorbelegt, damit der Regelfall ein Klick weniger ist – umschaltbar.
    empfaenger_typ: 'mitglied',
    empfaenger_name: '',
    empfaenger_iban: '',
    betrag: '',
    rechnungsdatum: '',
    rechnungsnummer: '',
  }
}

async function load() {
  const params = statusFilter.value ? { status: statusFilter.value } : {}
  const { data } = await api.get('/api/rechnungen', { params: { sicht: 'mine', ...params } })
  rechnungen.value = data
}

async function ladeStammdaten() {
  const [k, a] = await Promise.all([
    api.get('/api/rechnungen/kategorien'),
    api.get('/api/rechnungen/meine-abteilungen'),
  ])
  kategorien.value = k.data
  abteilungen.value = a.data
}

function neu() {
  aktuell.value = null
  anhaenge.value = []
  neueDateien.value = []
  error.value = ''
  form.value = leeresFormular()
  // Genau eine Abteilung → ohne Auswahlfeld vorbelegen.
  if (abteilungen.value.length === 1) form.value.abteilung_id = abteilungen.value[0].id
  dialogOpen.value = true
}

function dateienGewaehlt(ereignis) {
  for (const datei of ereignis.target.files) {
    const meldung = belegFehler(datei)
    if (meldung) {
      $q.notify({ type: 'warning', message: meldung })
      continue
    }
    neueDateien.value.push(datei)
  }
  ereignis.target.value = ''   // dieselbe Datei erneut wählbar machen
  error.value = ''
}

async function oeffne(r) {
  error.value = ''
  aktuell.value = r
  neueDateien.value = []
  form.value = {
    kategorie_id: r.kategorie_id,
    abteilung_id: r.abteilung_id,
    beschreibung: r.beschreibung || '',
    empfaenger_typ: r.empfaenger_typ || 'mitglied',
    empfaenger_name: r.empfaenger_name || '',
    empfaenger_iban: r.empfaenger_iban || '',
    betrag: r.betrag_cent != null ? String(r.betrag_cent / 100).replace('.', ',') : '',
    rechnungsdatum: r.rechnungsdatum || '',
    rechnungsnummer: r.rechnungsnummer || '',
  }
  dialogOpen.value = true
  const { data } = await api.get(`/api/rechnungen/${r.id}/anhaenge`)
  anhaenge.value = data
}

function nutzlast() {
  const extern = form.value.empfaenger_typ === 'extern'
  return {
    kategorie_id: form.value.kategorie_id,
    abteilung_id: form.value.abteilung_id,
    beschreibung: form.value.beschreibung || null,
    // Bei Erstattung setzt das Backend das Mitglied aus dem Einreicher; Name und
    // IBAN gehören dann nicht an die Rechnung (stehen im Mitgliedsstamm).
    empfaenger_typ: form.value.empfaenger_typ,
    empfaenger_name: extern ? (form.value.empfaenger_name || null) : null,
    empfaenger_iban: extern ? (form.value.empfaenger_iban || null) : null,
    betrag_cent: parseBetrag(form.value.betrag),
    rechnungsdatum: form.value.rechnungsdatum || null,
    rechnungsnummer: form.value.rechnungsnummer || null,
  }
}

/** Legt die Rechnung an bzw. aktualisiert sie und lädt vorgehaltene Belege hoch.
 *
 * Bricht ein Schritt ab, bleibt das bereits Erreichte bestehen: der Dialog zeigt
 * dann die angelegte Rechnung samt hochgeladener Belege, und der Anwender kann
 * ab der Fehlerstelle weitermachen, statt alles neu einzugeben.
 */
async function sichern() {
  if (aktuell.value?.id) {
    const { data } = await api.patch(`/api/rechnungen/${aktuell.value.id}`,
      { ...nutzlast(), expected_version: aktuell.value.version })
    aktuell.value = data
  } else {
    const { data } = await api.post('/api/rechnungen', nutzlast())
    aktuell.value = data
    anhaenge.value = []
  }
  while (neueDateien.value.length) {
    const datei = neueDateien.value[0]
    const formular = new FormData()
    formular.append('file', datei)
    const { data } = await api.post(
      `/api/rechnungen/${aktuell.value.id}/anhaenge`, formular,
      { headers: { 'Content-Type': 'multipart/form-data' } })
    anhaenge.value.push(data)
    neueDateien.value.shift()   // erst nach Erfolg entfernen
  }
}

async function speichern() {
  if (!form.value.kategorie_id) {
    error.value = 'Bitte eine Kategorie wählen.'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await sichern()
    $q.notify({ type: 'positive', message: 'Als Entwurf gespeichert' })
    dialogOpen.value = false
    await load()
  } catch (e) {
    error.value = fehlertext(e, 'Speichern fehlgeschlagen')
    await load()
  } finally {
    busy.value = false
  }
}

async function einreichen() {
  if (!form.value.kategorie_id) {
    error.value = 'Bitte eine Kategorie wählen.'
    return
  }
  busy.value = true
  error.value = ''
  try {
    // Anlegen, Beleg hochladen und einreichen in einem Rutsch – der Anwender
    // soll den Dialog nur einmal ausfüllen und einmal klicken.
    await sichern()
    await api.post(`/api/rechnungen/${aktuell.value.id}/einreichen`)
    $q.notify({ type: 'positive', message: 'Eingereicht – die Freigabe wurde informiert.' })
    dialogOpen.value = false
    await load()
  } catch (e) {
    error.value = fehlertext(e, 'Einreichen fehlgeschlagen')
    await load()
  } finally {
    busy.value = false
  }
}

function loeschen() {
  $q.dialog({
    title: 'Rechnung löschen',
    message: 'Den Entwurf samt Beleg in den Papierkorb legen?',
    cancel: true,
    ok: { label: 'Löschen', color: 'negative' },
  }).onOk(async () => {
    busy.value = true
    try {
      await api.delete(`/api/rechnungen/${aktuell.value.id}`)
      dialogOpen.value = false
      await load()
    } catch (e) {
      error.value = fehlertext(e, 'Löschen fehlgeschlagen')
    } finally {
      busy.value = false
    }
  })
}

function onUploaded(anhang) {
  anhaenge.value = [...anhaenge.value, anhang]
  load()
}
function onDeleted(id) {
  anhaenge.value = anhaenge.value.filter((a) => a.id !== id)
  load()
}

usePageRefresh(load)
onMounted(async () => {
  try {
    await Promise.all([ladeStammdaten(), load()])
    // Deep-Link aus der Benachrichtigung: /rechnungen?rechnung=42
    const id = Number(route.query.rechnung)
    const treffer = id && rechnungen.value.find((r) => r.id === id)
    if (treffer) await oeffne(treffer)
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
})
</script>
