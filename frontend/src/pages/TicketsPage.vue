<template>
  <q-page padding>
    <!-- Kopfzeile -->
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Tickets</div>
      <q-btn
        icon="add"
        :label="$q.screen.gt.sm ? 'Neues Ticket' : undefined"
        :round="$q.screen.lt.md"
        color="primary"
        unelevated
        @click="openCreateDialog"
      />
    </div>

    <!-- Filter -->
    <div class="row q-gutter-sm q-mb-md items-center">
      <q-select
        v-model="filterBereich"
        :options="bereichOptions"
        label="Bereich"
        outlined dense clearable
        style="min-width: 160px"
        option-value="id"
        option-label="name"
        emit-value map-options
      />
      <q-select
        v-model="filterStatus"
        :options="statusOptions"
        label="Status"
        outlined dense clearable
        style="min-width: 150px"
        emit-value map-options
      />
      <q-checkbox v-model="filterNurMeine" label="Nur meine" />
      <q-checkbox v-model="filterMitAbgeschlossenen" label="Abgeschlossene" />
      <q-checkbox v-if="kannVerwaltenIrgendwas" v-model="zeigeGeloeschte"
        color="negative" label="Gelöschte anzeigen" />
    </div>

    <q-banner v-if="zeigeGeloeschte" dense class="bg-red-1 text-red-10 q-mb-md" rounded>
      <template #avatar><q-icon name="delete_sweep" color="negative" /></template>
      Gelöschte (verborgene) Tickets – für die öffentliche Ansicht ausgeblendet.
      Verwalter können sie wiederherstellen.
    </q-banner>

    <!-- ── Mobile: Karten-Liste ── -->
    <template v-if="$q.screen.lt.md">
      <div v-if="loading" class="row justify-center q-py-xl">
        <q-spinner size="40px" color="primary" />
      </div>
      <div v-else-if="filteredTickets.length === 0" class="text-center text-grey q-py-xl">
        Keine Tickets gefunden.
      </div>
      <q-card
        v-for="t in filteredTickets"
        :key="t.id"
        elevated
        :class="`q-mb-md cursor-pointer ${statusBgClass(t.status)}`"
        :style="`border-radius: 14px; overflow: hidden; border-left: 5px solid ${prioritaetBorderColor(t.prioritaet)}`"
        @click="openDetailDialog(t)"
      >
        <q-card-section class="q-py-md q-px-md">
          <div class="row items-center q-mb-sm no-wrap">
            <span class="text-caption text-grey-5 col">#{{ t.id }}</span>
            <q-chip dense :color="statusColor(t.status)" text-color="white" :label="statusLabel(t.status)" />
            <q-btn v-if="zeigeGeloeschte" flat round dense icon="restore" color="primary" size="sm"
              @click.stop="onRestore(t)">
              <q-tooltip>Wiederherstellen</q-tooltip>
            </q-btn>
          </div>
          <div class="text-subtitle1 text-weight-bold q-mb-xs" style="line-height: 1.3">{{ t.titel }}</div>
          <div v-if="t.bereich_name" class="row items-center q-mb-sm">
            <q-icon name="folder_open" size="xs" color="grey-5" class="q-mr-xs" />
            <span class="text-body2 text-grey-7">{{ t.bereich_name }}</span>
          </div>
          <div class="row items-center text-caption text-grey-6 q-mt-xs">
            <q-icon name="person_outline" size="xs" class="q-mr-xs" />
            <span class="col">{{ t.gemeldet_von_username }}</span>
            <span v-if="t.kommentar_count > 0" class="q-mr-sm">
              <q-icon name="chat_bubble_outline" size="xs" /> {{ t.kommentar_count }}
            </span>
            <span v-if="t.anhang_count > 0" class="q-mr-sm">
              <q-icon name="attach_file" size="xs" /> {{ t.anhang_count }}
            </span>
            <span>{{ formatDate(t.created_at) }}</span>
          </div>
        </q-card-section>
      </q-card>
    </template>

    <!-- ── Desktop: Tabelle ── -->
    <q-table
      v-else
      :rows="filteredTickets"
      :columns="tableColumns"
      row-key="id"
      flat bordered
      :loading="loading"
      :rows-per-page-options="[25, 50, 0]"
      @row-click="(_, row) => openDetailDialog(row)"
      class="cursor-pointer"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-chip dense :color="statusColor(props.row.status)" text-color="white"
            :label="statusLabel(props.row.status)" size="sm" />
        </q-td>
      </template>
      <template #body-cell-prioritaet="props">
        <q-td :props="props">
          <div class="row items-center q-gutter-xs no-wrap">
            <q-icon :name="prioritaetIcon(props.row.prioritaet)" :color="prioritaetColor(props.row.prioritaet)" size="sm" />
            <span :class="`text-${prioritaetColor(props.row.prioritaet)} text-caption text-weight-medium`">
              {{ prioritaetLabel(props.row.prioritaet) }}
            </span>
          </div>
        </q-td>
      </template>
      <template #body-cell-counts="props">
        <q-td :props="props" class="text-grey">
          <span v-if="props.row.kommentar_count > 0" class="q-mr-sm">
            <q-icon name="chat_bubble_outline" size="xs" /> {{ props.row.kommentar_count }}
          </span>
          <span v-if="props.row.anhang_count > 0">
            <q-icon name="attach_file" size="xs" /> {{ props.row.anhang_count }}
          </span>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" @click.stop>
          <q-btn flat round dense icon="restore" color="primary" size="sm"
            @click="onRestore(props.row)">
            <q-tooltip>Wiederherstellen</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>


    <!-- ── Bereich-Vorauswahl beim Anlegen ── -->
    <q-dialog v-model="pickBereichOpen" persistent>
      <q-card style="min-width: 340px">
        <q-card-section class="text-h6">Neues Ticket</q-card-section>
        <q-separator />
        <q-card-section>
          <q-select
            v-model="pickBereichId"
            :options="bereichOptions"
            label="Bereich *"
            outlined autofocus
            option-value="id" option-label="name"
            emit-value map-options
          />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            label="Weiter"
            icon="arrow_forward"
            color="primary" unelevated
            :disable="!pickBereichId"
            :loading="saving"
            @click="onPickBereichConfirm"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ═══════════════════════════════════════════════════════
         Ticket-Dialog  (Anlegen + Detail in einem Fenster)
    ════════════════════════════════════════════════════════ -->
    <q-dialog v-model="detailDialogOpen" maximized persistent>
      <q-card>
        <q-bar class="bg-primary text-white">
          <q-icon name="confirmation_number" />
          <div class="text-subtitle1 q-ml-sm ellipsis" style="max-width:70vw">
            #{{ selectedTicket?.id }}
            <span v-if="!canWrite"> – {{ selectedTicket?.titel }}</span>
          </div>
          <q-space />
          <q-btn flat round dense icon="close" @click="closeDetailDialog" />
        </q-bar>

        <q-scroll-area style="height: calc(100vh - 50px)">
          <div class="q-pa-md" style="max-width: 800px; margin: 0 auto">
            <template v-if="selectedTicket">

              <!-- ── Gelöscht-Hinweis + Wiederherstellen ── -->
              <q-banner v-if="selectedIstGeloescht" class="bg-red-1 text-red-10 q-mb-md" rounded>
                <template #avatar><q-icon name="delete" color="negative" /></template>
                Dieses Ticket ist verborgen (gelöscht{{ selectedTicket.deleted_by ? ' von ' + selectedTicket.deleted_by : '' }}).
                Es erscheint nicht in der öffentlichen Ansicht.
                <template v-if="canVerwaltenSelected" #action>
                  <q-btn flat color="negative" icon="restore" label="Wiederherstellen" @click="onRestore()" />
                </template>
              </q-banner>

              <!-- ── Editierbare Felder (wenn Schreibrecht) ── -->
              <template v-if="canWrite && !selectedIstGeloescht">
                <q-input
                  v-model="detailForm.titel"
                  label="Titel *"
                  outlined
                  :autofocus="isDraftTicket"
                  class="q-mb-sm"
                />
                <q-input
                  v-model="detailForm.beschreibung"
                  label="Beschreibung"
                  outlined
                  type="textarea"
                  rows="4"
                  class="q-mb-sm"
                />
                <div class="row q-gutter-sm q-mb-sm">
                  <q-select
                    v-model="detailForm.bereich_id"
                    :options="bereichOptions"
                    label="Bereich *"
                    outlined dense
                    class="col"
                    option-value="id"
                    option-label="name"
                    emit-value map-options
                    :rules="[v => !!v || 'Pflichtfeld']"
                  />
                  <q-select
                    v-model="detailForm.kategorie_id"
                    :options="kategorieOptions"
                    label="Kategorie"
                    outlined dense clearable
                    class="col"
                    option-value="id"
                    option-label="name"
                    emit-value map-options
                  />
                </div>
                <div class="row q-gutter-sm q-mb-sm">
                  <q-select
                    v-model="detailForm.prioritaet"
                    :options="prioritaetOptions"
                    label="Priorität"
                    outlined dense
                    class="col"
                    emit-value map-options
                  />
                  <q-input
                    v-model="detailForm.faellig_am"
                    type="date"
                    label="Fällig am"
                    outlined dense
                    clearable
                    class="col"
                  />
                </div>
                <div class="row justify-end q-mb-md">
                  <q-btn
                    v-if="detailFormDirty"
                    label="Speichern"
                    icon="save"
                    color="primary"
                    unelevated
                    size="sm"
                    :loading="detailSaving"
                    @click="onDetailSave"
                  />
                </div>
              </template>

              <!-- ── Nur-Lesen-Ansicht ── -->
              <template v-else>
                <div class="text-h6 q-mb-sm">{{ selectedTicket.titel }}</div>
                <div class="text-body2 q-mb-md" style="white-space: pre-wrap">
                  {{ selectedTicket.beschreibung || '—' }}
                </div>
              </template>

              <!-- Metadaten-Zeile -->
              <div class="row q-gutter-md q-mb-md items-center">
                <div>
                  <div class="text-caption text-grey">Status</div>
                  <q-chip dense :color="statusColor(selectedTicket.status)" text-color="white"
                    :label="statusLabel(selectedTicket.status)" />
                </div>
                <div v-if="!canWrite">
                  <div class="text-caption text-grey">Priorität</div>
                  <div class="row items-center q-gutter-xs">
                    <q-icon :name="prioritaetIcon(selectedTicket.prioritaet)" :color="prioritaetColor(selectedTicket.prioritaet)" />
                    <span>{{ prioritaetLabel(selectedTicket.prioritaet) }}</span>
                  </div>
                </div>
                <div v-if="selectedTicket.faellig_am && !canWrite">
                  <div class="text-caption text-grey">Fällig am</div>
                  <div>{{ formatDate(selectedTicket.faellig_am) }}</div>
                </div>
              </div>

              <!-- Statuswechsel -->
              <div v-if="!isAbgeschlossen(selectedTicket) && canChangeStatus && !selectedIstGeloescht" class="q-mb-md">
                <div class="text-subtitle2 q-mb-xs">Status ändern</div>
                <div class="row q-gutter-sm">
                  <q-btn
                    v-for="s in erlaubteStatus(selectedTicket)"
                    :key="s"
                    outline
                    :color="statusColor(s)"
                    :label="statusLabel(s)"
                    size="sm"
                    @click="doStatusChange(s)"
                  />
                </div>
              </div>

              <!-- Zurückziehen (nur Ersteller, solange offen) -->
              <div v-if="canWithdraw && !isDraftTicket && !selectedIstGeloescht" class="q-mb-md">
                <q-btn
                  label="Ticket zurückziehen"
                  icon="undo"
                  flat
                  color="negative"
                  size="sm"
                  @click="onWithdraw"
                />
              </div>

              <!-- Verbergen / smart löschen (Verwalter) -->
              <div v-if="canVerwaltenSelected && !selectedIstGeloescht && !isDraftTicket" class="q-mb-md">
                <q-btn
                  label="Ticket verbergen"
                  icon="visibility_off"
                  flat
                  color="negative"
                  size="sm"
                  @click="onSmartDelete"
                />
              </div>

              <q-separator class="q-mb-md" />

              <!-- Anhänge -->
              <div class="q-mb-md">
                <div class="text-subtitle2 q-mb-sm">Anhänge</div>
                <anhang-panel
                  :anhaenge="detailAnhaenge"
                  :upload-url="`/api/tickets/${selectedTicket.id}/anhaenge`"
                  :can-upload="!isAbgeschlossen(selectedTicket) && !selectedIstGeloescht"
                  :can-delete="!isAbgeschlossen(selectedTicket) && !selectedIstGeloescht"
                  @uploaded="onAnhangUploaded"
                  @deleted="onAnhangDeleted"
                />
              </div>

              <q-separator class="q-mb-md" />

              <!-- Kommentar-Thread -->
              <div>
                <div class="text-subtitle2 q-mb-sm">
                  Kommentare
                  <q-badge v-if="kommentare.length > 0" color="grey" class="q-ml-xs">{{ kommentare.length }}</q-badge>
                </div>

                <div v-if="kommentareLoading" class="row justify-center q-py-md">
                  <q-spinner color="primary" />
                </div>

                <div v-for="k in kommentare" :key="k.id" class="q-mb-sm">
                  <q-card flat :class="['text-grey-9', k.sichtbarkeit === 'intern' ? 'bg-amber-1' : 'bg-grey-1']">
                    <q-card-section class="q-py-sm q-px-md">
                      <div class="row items-center q-mb-xs">
                        <span class="text-caption text-weight-bold col">{{ k.autor_username }}</span>
                        <q-badge v-if="k.sichtbarkeit === 'intern'" color="amber-8" label="intern" class="q-mr-sm" />
                        <span class="text-caption text-grey">{{ formatDateTime(k.created_at) }}</span>
                        <q-btn
                          v-if="k.autor_id === currentUserId || isAdmin"
                          flat round dense icon="delete" size="xs" color="negative"
                          class="q-ml-xs"
                          @click="deleteKommentar(k)"
                        />
                      </div>
                      <div class="text-body2" style="white-space: pre-wrap">{{ k.inhalt }}</div>
                    </q-card-section>
                  </q-card>
                </div>

                <!-- Neuer Kommentar -->
                <div v-if="!isAbgeschlossen(selectedTicket) && !selectedIstGeloescht" class="q-mt-md">
                  <q-input
                    v-model="neuerKommentar"
                    outlined
                    type="textarea"
                    rows="3"
                    label="Kommentar schreiben…"
                  />
                  <div class="row items-center q-mt-sm q-gutter-sm">
                    <q-toggle
                      v-if="canChangeStatus"
                      v-model="kommentarIntern"
                      label="Intern"
                      color="amber-8"
                      size="sm"
                    />
                    <q-space />
                    <q-btn
                      label="Absenden"
                      icon="send"
                      color="primary"
                      unelevated
                      size="sm"
                      :loading="kommentarSaving"
                      :disable="!neuerKommentar.trim()"
                      @click="sendKommentar"
                    />
                  </div>
                </div>
              </div>

            </template>

          </div>
        </q-scroll-area>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import AnhangPanel from 'src/components/AnhangPanel.vue'
