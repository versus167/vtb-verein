<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5">Datenbereinigung</div>
      <q-space />
      <q-btn
        color="negative" icon="delete_sweep" label="Bereinigung ausführen"
        :disable="nothingToDelete || loading" :loading="executing"
        class="q-mr-sm" @click="confirmOpen = true"
      />
      <q-btn
        flat round icon="refresh" :loading="loading"
        @click="reload" aria-label="Aktualisieren"
      >
        <q-tooltip>Aktualisieren</q-tooltip>
      </q-btn>
    </div>

    <q-banner dense rounded class="bg-blue-1 text-blue-10 q-mb-md">
      <template #avatar><q-icon name="visibility" color="blue-10" /></template>
      <b>Vorschau – es wird nichts gelöscht.</b>
      Die Tabelle zeigt, was ein späterer Bereinigungslauf <i>entfernen würde</i>:
      gelöschte (im Papierkorb liegende) Einträge, die alt genug und von nichts mehr
      abhängig sind. Die Werte je Bereich sind einstellbar; ohne eigenen Wert gilt der
      Standard.
    </q-banner>

    <q-table
      flat bordered
      :rows="rows"
      :columns="columns"
      row-key="name"
      :loading="loading"
      :pagination="{ rowsPerPage: 0 }"
      hide-bottom
      no-data-label="Keine Bereiche konfiguriert"
    >
      <template #body-cell-loeschbar="props">
        <q-td :props="props">
          <q-chip
            v-if="props.row.loeschbar > 0"
            dense color="negative" text-color="white" :label="props.row.loeschbar"
          />
          <span v-else>0</span>
        </q-td>
      </template>

      <template #body-cell-retention_days="props">
        <q-td :props="props">
          <q-input
            v-model.number="props.row.retention_days" type="number" dense outlined
            min="1" style="max-width: 90px" :suffix="'T'"
          />
        </q-td>
      </template>

      <template #body-cell-keep_min="props">
        <q-td :props="props">
          <q-input
            v-model.number="props.row.keep_min" type="number" dense outlined
            min="0" style="max-width: 80px"
          />
        </q-td>
      </template>

      <template #body-cell-history_retention_days="props">
        <q-td :props="props">
          <q-input
            v-if="props.row.history_table"
            v-model.number="props.row.history_retention_days" type="number" dense outlined
            min="1" style="max-width: 90px" :suffix="'T'"
          />
          <span v-else class="text-grey-6">–</span>
        </q-td>
      </template>

      <template #body-cell-quelle="props">
        <q-td :props="props">
          <q-chip
            dense outline
            :color="props.row.is_override ? 'primary' : 'grey'"
            :label="props.row.is_override ? 'angepasst' : 'Standard'"
          />
        </q-td>
      </template>

      <template #body-cell-aktion="props">
        <q-td :props="props">
          <q-btn
            dense flat color="primary" icon="save" :loading="saving === props.row.name"
            @click="save(props.row)"
          >
            <q-tooltip>Speichern</q-tooltip>
          </q-btn>
          <q-btn
            v-if="props.row.is_override"
            dense flat color="grey-7" icon="restart_alt" :loading="saving === props.row.name"
            @click="reset(props.row)"
          >
            <q-tooltip>Auf Standard zurücksetzen</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <div class="row q-mt-md text-grey-8" v-if="report">
      <div class="col">
        Insgesamt löschbar: <b>{{ report.summe_loeschbar }}</b> Einträge,
        History: <b>{{ report.summe_history_loeschbar }}</b> von
        {{ report.summe_history_gesamt }} Zeilen löschbar.
      </div>
      <div class="col-auto" v-if="report.generated_at">
        Stand: {{ fmtDate(report.generated_at) }}
      </div>
    </div>

    <q-dialog v-model="confirmOpen">
      <q-card style="min-width: 360px">
        <q-card-section class="row items-center">
          <q-icon name="warning" color="negative" size="sm" class="q-mr-sm" />
          <span class="text-h6">Endgültig löschen?</span>
        </q-card-section>
        <q-card-section v-if="report">
          Es werden <b>{{ report.summe_loeschbar }}</b> Datensätze und
          <b>{{ report.summe_history_loeschbar }}</b> History-Zeilen
          <b>unwiderruflich</b> gelöscht. Eine Wiederherstellung ist danach nicht
          mehr möglich.
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            color="negative" label="Endgültig löschen" :loading="executing"
            @click="execute"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()
