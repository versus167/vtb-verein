<template>
  <q-page padding>
    <!-- Header -->
    <div class="row items-center q-mb-sm">
      <q-btn flat round dense icon="arrow_back" :to="{ name: 'kassenbuch' }" class="q-mr-sm" />
      <div class="col">
        <div class="text-h5">{{ kasse?.name ?? 'Kassenbuch' }}</div>
        <div v-if="kasse?.beschreibung" class="text-caption text-grey">{{ kasse.beschreibung }}</div>
      </div>
      <div class="text-right">
        <div class="text-h6" :class="bestandCent < 0 ? 'text-negative' : 'text-positive'">
          {{ formatEuro(bestandCent) }}
        </div>
        <div class="text-caption text-grey">Bestand</div>
      </div>
    </div>

    <!-- Aktions-Leiste -->
    <div class="row q-gutter-sm q-mb-sm items-center">
      <q-btn
        v-if="$q.screen.lt.sm"
        flat round dense icon="filter_list"
        :color="filterAktiv ? 'primary' : 'grey'"
        @click="filterOpen = !filterOpen"
      >
        <q-badge v-if="filterAktiv" color="primary" floating />
        <q-tooltip>Filter</q-tooltip>
      </q-btn>

      <q-space />

      <template v-if="kannSchreiben">
        <q-btn
          icon="add"
          :label="$q.screen.gt.xs ? 'Einnahme' : undefined"
          color="positive"
          unelevated
          :round="$q.screen.lt.sm"
          @click="openCreateDialog('einnahme')"
        />
        <q-btn
          icon="remove"
          :label="$q.screen.gt.xs ? 'Ausgabe' : undefined"
          color="negative"
          unelevated
          :round="$q.screen.lt.sm"
          @click="openCreateDialog('ausgabe')"
        />
      </template>
      <q-btn
        v-if="kannExportieren"
        icon="download"
        :label="$q.screen.gt.xs ? 'CSV-Export' : undefined"
        color="primary"
        outline
        :round="$q.screen.lt.sm"
        @click="openExportDialog"
      />
      <q-btn
        icon="picture_as_pdf"
        :label="$q.screen.gt.xs ? 'PDF-Bericht' : undefined"
        color="secondary"
        outline
        :round="$q.screen.lt.sm"
        @click="openPdfDialog"
      />
    </div>

    <!-- Filter (Desktop: immer sichtbar; Mobile: einklappbar) -->
    <q-slide-transition>
      <div v-show="$q.screen.gt.xs || filterOpen" class="row q-gutter-sm q-mb-md items-center">
        <q-input v-model="filterVon" type="date" label="Von" outlined dense style="width: 150px" />
        <q-input v-model="filterBis" type="date" label="Bis" outlined dense style="width: 150px" />
        <q-btn label="Anwenden" outline color="primary" dense @click="applyFilter" />
        <q-checkbox v-model="showStorniert" label="Stornierte" @update:model-value="applyFilter" />
      </div>
    </q-slide-transition>

    <!-- ── Mobile: Karten-Liste ── -->
    <template v-if="$q.screen.lt.sm">
      <div v-if="loading" class="row justify-center q-py-xl">
        <q-spinner size="40px" color="primary" />
      </div>
      <div v-else-if="buchungenMitBestand.length === 0" class="text-center text-grey q-py-xl">
        Keine Buchungen im gewählten Zeitraum.
      </div>
      <q-card
        v-for="b in buchungenMitBestand"
        :key="b.id"
        elevated
        class="q-mb-sm"
        :class="buchungBgClass(b)"
        :style="`border-radius: 14px; overflow: hidden; border-left: 5px solid ${buchungBorderColor(b)}`"
      >
        <q-card-section class="q-py-sm q-px-md">
          <!-- Beleg + Datum -->
          <div class="row items-center q-mb-xs">
            <span class="text-caption text-grey col">
              {{ b.belegnummer }}
            </span>
            <q-chip v-if="b.exportiert_in_export_id" dense icon="lock" color="grey-4" text-color="grey-8" size="sm" class="q-ml-xs">
              Exportiert
            </q-chip>
            <q-chip v-if="b.deleted_at" dense icon="block" color="grey-4" text-color="grey-8" size="sm" class="q-ml-xs">
              Storniert
            </q-chip>
            <span class="text-caption text-grey q-ml-sm">{{ b.buchungsdatum }}</span>
          </div>

          <!-- Buchungstext + Kategorie -->
          <div class="text-body2 text-weight-medium" :class="b.deleted_at ? 'text-grey text-strike' : ''">
            {{ b.buchungstext }}
          </div>
          <div v-if="b.kategorie" class="text-caption text-grey q-mb-xs">{{ b.kategorie }}</div>

          <!-- Betrag + laufender Bestand -->
          <div class="row items-center q-mt-sm">
            <div class="col" />
            <div class="text-right">
              <div
                v-if="b.einnahme_cent > 0"
                class="row items-center justify-end q-gutter-xs"
                :class="b.deleted_at ? 'text-grey text-strike' : 'text-positive'"
              >
                <q-icon name="arrow_circle_up" size="sm" />
                <span class="text-subtitle1 text-weight-bold">{{ formatEuro(b.einnahme_cent) }}</span>
              </div>
              <div
                v-if="b.ausgabe_cent > 0"
                class="row items-center justify-end q-gutter-xs"
                :class="b.deleted_at ? 'text-grey text-strike' : 'text-negative'"
              >
                <q-icon name="arrow_circle_down" size="sm" />
                <span class="text-subtitle1 text-weight-bold">{{ formatEuro(b.ausgabe_cent) }}</span>
              </div>
              <div v-if="b.laufender_bestand_cent !== null" class="text-caption text-grey">
                Bestand {{ formatEuro(b.laufender_bestand_cent) }}
              </div>
            </div>
          </div>
        </q-card-section>

        <!-- Aktions-Zeile -->
        <q-card-actions class="q-px-sm q-py-xs">
          <q-btn flat round icon="attach_file" color="grey" size="md" @click="openAnhangDialog(b)">
            <q-badge v-if="b.anhang_count > 0" color="primary" floating>{{ b.anhang_count }}</q-badge>
            <q-tooltip>Anhänge</q-tooltip>
          </q-btn>
          <q-btn flat round icon="history" color="grey" size="md" @click="openHistoryDialog(b)">
            <q-tooltip>Änderungshistorie</q-tooltip>
          </q-btn>
          <q-space />
          <template v-if="kannSchreiben && !b.deleted_at && !b.exportiert_in_export_id">
            <q-btn flat round icon="edit" color="primary" size="md" @click="openEditDialog(b)" />
            <q-btn flat round icon="block" color="negative" size="md" @click="confirmStornieren(b)">
              <q-tooltip>Stornieren</q-tooltip>
            </q-btn>
          </template>
        </q-card-actions>
      </q-card>
    </template>

    <!-- ── Desktop: Tabelle ── -->
    <q-table
      v-else
      :rows="buchungenMitBestand"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      bordered
      :rows-per-page-options="[25, 50, 100, 0]"
    >
      <template #body="props">
        <q-tr :props="props" :style="rowBgStyle(props.row)">
          <q-td key="belegnummer" :props="props">
            <span :class="props.row.deleted_at ? 'text-strike text-grey' : ''">
              {{ props.row.belegnummer }}
            </span>
            <q-icon v-if="props.row.exportiert_in_export_id" name="lock" size="xs" color="grey" class="q-ml-xs">
              <q-tooltip>Exportiert – nicht mehr änderbar</q-tooltip>
            </q-icon>
          </q-td>

          <q-td key="buchungsdatum" :props="props" :class="props.row.deleted_at ? 'text-grey' : ''">
            {{ props.row.buchungsdatum }}
          </q-td>

          <q-td key="buchungstext" :props="props" :class="props.row.deleted_at ? 'text-grey text-strike' : ''">
            {{ props.row.buchungstext }}
          </q-td>

          <q-td key="kategorie" :props="props" :class="props.row.deleted_at ? 'text-grey' : ''">
            {{ props.row.kategorie }}
          </q-td>

          <q-td key="einnahme" :props="props" class="text-right">
            <div v-if="props.row.einnahme_cent > 0" class="row items-center justify-end q-gutter-xs no-wrap"
              :class="props.row.deleted_at ? 'text-grey text-strike' : 'text-positive'">
              <q-icon name="arrow_circle_up" size="xs" />
              <span>{{ formatEuro(props.row.einnahme_cent) }}</span>
            </div>
          </q-td>

          <q-td key="ausgabe" :props="props" class="text-right">
            <div v-if="props.row.ausgabe_cent > 0" class="row items-center justify-end q-gutter-xs no-wrap"
              :class="props.row.deleted_at ? 'text-grey text-strike' : 'text-negative'">
              <q-icon name="arrow_circle_down" size="xs" />
              <span>{{ formatEuro(props.row.ausgabe_cent) }}</span>
            </div>
          </q-td>

          <q-td key="bestand" :props="props" class="text-right text-weight-bold" :class="props.row.deleted_at ? 'text-grey' : ''">
            <span v-if="props.row.laufender_bestand_cent !== null">
              {{ formatEuro(props.row.laufender_bestand_cent) }}
            </span>
          </q-td>

          <q-td key="created_by" :props="props" :class="props.row.deleted_at ? 'text-grey' : ''">
            {{ props.row.created_by }}
          </q-td>

          <q-td key="actions" :props="props" class="q-gutter-xs" style="white-space: nowrap">
            <q-btn flat dense round icon="attach_file" color="grey" size="sm" @click="openAnhangDialog(props.row)">
              <q-badge v-if="props.row.anhang_count > 0" color="primary" floating>{{ props.row.anhang_count }}</q-badge>
              <q-tooltip>Anhänge</q-tooltip>
            </q-btn>
            <q-btn flat dense round icon="history" color="grey" size="sm" @click="openHistoryDialog(props.row)">
              <q-tooltip>Änderungshistorie</q-tooltip>
            </q-btn>
            <template v-if="kannSchreiben && !props.row.deleted_at && !props.row.exportiert_in_export_id">
              <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openEditDialog(props.row)" />
              <q-btn flat dense round icon="block" color="negative" size="sm" @click="confirmStornieren(props.row)">
                <q-tooltip>Stornieren</q-tooltip>
              </q-btn>
            </template>
          </q-td>
        </q-tr>
      </template>
    </q-table>

    <!-- Buchung anlegen / bearbeiten -->
    <q-dialog
      v-model="buchungDialogOpen"
      persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 460px'">
        <q-card-section class="text-h6">
          {{ editingBuchungId ? 'Buchung bearbeiten' : (buchungTyp === 'einnahme' ? 'Neue Einnahme' : 'Neue Ausgabe') }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input
            v-model="buchungForm.buchungsdatum"
            type="date"
            label="Datum *"
            outlined
            :min="datumMin ?? undefined"
            :max="datumMax"
          />
          <q-input v-model="buchungForm.buchungstext" label="Buchungstext *" outlined />
          <q-input v-model="buchungForm.kategorie" label="Kategorie" outlined />
          <q-btn-toggle
            v-model="buchungTyp"
            :options="[{ label: 'Einnahme', value: 'einnahme' }, { label: 'Ausgabe', value: 'ausgabe' }]"
            unelevated
            spread
            :toggle-color="buchungTyp === 'einnahme' ? 'positive' : 'negative'"
          />
          <q-input
            v-model.number="buchungBetragEuro"
            :label="buchungTyp === 'einnahme' ? 'Einnahme (€)' : 'Ausgabe (€)'"
            outlined
            type="number"
            step="0.01"
            min="0"
            inputmode="decimal"
          />
          <q-input v-model="buchungForm.notiz" label="Notiz" outlined type="textarea" rows="2" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            :label="editingBuchungId ? 'Speichern' : (buchungTyp === 'einnahme' ? 'Einnahme buchen' : 'Ausgabe buchen')"
            :color="buchungTyp === 'einnahme' ? 'positive' : 'negative'"
            unelevated
            :loading="buchungSaving"
            @click="onSaveBuchung"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Export-Dialog -->
    <q-dialog
      v-model="exportDialog"
      persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 520px; max-width: 680px'">
        <q-card-section class="text-h6">CSV-Export</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input
            v-model="exportBisDatum"
            type="date"
            label="Bis-Datum *"
            outlined
            :max="today"
            hint="Alle noch nicht exportierten Buchungen bis einschließlich dieses Datums werden gesperrt."
          />
        </q-card-section>

        <q-separator />

        <q-card-section>
          <div class="text-subtitle2 q-mb-sm">Bisherige Exporte</div>
          <q-table
            :rows="exporte"
            :columns="exportColumns"
            row-key="id"
            :loading="exporteLoading"
            flat
            dense
            hide-bottom
            no-data-label="Noch keine Exporte."
          >
            <template #body-cell-actions="props">
              <q-td :props="props">
                <q-btn flat dense round icon="download" color="primary" size="sm"
                  @click="redownload(props.row)">
                  <q-tooltip>Erneut herunterladen</q-tooltip>
                </q-btn>
              </q-td>
            </template>
          </q-table>
        </q-card-section>

        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            label="Exportieren & sperren"
            color="primary"
            unelevated
            :loading="exportLoading"
            :disable="!exportBisDatum"
            @click="doExport"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- PDF-Bericht-Dialog -->
    <q-dialog
      v-model="pdfDialog"
      persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 420px'">
        <q-card-section class="text-h6">PDF-Kassenbericht</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="pdfVon" type="date" label="Von *" outlined :max="pdfBis || today" />
          <q-input v-model="pdfBis" type="date" label="Bis *" outlined :min="pdfVon" :max="today" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            label="PDF erstellen"
            icon="picture_as_pdf"
            color="secondary"
            unelevated
            :loading="pdfLoading"
            :disable="!pdfVon || !pdfBis"
            @click="doPdfDownload"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- History-Dialog -->
    <q-dialog v-model="historyDialogOpen" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 520px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Änderungshistorie</div>
          <div v-if="historyBuchung" class="text-caption text-grey q-ml-sm">
            {{ historyBuchung.belegnummer }} · {{ historyBuchung.buchungstext }}
          </div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <div v-if="historyLoading" class="row justify-center q-py-md">
            <q-spinner size="32px" color="primary" />
          </div>
          <div v-else-if="historyEntries.length === 0" class="text-grey text-center q-py-md">
            Keine Einträge gefunden.
          </div>
          <q-timeline v-else color="grey" layout="dense">
            <template v-for="(h, idx) in historyEntries" :key="idx">
              <!-- Anhang-Events -->
              <q-timeline-entry
                v-if="h._typ === 'anhang_upload' || h._typ === 'anhang_delete'"
                :subtitle="`${h._zeit?.slice(0,16).replace('T',' ')} · ${h._von}`"
                :color="h._typ === 'anhang_delete' ? 'negative' : 'teal'"
                :icon="h._typ === 'anhang_delete' ? 'delete' : 'attach_file'"
              >
                <div class="text-caption">
                  <span class="text-grey">{{ h._typ === 'anhang_delete' ? 'Anhang gelöscht: ' : 'Anhang hochgeladen: ' }}</span>
                  {{ h._name }}
                </div>
              </q-timeline-entry>

              <!-- Buchungs-Events -->
              <q-timeline-entry
                v-else
                :subtitle="`v${h.version} · ${h.updated_at?.slice(0,16).replace('T',' ')} · ${h.updated_by}`"
                :color="h.deleted_at ? 'negative' : h.version === 1 ? 'positive' : 'primary'"
                :icon="h.deleted_at ? 'block' : h.version === 1 ? 'add_circle' : 'edit'"
              >
                <div v-if="h.deleted_at" class="text-negative text-caption">Storniert</div>
                <div v-else-if="buchungVersionIdx(idx) === 0" class="text-caption">
                  <div><span class="text-grey">Text: </span>{{ h.buchungstext }}</div>
                  <div v-if="h.kategorie"><span class="text-grey">Kategorie: </span>{{ h.kategorie }}</div>
                  <div v-if="h.buchungsdatum"><span class="text-grey">Datum: </span>{{ h.buchungsdatum }}</div>
                  <div v-if="h.einnahme_cent > 0"><span class="text-grey">Einnahme: </span><span class="text-positive">{{ formatEuro(h.einnahme_cent) }}</span></div>
                  <div v-if="h.ausgabe_cent > 0"><span class="text-grey">Ausgabe: </span><span class="text-negative">{{ formatEuro(h.ausgabe_cent) }}</span></div>
                  <div v-if="h.notiz"><span class="text-grey">Notiz: </span>{{ h.notiz }}</div>
                </div>
                <div v-else class="text-caption">
                  <template v-for="diff in historyDiff(prevBuchungVersion(idx), h)" :key="diff.feld">
                    <div>
                      <span class="text-grey">{{ diff.feld }}: </span>
                      <span class="text-strike text-grey-6">{{ diff.alt }}</span>
                      <q-icon name="arrow_forward" size="xs" class="q-mx-xs text-grey" />
                      <span class="text-weight-medium">{{ diff.neu }}</span>
                    </div>
                  </template>
                </div>
              </q-timeline-entry>
            </template>
          </q-timeline>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Anhang-Dialog -->
    <q-dialog
      v-model="anhangDialogOpen"
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width: 100%; border-radius: 16px 16px 0 0' : 'min-width: 460px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Anhänge</div>
          <div v-if="anhangBuchung" class="text-caption text-grey q-ml-sm">
            {{ anhangBuchung.belegnummer }} · {{ anhangBuchung.buchungstext }}
          </div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <anhang-panel
            :anhaenge="anhaenge"
            :upload-url="`/api/kassen/${kasseId}/buchungen/${anhangBuchung?.id}/anhaenge`"
            :can-upload="kannSchreiben && !!anhangBuchung && !anhangBuchung.deleted_at && !anhangBuchung.exportiert_in_export_id"
            :can-delete="kannSchreiben"
            @uploaded="onAnhangUploaded"
            @deleted="onAnhangDeleted"
          />
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import AnhangPanel from 'src/components/AnhangPanel.vue'

const $q = useQuasar()
const route = useRoute()
const auth = useAuthStore()

const kasseId = computed(() => Number(route.params.kasseId))
const isAdmin = computed(() => auth.user?.role === 'admin')

const kasse = ref(null)
const bestandCent = ref(0)
const buchungen = ref([])
const exporte = ref([])
const loading = ref(false)
const exporteLoading = ref(false)

const today = new Date().toISOString().slice(0, 10)
const vor90Tagen = (() => {
  const d = new Date()
  d.setDate(d.getDate() - 90)
  return d.toISOString().slice(0, 10)
})()

const filterVon = ref(vor90Tagen)
const filterBis = ref('')
const showStorniert = ref(false)
const filterOpen = ref(false)

const filterAktiv = computed(() => !!filterBis.value || showStorniert.value)

const datumMin = ref(null)
const datumMax = ref('')

const kannSchreiben = computed(() => isAdmin.value || !!kasse.value?.darf_schreiben)
const kannExportieren = computed(() => isAdmin.value || !!kasse.value?.darf_exportieren)

const buchungDialogOpen = ref(false)
const buchungSaving = ref(false)
const editingBuchungId = ref(null)
const editingBuchungVersion = ref(null)
const buchungTyp = ref('einnahme')
const buchungBetragEuro = ref(0)
const buchungForm = ref(emptyBuchungForm())

const exportDialog = ref(false)
const exportLoading = ref(false)
const exportBisDatum = ref(today)

const pdfDialog = ref(false)
const pdfLoading = ref(false)
const pdfVon = ref(vor90Tagen)
const pdfBis = ref(today)

const anhangDialogOpen = ref(false)
const anhangBuchung = ref(null)
const anhaenge = ref([])

const historyDialogOpen = ref(false)
const historyBuchung = ref(null)
const historyEntries = ref([])
const historyLoading = ref(false)

// Laufenden Bestand je Buchung berechnen.
// Strategie: rückwärts vom bekannten Gesamtbestand (bestandCent) — kein Extra-API-Aufruf nötig,
// funktioniert auch wenn der Filter nur einen Ausschnitt zeigt.
const buchungenMitBestand = computed(() => {
  // Neueste zuerst anzeigen → Backend-Liste (älteste zuerst) umkehren
  const neuesteZuerst = [...buchungen.value].reverse()
  let bestand = bestandCent.value
  return neuesteZuerst.map(b => {
    const laufend = b.deleted_at ? null : bestand
    if (!b.deleted_at) {
      // Bestand vor dieser Buchung (rückwärts)
      bestand = bestand - b.einnahme_cent + b.ausgabe_cent
    }
    return { ...b, laufender_bestand_cent: laufend }
  })
})

const columns = [
  { name: 'belegnummer', label: 'Beleg', field: 'belegnummer', align: 'left', style: 'width: 80px' },
  { name: 'buchungsdatum', label: 'Datum', field: 'buchungsdatum', align: 'left' },
  { name: 'buchungstext', label: 'Buchungstext', field: 'buchungstext', align: 'left' },
  { name: 'kategorie', label: 'Kategorie', field: 'kategorie', align: 'left' },
  { name: 'einnahme', label: 'Einnahme', field: 'einnahme_cent', align: 'right' },
  { name: 'ausgabe', label: 'Ausgabe', field: 'ausgabe_cent', align: 'right' },
  { name: 'bestand', label: 'Bestand', field: 'laufender_bestand_cent', align: 'right' },
  { name: 'created_by', label: 'Erfasst von', field: 'created_by', align: 'left' },
  { name: 'actions', label: '', field: 'actions', align: 'right', style: 'width: 120px' },
]

const exportColumns = [
  { name: 'zeitraum', label: 'Zeitraum', field: r => `${r.zeitraum_von} – ${r.zeitraum_bis}`, align: 'left' },
  { name: 'dateiname', label: 'Dateiname', field: 'dateiname', align: 'left' },
  { name: 'anzahl_buchungen', label: 'Buchungen', field: 'anzahl_buchungen', align: 'right' },
  { name: 'actions', label: '', field: 'actions', align: 'right' },
]

function rowBgStyle(row) {
  const dark = $q.dark.isActive
  if (row.deleted_at) return { backgroundColor: dark ? '#1a1a1e' : '#fafafa' }
  if (row.einnahme_cent > 0) return { backgroundColor: dark ? '#1a2e1a' : '#f1f8e9' }
  return { backgroundColor: dark ? '#2e1a1a' : '#ffebee' }
}

function buchungBorderColor(b) {
  if (b.deleted_at) return '#9e9e9e'
  if (b.einnahme_cent > 0) return '#4caf50'
  return '#f44336'
}

function buchungBgClass(b) {
  if (b.deleted_at) return 'bg-grey-1'
  if (b.einnahme_cent > 0) return 'bg-green-1'
  return 'bg-red-1'
}

function formatEuro(cent) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(cent / 100)
}