import { formatDate as fmtDate, formatDateTime as fmtDateTime } from 'src/utils/datetime'

const $q = useQuasar()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
const currentUserId = computed(() => auth.user?.id)

// ── Daten ──────────────────────────────────────────────────────────────────
const tickets = ref([])
const bereiche = ref([])
const kategorien = ref([])
const users = ref([])
const loading = ref(false)

// ── Filter ─────────────────────────────────────────────────────────────────
const filterBereich = ref(null)
const filterStatus = ref(null)
const filterNurMeine = ref(false)
const filterMitAbgeschlossenen = ref(false)
// "Einblenden": gelöschte (verborgene) Tickets anzeigen – nur für Verwalter.
const zeigeGeloeschte = ref(false)

// ── Erstellen / Detail ─────────────────────────────────────────────────────
const isDraftTicket = ref(false)
const saving = ref(false)

// ── Detail-Dialog ──────────────────────────────────────────────────────────
const detailDialogOpen = ref(false)
const selectedTicket = ref(null)
const detailAnhaenge = ref([])

// Inline-Edit-Formular im Detail-Dialog
const detailForm = ref({})
const detailSaving = ref(false)
const detailFormDirty = computed(() => {
  if (!selectedTicket.value) return false
  const t = selectedTicket.value
  return (
    detailForm.value.titel !== t.titel ||
    detailForm.value.beschreibung !== (t.beschreibung || '') ||
    detailForm.value.bereich_id !== t.bereich_id ||
    detailForm.value.kategorie_id !== t.kategorie_id ||
    detailForm.value.prioritaet !== t.prioritaet ||
    detailForm.value.faellig_am !== (t.faellig_am || '') ||
    false
  )
})