const loading = ref(false)
const saving = ref(null)
const executing = ref(false)
const confirmOpen = ref(false)
const rows = ref([])
const report = ref(null)

const nothingToDelete = computed(() =>
  !report.value || (report.value.summe_loeschbar + report.value.summe_history_loeschbar) === 0,
)

const fmtDate = (v) => (v ? new Date(v).toLocaleString('de-DE') : '–')

const columns = [
  { name: 'label', label: 'Bereich', field: 'label', align: 'left' },
  { name: 'im_papierkorb', label: 'Im Papierkorb', field: 'im_papierkorb', align: 'right' },
  { name: 'loeschbar', label: 'Jetzt löschbar', field: 'loeschbar', align: 'right' },
  { name: 'history_gesamt', label: 'History gesamt', field: (r) => r.history_gesamt ?? '–', align: 'right' },
  { name: 'history_loeschbar', label: 'History löschbar', field: (r) => r.history_loeschbar ?? '–', align: 'right' },
  { name: 'retention_days', label: 'Tage im Papierkorb', field: 'retention_days', align: 'center' },
  { name: 'keep_min', label: 'Min. behalten', field: 'keep_min', align: 'center' },
  { name: 'history_retention_days', label: 'History-Tage', field: 'history_retention_days', align: 'center' },
  { name: 'quelle', label: 'Quelle', field: 'is_override', align: 'center' },
  { name: 'aktion', label: '', field: 'name', align: 'center' },
]

async function reload() {
  loading.value = true
  try {
    const { data } = await api.get('/api/prune/vorschau')
    report.value = data
    rows.value = data.entities
  } catch {
    $q.notify({ type: 'negative', message: 'Vorschau konnte nicht geladen werden' })
  } finally {
    loading.value = false
  }
}

async function save(row) {
  saving.value = row.name
  try {
    await api.put(`/api/prune/einstellungen/${row.name}`, {
      retention_days: row.retention_days,
      keep_min: row.keep_min,
      history_retention_days: row.history_retention_days,
    })
    $q.notify({ type: 'positive', message: `${row.label}: Werte gespeichert` })
    await reload()
  } catch (e) {
    const detail = e?.response?.data?.detail
    $q.notify({ type: 'negative', message: 'Speichern fehlgeschlagen' + (detail ? `: ${JSON.stringify(detail)}` : '') })
  } finally {
    saving.value = null
  }
}

async function reset(row) {
  saving.value = row.name
  try {
    await api.delete(`/api/prune/einstellungen/${row.name}`)
    $q.notify({ type: 'positive', message: `${row.label}: auf Standard zurückgesetzt` })
    await reload()
  } catch {
    $q.notify({ type: 'negative', message: 'Zurücksetzen fehlgeschlagen' })
  } finally {
    saving.value = null
  }
}

async function execute() {
  executing.value = true
  try {
    const { data } = await api.post('/api/prune/ausfuehren', null, { params: { dry_run: false } })
    confirmOpen.value = false
    $q.notify({
      type: 'positive',
      message: `Bereinigt: ${data.summe_geloescht} Datensätze, ${data.summe_history_geloescht} History-Zeilen`,
    })
    await reload()
  } catch {
    $q.notify({ type: 'negative', message: 'Bereinigung fehlgeschlagen' })
  } finally {
    executing.value = false
  }
}

onMounted(reload)
</script>
