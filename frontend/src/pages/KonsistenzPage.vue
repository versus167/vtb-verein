<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5">Konsistenzprüfung</div>
      <q-space />
      <q-btn
        color="primary" icon="fact_check" label="Prüfung starten"
        :loading="loading" @click="reload"
      />
      <q-btn
        flat round icon="refresh" :loading="loading" class="q-ml-sm"
        @click="reload" aria-label="Aktualisieren"
      >
        <q-tooltip>Aktualisieren</q-tooltip>
      </q-btn>
    </div>

    <q-banner dense rounded class="bg-blue-1 text-blue-10 q-mb-md">
      <template #avatar><q-icon name="visibility" color="blue-10" /></template>
      <b>Read-only – es wird nichts geändert.</b>
      Der Scan sucht generisch über alle Fremdschlüssel nach <i>aktiven</i> Datensätzen,
      die auf einen bereits <i>gelöschten</i> (im Papierkorb liegenden) Datensatz zeigen –
      hängende Beziehungen, die die Datenbank-Constraints allein nicht verhindern.
    </q-banner>

    <div v-if="report" class="q-mb-md">
      <!-- Maßstab ist `summe_offen`, nicht die Gesamtzahl: Ein Teil der hängenden
           Verweise ist gewollt (Urheber-Angaben) oder vorübergehend (der Prune zieht
           sie nach). Stünden sie gleichrangig daneben, wäre der Bericht dauerhaft rot
           und der eine echte Fund ginge darin unter. -->
      <q-banner v-if="report.alles_konsistent" dense rounded class="bg-green-1 text-green-10">
        <template #avatar><q-icon name="check_circle" color="green-10" /></template>
        Keine offenen Befunde – {{ report.geprueft }} Beziehungen geprüft.
        <span v-if="report.summe_verletzungen">
          {{ report.summe_verletzungen }} hängende Verweise sind eingeordnet und
          erwartet (siehe Tabelle).
        </span>
      </q-banner>
      <q-banner v-else dense rounded class="vtb-warnung">
        <template #avatar><q-icon name="warning" /></template>
        <b>{{ report.summe_offen }}</b> offene hängende Verweise in
        <b>{{ offeneBefunde.length }}</b> von {{ report.geprueft }} geprüften Beziehungen.
        <span v-if="report.summe_verletzungen > report.summe_offen">
          Weitere {{ report.summe_verletzungen - report.summe_offen }} sind eingeordnet
          und erwartet.
        </span>
      </q-banner>

      <q-banner
        v-if="verwaisteRechte > 0" dense rounded
        class="bg-blue-grey-1 text-blue-grey-10 q-mt-sm"
      >
        <template #avatar><q-icon name="build" color="blue-grey-8" /></template>
        <b>Einmalige Altlast-Bereinigung verfügbar:</b>
        {{ verwaisteRechte }} Rechte-Einträge gehören bereits gelöschten Benutzern und können
        gefahrlos entzogen werden – das entspricht dem heutigen Verhalten beim Löschen eines
        Benutzers und muss nur einmal nachgeholt werden.
        <template #action>
          <q-btn
            color="orange-8" icon="cleaning_services" label="Verwaiste Rechte bereinigen"
            :loading="reparatur" @click="confirmRepair = true"
          />
        </template>
      </q-banner>
    </div>

    <q-table
      v-if="report && report.befunde.length"
      flat bordered
      :rows="report.befunde"
      :columns="columns"
      row-key="constraint"
      :loading="loading"
      :pagination="{ rowsPerPage: 0 }"
      hide-bottom
    >
      <template #body-cell-beziehung="props">
        <q-td :props="props">
          <span class="text-weight-medium">{{ props.row.child_table }}</span>.{{ props.row.child_column }}
          <q-icon name="arrow_forward" size="xs" class="q-mx-xs text-grey-6" />
          <span class="text-weight-medium">{{ props.row.parent_table }}</span>.{{ props.row.parent_column }}
        </q-td>
      </template>

      <template #body-cell-verletzungen="props">
        <q-td :props="props">
          <q-chip
            dense text-color="white" :label="props.row.verletzungen"
            :color="props.row.kategorie === 'offen' ? 'negative' : 'grey-6'"
          />
        </q-td>
      </template>

      <template #body-cell-einordnung="props">
        <q-td :props="props">
          <q-chip
            v-if="props.row.kategorie === 'offen'"
            dense outline color="negative" icon="error_outline" label="offen"
          />
          <q-chip
            v-else dense outline
            :color="props.row.kategorie === 'gewollt' ? 'grey-7' : 'primary'"
            :icon="props.row.kategorie === 'gewollt' ? 'check' : 'schedule'"
            :label="props.row.kategorie === 'gewollt' ? 'gewollt' : 'Nachzug'"
          >
            <q-tooltip>{{ props.row.begruendung }}</q-tooltip>
          </q-chip>
        </q-td>
      </template>

      <template #body-cell-beispiele="props">
        <q-td :props="props">
          <span class="text-grey-8">
            {{ props.row.beispiel_parent_ids.join(', ') }}<template
              v-if="props.row.verletzungen > props.row.beispiel_parent_ids.length"> …</template>
          </span>
        </q-td>
      </template>
    </q-table>

    <div v-if="report?.generated_at" class="text-grey-7 q-mt-sm text-caption">
      Stand: {{ fmtDate(report.generated_at) }}
    </div>

    <q-dialog v-model="confirmRepair">
      <q-card style="min-width: 380px">
        <q-card-section class="row items-center">
          <q-icon name="build" color="orange-8" size="sm" class="q-mr-sm" />
          <span class="text-h6">Verwaiste Rechte bereinigen?</span>
        </q-card-section>
        <q-card-section>
          Es werden <b>{{ verwaisteRechte }}</b> Rechte-Einträge bereits gelöschter Benutzer
          entzogen (soft-delete). Betroffen sind ausschließlich Rechte zu Benutzern, die schon
          im Papierkorb liegen – alle anderen Befunde bleiben unberührt. Der Schritt ist
          einmalig und kann ohne Schaden wiederholt werden.
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            color="orange-8" label="Bereinigen" :loading="reparatur"
            @click="repariereVerwaisteRechte"
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