// ── Kommentare ─────────────────────────────────────────────────────────────
const kommentare = ref([])
const kommentareLoading = ref(false)
const neuerKommentar = ref('')
const kommentarIntern = ref(false)
const kommentarSaving = ref(false)

// ── Berechtigungen ─────────────────────────────────────────────────────────
const meineBerechtigungen = ref({ ist_admin: false, bereiche: {} })

function _bereichFlags(ticket) {
  if (!ticket) return {}
  if (meineBerechtigungen.value.ist_admin) return { darf_lesen: true, darf_bearbeiten: true, darf_schliessen: true }
  return meineBerechtigungen.value.bereiche[String(ticket.bereich_id)] ?? {}
}

const canWrite = computed(() => {
  if (!selectedTicket.value) return false
  if (isAdmin.value) return true
  if (isDraftTicket.value) return true
  const t = selectedTicket.value
  if (t.gemeldet_von === currentUserId.value) return true
  return !!_bereichFlags(t).darf_bearbeiten
})

const canChangeStatus = computed(() => {
  if (!selectedTicket.value) return false
  if (isAdmin.value) return true
  return !!_bereichFlags(selectedTicket.value).darf_bearbeiten
})

const canClose = computed(() => {
  if (!selectedTicket.value) return false
  if (isAdmin.value) return true
  return !!_bereichFlags(selectedTicket.value).darf_schliessen
})