function emptyBuchungForm() {
  return { buchungsdatum: today, buchungstext: '', kategorie: '', notiz: '' }
}

async function applyFilter() {
  filterOpen.value = false
  await Promise.all([loadBuchungen(), loadBestand()])
}

async function loadAll() {
  await Promise.all([loadKasse(), loadBuchungen(), loadBestand(), loadDatumBereich()])
}

async function loadKasse() {
  try {
    const { data } = await api.get('/api/kassen/')
    kasse.value = data.find(k => k.id === kasseId.value) ?? null
  } catch { /* ignorieren */ }
}

async function loadBestand() {
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/bestand`)
    bestandCent.value = data.bestand_cent
  } catch { /* ignorieren */ }
}

async function loadBuchungen() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (filterVon.value) params.append('von', filterVon.value)
    if (filterBis.value) params.append('bis', filterBis.value)
    if (showStorniert.value) params.append('storniert', 'true')
    const { data } = await api.get(`/api/kassen/${kasseId.value}/buchungen?${params}`)
    buchungen.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden.' })
  } finally {
    loading.value = false
  }
}

async function loadExporte() {
  exporteLoading.value = true
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/exporte`)
    exporte.value = data
  } catch { /* ignorieren */ } finally {
    exporteLoading.value = false
  }
}