defineOptions({ name: 'KonsistenzPage' })

const $q = useQuasar()
const loading = ref(false)
const reparatur = ref(false)
const confirmRepair = ref(false)
const report = ref(null)

const fmtDate = (v) => (v ? new Date(v).toLocaleString('de-DE') : '–')

// Anzahl der verwaisten Rechte-Einträge (user_permissions -> gelöschter User) im Report.
const verwaisteRechte = computed(() => {
  const b = report.value?.befunde?.find(
    (x) => x.child_table === 'user_permissions' && x.parent_table === 'users',
  )
  return b?.verletzungen ?? 0
})

const columns = [
  { name: 'beziehung', label: 'Beziehung (Kind → Parent)', field: 'child_table', align: 'left' },
  { name: 'verletzungen', label: 'Hängende Verweise', field: 'verletzungen', align: 'right' },
  { name: 'einordnung', label: 'Einordnung', field: 'kategorie', align: 'left' },
  { name: 'beispiele', label: 'Beispiel-Parent-IDs', field: 'beispiel_parent_ids', align: 'left' },
]

// Nur die offenen sind ein Befund im eigentlichen Sinn – die Kopfzeile zählt sie.
const offeneBefunde = computed(
  () => report.value?.befunde?.filter((b) => b.kategorie === 'offen') ?? [],
)

async function reload() {
  loading.value = true
  try {
    const { data } = await api.get('/api/konsistenz/pruefung')
    report.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Prüfung konnte nicht geladen werden' })
  } finally {
    loading.value = false
  }
}

async function repariereVerwaisteRechte() {
  reparatur.value = true
  try {
    const { data } = await api.post('/api/konsistenz/reparatur/verwaiste-rechte')
    confirmRepair.value = false
    $q.notify({ type: 'positive', message: `${data.bereinigt} verwaiste Rechte-Einträge bereinigt` })
    await reload()
  } catch {
    $q.notify({ type: 'negative', message: 'Bereinigung fehlgeschlagen' })
  } finally {
    reparatur.value = false
  }
}

usePageRefresh(reload)
onMounted(reload)
</script>