const canWithdraw = computed(() => {
  if (!selectedTicket.value || isAbgeschlossen(selectedTicket.value)) return false
  return selectedTicket.value.gemeldet_von === currentUserId.value
})

// ── Verwalten (verbergen / einblenden / wiederherstellen) ────────────────────
// Verwalter = Admin oder darf_bearbeiten im Bereich. Kategorie hat kein eigenes
// Rechtemodell – die Rechte hängen am Bereich.
function kannVerwalten(ticket) {
  if (isAdmin.value) return true
  return !!_bereichFlags(ticket).darf_bearbeiten
}
const kannVerwaltenIrgendwas = computed(() =>
  isAdmin.value || Object.values(meineBerechtigungen.value.bereiche || {}).some(b => b.darf_bearbeiten)
)
const canVerwaltenSelected = computed(() => kannVerwalten(selectedTicket.value))
const selectedIstGeloescht = computed(() => !!selectedTicket.value?.deleted_at)

// ── Status-/Prioritäts-Konstanten ──────────────────────────────────────────
const STATUS_UEBERGAENGE = {
  offen:       ['in_pruefung', 'erledigt', 'abgelehnt'],
  in_pruefung: ['eingeplant', 'rueckfrage', 'erledigt', 'abgelehnt'],
  eingeplant:  ['in_pruefung', 'erledigt'],
  rueckfrage:  ['in_pruefung', 'abgelehnt'],
  erledigt:    [],
  abgelehnt:   [],
}