async function loadDatumBereich() {
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/datum-bereich`)
    datumMin.value = data.min_datum
    datumMax.value = data.max_datum
  } catch { /* ignorieren */ }
}

function openCreateDialog(typ) {
  editingBuchungId.value = null
  editingBuchungVersion.value = null
  buchungTyp.value = typ
  buchungBetragEuro.value = 0
  buchungForm.value = emptyBuchungForm()
  buchungDialogOpen.value = true
}

function openEditDialog(buchung) {
  editingBuchungId.value = buchung.id
  editingBuchungVersion.value = buchung.version
  buchungTyp.value = buchung.einnahme_cent > 0 ? 'einnahme' : 'ausgabe'
  buchungBetragEuro.value = buchung.einnahme_cent > 0
    ? buchung.einnahme_cent / 100
    : buchung.ausgabe_cent / 100
  buchungForm.value = {
    buchungsdatum: buchung.buchungsdatum,
    buchungstext: buchung.buchungstext,
    kategorie: buchung.kategorie || '',
    notiz: buchung.notiz || '',
  }
  buchungDialogOpen.value = true
}

async function onSaveBuchung() {
  if (!buchungForm.value.buchungstext.trim()) {
    $q.notify({ type: 'warning', message: 'Bitte den Buchungstext ausfüllen.' })
    return
  }
  buchungSaving.value = true
  const betragCent = Math.round(buchungBetragEuro.value * 100)
  const payload = {
    buchungsdatum: buchungForm.value.buchungsdatum,
    buchungstext: buchungForm.value.buchungstext.trim(),
    kategorie: buchungForm.value.kategorie.trim(),
    notiz: buchungForm.value.notiz || null,
    einnahme_cent: buchungTyp.value === 'einnahme' ? betragCent : 0,
    ausgabe_cent: buchungTyp.value === 'ausgabe' ? betragCent : 0,
  }
  try {
    if (editingBuchungId.value) {
      await api.put(
        `/api/kassen/${kasseId.value}/buchungen/${editingBuchungId.value}`,
        { ...payload, expected_version: editingBuchungVersion.value },
      )
    } else {
      await api.post(`/api/kassen/${kasseId.value}/buchungen`, payload)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert.' })
    buchungDialogOpen.value = false
    await Promise.all([loadBuchungen(), loadBestand()])
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    buchungSaving.value = false
  }
}

function confirmStornieren(buchung) {
  $q.dialog({
    title: 'Buchung stornieren',
    message: `Buchung Nr. ${buchung.belegnummer} „${buchung.buchungstext}" stornieren?`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/kassen/${kasseId.value}/buchungen/${buchung.id}`)
      $q.notify({ type: 'positive', message: 'Buchung storniert.' })
      await Promise.all([loadBuchungen(), loadBestand()])
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Stornieren.' })
    }
  })
}

