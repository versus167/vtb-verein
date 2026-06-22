<template>
  <q-dialog
    :model-value="modelValue"
    @update:model-value="onDialogToggle"
    persistent
    :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
  >
    <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:560px;max-width:720px'">
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6 col">
          <template v-if="isNewLocal">Als Vereinsmitglied erfassen</template>
          <template v-else>{{ form.mitgliedsnummer != null ? 'Mitglied ' + form.mitgliedsnummer : 'Mitglied' }}</template>
          <span v-if="mitgliedName" class="text-weight-regular">{{ ' – ' + mitgliedName }}</span>
        </div>
        <q-btn flat dense round icon="close" @click="requestClose" />
      </q-card-section>

      <q-tabs v-model="tab" dense align="left" class="q-px-md text-primary">
        <q-tab name="stammdaten" label="Stammdaten" icon="person" />
        <q-tab v-if="!isNewLocal" name="abteilungen" label="Abteilungen" icon="group" />
        <q-tab v-if="!isNewLocal" name="funktionen" label="Funktionen" icon="badge" />
        <q-tab v-if="!isNewLocal && personMode" name="kontakte" label="Kontakte" icon="contact_phone" />
        <q-tab v-if="!isNewLocal && personMode && canSeeTeams" name="mannschaften" label="Mannschaften" icon="groups" />
        <q-tab v-if="!isNewLocal && canSeeFinanzen" name="finanzen" label="Beiträge &amp; Gebühren" icon="euro" />
      </q-tabs>
      <q-separator />

      <div style="position:relative; min-height:120px">
        <q-inner-loading :showing="loading" />

        <q-tab-panels v-model="tab" animated style="max-height:68vh; overflow-y:auto">
          <!-- ── Stammdaten ───────────────────────────────────── -->
          <q-tab-panel name="stammdaten" class="q-gutter-sm">
            <div class="row q-gutter-sm">
              <q-input v-model="form.vorname" label="Vorname *" outlined dense class="col" :readonly="!canWrite" />
              <q-input v-model="form.nachname" label="Nachname *" outlined dense class="col" :readonly="!canWrite" />
            </div>
            <div class="row q-gutter-sm">
              <q-input v-if="!personMode" v-model="form.mitgliedsnummer" label="Mitgliedsnr." outlined dense type="number" class="col" :readonly="!canWrite" />
              <q-input v-model="form.geburtsdatum" label="Geburtsdatum *" outlined dense type="date" class="col" :readonly="!canWrite" />
              <q-select
                v-model="form.geschlecht" label="Geschlecht" outlined dense class="col"
                :options="geschlechtOptions" emit-value map-options clearable
                :readonly="!canWrite"
              />
            </div>
            <!-- E-Mail nur im Mitglieder-Kontext direkt; im Personen-Kontext über den Kontakte-Tab pflegen -->
            <q-input v-if="!personMode" v-model="form.email" label="E-Mail" outlined dense type="email" :readonly="!canWrite" />
            <q-input v-model="form.telefon" label="Telefon" outlined dense :readonly="!canWrite" />
            <div class="row q-gutter-sm">
              <q-input v-model="form.eintrittsdatum" label="Eintrittsdatum *" outlined dense type="date" class="col" :readonly="!canWrite" />
              <q-input v-model="form.austrittsdatum" label="Austrittsdatum" outlined dense type="date" class="col" :readonly="!canWrite" />
            </div>
            <q-select
              v-model="form.status" label="Vereinsstatus" outlined dense
              :options="statusOptions" :readonly="!canWrite"
            />
            <q-expansion-item label="Adresse" dense icon="home">
              <div class="q-gutter-sm q-pt-sm">
                <q-input v-model="form.strasse" label="Straße" outlined dense :readonly="!canWrite" />
                <div class="row q-gutter-sm">
                  <q-input v-model="form.plz" label="PLZ" outlined dense style="width:110px" :readonly="!canWrite" />
                  <q-input v-model="form.ort" label="Ort" outlined dense class="col" :readonly="!canWrite" />
                </div>
                <q-input v-model="form.land" label="Land" outlined dense :readonly="!canWrite" />
              </div>
            </q-expansion-item>
            <q-expansion-item label="Zahlung / SEPA" dense icon="payments">
              <div class="q-gutter-sm q-pt-sm">
                <q-select v-model="form.zahlungsart" :options="zahlungsartOptionen"
                  emit-value map-options label="Zahlungsart" outlined dense :readonly="!canWrite" />
                <q-input v-model="form.iban" label="IBAN" outlined dense :readonly="!canWrite" :rules="[ibanRule]" />
                <q-input v-model="form.bic" label="BIC" outlined dense :readonly="!canWrite" />
                <q-input v-model="form.kontoinhaber" label="Kontoinhaber" outlined dense :readonly="!canWrite" />
              </div>
            </q-expansion-item>
            <div v-if="stammError" class="text-negative text-caption">{{ stammError }}</div>
            <div v-if="canWrite" class="row justify-end">
              <q-btn :label="isNewLocal ? 'Erfassen' : 'Stammdaten speichern'" color="primary" unelevated
                :loading="savingStamm" @click="saveStammdaten" />
            </div>
          </q-tab-panel>

          <!-- ── Abteilungen ──────────────────────────────────── -->
          <q-tab-panel name="abteilungen" class="q-pa-none">
            <q-card-section class="row items-center q-pb-sm">
              <div class="text-subtitle2 col">Abteilungs-Zuordnungen</div>
              <q-btn v-if="canWrite" label="Hinzufügen" icon="add" color="primary"
                unelevated size="sm" @click="openZuordnungForm(null)" />
            </q-card-section>
            <q-separator />
            <q-card-section>
              <div v-if="zuordnungen.length === 0" class="text-grey text-center q-py-md">
                Keine Abteilungszuordnungen vorhanden
              </div>
              <q-list separator>
                <q-item v-for="z in zuordnungen" :key="z.id">
                  <q-item-section>
                    <q-item-label>
                      {{ z.abteilung_name }}
                      <q-badge class="q-ml-sm" :color="abteilungStatusColor(z.status)" text-color="white">{{ z.status }}</q-badge>
                    </q-item-label>
                    <q-item-label caption>
                      <span v-if="z.von">ab {{ z.von }}</span>
                      <span v-if="z.von && z.bis"> · </span>
                      <span v-if="z.bis">bis {{ z.bis }}</span>
                      <span v-if="!z.von && !z.bis">Kein Zeitraum angegeben</span>
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <div class="q-gutter-xs">
                      <q-btn v-if="canWrite" flat dense round icon="edit" color="primary" size="sm" @click="openZuordnungForm(z)" />
                      <q-btn v-if="canDelete" flat dense round icon="delete" color="negative" size="sm" @click="deleteZuordnung(z)" />
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-tab-panel>

          <!-- ── Funktionen ───────────────────────────────────── -->
          <q-tab-panel name="funktionen" class="q-pa-none">
            <q-card-section class="row items-center q-pb-sm">
              <div class="text-subtitle2 col">Funktionen</div>
              <q-btn v-if="canWrite" label="Hinzufügen" icon="add" color="primary"
                unelevated size="sm" @click="openFunktionForm(null)" />
            </q-card-section>
            <q-separator />
            <q-card-section>
              <div v-if="funktionen.length === 0" class="text-grey text-center q-py-md">
                Keine Funktionen zugeordnet
              </div>
              <q-list separator>
                <q-item v-for="f in funktionen" :key="f.id">
                  <q-item-section>
                    <q-item-label>
                      {{ funktionLabel(f.funktion) }}
                      <q-badge class="q-ml-sm" color="teal">{{ f.abteilung_name ?? 'Verein' }}</q-badge>
                    </q-item-label>
                    <q-item-label caption>
                      <span v-if="f.von">ab {{ f.von }}</span>
                      <span v-if="f.von && f.bis"> · </span>
                      <span v-if="f.bis">bis {{ f.bis }}</span>
                      <span v-if="!f.von && !f.bis">Kein Zeitraum angegeben</span>
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <div class="q-gutter-xs">
                      <q-btn v-if="canWrite" flat dense round icon="edit" color="primary" size="sm" @click="openFunktionForm(f)" />
                      <q-btn v-if="canDelete" flat dense round icon="delete" color="negative" size="sm" @click="deleteFunktion(f)" />
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-tab-panel>

          <!-- ── Kontakte ─────────────────────────────────────── -->
          <q-tab-panel v-if="personMode" name="kontakte" class="q-pa-none">
            <q-card-section class="row items-center q-pb-sm">
              <div class="text-subtitle2 col">Kontaktdaten</div>
              <q-btn v-if="canWrite" label="Hinzufügen" icon="add" color="primary"
                unelevated size="sm" @click="openKontaktForm(null)" />
            </q-card-section>
            <q-separator />
            <q-card-section>
              <div v-if="kontakte.length === 0" class="text-grey text-center q-py-md">
                Keine Kontaktdaten erfasst
              </div>
              <q-list separator>
                <q-item v-for="k in kontakte" :key="k.id">
                  <q-item-section avatar><q-icon :name="kontaktIcon(k.typ)" color="cyan-8" /></q-item-section>
                  <q-item-section>
                    <q-item-label>
                      {{ k.wert }}
                      <q-badge v-if="k.ist_primaer" class="q-ml-sm" color="cyan-8" text-color="white">primär</q-badge>
                    </q-item-label>
                    <q-item-label caption>
                      {{ typLabel(k.typ) }}<span v-if="k.label"> · {{ k.label }}</span>
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <div class="q-gutter-xs">
                      <q-btn v-if="canWrite && !k.ist_primaer" flat dense round icon="star" color="amber-8" size="sm" @click="setPrimaer(k)">
                        <q-tooltip>Als primär setzen</q-tooltip>
                      </q-btn>
                      <q-btn v-if="canWrite" flat dense round icon="edit" color="primary" size="sm" @click="openKontaktForm(k)" />
                      <q-btn v-if="canDelete" flat dense round icon="delete" color="negative" size="sm" @click="deleteKontakt(k)" />
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-tab-panel>

          <!-- ── Mannschaften ─────────────────────────────────── -->
          <q-tab-panel v-if="personMode && canSeeTeams" name="mannschaften" class="q-pa-none">
            <q-card-section class="row items-center q-pb-sm">
              <div class="text-subtitle2 col">Mannschaften</div>
              <q-btn v-if="canWrite" label="Hinzufügen" icon="add" color="primary"
                unelevated size="sm" @click="openTeamForm(null)" />
            </q-card-section>
            <q-separator />
            <q-card-section>
              <div v-if="mitgliedTeams.length === 0" class="text-grey text-center q-py-md">
                In keiner Mannschaft
              </div>
              <q-list separator>
                <q-item v-for="t in mitgliedTeams" :key="t.id">
                  <q-item-section avatar><q-icon name="groups" color="cyan-8" /></q-item-section>
                  <q-item-section>
                    <q-item-label>{{ t.mannschaft_name }}</q-item-label>
                    <q-item-label caption>
                      <q-badge class="q-mr-xs" :color="teamRolleColor(t.rolle)" text-color="white">{{ teamRolleLabel(t.rolle) }}</q-badge>
                      <span v-if="t.abteilung_name" class="q-mr-xs">{{ t.abteilung_name }}</span>
                      <span>{{ t.von }} – {{ t.bis ?? 'heute' }}</span>
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <div class="q-gutter-xs">
                      <q-btn v-if="canWrite" flat dense round icon="edit" color="primary" size="sm" @click="openTeamForm(t)" />
                      <q-btn v-if="canDelete" flat dense round icon="delete" color="negative" size="sm" @click="removeTeam(t)" />
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-tab-panel>

          <!-- Beiträge & Gebühren (read-only) -->
          <q-tab-panel v-if="canSeeFinanzen" name="finanzen" class="q-pa-none">
            <q-card-section>
              <div class="text-subtitle2 q-mb-xs">Beitrags-Sollstellungen</div>
              <div v-if="mitgliedSollstellungen.length === 0" class="text-grey q-py-sm">Keine Sollstellungen.</div>
              <q-list v-else separator dense>
                <q-item v-for="s in mitgliedSollstellungen" :key="'s'+s.id">
                  <q-item-section>
                    <q-item-label>{{ s.beitragsregel_name }} · {{ s.zeitraum }}</q-item-label>
                    <q-item-label caption>{{ Number(s.betrag_soll).toFixed(2) }} €<span v-if="s.faelligkeitsdatum"> · fällig {{ s.faelligkeitsdatum }}</span></q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-badge :color="fibuStatus(s).color" text-color="white">{{ fibuStatus(s).label }}</q-badge>
                  </q-item-section>
                </q-item>
              </q-list>

              <q-separator class="q-my-md" />

              <div class="text-subtitle2 q-mb-xs">Gebühren-Forderungen</div>
              <div v-if="mitgliedForderungen.length === 0" class="text-grey q-py-sm">Keine Forderungen.</div>
              <q-list v-else separator dense>
                <q-item v-for="f in mitgliedForderungen" :key="'f'+f.id">
                  <q-item-section>
                    <q-item-label>{{ f.gebuehr_name }}</q-item-label>
                    <q-item-label caption>{{ Number(f.betrag_soll).toFixed(2) }} € · {{ f.datum }}</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-badge :color="fibuStatus(f).color" text-color="white">{{ fibuStatus(f).label }}</q-badge>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </q-tab-panel>
        </q-tab-panels>
      </div>

      <q-separator />
      <q-card-actions align="right">
        <q-btn flat label="Schließen" @click="requestClose" />
      </q-card-actions>
    </q-card>

    <!-- Nachfrage beim Schließen mit ungespeicherten Stammdaten -->
    <q-dialog v-model="closeConfirmOpen">
      <q-card style="min-width: 360px">
        <q-card-section class="row items-center no-wrap">
          <q-avatar icon="warning" color="warning" text-color="white" />
          <span class="q-ml-sm text-subtitle1">Ungespeicherte Änderungen</span>
        </q-card-section>
        <q-card-section class="q-pt-none">
          Die Stammdaten wurden geändert. Möchtest du die Änderungen speichern?
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn flat label="Verwerfen" color="negative" @click="discardAndClose" />
          <q-btn unelevated label="Speichern" color="primary" :loading="savingStamm" @click="saveAndClose" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Abteilungs-Zuordnung anlegen / bearbeiten -->
    <q-dialog v-model="zuordnungFormOpen" persistent>
      <q-card style="min-width: 400px">
        <q-card-section class="text-h6">
          {{ editingZuordnungId ? 'Zuordnung bearbeiten' : 'Neue Zuordnung' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-select
            v-if="!editingZuordnungId"
            v-model="zuordnungForm.abteilung_id" label="Abteilung *" outlined dense
            :options="abteilungOptions" option-value="id" option-label="name"
            emit-value map-options :rules="[(v) => !!v || 'Pflichtfeld']"
          />
          <q-select v-model="zuordnungForm.status" label="Status *" outlined dense :options="abteilungStatusOptions" />
          <div class="row q-gutter-sm">
            <q-input v-model="zuordnungForm.von" label="Von" outlined dense type="date" class="col" clearable
              :min="form.eintrittsdatum || undefined" :max="form.austrittsdatum || undefined" />
            <q-input v-model="zuordnungForm.bis" label="Bis" outlined dense type="date" class="col" clearable />
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="zuordnungSaving" @click="saveZuordnung" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Funktion anlegen / bearbeiten -->
    <q-dialog v-model="funktionFormOpen" persistent>
      <q-card style="min-width: 400px">
        <q-card-section class="text-h6">
          {{ editingFunktionId ? 'Funktion bearbeiten' : 'Neue Funktion' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-select
            v-model="funktionForm.funktion" label="Funktion *" outlined dense
            :options="funktionOptionen" emit-value map-options
            :rules="[(v) => !!v || 'Pflichtfeld']"
          />
          <q-select
            v-model="funktionForm.abteilung_id" label="Abteilung" outlined dense
            :options="abteilungOptions" option-value="id" option-label="name"
            emit-value map-options clearable
          />
          <div class="row q-gutter-sm">
            <q-input v-model="funktionForm.von" label="Von *" outlined dense type="date" class="col" clearable
              :min="form.eintrittsdatum || undefined" :max="form.austrittsdatum || undefined" />
            <q-input v-model="funktionForm.bis" label="Bis" outlined dense type="date" class="col" clearable />
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="funktionSaving" @click="saveFunktion" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Kontakt anlegen / bearbeiten -->
    <q-dialog v-model="kontaktFormOpen" persistent>
      <q-card style="min-width: 400px">
        <q-card-section class="text-h6">
          {{ editingKontaktId ? 'Kontakt bearbeiten' : 'Neuer Kontakt' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-select v-model="kontaktForm.typ" label="Typ *" outlined dense
            :options="kontaktTypOptionen" emit-value map-options />
          <q-input v-model="kontaktForm.wert" label="Wert *" outlined dense
            :type="kontaktForm.typ === 'email' ? 'email' : 'text'" />
          <q-input v-model="kontaktForm.label" label="Bezeichnung (optional, z. B. privat)" outlined dense />
          <q-toggle v-model="kontaktForm.ist_primaer" label="Primärer Kontakt dieses Typs" color="cyan-8" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="kontaktSaving" @click="saveKontakt" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Mannschaft anlegen / bearbeiten -->
    <q-dialog v-model="teamFormOpen" persistent>
      <q-card style="min-width: 400px">
        <q-card-section class="text-h6">
          {{ editingTeamId ? 'Mannschaft bearbeiten' : 'Zu Mannschaft hinzufügen' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-select v-if="!editingTeamId" v-model="teamForm.mannschaft_id" :options="alleMannschaften"
            option-value="id" :option-label="t => `${t.name} (${t.abteilung_name})`" emit-value map-options
            use-input input-debounce="0" @filter="filterTeams" label="Mannschaft *" outlined dense />
          <q-select v-model="teamForm.rolle" :options="teamRolleOptionen" option-value="value" option-label="label"
            emit-value map-options label="Rolle *" outlined dense />
          <div class="row q-gutter-sm">
            <q-input v-model="teamForm.von" label="Von *" outlined dense type="date" class="col" clearable
              :min="form.eintrittsdatum || undefined" :max="form.austrittsdatum || undefined" />
            <q-input v-model="teamForm.bis" label="Bis" outlined dense type="date" class="col" clearable />
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="teamSaving" @click="saveTeam" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import { ibanRule, normalizeIban, isValidIban } from 'src/utils/iban'
import { proposeAufnahmegebuehr } from 'src/utils/aufnahmegebuehr'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  mitgliedId: { type: [Number, String], default: null },
  mitgliedName: { type: String, default: '' },
  // Personen-Kontext: User-ID (für Stammdaten-Speichern über /api/personen),
  // Neu-Anlage eines Mitgliedsatzes und die Zusatz-Tabs Kontakte/Mannschaften.
  userId: { type: [Number, String], default: null },
  isNew: { type: Boolean, default: false },
  initialTab: { type: String, default: 'stammdaten' },
  personMode: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const $q = useQuasar()
const auth = useAuthStore()

const canWrite = computed(() => auth.hasPermission('personen.write'))
const canDelete = computed(() => auth.hasPermission('personen.delete'))
const canSeeTeams = computed(() => auth.hasPermission('mannschaften.read'))
const canSeeFinanzen = computed(() => auth.hasPermission('beitraege.read') || auth.hasPermission('gebuehren.read'))

const tab = ref('stammdaten')
const loading = ref(false)
// Sammelt, ob in dieser Sitzung etwas geändert wurde – nur dann lohnt sich beim
// Schließen ein 'saved' (damit der Aufrufer die Vorschau/Liste einmalig neu berechnet).
const dirty = ref(false)
// Lokale Kopie von props.isNew, damit wir nach dem ersten Speichern
// die Zusatz-Tabs (Abteilungen, Funktionen, Kontakte, Mannschaften) aktivieren können.
const isNewLocal = ref(props.isNew)
// Lokale mitglied_id für Neuanlagen: nach dem ersten Speichern haben wir eine ID,
// die wir für Abteilungen/Funktionen/Kontakte/Mannschaften benötigen.
const localMitgliedId = ref(props.mitgliedId)

// Hilfsfunktion: gibt die effektive mitglied_id zurück (lokal oder aus Props)
function getMitgliedId() {
  return localMitgliedId.value ?? props.mitgliedId
}

// ── Stammdaten ───────────────────────────────────────────────
const statusOptions = ['aktiv', 'passiv', 'ausgetreten']
const abteilungStatusOptions = ['aktiv', 'passiv', 'trainer', 'vorstand', 'ehrenmitglied']
const geschlechtOptions = [
  { label: 'männlich', value: 'm' },
  { label: 'weiblich', value: 'w' },
  { label: 'divers', value: 'd' },
]

// Lastschrift steuert den SEPA-Einzug im Fibu-Export (Feld 36); Standard = Lastschrift.
const zahlungsartOptionen = [
  { label: 'Lastschrift', value: 'lastschrift' },
  { label: 'Sonstiges', value: 'sonstiges' },
]

const emptyForm = () => ({
  vorname: '', nachname: '', mitgliedsnummer: null, geburtsdatum: null, geschlecht: null,
  email: null, telefon: null, strasse: null, plz: null, ort: null, land: null,
  eintrittsdatum: null, austrittsdatum: null, status: 'aktiv', zahlungsart: 'lastschrift',
  iban: null, bic: null, kontoinhaber: null, abgerechnet_bis: null,
})
const form = ref(emptyForm())
// Snapshot des zuletzt geladenen/gespeicherten Stands – Basis für die
// Erkennung ungespeicherter Stammdaten-Änderungen beim Schließen.
const pristineForm = ref(emptyForm())
const savingStamm = ref(false)
const stammError = ref('')
// Steuert den Nachfrage-Dialog beim Schließen mit ungespeicherten Stammdaten.
const closeConfirmOpen = ref(false)

function snapshotForm() {
  pristineForm.value = JSON.parse(JSON.stringify(form.value))
}
// true, sobald sich ein Stammdaten-Feld gegenüber dem Snapshot unterscheidet.
const stammDirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(pristineForm.value))

function abteilungStatusColor(s) {
  return { aktiv: 'positive', passiv: 'grey', trainer: 'blue', vorstand: 'purple', ehrenmitglied: 'amber-8' }[s] ?? 'grey'
}

// ── Abteilungen ──────────────────────────────────────────────
const zuordnungen = ref([])
const abteilungOptions = ref([])
const zuordnungFormOpen = ref(false)
const zuordnungSaving = ref(false)
const editingZuordnungId = ref(null)
const editingZuordnungVersion = ref(null)
const zuordnungForm = ref({ abteilung_id: null, status: 'aktiv', von: null, bis: null })

// ── Funktionen ───────────────────────────────────────────────
const funktionen = ref([])
const funktionOptionen = ref([])
const funktionFormOpen = ref(false)
const funktionSaving = ref(false)
const editingFunktionId = ref(null)
const editingFunktionVersion = ref(null)
const funktionForm = ref({ funktion: null, abteilung_id: null, von: null, bis: null })

function funktionLabel(f) {
  if (!f) return ''
  return funktionOptionen.value.find(o => o.value === f)?.label ?? f
}

// ── Kontakte (nur Personen-Kontext) ──────────────────────────
const kontakte = ref([])
const kontaktFormOpen = ref(false)
const kontaktSaving = ref(false)
const editingKontaktId = ref(null)
const editingKontaktVersion = ref(null)
const kontaktForm = ref({ typ: 'email', wert: '', label: '', ist_primaer: false })
const kontaktTypOptionen = [
  { label: 'E-Mail', value: 'email' },
  { label: 'Telefon', value: 'telefon' },
  { label: 'Mobil', value: 'mobil' },
  { label: 'Fax', value: 'fax' },
]
function typLabel(t) { return kontaktTypOptionen.find(o => o.value === t)?.label ?? t }
function kontaktIcon(t) { return { email: 'mail', telefon: 'call', mobil: 'smartphone', fax: 'fax' }[t] ?? 'contact_phone' }

// ── Mannschaften (nur Personen-Kontext) ──────────────────────
const mitgliedTeams = ref([])
const alleMannschaften = ref([])
const alleMannschaftenAll = ref([])
const teamFormOpen = ref(false)
const teamSaving = ref(false)
const editingTeamId = ref(null)
const editingTeamMannschaft = ref(null)
const editingTeamVersion = ref(null)
const teamForm = ref({ mannschaft_id: null, rolle: 'spieler', von: null, bis: null })
const teamRolleOptionen = [
  { label: 'Spieler', value: 'spieler' },
  { label: 'Übungsleiter', value: 'uebungsleiter' },
  { label: 'Trainer', value: 'trainer' },
  { label: 'Betreuer', value: 'betreuer' },
]
function teamRolleLabel(r) { return teamRolleOptionen.find(o => o.value === r)?.label ?? r }
function teamRolleColor(r) {
  return { spieler: 'blue', uebungsleiter: 'indigo', trainer: 'deep-purple', betreuer: 'teal' }[r] ?? 'grey'
}
function filterTeams(val, update) {
  const needle = val.toLowerCase()
  update(() => {
    alleMannschaften.value = !needle
      ? alleMannschaftenAll.value
      : alleMannschaftenAll.value.filter(t => `${t.name} ${t.abteilung_name}`.toLowerCase().includes(needle))
  })
}

// ── Laden ────────────────────────────────────────────────────
watch(() => props.modelValue, (open) => {
  if (!open) return
  tab.value = props.initialTab || 'stammdaten'
  dirty.value = false
  stammError.value = ''
  closeConfirmOpen.value = false
  isNewLocal.value = props.isNew
  localMitgliedId.value = props.mitgliedId
  if (props.isNew) {
    // Neu-Anlage: nur Stammdaten, noch keine mitglied_id → nichts zu laden.
    form.value = emptyForm()
    snapshotForm()
  } else if (getMitgliedId() != null) {
    loadAll()
  }
})

async function loadAll() {
  loading.value = true
  stammError.value = ''
  try {
    const reqs = [
      api.get(`/api/mitglieder/${getMitgliedId()}`),
      api.get('/api/abteilungen/'),
      api.get(`/api/mitglieder/${getMitgliedId()}/funktionen`),
      api.get('/api/funktionen'),
      api.get(`/api/mitglieder/${getMitgliedId()}/abteilungen`),
    ]
    if (props.personMode) {
      reqs.push(api.get(`/api/mitglieder/${getMitgliedId()}/kontakte`))
    }
    const res = await Promise.all(reqs)
    const [{ data: m }, { data: ab }, { data: fns }, { data: katalog }, { data: z }] = res
    form.value = { ...emptyForm(), ...m }
    // Zahlungsart auf das Dropdown normalisieren: ein expliziter Nicht-Lastschrift-Wert
    // (Altwert 'ueberweisung' o.Ä.) wird zu 'sonstiges'; alles übrige (auch leer) ist
    // 'lastschrift' (Standard).
    form.value.zahlungsart = m.zahlungsart && m.zahlungsart !== 'lastschrift' ? 'sonstiges' : 'lastschrift'
    snapshotForm()
    abteilungOptions.value = ab
    funktionen.value = fns
    funktionOptionen.value = katalog.map(f => ({ label: f.name, value: f.key }))
    zuordnungen.value = z
    if (props.personMode) {
      kontakte.value = res[5].data
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
  // Mannschaften separat & fehlertolerant laden: fehlt mannschaften.read,
  // darf der 403 nicht die übrigen Stammdaten blockieren (Ticket #30).
  if (props.personMode && canSeeTeams.value) {
    loadTeams()
  }
  if (canSeeFinanzen.value) {
    loadFinanzen()
  }
}

// Beiträge/Gebühren der Person (read-only) – fehlertolerant nachladen.
const mitgliedSollstellungen = ref([])
const mitgliedForderungen = ref([])
// Die VTB-App kennt zur Sollstellung nur: erzeugt (offen) und ob sie an die Fibu
// übergeben wurde – kein „bezahlt". Zahlung/Ausgleich passiert in der Fibu.
function fibuStatus(item) {
  if (item.status === 'storniert') {
    return item.exportiert_in_export_id
      ? { label: 'storniert (Gegenbuchung an Fibu)', color: 'grey' }
      : { label: 'storniert', color: 'grey' }
  }
  if (item.exportiert_in_export_id) return { label: 'an Fibu übergeben', color: 'indigo' }
  return { label: 'offen', color: 'orange' }
}

async function loadFinanzen() {
  const id = getMitgliedId()
  if (id == null) return
  try {
    if (auth.hasPermission('beitraege.read')) {
      const { data } = await api.get(`/api/beitraege/sollstellungen/mitglied/${id}`)
      mitgliedSollstellungen.value = data
    }
    if (auth.hasPermission('gebuehren.read')) {
      const { data } = await api.get(`/api/gebuehren/forderungen/mitglied/${id}`)
      mitgliedForderungen.value = data
    }
  } catch { /* still: read-only Zusatzsicht, blockiert die Stammdaten nicht */ }
}

async function loadTeams() {
  try {
    const [{ data: teams }, { data: alle }] = await Promise.all([
      api.get(`/api/mitglieder/${getMitgliedId()}/mannschaften`),
      api.get('/api/mannschaften'),
    ])
    mitgliedTeams.value = teams
    alleMannschaftenAll.value = alle
    alleMannschaften.value = alle
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der Mannschaften' })
  }
}

async function reloadZuordnungen() {
  const { data } = await api.get(`/api/mitglieder/${getMitgliedId()}/abteilungen`)
  zuordnungen.value = data
}

async function reloadFunktionen() {
  const { data } = await api.get(`/api/mitglieder/${getMitgliedId()}/funktionen`)
  funktionen.value = data
}

async function reloadKontakte() {
  const { data } = await api.get(`/api/mitglieder/${getMitgliedId()}/kontakte`)
  kontakte.value = data
}

async function reloadTeams() {
  const { data } = await api.get(`/api/mitglieder/${getMitgliedId()}/mannschaften`)
  mitgliedTeams.value = data
}

// ── Stammdaten speichern ─────────────────────────────────────
async function saveStammdaten() {
  stammError.value = ''
  if (!form.value.eintrittsdatum) {
    stammError.value = 'Eintrittsdatum ist erforderlich.'
    return false
  }
  if (!form.value.geburtsdatum) {
    stammError.value = 'Geburtsdatum ist erforderlich.'
    return false
  }
  form.value.iban = normalizeIban(form.value.iban)
  if (form.value.iban && !isValidIban(form.value.iban)) {
    stammError.value = 'Ungültige IBAN – bitte Format und Prüfziffer prüfen.'
    return false
  }
  savingStamm.value = true
  try {
    if (props.personMode) {
      // E-Mail/Mitgliedsnr. werden im Personen-Kontext nicht hier gepflegt
      // (E-Mail → Kontakte-Tab). Telefon synchronisiert das Backend mit dem primären Kontakt.
      const payload = {
        vorname: form.value.vorname,
        nachname: form.value.nachname,
        geburtsdatum: form.value.geburtsdatum || null,
        geschlecht: form.value.geschlecht || null,
        telefon: form.value.telefon || null,
        strasse: form.value.strasse || null,
        plz: form.value.plz || null,
        ort: form.value.ort || null,
        land: form.value.land || null,
        eintrittsdatum: form.value.eintrittsdatum || null,
        austrittsdatum: form.value.austrittsdatum || null,
        status: form.value.status,
        zahlungsart: form.value.zahlungsart || '',
        iban: form.value.iban || null,
        bic: form.value.bic || null,
        kontoinhaber: form.value.kontoinhaber || null,
        abgerechnet_bis: form.value.abgerechnet_bis || null,
        expected_version: form.value.version ?? 1,
      }
      let response
      if (isNewLocal.value) {
        response = await api.post(`/api/personen/${props.userId}/mitglied`, payload)
      } else if (props.userId != null) {
        response = await api.put(`/api/personen/${props.userId}/mitglied`, payload)
      } else {
        // Mitglied ohne Login-Account → über mitglied_id
        response = await api.put(`/api/personen/mitglied/${getMitgliedId()}`, payload)
      }
      // Für Neuanlagen: mitglied_id aus der Antwort speichern
      if (isNewLocal.value && response?.data?.mitglied?.id) {
        localMitgliedId.value = response.data.mitglied.id
      }
    } else {
      await api.put(`/api/mitglieder/${getMitgliedId()}`, form.value)
    }
    dirty.value = true
    const wasNew = isNewLocal.value
    $q.notify({ type: 'positive', message: wasNew ? 'Mitglied erfasst' : 'Stammdaten gespeichert' })
    if (wasNew) {
      // Mitglied existiert jetzt – Dialog bleibt offen, damit Zuordnungen/Kontakte
      // direkt erfasst werden können (Ticket #43). Zusatz-Tabs aktivieren und die
      // Kataloge/Listen (Abteilungen, Funktionen, Kontakte, Mannschaften) nachladen,
      // sonst sind die Auswahllisten leer und der Datensatz hätte keine version.
      // loadAll() setzt dabei auch den Snapshot neu.
      isNewLocal.value = false
      await loadAll()
    } else {
      snapshotForm()
    }
    return true
  } catch (e) {
    stammError.value = e.response?.data?.detail || 'Fehler beim Speichern'
    return false
  } finally {
    savingStamm.value = false
  }
}

// Standard-Beginn einer Zuordnung: heute – aber nie vor dem Vereinseintritt.
// Bei zukünftigem Eintrittsdatum wird dieses vorbelegt (Zuordnung kann nicht vor
// der Mitgliedschaft beginnen).
function defaultVon() {
  const heute = new Date().toISOString().slice(0, 10)
  const eintritt = form.value?.eintrittsdatum
  return (eintritt && eintritt > heute) ? eintritt : heute
}

// ── Abteilungs-Zuordnungen ───────────────────────────────────
function openZuordnungForm(z) {
  if (z) {
    editingZuordnungId.value = z.id
    editingZuordnungVersion.value = z.version
    zuordnungForm.value = { abteilung_id: z.abteilung_id, status: z.status, von: z.von, bis: z.bis }
  } else {
    editingZuordnungId.value = null
    editingZuordnungVersion.value = null
    zuordnungForm.value = { abteilung_id: null, status: 'aktiv', von: defaultVon(), bis: null }
  }
  zuordnungFormOpen.value = true
}

async function saveZuordnung() {
  zuordnungSaving.value = true
  const istNeu = !editingZuordnungId.value
  const neueAbteilungId = zuordnungForm.value.abteilung_id
  const von = zuordnungForm.value.von || defaultVon()
  try {
    if (editingZuordnungId.value) {
      await api.put(`/api/mitglieder/${getMitgliedId()}/abteilungen/${editingZuordnungId.value}`, {
        status: zuordnungForm.value.status,
        von: zuordnungForm.value.von || null,
        bis: zuordnungForm.value.bis || null,
        expected_version: editingZuordnungVersion.value,
      })
    } else {
      await api.post(`/api/mitglieder/${getMitgliedId()}/abteilungen`, {
        abteilung_id: zuordnungForm.value.abteilung_id,
        status: zuordnungForm.value.status,
        von: zuordnungForm.value.von || null,
        bis: zuordnungForm.value.bis || null,
      })
    }
    dirty.value = true
    zuordnungFormOpen.value = false
    await reloadZuordnungen()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    // Ticket #42: bei NEUER Abteilungs-Zuordnung passende Aufnahmegebühr vorschlagen.
    if (istNeu) {
      await proposeAufnahmegebuehr($q, { mitgliedId: getMitgliedId(), abteilungId: neueAbteilungId, datum: von })
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    zuordnungSaving.value = false
  }
}

function deleteZuordnung(z) {
  $q.dialog({
    title: 'Zuordnung entfernen',
    message: `Zuordnung zu „${z.abteilung_name}" wirklich entfernen?`,
    cancel: true, persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/mitglieder/${getMitgliedId()}/abteilungen/${z.id}`)
      dirty.value = true
      await reloadZuordnungen()
      $q.notify({ type: 'positive', message: 'Zuordnung entfernt' })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen' })
    }
  })
}

// ── Funktionen ───────────────────────────────────────────────
function openFunktionForm(f) {
  if (f) {
    editingFunktionId.value = f.id
    editingFunktionVersion.value = f.version
    funktionForm.value = { funktion: f.funktion, abteilung_id: f.abteilung_id, von: f.von, bis: f.bis }
  } else {
    editingFunktionId.value = null
    editingFunktionVersion.value = null
    funktionForm.value = { funktion: null, abteilung_id: null, von: defaultVon(), bis: null }
  }
  funktionFormOpen.value = true
}

async function saveFunktion() {
  if (!funktionForm.value.funktion) {
    $q.notify({ type: 'negative', message: 'Bitte eine Funktion auswählen.' })
    return
  }
  if (!funktionForm.value.von) {
    $q.notify({ type: 'negative', message: 'Bitte ein „Von"-Datum angeben (Zeitraum ist Pflicht).' })
    return
  }
  funktionSaving.value = true
  try {
    if (editingFunktionId.value) {
      await api.put(`/api/mitglieder/${getMitgliedId()}/funktionen/${editingFunktionId.value}`, {
        funktion: funktionForm.value.funktion,
        abteilung_id: funktionForm.value.abteilung_id || null,
        von: funktionForm.value.von || null,
        bis: funktionForm.value.bis || null,
        expected_version: editingFunktionVersion.value,
      })
    } else {
      await api.post(`/api/mitglieder/${getMitgliedId()}/funktionen`, {
        funktion: funktionForm.value.funktion,
        abteilung_id: funktionForm.value.abteilung_id || null,
        von: funktionForm.value.von || null,
        bis: funktionForm.value.bis || null,
      })
    }
    dirty.value = true
    funktionFormOpen.value = false
    await reloadFunktionen()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    funktionSaving.value = false
  }
}

function deleteFunktion(f) {
  $q.dialog({
    title: 'Funktion entfernen',
    message: `Funktion „${funktionLabel(f.funktion)}" wirklich entfernen?`,
    cancel: true, persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/mitglieder/${getMitgliedId()}/funktionen/${f.id}`)
      dirty.value = true
      await reloadFunktionen()
      $q.notify({ type: 'positive', message: 'Funktion entfernt' })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen' })
    }
  })
}

// ── Kontakte ─────────────────────────────────────────────────
function openKontaktForm(k) {
  if (k) {
    editingKontaktId.value = k.id
    editingKontaktVersion.value = k.version
    kontaktForm.value = { typ: k.typ, wert: k.wert, label: k.label ?? '', ist_primaer: k.ist_primaer }
  } else {
    editingKontaktId.value = null
    editingKontaktVersion.value = null
    kontaktForm.value = { typ: 'email', wert: '', label: '', ist_primaer: false }
  }
  kontaktFormOpen.value = true
}

async function saveKontakt() {
  if (!kontaktForm.value.typ || !kontaktForm.value.wert.trim()) {
    $q.notify({ type: 'negative', message: 'Typ und Wert sind erforderlich.' })
    return
  }
  kontaktSaving.value = true
  try {
    if (editingKontaktId.value) {
      await api.put(`/api/mitglieder/${getMitgliedId()}/kontakte/${editingKontaktId.value}`, {
        typ: kontaktForm.value.typ,
        wert: kontaktForm.value.wert.trim(),
        label: kontaktForm.value.label || null,
        ist_primaer: kontaktForm.value.ist_primaer,
        expected_version: editingKontaktVersion.value,
      })
    } else {
      await api.post(`/api/mitglieder/${getMitgliedId()}/kontakte`, {
        typ: kontaktForm.value.typ,
        wert: kontaktForm.value.wert.trim(),
        label: kontaktForm.value.label || null,
        ist_primaer: kontaktForm.value.ist_primaer,
      })
    }
    dirty.value = true
    kontaktFormOpen.value = false
    await reloadKontakte()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    kontaktSaving.value = false
  }
}

async function setPrimaer(k) {
  try {
    await api.put(`/api/mitglieder/${getMitgliedId()}/kontakte/${k.id}/primaer`)
    dirty.value = true
    await reloadKontakte()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

function deleteKontakt(k) {
  $q.dialog({
    title: 'Kontakt entfernen',
    message: `„${k.wert}" wirklich entfernen?`,
    cancel: true, persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/mitglieder/${getMitgliedId()}/kontakte/${k.id}`)
      dirty.value = true
      await reloadKontakte()
      $q.notify({ type: 'positive', message: 'Kontakt entfernt' })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen' })
    }
  })
}

// ── Mannschaften ─────────────────────────────────────────────
function openTeamForm(t) {
  if (t) {
    editingTeamId.value = t.id
    editingTeamMannschaft.value = t.mannschaft_id
    editingTeamVersion.value = t.version
    teamForm.value = { mannschaft_id: t.mannschaft_id, rolle: t.rolle, von: t.von ?? '', bis: t.bis ?? '' }
  } else {
    editingTeamId.value = null
    editingTeamMannschaft.value = null
    editingTeamVersion.value = null
    teamForm.value = { mannschaft_id: null, rolle: 'spieler', von: defaultVon(), bis: '' }
    alleMannschaften.value = alleMannschaftenAll.value
  }
  teamFormOpen.value = true
}

async function saveTeam() {
  if (!editingTeamId.value && !teamForm.value.mannschaft_id) {
    $q.notify({ type: 'negative', message: 'Bitte eine Mannschaft wählen.' })
    return
  }
  if (!teamForm.value.von) {
    $q.notify({ type: 'negative', message: 'Bitte ein „Von"-Datum angeben.' })
    return
  }
  teamSaving.value = true
  try {
    if (editingTeamId.value) {
      await api.put(`/api/mannschaften/${editingTeamMannschaft.value}/mitglieder/${editingTeamId.value}`, {
        rolle: teamForm.value.rolle,
        von: teamForm.value.von || null,
        bis: teamForm.value.bis || null,
        expected_version: editingTeamVersion.value,
      })
    } else {
      await api.post(`/api/mannschaften/${teamForm.value.mannschaft_id}/mitglieder`, {
        mitglied_id: getMitgliedId(),
        rolle: teamForm.value.rolle,
        von: teamForm.value.von || null,
        bis: teamForm.value.bis || null,
      })
    }
    dirty.value = true
    teamFormOpen.value = false
    await reloadTeams()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    teamSaving.value = false
  }
}

function removeTeam(t) {
  $q.dialog({
    title: 'Aus Mannschaft entfernen',
    message: `Aus „${t.mannschaft_name}" wirklich entfernen?`,
    cancel: true, persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/mannschaften/${t.mannschaft_id}/mitglieder/${t.id}`)
      dirty.value = true
      await reloadTeams()
      $q.notify({ type: 'positive', message: 'Entfernt' })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen' })
    }
  })
}

// ── Schließen ────────────────────────────────────────────────
function onDialogToggle(val) {
  if (!val) requestClose()
}

// Einstieg für X-Button und „Schließen": bei ungespeicherten Stammdaten-
// Änderungen erst nachfragen, sonst direkt schließen.
function requestClose() {
  if (canWrite.value && stammDirty.value) {
    closeConfirmOpen.value = true
    return
  }
  doClose()
}

function doClose() {
  closeConfirmOpen.value = false
  emit('update:modelValue', false)
  if (dirty.value) {
    emit('saved')
    dirty.value = false
  }
}

async function saveAndClose() {
  const ok = await saveStammdaten()
  if (ok) {
    doClose()
  } else {
    // Speichern fehlgeschlagen → Nachfrage schließen, damit der Fehler im
    // Formular sichtbar wird; der Edit-Dialog bleibt offen.
    closeConfirmOpen.value = false
  }
}

function discardAndClose() {
  doClose()
}
</script>