const STATUS_LABELS = {
  offen: 'Offen', in_pruefung: 'In Prüfung', eingeplant: 'Eingeplant',
  rueckfrage: 'Rückfrage', erledigt: 'Erledigt', abgelehnt: 'Abgelehnt',
}

const STATUS_COLORS = {
  offen: 'blue', in_pruefung: 'orange', eingeplant: 'purple',
  rueckfrage: 'amber-8', erledigt: 'positive', abgelehnt: 'negative',
}

const statusOptions = Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))

const prioritaetOptions = [
  { value: 'niedrig', label: 'Niedrig' },
  { value: 'normal',  label: 'Normal'  },
  { value: 'hoch',    label: 'Hoch'    },
  { value: 'sicherheit', label: 'Sicherheit' },
]

const bereichOptions = computed(() => bereiche.value)
const kategorieOptions = computed(() => kategorien.value)
const userOptions = computed(() => users.value.map(u => ({ value: u.id, label: u.username })))

const filteredTickets = computed(() => {
  let result = tickets.value
  // In der Gelöscht-Ansicht zeigen wir alle verborgenen Tickets (auch abgeschlossene).
  if (!filterMitAbgeschlossenen.value && !zeigeGeloeschte.value) result = result.filter(t => !isAbgeschlossen(t))
  if (filterBereich.value) result = result.filter(t => t.bereich_id === filterBereich.value)
  if (filterStatus.value)  result = result.filter(t => t.status === filterStatus.value)
  if (filterNurMeine.value) result = result.filter(t =>
    t.gemeldet_von === currentUserId.value ||
    !!_bereichFlags(t).darf_bearbeiten
  )
  return result
})

const columns = [
  { name: 'id',                    label: '#',           field: 'id',                    align: 'left',   sortable: true, style: 'width:55px' },
  { name: 'prioritaet',            label: 'Priorität',   field: 'prioritaet',            align: 'left',   style: 'width:120px' },
  { name: 'titel',                 label: 'Titel',       field: 'titel',                 align: 'left',   sortable: true },
  { name: 'bereich_name',          label: 'Bereich',     field: 'bereich_name',          align: 'left',   sortable: true },
  { name: 'status',                label: 'Status',      field: 'status',                align: 'left'  },
  { name: 'gemeldet_von_username', label: 'Erstellt von', field: 'gemeldet_von_username', align: 'left',  sortable: true },
  { name: 'counts',                label: '',            field: 'id',                    align: 'left',   style: 'width:80px' },
  { name: 'created_at',            label: 'Erstellt',    field: 'created_at',            align: 'left',   sortable: true, format: v => formatDate(v) },
]

