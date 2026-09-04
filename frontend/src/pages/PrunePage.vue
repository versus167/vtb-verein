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
      Die Tabelle zeigt, was ein späterer Bereinigungslauf <i>entfernen würde</i>. Die
      Werte je Bereich sind einstellbar; ohne eigenen Wert gilt der Standard.
      <div class="q-mt-xs">
        <b>Papierkorb:</b> gelöschte Einträge, die alt genug und von nichts mehr abhängig
        sind – diese verschwinden endgültig.
        <b>Aufbewahrungsfristen</b> (orange): Datensätze, deren Frist abgelaufen ist,
        wandern nach Alter zunächst nur <i>in den Papierkorb</i> und bleiben
        wiederherstellbar.
        <b>Protokolle, Gerätebindungen und Dateien:</b> kein Papierkorb – hier wird nach
        Alter direkt entfernt.
        <b>Nachzug</b> (blau): aktive Einträge, die an einem gelöschten Datensatz hängen,
        dessen Aufbewahrungsfrist abgelaufen ist – sie wandern ebenfalls nur
        <i>in den Papierkorb</i>. Ohne das hielten sie ihn dauerhaft fest.
      </div>
    </q-banner>

    <div class="row items-center q-mb-md text-grey-8" v-if="report">
      <div class="col">
        Insgesamt löschbar: <b>{{ report.summe_loeschbar }}</b> Einträge,
        History: <b>{{ report.summe_history_loeschbar }}</b> von
        {{ report.summe_history_gesamt }} Zeilen löschbar.
        <span v-if="report.summe_archivierbar">
          · <b>{{ report.summe_archivierbar }}</b> Datensätze werden altersbedingt
          archiviert (Papierkorb).
        </span>
        <span v-if="report.summe_nachzug">
          · <b>{{ report.summe_nachzug }}</b> Einträge werden gelöschten Datensätzen
          nachgezogen (Papierkorb).
        </span>
        <span v-if="report.summe_verwaiste_dateien">
          · <b>{{ report.summe_verwaiste_dateien }}</b> verwaiste Dateien.
        </span>
      </div>
      <div class="col-auto" v-if="report.generated_at">
        Stand: {{ fmtDate(report.generated_at) }}
      </div>
    </div>

    <!-- Sonst wirkt die Liste unvollständig: Ohne diesen Hinweis sähe es aus, als
         kenne die App nur eine Handvoll Bereiche (#170). -->
    <div v-if="ausgeblendeteBereiche" class="text-caption text-grey-7 text-right q-mb-xs">
      {{ ausgeblendeteBereiche === 1 ? '1 Bereich ohne Löschbares ausgeblendet'
        : ausgeblendeteBereiche + ' Bereiche ohne Löschbares ausgeblendet' }}
    </div>

    <q-table
      flat bordered
      :rows="sichtbareRows"
      :columns="columns"
      row-key="name"
      :loading="loading"
      :filter="filter"
      :pagination="{ rowsPerPage: 0, sortBy: 'gruppe' }"
      hide-bottom
      :no-data-label="nurLoeschbares && !filter
        ? 'In keinem Bereich ist derzeit etwas zu löschen'
        : 'Keine Bereiche konfiguriert'"
    >
      <template #top-right>
        <div class="row items-center q-gutter-md">
          <!-- Die Tabelle listet jeden Bereich, auch wenn dort seit Monaten nichts
               anfällt – bei ~90 Zeilen sucht man das Wenige mit der Lupe (#170). -->
          <q-toggle v-model="nurLoeschbares" dense label="Nur mit Löschbarem" />
          <q-input
            v-model="filter" dense outlined clearable debounce="200"
            placeholder="Bereich suchen"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </div>
      </template>

      <template #body-cell-gruppe="props">
        <q-td :props="props">
          <q-chip dense outline color="primary" :label="props.row.gruppe" />
        </q-td>
      </template>

      <template #body-cell-loeschbar="props">
        <q-td :props="props">
          <q-chip
            v-if="props.row.archiviert_statt_geloescht && props.row.archivierbar > 0"
            dense color="orange-8" text-color="white" icon="archive"
            :label="props.row.archivierbar"
          >
            <!-- Der Regelfall ist wiederherstellbar; Regeln mit eigener Wirkung
                 (Saldovortrag, #187) sagen im `hinweis` selbst, was sie tun. -->
            <q-tooltip>{{ props.row.hinweis
              || 'Werden in den Papierkorb verschoben (wiederherstellbar)' }}</q-tooltip>
          </q-chip>
          <q-chip
            v-else-if="props.row.loeschbar > 0"
            dense color="negative" text-color="white" :label="props.row.loeschbar"
          />
          <span v-else>0</span>
          <!-- Nachzug: hängen gebliebene Kinder dieses Bereichs. Eigener Chip, weil es
               ein Soft-Delete an einer ANDEREN Tabelle ist – nicht zu verwechseln mit
               dem, was in diesem Bereich endgültig gelöscht wird. -->
          <div v-if="props.row.nachzug" class="q-mt-xs">
            <q-chip
              dense color="primary" text-color="white" icon="link_off"
              :label="`+${props.row.nachzug}`"
            >
              <q-tooltip>
                {{ props.row.nachzug }} aktive Einträge hängen an gelöschten
                {{ props.row.label }}, deren Frist abgelaufen ist. Sie wandern in den
                Papierkorb (wiederherstellbar) – sonst bliebe dieser Bereich für immer
                blockiert.
              </q-tooltip>
            </q-chip>
          </div>
          <!-- Saldovortrag: Der Betrag der archivierten Zeilen wandert in den
               Anfangsbestand der Kasse, damit der Bestand nicht springt (#189). -->
          <div v-if="props.row.vortrag_cent" class="text-caption text-grey-7 q-mt-xs">
            Vortrag {{ formatEuro(props.row.vortrag_cent) }}
            <q-tooltip>
              Dieser Saldo wandert in den Anfangsbestand der jeweiligen Kasse,
              damit der Kassenbestand unverändert bleibt.
            </q-tooltip>
          </div>
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
            v-if="props.row.keep_min !== null"
            v-model.number="props.row.keep_min" type="number" dense outlined
            min="0" style="max-width: 80px"
          />
          <span v-else class="text-grey-6">–</span>
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

    <q-dialog v-model="confirmOpen">
      <q-card style="min-width: 360px">
        <!-- Titel, Symbol und Knopf richten sich danach, was der Lauf TATSÄCHLICH tut.
             Stehen nur Archivierung und Nachzug an, ist alles daran umkehrbar – die
             Warnsprache eines unwiderruflichen Vorgangs wäre dann schlicht falsch und
             ließe den Admin abbrechen oder etwas Falsches erwarten. -->
        <q-card-section class="row items-center">
          <q-icon
            :name="nurPapierkorb ? 'inventory_2' : 'warning'"
            :color="nurPapierkorb ? 'primary' : 'negative'" size="sm" class="q-mr-sm"
          />
          <span class="text-h6">
            {{ nurPapierkorb ? 'In den Papierkorb verschieben?' : 'Endgültig löschen?' }}
          </span>
        </q-card-section>
        <q-card-section v-if="report">
          <template v-if="report.summe_loeschbar + report.summe_history_loeschbar > 0">
            Es werden <b>{{ report.summe_loeschbar }}</b> Datensätze und
            <b>{{ report.summe_history_loeschbar }}</b> History-Zeilen
            <b>unwiderruflich</b> gelöscht. Eine Wiederherstellung ist danach nicht
            mehr möglich.
          </template>
          <div v-if="report.summe_archivierbar" class="q-mt-sm text-orange-9">
            Außerdem werden <b>{{ report.summe_archivierbar }}</b> altersbedingt fällige
            Datensätze in den Papierkorb verschoben – wiederherstellbar, bis der reguläre
            Prune sie später endgültig entfernt.
          </div>
          <div v-if="report.summe_nachzug" class="q-mt-sm text-primary">
            Ebenfalls in den Papierkorb: <b>{{ report.summe_nachzug }}</b> aktive
            Einträge, die an gelöschten Datensätzen mit abgelaufener Frist hängen.
            Auch das ist wiederherstellbar.
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            :color="nurPapierkorb ? 'primary' : 'negative'"
            :label="nurPapierkorb ? 'In den Papierkorb' : 'Endgültig löschen'"
            :loading="executing" @click="execute"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()
const loading = ref(false)
const saving = ref(null)
const executing = ref(false)
const confirmOpen = ref(false)
const rows = ref([])
const report = ref(null)

/**
 * Läuft dieser Durchgang ohne jeden unumkehrbaren Schritt?
 *
 * Verwaiste Dateien zählen mit: Sie werden physisch entfernt, nicht in den Papierkorb
 * gelegt. Archivierung und Nachzug sind dagegen reine Soft-Deletes.
 */
const nurPapierkorb = computed(() =>
  !!report.value &&
  (report.value.summe_loeschbar + report.value.summe_history_loeschbar
    + (report.value.summe_verwaiste_dateien || 0)) === 0,
)

const nothingToDelete = computed(() =>
  !report.value ||
  (report.value.summe_loeschbar + report.value.summe_history_loeschbar
    + (report.value.summe_archivierbar || 0)
    + (report.value.summe_nachzug || 0)) === 0,
)

const fmtDate = (v) => (v ? new Date(v).toLocaleString('de-DE') : '–')
const formatEuro = (cent) => new Intl.NumberFormat('de-DE',
  { style: 'currency', currency: 'EUR' }).format((cent || 0) / 100)

const filter = ref('')

// #170: Standardmäßig nur Bereiche zeigen, in denen tatsächlich etwas anfällt.
// Wer die Aufbewahrungsfristen pflegen will, schaltet um oder sucht den Bereich –
// deshalb hebt eine Sucheingabe den Filter auf: Wer tippt, meint genau diese Zeile.
const nurLoeschbares = ref(true)
const hatLoeschbares = (r) => (r.loeschbar || 0) > 0
  || (r.archivierbar || 0) > 0
  || (r.nachzug || 0) > 0
  || (r.history_loeschbar || 0) > 0
const sichtbareRows = computed(() => (
  !nurLoeschbares.value || filter.value ? rows.value : rows.value.filter(hatLoeschbares)))
const ausgeblendeteBereiche = computed(() => rows.value.length - sichtbareRows.value.length)

const columns = [
  { name: 'gruppe', label: 'Gruppe', field: 'gruppe', align: 'left', sortable: true },
  { name: 'label', label: 'Bereich', field: 'label', align: 'left', sortable: true },
  { name: 'eintraege', label: 'Einträge', field: (r) => r.eintraege ?? '–', align: 'right' },
  { name: 'im_papierkorb', label: 'Im Papierkorb', field: (r) => r.im_papierkorb ?? '–', align: 'right' },
  { name: 'loeschbar', label: 'Jetzt löschbar', field: 'loeschbar', align: 'right' },
  { name: 'history_gesamt', label: 'History gesamt', field: (r) => r.history_gesamt ?? '–', align: 'right' },
  { name: 'history_loeschbar', label: 'History löschbar', field: (r) => r.history_loeschbar ?? '–', align: 'right' },
  { name: 'retention_days', label: 'Aufbewahrung (Tage)', field: 'retention_days', align: 'center' },
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
      keep_min: row.keep_min ?? 0,                      // Protokoll-Zeile hat keine Mindestanzahl
      history_retention_days: row.history_retention_days ?? 1,  // … und keine History
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
      message: `Bereinigt: ${data.summe_geloescht} Datensätze, ${data.summe_history_geloescht} History-Zeilen`
        + (data.summe_archiviert ? `, ${data.summe_archiviert} archiviert` : '')
        + (data.summe_nachzug ? `, ${data.summe_nachzug} nachgezogen` : '')
        + (data.summe_dateien_geloescht ? `, ${data.summe_dateien_geloescht} Dateien` : ''),
    })
    await reload()
  } catch {
    $q.notify({ type: 'negative', message: 'Bereinigung fehlgeschlagen' })
  } finally {
    executing.value = false
  }
}

usePageRefresh(reload)
onMounted(reload)
</script>
