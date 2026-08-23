<template>
  <div>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-subtitle1">Übergabe an die Buchhaltung</div>
      <q-space />
      <q-btn unelevated color="primary" icon="download"
        :label="`Export starten (${vorschau.anzahl})`"
        :disable="vorschau.anzahl === 0 || vorschau.fehler.length > 0"
        :loading="busy" @click="exportieren" />
    </div>

    <!-- Konten fehlen: Der Lauf würde abbrechen, also gar nicht erst anbieten.
         Rot und über den Hinweisen, weil es hier nicht um eine Warnung geht,
         sondern um die Bedingung dafür, dass überhaupt exportiert werden kann. -->
    <q-banner v-if="vorschau.fehler.length" dense class="bg-red-1 q-mb-md">
      <template #avatar><q-icon name="error" color="negative" /></template>
      <div class="text-weight-medium text-negative">
        Export nicht möglich – Konten unvollständig konfiguriert.
      </div>
      <div v-for="(f, i) in vorschau.fehler" :key="i" class="text-caption">{{ f }}</div>
      <div class="text-caption q-mt-xs">
        Zu setzen unter <b>Finanzen → Fibu-Export → Einstellungen</b> bzw. je Kategorie
        unter <b>Rechnungen → Kategorien</b>.
      </div>
    </q-banner>

    <q-banner v-if="vorschau.hinweise.length" dense class="bg-orange-1 q-mb-md">
      <template #avatar><q-icon name="warning" color="orange" /></template>
      <div v-for="(h, i) in vorschau.hinweise" :key="i" class="text-caption">{{ h }}</div>
    </q-banner>

    <!-- Was im Zip zu erwarten ist – die Dateinamen tragen die Angaben mit,
         damit man einen Beleg auch ohne Liste seiner Buchungszeile zuordnen kann. -->
    <div class="text-caption text-grey-7 q-mb-md">
      Das Zip enthält <code>fbasc.hia</code> (die Buchungszeilen für die Fibu) und
      je Beleg eine Datei. Jede Rechnung wird als Kreditor-Buchung übergeben:
      Aufwandskonto der Kategorie im Soll gegen den Empfänger im Haben. Die
      Dateinamen tragen die Angaben mit:
      <code>Nr - Zahlung an - Abteilung - Kategorie - Notiz - Originalname</code>
    </div>

    <!-- Was der nächste Lauf mitnimmt -->
    <q-card flat bordered class="q-mb-lg">
      <q-card-section class="q-pb-none">
        <div class="text-subtitle2">
          Offen: {{ vorschau.anzahl }} Rechnung(en)
          <span v-if="vorschau.summe_cent" class="text-grey-7">
            · {{ fmtBetrag(vorschau.summe_cent) }}
          </span>
        </div>
      </q-card-section>
      <q-list separator>
        <q-item v-for="r in vorschau.rechnungen" :key="r.id">
          <q-item-section>
            <q-item-label>
              R{{ r.id }} · {{ r.kategorie_name }}
              <span v-if="r.abteilung_name" class="text-grey-7">· {{ r.abteilung_name }}</span>
            </q-item-label>
            <q-item-label caption>
              <span v-if="r.betrag_cent != null">{{ fmtBetrag(r.betrag_cent) }} · </span>
              freigegeben von {{ r.freigegeben_von }} am {{ fmtDatum(r.freigegeben_am) }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-badge :color="r.anhang_count ? 'primary' : 'negative'">
              {{ r.anhang_count }} Beleg(e)
            </q-badge>
          </q-item-section>
        </q-item>
        <q-item v-if="vorschau.anzahl === 0">
          <q-item-section class="text-grey text-center q-py-md">
            Keine freigegebenen Rechnungen offen.
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>

    <div class="text-subtitle1 q-mb-sm">Bisherige Läufe</div>
    <q-list bordered separator>
      <q-item v-for="(e, i) in exporte" :key="e.id">
        <q-item-section>
          <q-item-label>{{ e.dateiname }}</q-item-label>
          <q-item-label caption>
            {{ fmtDatum(e.exportiert_am) }} · {{ e.anzahl_rechnungen }} Rechnung(en)
            <span v-if="e.summe_cent"> · {{ fmtBetrag(e.summe_cent) }}</span>
            · von {{ e.exportiert_von }}
          </q-item-label>
        </q-item-section>
        <q-item-section side class="row items-center q-gutter-xs">
          <q-btn flat dense round icon="download" color="primary"
            @click="erneutLaden(e)">
            <q-tooltip>Erneut herunterladen</q-tooltip>
          </q-btn>
          <!-- Un-Export nur für den jüngsten Lauf: ältere haben Folge-Abhängigkeiten -->
          <q-btn v-if="i === 0" flat dense round icon="undo" color="negative"
            @click="zuruecknehmen(e)">
            <q-tooltip>Lauf zurücknehmen</q-tooltip>
          </q-btn>
        </q-item-section>
      </q-item>
      <q-item v-if="exporte.length === 0">
        <q-item-section class="text-grey text-center q-py-md">
          Noch nichts exportiert.
        </q-item-section>
      </q-item>
    </q-list>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'
import { fmtBetrag, fmtDatum, fehlertext, blobFehlertext } from 'src/composables/useRechnungen'

defineOptions({ name: 'RechnungenExportPage' })

const $q = useQuasar()

const vorschau = ref({ rechnungen: [], anzahl: 0, summe_cent: 0, hinweise: [], fehler: [] })
const exporte = ref([])
const busy = ref(false)

async function load() {
  const [v, e] = await Promise.all([
    api.get('/api/rechnungen/export/vorschau'),
    api.get('/api/rechnungen/export'),
  ])
  vorschau.value = v.data
  exporte.value = e.data
}

// Download über Blob, weil die API per Cookie authentifiziert (kein direkter Link).
function speichereZip(daten, dateiname) {
  const url = URL.createObjectURL(daten)
  const a = document.createElement('a')
  a.href = url
  a.download = dateiname
  a.click()
  URL.revokeObjectURL(url)
}

function dateinameAus(res, fallback) {
  const cd = res.headers['content-disposition'] || ''
  return cd.match(/filename="?([^"]+)"?/)?.[1] || fallback
}

