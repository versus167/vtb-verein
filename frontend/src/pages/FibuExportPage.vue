<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Fibu-Export</div>
      <q-space />
    </div>

    <q-tabs v-model="tab" dense align="left" class="text-primary q-mb-md" narrow-indicator>
      <q-tab name="export" label="Export" icon="account_balance" />
      <q-tab name="sepa" label="SEPA-Einzug" icon="euro" />
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

      <q-banner v-if="vorschau && vorschau.fehler.length" class="vtb-warnung q-mb-md" rounded>
        <template #avatar><q-icon name="warning" /></template>
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
                <q-badge v-if="p.quelle_typ === 'ul_abrechnung'" color="indigo" text-color="white"
                  class="q-ml-xs">ÜL-Honorar (Kreditor)</q-badge>
              </td>
              <td>{{ p.konto ?? '–' }}</td><td>{{ p.gegenkonto ?? '–' }}</td>
              <td>{{ p.kostenstelle ?? '–' }} / {{ p.kostentraeger ?? '–' }}</td>
              <td class="text-right">
                {{ p.soll_haben === 'H' ? '−' : '' }}{{ fmt(p.betrag) }} €
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

    <!-- ════════════ SEPA-Einzug ════════════ -->
    <div v-show="tab === 'sepa'">
      <q-banner class="bg-grey-2 q-mb-md" rounded>
        <template #avatar><q-icon name="info" color="primary" /></template>
        Der Verein zieht selbst ein: aus den fälligen offenen Posten entsteht eine
        Lastschriftdatei (pain.008), die im Online-Banking eingereicht wird. Eingezogen
        wird ausschließlich bei Mitgliedern mit Einzugs-Haken im Profil.
      </q-banner>

      <q-banner v-if="sepaVorschau && sepaVorschau.konfiguration_fehler.length"
        class="vtb-warnung q-mb-md" rounded>
        <template #avatar><q-icon name="warning" /></template>
        <div class="text-weight-medium">Gläubiger-Angaben fehlen – ohne sie ist keine Datei möglich:</div>
        <ul class="q-my-xs">
          <li v-for="(f, i) in sepaVorschau.konfiguration_fehler" :key="i">{{ f }}</li>
        </ul>
        <template #action>
          <q-btn flat dense label="Zu den Einstellungen" @click="tab = 'einstellungen'" />
        </template>
      </q-banner>

      <div class="row items-center q-mb-sm q-gutter-sm">
        <q-input v-model="sepaTermin" label="Ausführungsdatum" outlined dense type="date"
          style="max-width:200px" :hint="terminHinweis" @update:model-value="loadSepaVorschau" />
        <q-btn color="primary" outline icon="refresh" label="Vorschau"
          :loading="ladeSepa" @click="loadSepaVorschau" />
        <q-space />
        <q-btn color="primary" unelevated icon="download" label="Lastschriftdatei erzeugen"
          :disable="!kannEinziehen" :loading="erzeugeSepa" @click="doSepaLauf" />
      </div>

      <div v-if="sepaVorschau" class="text-caption text-grey-7 q-mb-sm">
        {{ sepaVorschau.anzahl }} Lastschrift(en) · Summe
        {{ fmt(sepaVorschau.summe_cent / 100) }} € · Einzug am
        {{ formatDate(sepaVorschau.ausfuehrungsdatum) }}
      </div>

      <div v-if="sepaVorschau && sepaVorschau.einziehbar.length" class="q-mb-md">
        <div class="text-subtitle2 q-mb-xs">Einzuziehen</div>
        <q-markup-table flat bordered dense>
          <thead>
            <tr>
              <th class="text-left">Mitglied</th><th class="text-left">Posten</th>
              <th class="text-left">Fällig</th><th class="text-left">IBAN</th>
              <th class="text-left">Mandat</th><th class="text-right">Betrag</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in sepaVorschau.einziehbar" :key="k.quelle_typ + k.quelle_id">
              <td>{{ k.mitglied_name }}</td>
              <td>{{ k.bezeichnung }}</td>
              <td>{{ formatDate(k.faelligkeitsdatum) }}</td>
              <td>{{ k.iban }}</td>
              <td>{{ k.mandatsref }} · {{ formatDate(k.mandatsdatum) }}</td>
              <td class="text-right">{{ fmt(k.betrag_cent / 100) }} €</td>
            </tr>
          </tbody>
        </q-markup-table>
      </div>

      <div v-if="sepaVorschau && sepaVorschau.nicht_einziehbar.length" class="q-mb-md">
        <div class="text-subtitle2 q-mb-xs">
          Nicht einziehbar ({{ sepaVorschau.nicht_einziehbar.length }})
        </div>
        <div class="text-caption text-grey-7 q-mb-xs">
          Diese fälligen Posten bleiben offen – sie müssen überwiesen oder im Profil
          vervollständigt werden.
        </div>
        <q-markup-table flat bordered dense>
          <thead>
            <tr>
              <th class="text-left">Mitglied</th><th class="text-left">Posten</th>
              <th class="text-right">Betrag</th><th class="text-left">Grund</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in sepaVorschau.nicht_einziehbar" :key="k.quelle_typ + k.quelle_id">
              <td>{{ k.mitglied_name }}</td><td>{{ k.bezeichnung }}</td>
              <td class="text-right">{{ fmt(k.betrag_cent / 100) }} €</td>
              <td class="text-grey-8">{{ k.ausschluss }}</td>
            </tr>
          </tbody>
        </q-markup-table>
      </div>

      <div v-if="sepaVorschau && sepaVorschau.anzahl === 0 && !sepaVorschau.nicht_einziehbar.length"
        class="text-grey text-center q-py-lg">
        Keine fälligen Posten zum Einziehen.
      </div>

      <q-separator class="q-my-md" />
      <div class="text-subtitle2 q-mb-xs">Einzugsläufe</div>
      <q-list bordered separator>
        <q-item v-for="x in sepaLaeufe" :key="x.id">
          <q-item-section>
            <q-item-label>
              Lauf #{{ x.id }} · Einzug am {{ formatDate(x.ausfuehrungsdatum) }}
            </q-item-label>
            <q-item-label caption>
              {{ x.anzahl_positionen }} Lastschrift(en) · {{ fmt(x.summe_cent / 100) }} € ·
              erzeugt {{ formatDateTime(x.created_at) }} von {{ x.created_by }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row items-center q-gutter-xs">
              <q-btn flat dense round icon="download" color="primary" @click="sepaReDownload(x)">
                <q-tooltip>Datei erneut herunterladen</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="undo" color="orange-9" @click="sepaZuruecknehmen(x)">
                <q-tooltip>Lauf zurücknehmen (nur falls NICHT bei der Bank eingereicht)</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="sepaLaeufe.length === 0" class="text-grey text-center q-py-lg">
        Noch keine Einzugsläufe.
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
              · {{ formatDateTime(x.exportiert_am) }}
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
          <q-separator class="q-my-sm" />
          <div class="text-subtitle2">Übungsleiter-Honorar (Kreditor)</div>
          <q-input v-model="einst.ul_aufwand_konto" label="ÜL-Aufwandskonto (Soll-Sachkonto)" outlined dense
            clearable hint="Gegenkonto der Kreditor-Buchung – Honorar-Aufwand" />
          <q-input v-model.number="einst.ul_kreditor_konto_basis" label="ÜL-Kreditor-Konto-Basis" outlined dense
            type="number" clearable hint="Kreditor-Konto = Basis + Mitgliedsnummer · Kostenstelle kommt aus der Abteilung" />
          <q-separator class="q-my-sm" />
          <div class="text-subtitle2">Kassenexport (FBASC)</div>
          <q-input v-model="einst.kassendifferenz_gegenkonto" label="Gegenkonto Kassendifferenz" outlined dense
            clearable hint="Gegenkonto (Feld 01) der System-Kategorie Kassendifferenz beim Kassenexport" />
          <q-separator class="q-my-sm" />
          <div class="text-subtitle2">SEPA-Lastschrift (eigener Einzug)</div>
          <q-input v-model="einst.sepa_glaeubiger_id" label="Gläubiger-ID (Creditor Identifier)" outlined dense
            clearable hint="von der Bundesbank vergeben, z. B. DE98ZZZ09999999999" />
          <q-input v-model="einst.sepa_glaeubiger_name" label="Gläubiger-Name" outlined dense
            clearable hint="Zahlungsempfänger, wie er auf dem Kontoauszug des Mitglieds erscheint" />
          <div class="row q-gutter-sm">
            <q-input v-model="einst.sepa_iban" label="IBAN Vereinskonto" outlined dense
              class="col" clearable hint="Konto, auf das eingezogen wird" />
            <q-input v-model="einst.sepa_bic" label="BIC (optional)" outlined dense
              class="col" clearable hint="leer = IBAN-only" />
          </div>
          <q-input v-model.number="einst.sepa_vorlauftage" label="Vorlauffrist (Bankarbeitstage)" outlined dense
            type="number" min="1"
            hint="Abstand bis zum Ausführungsdatum; die Bank braucht mindestens einen Tag" />
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
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { formatDate, formatDateTime } from 'src/utils/datetime'

const $q = useQuasar()

const tab = ref('export')
const vorschau = ref(null)
const ladeVorschau = ref(false)
const exportiere = ref(false)
const exporte = ref([])
const einst = ref({
  debitor_konto_basis: null, default_gegenkonto: '', default_steuerschluessel: '',
  verein_kostenstelle: 12, default_kostentraeger: 1,
  ul_aufwand_konto: '', ul_kreditor_konto_basis: null,
  kassendifferenz_gegenkonto: '',
  sepa_glaeubiger_id: '', sepa_glaeubiger_name: '', sepa_iban: '', sepa_bic: '',
  sepa_vorlauftage: 2,
})
const speichere = ref(false)

// --- SEPA-Einzug ---
const sepaVorschau = ref(null)
const sepaLaeufe = ref([])
const sepaTermin = ref('')          // leer = frühestmöglicher Termin (Server entscheidet)
const ladeSepa = ref(false)
const erzeugeSepa = ref(false)

const kannExportieren = computed(() =>
  !!vorschau.value && vorschau.value.anzahl > 0 && vorschau.value.fehler.length === 0)

const kannEinziehen = computed(() =>
  !!sepaVorschau.value && sepaVorschau.value.anzahl > 0
  && sepaVorschau.value.konfiguration_fehler.length === 0)

const terminHinweis = computed(() => {
  const frueh = sepaVorschau.value?.fruehestes_ausfuehrungsdatum
  return frueh ? `frühestens ${formatDate(frueh)} (Vorlauffrist)` : 'leer = frühestmöglich'
})

function fmt(n) { return (Number(n) || 0).toFixed(2) }

// Abteilungs-Gegenbuchung: liegt als Haben-Zeile in den Forderungen (zahler_typ='abteilung').
function istAbteilungUmbuchung(p) {
  return p.quelle_typ !== 'ul_abrechnung' && p.art === 'forderung' && p.soll_haben === 'H'
}

function downloadBlob(data, filename) {
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

// Dateiname aus dem Content-Disposition des Servers (SEPA-Läufe heißen nach Einzugstermin).
function dateinameAusResponse(res, fallback) {
  const treffer = /filename="?([^"]+)"?/.exec(res.headers?.['content-disposition'] || '')
  return treffer ? treffer[1] : fallback
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

async function loadSepaVorschau() {
  ladeSepa.value = true
  try {
    const params = sepaTermin.value ? { ausfuehrungsdatum: sepaTermin.value } : {}
    const { data } = await api.get('/api/fibu/sepa/vorschau', { params })
    sepaVorschau.value = data
    // Leeres Feld mit dem Servertermin vorbelegen, damit sichtbar ist, wann eingezogen wird.
    if (!sepaTermin.value) sepaTermin.value = data.ausfuehrungsdatum
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der SEPA-Vorschau' })
  } finally { ladeSepa.value = false }
}

async function loadSepaLaeufe() {
  const { data } = await api.get('/api/fibu/sepa/laeufe')
  sepaLaeufe.value = data
}

async function doSepaLauf() {
  const anzahl = sepaVorschau.value.anzahl
  const summe = fmt(sepaVorschau.value.summe_cent / 100)
  $q.dialog({
    title: 'Lastschriftdatei erzeugen?',
    message: `${anzahl} Lastschrift(en) über ${summe} € mit Einzug am `
      + `${formatDate(sepaVorschau.value.ausfuehrungsdatum)}. Die Posten gelten danach als `
      + 'eingezogen und erscheinen nicht mehr in der Vorschau – bis der Lauf zurückgenommen wird.',
    cancel: true, ok: { label: 'Erzeugen', color: 'primary' },
  }).onOk(async () => {
    erzeugeSepa.value = true
    try {
      const res = await api.post('/api/fibu/sepa/laeufe',
        { ausfuehrungsdatum: sepaTermin.value || null }, { responseType: 'blob' })
      downloadBlob(res.data, dateinameAusResponse(res, 'sepa.xml'))
      $q.notify({ type: 'positive', message: 'Lastschriftdatei erstellt' })
      await Promise.all([loadSepaVorschau(), loadSepaLaeufe()])
    } catch (e) {
      $q.notify({ type: 'negative', message: await blobFehler(e, 'Erzeugen fehlgeschlagen') })
    } finally { erzeugeSepa.value = false }
  })
}

async function sepaReDownload(x) {
  try {
    const res = await api.get(`/api/fibu/sepa/laeufe/${x.id}/download`, { responseType: 'blob' })
    downloadBlob(res.data, x.dateiname || 'sepa.xml')
  } catch (e) {
    $q.notify({ type: 'negative', message: await blobFehler(e, 'Download fehlgeschlagen') })
  }
}

function sepaZuruecknehmen(x) {
  $q.dialog({
    title: `Einzugslauf #${x.id} zurücknehmen?`,
    message: 'Nur wählen, wenn die Datei NOCH NICHT bei der Bank eingereicht wurde. '
      + 'Die Posten werden wieder einziehbar. Ist die Lastschrift schon unterwegs, '
      + 'läuft die Korrektur über die Bank (Rückgabe), nicht über die App.',
    cancel: true, ok: { label: 'Zurücknehmen', color: 'orange-9' },
  }).onOk(async () => {
    try {
      const { data } = await api.post(`/api/fibu/sepa/laeufe/${x.id}/zuruecknehmen`)
      $q.notify({ type: 'positive',
        message: `Lauf #${x.id} zurückgenommen · ${data.posten_wieder_offen} Posten wieder offen` })
      await Promise.all([loadSepaVorschau(), loadSepaLaeufe()])
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Rücknahme fehlgeschlagen' })
    }
  })
}

// Zuletzt geladener Server-Stand des Formulars (JSON). Weicht das Formular davon ab,
// hat der Benutzer etwas eingetippt und noch nicht gespeichert.
let einstStand = ''
function einstSnapshot(werte) { return JSON.stringify(werte) }
function einstGeaendert() { return !!einstStand && einstSnapshot(einst.value) !== einstStand }

async function loadEinstellungen() {
  const { data } = await api.get('/api/fibu/einstellungen')
  const frisch = {
    debitor_konto_basis: data.debitor_konto_basis,
    default_gegenkonto: data.default_gegenkonto ?? '',
    default_steuerschluessel: data.default_steuerschluessel ?? '',
    verein_kostenstelle: data.verein_kostenstelle,
    default_kostentraeger: data.default_kostentraeger,
    ul_aufwand_konto: data.ul_aufwand_konto ?? '',
    ul_kreditor_konto_basis: data.ul_kreditor_konto_basis,
    kassendifferenz_gegenkonto: data.kassendifferenz_gegenkonto ?? '',
    sepa_glaeubiger_id: data.sepa_glaeubiger_id ?? '',
    sepa_glaeubiger_name: data.sepa_glaeubiger_name ?? '',
    sepa_iban: data.sepa_iban ?? '',
    sepa_bic: data.sepa_bic ?? '',
    sepa_vorlauftage: data.sepa_vorlauftage ?? 2,
  }
  // Der Auto-Refresh (Fensterwechsel) läuft auch mitten in der Eingabe – dann das
  // Formular stehen lassen, sonst verschwinden angefangene Angaben (z. B. die IBAN).
  if (einstGeaendert()) return
  einst.value = frisch
  einstStand = einstSnapshot(frisch)
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
      ul_aufwand_konto: einst.value.ul_aufwand_konto || null,
      ul_kreditor_konto_basis: einst.value.ul_kreditor_konto_basis ?? null,
      kassendifferenz_gegenkonto: einst.value.kassendifferenz_gegenkonto || null,
      sepa_glaeubiger_id: einst.value.sepa_glaeubiger_id || null,
      sepa_glaeubiger_name: einst.value.sepa_glaeubiger_name || null,
      sepa_iban: einst.value.sepa_iban || null,
      sepa_bic: einst.value.sepa_bic || null,
      sepa_vorlauftage: einst.value.sepa_vorlauftage ?? 2,
    })
    // Gespeichert = der Formularstand IST jetzt der Server-Stand; ohne das gälte das
    // Formular dauerhaft als geändert und würde nie wieder nachgeladen.
    einstStand = einstSnapshot(einst.value)
    $q.notify({ type: 'positive', message: 'Einstellungen gespeichert' })
    await Promise.all([loadVorschau(), loadSepaVorschau()])
  } catch { $q.notify({ type: 'negative', message: 'Fehler beim Speichern' }) }
  finally { speichere.value = false }
}

function loadAll() {
  return Promise.all([loadVorschau(), loadExporte(), loadEinstellungen(),
                      loadSepaVorschau(), loadSepaLaeufe()])
}

usePageRefresh(loadAll)
onMounted(async () => {
  try { await loadAll() }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})
</script>