// In der Gelöscht-Ansicht eine Aktionsspalte (Wiederherstellen) anhängen.
const tableColumns = computed(() =>
  zeigeGeloeschte.value
    ? [...columns, { name: 'actions', label: '', field: 'id', align: 'right', style: 'width:60px' }]
    : columns
)

// ── Hilfsfunktionen ────────────────────────────────────────────────────────
function statusLabel(s)    { return STATUS_LABELS[s] ?? s }
function statusColor(s)    { return STATUS_COLORS[s] ?? 'grey' }
function isAbgeschlossen(t){ return t?.status === 'erledigt' || t?.status === 'abgelehnt' }
function erlaubteStatus(t) {
  const alle = STATUS_UEBERGAENGE[t?.status] ?? []
  if (canClose.value) return alle
  return alle.filter(s => s !== 'erledigt' && s !== 'abgelehnt')
}

function prioritaetIcon(p)  { return { niedrig: 'keyboard_arrow_down', normal: 'remove', hoch: 'keyboard_arrow_up', sicherheit: 'warning' }[p] ?? 'remove' }
function prioritaetColor(p) { return { niedrig: 'grey', normal: 'primary', hoch: 'orange', sicherheit: 'negative' }[p] ?? 'grey' }
function prioritaetLabel(p) { return { niedrig: 'Niedrig', normal: 'Normal', hoch: 'Hoch', sicherheit: 'Sicherheit' }[p] ?? p }
function prioritaetBorderColor(p) { return { niedrig: '#9e9e9e', normal: 'var(--q-primary)', hoch: '#ef6c00', sicherheit: 'var(--q-negative)' }[p] ?? '#9e9e9e' }
function statusBgClass(s) { return { offen: 'bg-blue-1 text-grey-9', in_pruefung: 'bg-orange-1 text-grey-9', eingeplant: 'bg-purple-1 text-grey-9', rueckfrage: 'bg-amber-1 text-grey-9', erledigt: 'bg-green-1 text-grey-9', abgelehnt: 'bg-red-1 text-grey-9' }[s] ?? '' }

function formatDate(iso) {
  return fmtDate(iso, { placeholder: '—' })
}
function formatDateTime(iso) {
  return fmtDateTime(iso, { placeholder: '—' })
}

function emptyCreateForm() {
  return { titel: '', beschreibung: '', bereich_id: null, kategorie_id: null, prioritaet: 'normal', faellig_am: '' }
}

function syncDetailForm(ticket) {
  detailForm.value = {
    titel:         ticket.titel,
    beschreibung:  ticket.beschreibung || '',
    bereich_id:    ticket.bereich_id,
    kategorie_id:  ticket.kategorie_id,
    prioritaet:    ticket.prioritaet,
    faellig_am:    ticket.faellig_am || '',
  }
}

// ── Laden ──────────────────────────────────────────────────────────────────
function _ticketParams() {
  return zeigeGeloeschte.value ? { nur_geloeschte: true } : {}
}

async function loadAll() {
  loading.value = true
  try {
    const requests = [
      api.get('/api/tickets/', { params: _ticketParams() }),
      api.get('/api/tickets/bereiche'),
      api.get('/api/tickets/kategorien'),
      api.get('/api/tickets/meine-berechtigungen'),
    ]
    if (isAdmin.value) requests.push(api.get('/api/users/'))
    const results = await Promise.all(requests)
    tickets.value    = results[0].data
    bereiche.value   = results[1].data
    kategorien.value = results[2].data
    meineBerechtigungen.value = results[3].data
    if (isAdmin.value) users.value = results[4].data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Tickets.' })
  } finally {
    loading.value = false
  }
}

// Nur die Ticket-Liste neu laden (beim Umschalten der Gelöscht-Ansicht).
async function loadTickets() {
  loading.value = true
  try {
    const { data } = await api.get('/api/tickets/', { params: _ticketParams() })
    tickets.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Tickets.' })
  } finally {
    loading.value = false
  }
}

watch(zeigeGeloeschte, loadTickets)

// ── Erstellen ──────────────────────────────────────────────────────────────
const pickBereichOpen = ref(false)
const pickBereichId = ref(null)

function openCreateDialog() {
  pickBereichId.value = null
  pickBereichOpen.value = true
}