function openExportDialog() {
  const heute = new Date()
  exportBisDatum.value = isoDate(new Date(heute.getFullYear(), heute.getMonth(), 0))
  exportDialog.value = true
  loadExporte()
}

async function doExport() {
  exportLoading.value = true
  try {
    const response = await api.post(
      `/api/kassen/${kasseId.value}/exporte`,
      { bis_datum: exportBisDatum.value },
      { responseType: 'blob' },
    )
    const disposition = response.headers['content-disposition'] || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    const filename = match ? match[1] : `kassenbuch-export-${exportBisDatum.value}.csv`
    const url = URL.createObjectURL(new Blob([response.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    $q.notify({ type: 'positive', message: `Export erstellt: ${filename}` })
    exportDialog.value = false
    await Promise.all([loadBuchungen(), loadExporte(), loadDatumBereich()])
  } catch (e) {
    if (e.response?.data instanceof Blob) {
      const text = await e.response.data.text()
      try { $q.notify({ type: 'negative', message: JSON.parse(text).detail || 'Fehler.' }) }
      catch { $q.notify({ type: 'negative', message: 'Fehler beim Export.' }) }
    } else {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Export.' })
    }
  } finally {
    exportLoading.value = false
  }
}

async function redownload(exportObj) {
  try {
    const response = await api.get(
      `/api/kassen/${kasseId.value}/exporte/${exportObj.id}/download`,
      { responseType: 'blob' },
    )
    const disposition = response.headers['content-disposition'] || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    const filename = match ? match[1] : exportObj.dateiname
    const url = URL.createObjectURL(new Blob([response.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Download.' })
  }
}

function buchungVersionIdx(idx) {
  // Wie viele Buchungs-Versionen (ohne Anhang-Events) liegen nach diesem Eintrag? (0 = älteste)
  return historyEntries.value.slice(idx + 1).filter(e => e._typ === 'buchung').length
}

function prevBuchungVersion(idx) {
  // Nächster Buchungs-Eintrag hinter idx (= ältere Version in umgekehrter Liste)
  return historyEntries.value.slice(idx + 1).find(e => e._typ === 'buchung')
}

function historyDiff(prev, curr) {
  const felder = [
    { key: 'buchungstext',  label: 'Text' },
    { key: 'buchungsdatum', label: 'Datum' },
    { key: 'kategorie',     label: 'Kategorie' },
    { key: 'notiz',         label: 'Notiz' },
    { key: 'einnahme_cent', label: 'Einnahme', fmt: v => v ? formatEuro(v) : '—' },
    { key: 'ausgabe_cent',  label: 'Ausgabe',  fmt: v => v ? formatEuro(v) : '—' },
  ]
  return felder
    .filter(f => (prev[f.key] ?? '') !== (curr[f.key] ?? ''))
    .map(f => ({
      feld: f.label,
      alt:  f.fmt ? f.fmt(prev[f.key]) : (prev[f.key] || '—'),
      neu:  f.fmt ? f.fmt(curr[f.key]) : (curr[f.key] || '—'),
    }))
}

async function openHistoryDialog(buchung) {
  historyBuchung.value = buchung
  historyEntries.value = []
  historyDialogOpen.value = true
  historyLoading.value = true
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/buchungen/${buchung.id}/history`)
    const buchungEvents = data.buchungen.map(h => ({ ...h, _typ: 'buchung' }))
    const anhangEvents = data.anhaenge.flatMap(a => {
      const events = [{ _typ: 'anhang_upload', _zeit: a.hochgeladen_am, _name: a.original_name, _von: a.hochgeladen_von }]
      if (a.deleted_at) events.push({ _typ: 'anhang_delete', _zeit: a.deleted_at, _name: a.original_name, _von: a.deleted_by })
      return events
    })
    const alle = [...buchungEvents, ...anhangEvents].sort((a, b) => {
      const tA = a._typ === 'buchung' ? a.updated_at : a._zeit
      const tB = b._typ === 'buchung' ? b.updated_at : b._zeit
      return tA < tB ? -1 : tA > tB ? 1 : 0
    })
    historyEntries.value = alle.reverse()
  } catch {
    $q.notify({ type: 'negative', message: 'Historie konnte nicht geladen werden.' })
  } finally {
    historyLoading.value = false
  }
}

async function openAnhangDialog(buchung) {
  anhangBuchung.value = buchung
  anhaenge.value = []
  anhangDialogOpen.value = true
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/buchungen/${buchung.id}/anhaenge`)
    anhaenge.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Anhänge konnten nicht geladen werden.' })
  }
}

function onAnhangUploaded(newAnhang) {
  anhaenge.value = [...anhaenge.value, newAnhang]
  const b = buchungen.value.find(b => b.id === anhangBuchung.value?.id)
  if (b) b.anhang_count = (b.anhang_count || 0) + 1
}

function onAnhangDeleted(anhangId) {
  anhaenge.value = anhaenge.value.filter(a => a.id !== anhangId)
  const b = buchungen.value.find(b => b.id === anhangBuchung.value?.id)
  if (b && b.anhang_count > 0) b.anhang_count--
}

function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function openPdfDialog() {
  const heute = new Date()
  const letzterVormonat = new Date(heute.getFullYear(), heute.getMonth(), 0)
  pdfBis.value = isoDate(letzterVormonat)

  if (exporte.value.length > 0) {
    const letzterExport = [...exporte.value].sort((a, b) =>
      b.zeitraum_bis.localeCompare(a.zeitraum_bis)
    )[0]
    const tagNach = new Date(letzterExport.zeitraum_bis)
    tagNach.setDate(tagNach.getDate() + 1)
    pdfVon.value = isoDate(tagNach)
  } else {
    pdfVon.value = isoDate(new Date(letzterVormonat.getFullYear(), letzterVormonat.getMonth(), 1))
  }

  pdfDialog.value = true
}

async function doPdfDownload() {
  pdfLoading.value = true
  try {
    const { data } = await api.get(`/api/kassen/${kasseId.value}/bericht.pdf`, {
      params: { von: pdfVon.value, bis: pdfBis.value },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(new Blob([data], { type: 'application/pdf' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `kassenbuch_${pdfVon.value}_${pdfBis.value}.pdf`
    a.click()
    URL.revokeObjectURL(url)
    pdfDialog.value = false
  } catch {
    $q.notify({ type: 'negative', message: 'PDF konnte nicht erstellt werden.' })
  } finally {
    pdfLoading.value = false
  }
}

onMounted(loadAll)
</script>
