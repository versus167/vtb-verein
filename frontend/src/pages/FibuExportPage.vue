<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Fibu-Export</div>
      <q-space />
    </div>

    <q-tabs v-model="tab" dense align="left" class="text-primary q-mb-md" narrow-indicator>
      <q-tab name="export" label="Export" icon="account_balance" />
      <q-tab name="historie" label="Historie" icon="history" />
      <q-tab name="einstellungen" label="Einstellungen" icon="settings" />
    </q-tabs>

    <!-- ════════════ Export ════════════ -->
    <div v-show="tab === 'export'">
      <div class="row items-center q-mb-sm q-gutter-sm">
        <q-btn color="primary" outline icon="refresh" label="Vorschau" :loading="ladeVorschau" @click="loadVorschau" />
        <q-space />
        <q-btn color="primary" unelevated icon="download" label="Exportieren (fbasc.hia)"
          :disable="!kannExportieren" :loading="exportiere" @click="doExport" />
      </div>

      <q-banner v-if="vorschau && vorschau.fehler.length" class="bg-orange-1 text-orange-10 q-mb-md" rounded>
        <template #avatar><q-icon name="warning" color="orange" /></template>
        <div class="text-weight-medium">{{ vorschau.fehler.length }} Position(en) nicht exportierbar – bitte Konten/Mitgliedsnummern ergänzen:</div>
        <ul class="q-my-xs">
          <li v-for="(f, i) in vorschau.fehler" :key="i">
            {{ f.mitglied_name }} — {{ f.bezeichnung }} <span class="text-grey-8">({{ f.problem }})</span>
          </li>
        </ul>
      </q-banner>

      <div v-if="vorschau" class="text-caption text-grey-7 q-mb-sm">
        {{ vorschau.anzahl }} Position(en) · Netto-Summe {{ fmt(vorschau.summe) }} €
      </div>

      <div v-if="vorschau && vorschau.forderungen.length" class="q-mb-md">
        <div class="text-subtitle2 q-mb-xs">Forderungen (Soll)</div>
        <div class="text-caption text-grey-7 q-mb-xs">
          Abteilungs-getragene Beiträge erscheinen als Paar: Einbuchung (Soll, Kostenstelle
          Verein) und <q-badge color="teal" text-color="white">Abteilung trägt</q-badge>
          Gegenbuchung (Haben, Kostenstelle Abteilung) – Mitglied wird netto nicht belastet.
        </div>
        <q-markup-table flat bordered dense>
          <thead>
            <tr>
              <th class="text-left">Mitglied</th><th class="text-left">Bezeichnung</th>
              <th class="text-left">Konto</th><th class="text-left">Gegenkonto</th>
              <th class="text-left">Kost/KoStr</th><th class="text-right">Betrag</th><th class="text-left">Beleg</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, i) in vorschau.forderungen" :key="'f'+i">
              <td>{{ p.mitglied_name }}</td>
              <td>
                {{ p.bezeichnung }}
                <q-badge v-if="istAbteilungUmbuchung(p)" color="teal" text-color="white"
                  class="q-ml-xs">Abteilung trägt</q-badge>
              </td>
              <td>{{ p.konto ?? '–' }}</td><td>{{ p.gegenkonto ?? '–' }}</td>
              <td>{{ p.kostenstelle ?? '–' }} / {{ p.kostentraeger ?? '–' }}</td>
              <td class="text-right">
                {{ istAbteilungUmbuchung(p) ? '−' : '' }}{{ fmt(p.betrag) }} €
              </td>
              <td>{{ p.belegnummer }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </div>

      <div v-if="vorschau && vorschau.gegenbuchungen.length" class="q-mb-md">
        <div class="text-subtitle2 q-mb-xs">Gegenbuchungen / Stornos (Haben)</div>
        <q-markup-table flat bordered dense>
          <thead>
            <tr>
              <th class="text-left">Mitglied</th><th class="text-left">Bezeichnung</th>
              <th class="text-left">Konto</th><th class="text-left">Gegenkonto</th>
              <th class="text-right">Betrag</th><th class="text-left">Beleg</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, i) in vorschau.gegenbuchungen" :key="'g'+i">
              <td>{{ p.mitglied_name }}</td><td>{{ p.bezeichnung }}</td>
              <td>{{ p.konto ?? '–' }}</td><td>{{ p.gegenkonto ?? '–' }}</td>
              <td class="text-right">−{{ fmt(p.betrag) }} €</td><td>{{ p.belegnummer }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </div>

      <div v-if="vorschau && vorschau.anzahl === 0" class="text-grey text-center q-py-lg">
        Keine neuen Positionen zum Export.
      </div>
    </div>

    <!-- ════════════ Historie ════════════ -->
    <div v-show="tab === 'historie'">
      <q-list bordered separator>
        <q-item v-for="x in exporte" :key="x.id">
          <q-item-section>
            <q-item-label>
              <span v-if="istStornoLauf(x)">Storno-Lauf #{{ x.id }} <span class="text-grey-7">→ bucht #{{ x.storno_von_export_id }} gegen</span></span>
              <span v-else>Export #{{ x.id }}</span>
              · {{ (x.exportiert_am || '').slice(0, 19) }}
              <q-badge v-if="istStorniert(x)" color="grey-7" text-color="white" class="q-ml-xs">storniert durch #{{ stornoLaufId(x) }}</q-badge>
            </q-item-label>
            <q-item-label caption>
              {{ x.anzahl_positionen }} Positionen · Netto {{ fmt(x.summe_cent / 100) }} € · {{ x.exportiert_von }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row items-center q-gutter-xs">
              <q-btn flat dense round icon="download" color="primary" @click="reDownload(x.id)">
                <q-tooltip>Erneut herunterladen</q-tooltip>
              </q-btn>
              <q-btn v-if="kannZuruecknehmen(x)" flat dense round icon="undo" color="orange-9" @click="zuruecknehmen(x)">
                <q-tooltip>Lauf zurücknehmen (nur falls noch NICHT in die Fibu eingelesen)</q-tooltip>
              </q-btn>
              <q-btn v-if="kannStornieren(x)" flat dense round icon="block" color="negative" @click="stornieren(x)">
                <q-tooltip>Gegenbuchungs-Lauf (falls bereits in die Fibu eingelesen)</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="exporte.length === 0" class="text-grey text-center q-py-lg">Noch keine Exporte.</div>
    </div>

    <!-- ════════════ Einstellungen ════════════ -->
    <div v-show="tab === 'einstellungen'">
      <q-card flat bordered style="max-width:560px">
        <q-card-section class="q-gutter-sm">
          <q-input v-model.number="einst.debitor_konto_basis" label="Debitor-Konto-Basis" outlined dense
            type="number" clearable hint="Debitor-Konto = Basis + Mitgliedsnummer" />
          <q-input v-model="einst.default_gegenkonto" label="Default-Gegenkonto (Erlöskonto)" outlined dense
            clearable hint="Fallback, wenn Regel/Gebühr kein Gegenkonto hat" />
          <q-input v-model="einst.default_steuerschluessel" label="Default-Steuerschlüssel" outlined dense
            clearable hint="i.d.R. leer (Automatikkonto)" />
          <div class="row q-gutter-sm">
            <q-input v-model.number="einst.verein_kostenstelle" label="Kostenstelle Verein" outlined dense
              type="number" class="col" hint="für Vereinsbeiträge (ohne Abteilung)" />
            <q-input v-model.number="einst.default_kostentraeger" label="Default-Kostenträger" outlined dense
              type="number" class="col" />
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn unelevated color="primary" label="Speichern" :loading="speichere" @click="saveEinstellungen" />
        </q-card-actions>
      </q-card>
    </div>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()

const tab = ref('export')
const vorschau = ref(null)
const ladeVorschau = ref(false)
const exportiere = ref(false)
const exporte = ref([])
const einst = ref({
  debitor_konto_basis: null, default_gegenkonto: '', default_steuerschluessel: '',
  verein_kostenstelle: 12, default_kostentraeger: 1,
})
const speichere = ref(false)

const kannExportieren = computed(() =>
  !!vorschau.value && vorschau.value.anzahl > 0 && vorschau.value.fehler.length === 0)

function fmt(n) { return (Number(n) || 0).toFixed(2) }

// Abteilungs-Gegenbuchung: liegt als Haben-Zeile in den Forderungen (zahler_typ='abteilung').
function istAbteilungUmbuchung(p) { return p.art === 'forderung' && p.soll_haben === 'H' }

function downloadBlob(data, filename) {
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

async function loadVorschau() {
  ladeVorschau.value = true
  try {
    const { data } = await api.get('/api/fibu/vorschau')
    vorschau.value = data
  } catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden der Vorschau' }) }
  finally { ladeVorschau.value = false }
}

async function doExport() {
  exportiere.value = true
  try {
    const res = await api.post('/api/fibu/export', null, { responseType: 'blob' })
    downloadBlob(res.data, 'fbasc.hia')
    $q.notify({ type: 'positive', message: 'Export erstellt (fbasc.hia)' })
    await Promise.all([loadVorschau(), loadExporte()])
  } catch {
    $q.notify({ type: 'negative', message: 'Export fehlgeschlagen' })
  } finally { exportiere.value = false }
}

async function loadExporte() {
  const { data } = await api.get('/api/fibu/exporte')
  exporte.value = data
}

async function reDownload(id) {
  try {
    const res = await api.get(`/api/fibu/exporte/${id}/download`, { responseType: 'blob' })
    downloadBlob(res.data, 'fbasc.hia')
  } catch { $q.notify({ type: 'negative', message: 'Download fehlgeschlagen' }) }
}

// Storno-Beziehungen werden aus der (nach id absteigend sortierten) Liste abgeleitet.
function istStornoLauf(x) { return x.storno_von_export_id != null }
function stornoLaufId(x) { return exporte.value.find(e => e.storno_von_export_id === x.id)?.id }
function istStorniert(x) { return stornoLaufId(x) != null }
function istNeuester(x) { return exporte.value.length > 0 && exporte.value[0].id === x.id }
// Un-Export nur für den jüngsten Lauf; Gegenbuchung für jeden noch nicht stornierten Normallauf.
function kannZuruecknehmen(x) { return istNeuester(x) }
function kannStornieren(x) { return !istStornoLauf(x) && !istStorniert(x) }

async function blobFehler(e, fallback) {
  try { return JSON.parse(await e.response.data.text()).detail || fallback } catch { return fallback }
}

function zuruecknehmen(x) {
  $q.dialog({
    title: `Lauf #${x.id} zurücknehmen?`,
    message: 'Nur wählen, wenn die Datei NOCH NICHT in die Fibu eingelesen wurde. '
      + 'Die Positionen werden wieder offen und erscheinen in der nächsten Vorschau. '
      + 'Der Lauf verschwindet aus der Historie.',
    cancel: true, ok: { label: 'Zurücknehmen', color: 'orange-9' },
  }).onOk(async () => {
    try {
      const { data } = await api.post(`/api/fibu/exporte/${x.id}/zuruecknehmen`)
      $q.notify({ type: 'positive', message: `Lauf #${x.id} zurückgenommen · ${data.positionen_wieder_offen} Position(en) wieder offen` })
      await Promise.all([loadVorschau(), loadExporte()])
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Rücknahme fehlgeschlagen' })
    }
  })
}

function stornieren(x) {
  $q.dialog({
    title: `Lauf #${x.id} gegenbuchen?`,
    message: 'Nur wählen, wenn die Datei BEREITS in die Fibu eingelesen wurde. '
      + 'Es entsteht ein neuer Storno-Lauf, der #' + x.id + ' komplett gegenbucht (Soll↔Haben). '
      + 'Original und Storno bleiben in der Historie.',
    cancel: true, ok: { label: 'Gegenbuchen', color: 'negative' },
  }).onOk(async () => {
    try {
      const res = await api.post(`/api/fibu/exporte/${x.id}/storno`, null, { responseType: 'blob' })
      downloadBlob(res.data, 'fbasc.hia')
      $q.notify({ type: 'positive', message: `Gegenbuchungs-Lauf für #${x.id} erstellt (fbasc.hia)` })
      await Promise.all([loadVorschau(), loadExporte()])
    } catch (e) {
      $q.notify({ type: 'negative', message: await blobFehler(e, 'Storno fehlgeschlagen') })
    }
  })
}

async function loadEinstellungen() {
  const { data } = await api.get('/api/fibu/einstellungen')
  einst.value = {
    debitor_konto_basis: data.debitor_konto_basis,
    default_gegenkonto: data.default_gegenkonto ?? '',
    default_steuerschluessel: data.default_steuerschluessel ?? '',
    verein_kostenstelle: data.verein_kostenstelle,
    default_kostentraeger: data.default_kostentraeger,
  }
}

async function saveEinstellungen() {
  speichere.value = true
  try {
    await api.put('/api/fibu/einstellungen', {
      debitor_konto_basis: einst.value.debitor_konto_basis ?? null,
      default_gegenkonto: einst.value.default_gegenkonto || null,
      default_steuerschluessel: einst.value.default_steuerschluessel || null,
      verein_kostenstelle: einst.value.verein_kostenstelle ?? 12,
      default_kostentraeger: einst.value.default_kostentraeger ?? 1,
    })
    $q.notify({ type: 'positive', message: 'Einstellungen gespeichert' })
    await loadVorschau()
  } catch { $q.notify({ type: 'negative', message: 'Fehler beim Speichern' }) }
  finally { speichere.value = false }
}

onMounted(async () => {
  try { await Promise.all([loadVorschau(), loadExporte(), loadEinstellungen()]) }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})
</script>