async function onPickBereichConfirm() {
  if (!pickBereichId.value) return
  saving.value = true
  try {
    const { data } = await api.post('/api/tickets/?draft=true', { titel: 'Neues Ticket', prioritaet: 'normal', bereich_id: pickBereichId.value })
    pickBereichOpen.value = false
    tickets.value = [data, ...tickets.value]
    isDraftTicket.value = true
    await openDetailDialog(data)
  } catch (e) {
    $q.notify({ type: 'negative', message: 'Fehler beim Anlegen des Tickets.' })
  } finally {
    saving.value = false
  }
}

// ── Detail ─────────────────────────────────────────────────────────────────
async function openDetailDialog(ticket) {
  selectedTicket.value = ticket
  syncDetailForm(ticket)
  if (isDraftTicket.value) detailForm.value.titel = ''
  detailAnhaenge.value = []
  kommentare.value = []
  detailDialogOpen.value = true
  await Promise.all([loadAnhaenge(ticket.id), loadKommentare(ticket.id)])
}

async function onWithdraw() {
  $q.dialog({
    title: 'Ticket zurückziehen',
    message: 'Das Ticket wird zurückgezogen und aus der Liste entfernt. Fortfahren?',
    cancel: true,
    ok: { label: 'Zurückziehen', color: 'negative' },
  }).onOk(async () => {
    try {
      await api.delete(`/api/tickets/${selectedTicket.value.id}`)
      tickets.value = tickets.value.filter(t => t.id !== selectedTicket.value.id)
      isDraftTicket.value = false
      detailDialogOpen.value = false
      $q.notify({ type: 'info', message: 'Ticket zurückgezogen.' })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler.' })
    }
  })
}

// ── Verbergen (smart löschen) / Wiederherstellen ────────────────────────────
function onSmartDelete() {
  const t = selectedTicket.value
  if (!t) return
  $q.dialog({
    title: 'Ticket verbergen',
    message: `Ticket #${t.id} „${t.titel}" aus der öffentlichen Ansicht entfernen? `
      + 'Es bleibt erhalten und kann von Verwaltern jederzeit wieder eingeblendet werden.',
    cancel: true,
    ok: { label: 'Verbergen', color: 'negative' },
  }).onOk(async () => {
    try {
      await api.delete(`/api/tickets/${t.id}`)
      tickets.value = tickets.value.filter(x => x.id !== t.id)
      detailDialogOpen.value = false
      $q.notify({ type: 'info', message: 'Ticket verborgen.' })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Verbergen.' })
    }
  })
}

function onRestore(ticket) {
  const t = ticket || selectedTicket.value
  if (!t) return
  $q.dialog({
    title: 'Ticket wiederherstellen',
    message: `Ticket #${t.id} „${t.titel}" wieder einblenden?`,
    cancel: true,
    ok: { label: 'Wiederherstellen', color: 'primary' },
  }).onOk(async () => {
    try {
      await api.post(`/api/tickets/${t.id}/restore`)
      // In der Gelöscht-Ansicht verschwindet das Ticket dadurch aus der Liste.
      tickets.value = tickets.value.filter(x => x.id !== t.id)
      if (selectedTicket.value?.id === t.id) detailDialogOpen.value = false
      $q.notify({ type: 'positive', message: 'Ticket wiederhergestellt.' })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Wiederherstellen.' })
    }
  })
}

async function closeDetailDialog() {
  if (isDraftTicket.value && selectedTicket.value) {
    try {
      await api.delete(`/api/tickets/${selectedTicket.value.id}`)
      tickets.value = tickets.value.filter(t => t.id !== selectedTicket.value.id)
      $q.notify({ type: 'info', message: 'Ticket verworfen.' })
    } catch { /* ignorieren */ }
  }
  isDraftTicket.value = false
  detailDialogOpen.value = false
}

// Wenn selectedTicket von außen aktualisiert wird (Statuswechsel), Form nachziehen
watch(selectedTicket, (t) => { if (t && !isDraftTicket.value) syncDetailForm(t) }, { deep: false })

async function loadAnhaenge(ticketId) {
  try {
    const { data } = await api.get(`/api/tickets/${ticketId}/anhaenge`)
    detailAnhaenge.value = data
  } catch { /* ignorieren */ }
}