async function exportieren() {
  busy.value = true
  try {
    const res = await api.post('/api/rechnungen/export', null, { responseType: 'blob' })
    speichereZip(res.data, dateinameAus(res, 'rechnungen-export.zip'))
    $q.notify({ type: 'positive', message: 'Export erstellt' })
    await load()
  } catch (e) {
    $q.notify({ type: 'negative', multiLine: true, timeout: 8000,
      message: await blobFehlertext(e, 'Export fehlgeschlagen') })
    // Die Vorschau nachziehen: Bei fehlenden Konten steht dort ab jetzt, welche.
    await load().catch(() => {})
  } finally {
    busy.value = false
  }
}

async function erneutLaden(e) {
  try {
    const res = await api.get(`/api/rechnungen/export/${e.id}`, { responseType: 'blob' })
    speichereZip(res.data, dateinameAus(res, e.dateiname))
  } catch (err) {
    $q.notify({ type: 'negative',
      message: await blobFehlertext(err, 'Download fehlgeschlagen') })
  }
}

function zuruecknehmen(e) {
  $q.dialog({
    title: 'Export zurücknehmen',
    message: `„${e.dateiname}“ zurücknehmen? Die ${e.anzahl_rechnungen} Rechnung(en) `
      + 'erscheinen wieder als offen. Nur sinnvoll, solange die Datei noch nicht in '
      + 'die Fibu eingelesen wurde.',
    cancel: true,
    ok: { label: 'Zurücknehmen', color: 'negative' },
  }).onOk(async () => {
    try {
      const { data } = await api.delete(`/api/rechnungen/export/${e.id}`)
      $q.notify({
        type: 'info',
        message: `${data.rechnungen_wieder_offen} Rechnung(en) wieder offen`,
      })
      await load()
    } catch (err) {
      $q.notify({ type: 'negative', message: fehlertext(err, 'Rücknahme fehlgeschlagen') })
    }
  })
}

usePageRefresh(load)
onMounted(async () => {
  try { await load() } catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})
</script>