// ── Inline-Speichern ───────────────────────────────────────────────────────
async function onDetailSave() {
  if (!detailForm.value.bereich_id) {
    $q.notify({ type: 'warning', message: 'Bitte einen Bereich wählen.' })
    return
  }
  if (!detailForm.value.titel.trim()) {
    $q.notify({ type: 'warning', message: 'Bitte einen Titel eingeben.' })
    return
  }
  detailSaving.value = true
  try {
    const { data } = await api.put(`/api/tickets/${selectedTicket.value.id}`, {
      ...detailForm.value,
      expected_version: selectedTicket.value.version,
      notify_as_new: isDraftTicket.value,
    })
    const wasDraft = isDraftTicket.value
    selectedTicket.value = data
    isDraftTicket.value = false
    const idx = tickets.value.findIndex(t => t.id === data.id)
    if (idx >= 0) tickets.value[idx] = data
    if (wasDraft) {
      detailDialogOpen.value = false
      $q.notify({ type: 'positive', message: 'Ticket gespeichert.' })
    } else {
      $q.notify({ type: 'positive', message: 'Gespeichert.' })
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    detailSaving.value = false
  }
}

// ── Statuswechsel ──────────────────────────────────────────────────────────
async function doStatusChange(newStatus) {
  if (!selectedTicket.value) return
  try {
    const { data } = await api.patch(`/api/tickets/${selectedTicket.value.id}/status`, {
      status: newStatus,
      expected_version: selectedTicket.value.version,
    })
    selectedTicket.value = data
    const idx = tickets.value.findIndex(t => t.id === data.id)
    if (idx >= 0) tickets.value[idx] = data
    $q.notify({ type: 'positive', message: `Status auf „${statusLabel(newStatus)}" gesetzt.` })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Statuswechsel.' })
  }
}

// ── Anhänge ────────────────────────────────────────────────────────────────
// Hilfsfunktion: anhang_count im selektierten Ticket UND in der Listenzeile
// synchron halten (sonst zeigt die Liste einen veralteten Zähler – siehe #54).
function setAnhangCount(count) {
  if (!selectedTicket.value) return
  const safe = Math.max(0, count)
  selectedTicket.value = { ...selectedTicket.value, anhang_count: safe }
  const idx = tickets.value.findIndex(t => t.id === selectedTicket.value.id)
  if (idx >= 0) tickets.value[idx] = { ...tickets.value[idx], anhang_count: safe }
}

function onAnhangUploaded(newAnhang) {
  isDraftTicket.value = false
  detailAnhaenge.value = [...detailAnhaenge.value, newAnhang]
  setAnhangCount((selectedTicket.value?.anhang_count || 0) + 1)
}

function onAnhangDeleted(anhangId) {
  detailAnhaenge.value = detailAnhaenge.value.filter(a => a.id !== anhangId)
  setAnhangCount((selectedTicket.value?.anhang_count || 0) - 1)
}

// ── Kommentare ─────────────────────────────────────────────────────────────
async function loadKommentare(ticketId) {
  kommentareLoading.value = true
  try {
    const { data } = await api.get(`/api/tickets/${ticketId}/kommentare`)
    kommentare.value = data
  } catch { /* ignorieren */ } finally {
    kommentareLoading.value = false
  }
}

async function sendKommentar() {
  if (!neuerKommentar.value.trim() || !selectedTicket.value) return
  kommentarSaving.value = true
  try {
    const { data } = await api.post(`/api/tickets/${selectedTicket.value.id}/kommentare`, {
      inhalt: neuerKommentar.value,
      sichtbarkeit: kommentarIntern.value ? 'intern' : 'oeffentlich',
    })
    isDraftTicket.value = false
    kommentare.value = [...kommentare.value, data]
    neuerKommentar.value = ''
    kommentarIntern.value = false
    const cnt = (selectedTicket.value.kommentar_count || 0) + 1
    selectedTicket.value = { ...selectedTicket.value, kommentar_count: cnt }
    const idx = tickets.value.findIndex(t => t.id === selectedTicket.value.id)
    if (idx >= 0) tickets.value[idx] = { ...tickets.value[idx], kommentar_count: cnt }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Senden.' })
  } finally {
    kommentarSaving.value = false
  }
}

async function deleteKommentar(k) {
  $q.dialog({ title: 'Kommentar löschen', message: 'Wirklich löschen?', cancel: true })
    .onOk(async () => {
      try {
        await api.delete(`/api/tickets/${selectedTicket.value.id}/kommentare/${k.id}`)
        kommentare.value = kommentare.value.filter(c => c.id !== k.id)
        if (selectedTicket.value?.kommentar_count > 0) {
          selectedTicket.value = { ...selectedTicket.value, kommentar_count: selectedTicket.value.kommentar_count - 1 }
        }
      } catch (e) {
        $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen.' })
      }
    })
}

usePageRefresh(loadAll)
onMounted(() => {
  loadAll()
  window.addEventListener('vtb:ticket-created', loadAll)
})
onUnmounted(() => {
  window.removeEventListener('vtb:ticket-created', loadAll)
})
</script>
