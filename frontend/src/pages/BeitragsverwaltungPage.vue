<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Beitragsverwaltung</div>

    <q-tabs v-model="tab" dense align="left" class="q-mb-md">
      <q-tab name="dashboard"    label="Dashboard"     icon="insights" />
      <q-tab name="regeln"       label="Regeln"        icon="rule" />
      <q-tab name="abrechnung"   label="Abrechnung"    icon="calculate" />
      <q-tab name="sollstellungen" label="Sollstellungen" icon="list_alt" />
    </q-tabs>

    <!-- ════════════════════════════════════════════════
         Tab: Beitragsregeln
         ════════════════════════════════════════════════ -->
    <q-tab-panels v-model="tab" animated>
      <!-- ════════════════════════════════════════════════
           Tab: Dashboard (Projektion aktuelles Quartal)
           ════════════════════════════════════════════════ -->
      <q-tab-panel name="dashboard" class="q-pa-none">
        <div class="row items-center q-gutter-sm q-mb-md">
          <q-btn flat round dense icon="chevron_left" @click="verschiebeQuartal(-1)" />
          <div class="text-h6" style="min-width: 110px; text-align: center">
            {{ dashboard?.zeitraum || '—' }}
          </div>
          <q-btn flat round dense icon="chevron_right" @click="verschiebeQuartal(1)" />
          <q-btn flat dense no-caps label="Aktuelles Quartal" icon="today"
            @click="dashboardStichtag = heute; ladeDashboard()" />
          <q-space />
          <q-btn flat round dense icon="refresh" :loading="dashboardLoading" @click="ladeDashboard" />
        </div>
        <div class="text-caption text-grey-7 q-mb-md">
          Projektion aus den Beitragsregeln (anteilig nach Ein-/Austritt) – unabhängig davon,
          ob die Abrechnung bereits gelaufen ist. Beträge je Regel für den Zeitraum, der den
          Stichtag enthält.
        </div>

        <div v-if="dashboardLoading" class="row justify-center q-py-xl">
          <q-spinner size="40px" color="primary" />
        </div>

        <template v-else-if="dashboard">
          <!-- Kennzahlen -->
          <div class="row q-col-gutter-md q-mb-md">
            <div class="col-12 col-sm-4">
              <q-card flat bordered>
                <q-card-section class="text-center">
                  <div class="text-caption text-grey-7">Summe gesamt</div>
                  <div class="text-h5 text-primary">{{ euro(dashboard.gesamt_summe) }}</div>
                </q-card-section>
              </q-card>
            </div>
            <div class="col-12 col-sm-4">
              <q-card flat bordered>
                <q-card-section class="text-center">
                  <div class="text-caption text-grey-7">Zahler</div>
                  <div class="text-h5">{{ dashboard.gesamt_zahler }}</div>
                </q-card-section>
              </q-card>
            </div>
            <div class="col-12 col-sm-4">
              <q-card flat bordered>
                <q-card-section class="text-center">
                  <div class="text-caption text-grey-7">Positionen</div>
                  <div class="text-h5">{{ dashboard.gesamt_positionen }}</div>
                </q-card-section>
              </q-card>
            </div>
          </div>

          <!-- Aufschlüsselung je Abteilung -->
          <q-table :rows="dashboard.gruppen" :columns="dashboardColumns" row-key="abteilung_name"
            flat bordered hide-pagination :pagination="{ rowsPerPage: 0 }">
            <template #body-cell-abteilung_name="props">
              <q-td :props="props">
                <q-chip v-if="props.row.abteilung_id == null" dense size="sm"
                  color="primary" text-color="white">Verein</q-chip>
                <q-chip v-else dense size="sm" color="purple" text-color="white">
                  {{ props.row.abteilung_name }}
                </q-chip>
              </q-td>
            </template>
            <template #bottom-row>
              <q-tr class="text-weight-bold">
                <q-td>Gesamt</q-td>
                <q-td class="text-right">{{ euro(dashboard.gesamt_summe) }}</q-td>
                <q-td class="text-center">{{ dashboard.gesamt_zahler }}</q-td>
                <q-td class="text-center">{{ dashboard.gesamt_positionen }}</q-td>
              </q-tr>
            </template>
          </q-table>
          <div v-if="dashboard.gruppen.length === 0" class="text-grey text-center q-py-lg">
            Keine fälligen Beiträge im {{ dashboard.zeitraum }}.
          </div>
        </template>
      </q-tab-panel>

      <q-tab-panel name="regeln" class="q-pa-none">
        <div class="row items-center q-mb-md">
          <q-select v-model="filterAbteilung" :options="abteilungFilterOptions"
            emit-value map-options clearable dense outlined
            label="Abteilung filtern" style="min-width: 240px" />
          <q-space />
          <q-btn v-if="kannSchreiben" icon="add" label="Neue Regel" color="primary"
            unelevated @click="openRegelDialog()" />
        </div>
        <div v-if="regelnLoading" class="row justify-center q-py-xl">
          <q-spinner size="40px" color="primary" />
        </div>
        <q-list bordered separator v-else>
          <q-item v-for="r in gefilterteRegeln" :key="r.id">
            <q-item-section>
              <q-item-label class="text-weight-medium">{{ r.name }}</q-item-label>
              <q-item-label caption>
                {{ r.betrag_pro_monat.toFixed(2) }} €/Monat
                · {{ r.betrag_pro_einzug.toFixed(2) }} €/{{ turnusLabel(r.einzug_turnus) }}
                · ab {{ r.gueltig_ab }}
                <span v-if="r.gueltig_bis"> bis {{ r.gueltig_bis }}</span>
              </q-item-label>
              <q-item-label caption class="q-mt-xs">
                <q-chip v-if="r.abteilung_name" dense size="sm" color="purple" text-color="white">
                  {{ r.abteilung_name }}
                </q-chip>
                <q-chip v-else dense size="sm" color="primary" text-color="white">
                  Alle Mitglieder
                </q-chip>
                <q-chip v-if="r.bedingung_abteilung_status" dense size="sm" color="orange" text-color="white">
                  Status: {{ r.bedingung_abteilung_status }}
                </q-chip>
                <q-chip v-if="r.bedingung_funktionen && r.bedingung_funktionen.length" dense size="sm" color="indigo" text-color="white">
                  Funktion: {{ bedingungText(r) }}
                </q-chip>
                <q-chip v-if="r.ausnahme_funktionen && r.ausnahme_funktionen.length" dense size="sm" color="deep-orange" text-color="white">
                  Ausnahme: {{ ausnahmeText(r) }}
                </q-chip>
                <q-chip v-if="r.bedingung_alter_min != null || r.bedingung_alter_max != null" dense size="sm" color="blue-grey" text-color="white">
                  Alter {{ r.bedingung_alter_min ?? 0 }}–{{ r.bedingung_alter_max ?? '∞' }} J.
                </q-chip>
                <q-chip v-if="r.zahler_typ === 'abteilung'" dense size="sm" color="teal" text-color="white">
                  Zahlung: {{ r.abteilung_name ?? 'Abteilung' }}
                </q-chip>
                <q-chip v-if="r.gegenkonto" dense size="sm" color="green-8" text-color="white" icon="account_balance">
                  Konto: {{ r.gegenkonto }}
                </q-chip>
              </q-item-label>
            </q-item-section>
            <q-item-section side v-if="kannSchreiben">
              <div class="row q-gutter-xs">
                <q-btn flat dense round icon="edit" color="primary" @click="openRegelDialog(r)" />
                <q-btn flat dense round icon="delete" color="negative" @click="deleteRegel(r)" />
              </div>
            </q-item-section>
          </q-item>
          <q-item v-if="gefilterteRegeln.length === 0">
            <q-item-section class="text-grey text-center q-py-md">
              {{ regeln.length === 0 ? 'Noch keine Beitragsregeln angelegt.' : 'Keine Regeln für diese Abteilung.' }}
            </q-item-section>
          </q-item>
        </q-list>
      </q-tab-panel>

      <!-- ════════════════════════════════════════════════
           Tab: Abrechnung
           ════════════════════════════════════════════════ -->
      <q-tab-panel name="abrechnung" class="q-pa-none">
        <div class="row q-col-gutter-md q-mb-md items-stretch">
          <div class="col-12 col-md-auto">
            <q-card flat bordered style="max-width: 480px; height: 100%">
              <q-card-section>
                <div class="text-subtitle1 text-weight-bold q-mb-sm">Abrechnung starten</div>
                <div class="text-caption text-grey-7 q-mb-md">
                  Abgerechnet werden alle noch nicht abgerechneten Beiträge bis zum Quartal
                  des Stichtags – inklusive bis zu {{ quartaleRueckschau }}
                  {{ quartaleRueckschau === 1 ? 'Quartal' : 'Quartalen' }} davor (Rückschau).
                  Frühestens ab dem 01.04.2026. Bitte erst Vorschau prüfen, dann bestätigen.
                </div>
                <q-input v-model="stichtag" type="date" label="Stichtag (bis) *" outlined dense
                  :max="heute" class="q-mb-sm" />
                <div class="row q-gutter-sm">
                  <q-btn label="Vorschau berechnen" outline color="primary" :loading="vorschauLoading"
                    :disable="!stichtag" @click="ladeVorschau" />
                </div>
              </q-card-section>
            </q-card>
          </div>

          <div v-if="kannSchreiben" class="col-12 col-md-auto">
            <q-card flat bordered style="max-width: 480px; height: 100%">
              <q-card-section>
                <div class="text-subtitle1 text-weight-bold q-mb-sm">Rückschau-Einstellung</div>
                <div class="text-caption text-grey-7 q-mb-md">
                  Wie viele Quartale vor dem aktuellen eine Abrechnung mitnimmt (Sicherheitsnetz
                  für verpasste Läufe). Im Dauerbetrieb meist 1. Die harte Untergrenze 01.04.2026
                  wird nie unterschritten.
                </div>
                <div class="row items-center q-gutter-sm">
                  <q-input v-model.number="quartaleRueckschau" type="number" min="0" max="40"
                    label="Quartale Rückschau" outlined dense style="width: 160px" />
                  <q-btn label="Speichern" color="primary" unelevated
                    :loading="einstellungenLoading" @click="speichereEinstellungen" />
                </div>
              </q-card-section>
            </q-card>
          </div>
        </div>

        <!-- Vorschau-Tabelle -->
        <template v-if="vorschau.length > 0">
          <div class="row q-gutter-sm q-mb-sm items-center">
            <q-input v-model="vorschauFilterName" dense outlined clearable
              label="Nach Name suchen" style="min-width: 200px" />
            <q-select v-model="vorschauFilterAbteilung" :options="vorschauAbteilungOptionen"
              emit-value map-options clearable dense outlined
              label="Abteilung filtern" style="min-width: 200px" />
            <q-checkbox v-model="vorschauZeigeVorhandene" dense
              :label="`Vorhandene anzeigen (${gefilterteVorschau.filter(p => p.bereits_vorhanden).length})`" />
            <div class="text-subtitle2 col-auto">
              {{ gefilterteVorschau.filter(p => !p.bereits_vorhanden).length }} neu,
              {{ gefilterteVorschau.filter(p => p.bereits_vorhanden).length }} vorhanden
              <span v-if="vorschauFilterName || vorschauFilterAbteilung" class="text-grey-6">
                (von {{ vorschauNeu.length + vorschauDuplikate.length }} gesamt)
              </span>
            </div>
          </div>
          <q-table :rows="sichtbareVorschau" :columns="vorschauColumns" :row-key="vorschauRowKey"
            flat bordered dense :rows-per-page-options="[0]" hide-bottom>
            <template #body-cell-status="props">
              <q-td :props="props">
                <q-chip dense size="sm"
                  :color="props.row.bereits_vorhanden ? 'grey' : 'positive'"
                  text-color="white">
                  {{ props.row.bereits_vorhanden ? 'vorhanden' : 'neu' }}
                </q-chip>
              </q-td>
            </template>
            <template #body-cell-zahler="props">
              <q-td :props="props">
                <q-chip dense size="sm"
                  :color="props.row.zahler_typ === 'abteilung' ? 'teal' : 'primary'"
                  text-color="white">
                  {{ props.row.zahler_typ === 'abteilung' ? 'Abteilung' : 'SEPA' }}
                </q-chip>
              </q-td>
            </template>
            <template #body-cell-edit="props">
              <q-td :props="props">
                <q-btn v-if="kannMitgliedBearbeiten" flat dense round icon="edit"
                  color="primary" size="sm" @click="openMitgliedEdit(props.row)">
                  <q-tooltip>Mitglied bearbeiten (Schlüsselung prüfen/korrigieren)</q-tooltip>
                </q-btn>
              </q-td>
            </template>
          </q-table>
          <div class="q-mt-md">
            <q-btn v-if="kannAbrechnen && vorschauNeu.length > 0"
              label="Abrechnung bestätigen" color="primary" unelevated
              :loading="abrechnungLoading" @click="confirmAbrechnung" />
          </div>
        </template>

        <!-- Ergebnis -->
        <q-banner v-if="abrechnungErgebnis" class="bg-positive text-white q-mt-md" rounded>
          <template #avatar><q-icon name="check_circle" /></template>
          <strong>{{ abrechnungErgebnis.zeitraum || 'Keine neuen Zeiträume' }}</strong> abgerechnet:
          {{ abrechnungErgebnis.angelegt }} Sollstellungen angelegt
          ({{ abrechnungErgebnis.uebersprungen }} übersprungen).
        </q-banner>
      </q-tab-panel>

      <!-- ════════════════════════════════════════════════
           Tab: Sollstellungen
           ════════════════════════════════════════════════ -->
      <q-tab-panel name="sollstellungen" class="q-pa-none">
        <div class="row q-gutter-sm q-mb-md items-center">
          <q-select v-model="filterZeitraum" :options="zeitraumOptionen" label="Zeitraum"
            outlined dense clearable style="min-width: 200px"
            @update:model-value="ladeSollstellungen">
            <template #no-option>
              <q-item>
                <q-item-section class="text-grey">Noch keine Abrechnung vorhanden</q-item-section>
              </q-item>
            </template>
          </q-select>
          <q-btn label="Neu laden" color="primary" outline dense :disable="!filterZeitraum"
            @click="ladeSollstellungen" />
          <q-select v-model="sollFibuFilter" :options="sollFibuFilterOptionen"
            option-value="value" option-label="label" emit-value map-options dense outlined
            label="Status" style="min-width: 180px" />
          <q-btn v-if="kannAbrechnen" dense icon="delete_sweep"
            :color="papierkorbOffen ? 'primary' : 'grey-7'" :outline="!papierkorbOffen" :unelevated="papierkorbOffen"
            :label="`Papierkorb${papierkorbRows.length ? ' (' + papierkorbRows.length + ')' : ''}`"
            @click="togglePapierkorb" />
          <q-space />
          <q-input v-model="sollSuche" dense outlined clearable debounce="200"
            placeholder="Suche (Name, Regel …)" style="min-width: 220px">
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </div>

        <q-table :rows="gefilterteSollstellungen" :columns="sollColumns" row-key="id"
          :filter="sollSuche"
          flat bordered :loading="sollLoading" :rows-per-page-options="[25, 50, 0]">
          <template #body-cell-status="props">
            <q-td :props="props">
              <q-chip dense size="sm" :color="fibuStatus(props.row).color" text-color="white">
                {{ fibuStatus(props.row).label }}
              </q-chip>
            </q-td>
          </template>
          <template #body-cell-actions="props">
            <q-td :props="props" v-if="kannAbrechnen">
              <q-btn v-if="props.row.status === 'offen'" flat dense round icon="block" color="negative" size="sm"
                @click="markStorniert(props.row)">
                <q-tooltip>{{ props.row.exportiert_in_export_id ? 'Stornieren (Gegenbuchung im nächsten Fibu-Export)' : 'Stornieren (bleibt bestehen, wird nicht neu abgerechnet)' }}</q-tooltip>
              </q-btn>
              <!-- An die Fibu übergebene Sollstellungen nicht löschbar – Rücknahme nur per Storno. -->
              <q-btn v-if="!props.row.exportiert_in_export_id" flat dense round icon="delete" color="negative" size="sm"
                @click="deleteSollstellung(props.row)">
                <q-tooltip>In den Papierkorb (wird bei der nächsten Abrechnung neu erzeugt)</q-tooltip>
              </q-btn>
              <q-icon v-else name="lock" size="xs" color="grey-6">
                <q-tooltip>An Fibu übergeben – Rücknahme nur per Storno (Gegenbuchung)</q-tooltip>
              </q-icon>
            </q-td>
            <q-td :props="props" v-else />
          </template>
        </q-table>

        <!-- Papierkorb: gelöschte Sollstellungen wiederherstellen (Ticket #52) -->
        <div v-if="kannAbrechnen && papierkorbOffen" class="q-mt-md">
          <div class="text-subtitle2 q-mb-xs row items-center">
            <q-icon name="delete_outline" class="q-mr-xs" /> Papierkorb – gelöschte Sollstellungen
          </div>
          <q-table :rows="papierkorbRows" :columns="papierkorbColumns" row-key="id"
            flat bordered :loading="papierkorbLoading" :rows-per-page-options="[10, 25, 0]"
            no-data-label="Papierkorb ist leer">
            <template #body-cell-actions="props">
              <q-td :props="props">
                <q-btn flat dense size="sm" icon="restore" color="primary" label="Wiederherstellen"
                  no-caps @click="restoreSollstellung(props.row)" />
              </q-td>
            </template>
          </q-table>
        </div>
      </q-tab-panel>
    </q-tab-panels>

    <!-- Regel-Dialog -->
    <q-dialog v-model="regelDialogOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:500px'">
        <q-card-section class="text-h6">{{ editingRegel?.id ? 'Regel bearbeiten' : 'Neue Beitragsregel' }}</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="regelForm.name" label="Name *" outlined dense />
          <q-select v-model="regelForm.abteilung_id" :options="abteilungOptions"
            option-value="id" option-label="name" emit-value map-options
            label="Abteilung (leer = Vereinsbeitrag)" outlined dense clearable />
          <div class="row q-gutter-sm">
            <q-input v-model.number="regelForm.betrag_pro_monat" label="Betrag/Monat (€) *"
              outlined dense type="number" step="0.01" class="col" />
            <q-select v-model="regelForm.einzug_turnus"
              :options="turnusOptions" emit-value map-options
              label="Einzug-Turnus" outlined dense class="col" />
          </div>
          <div class="row q-gutter-sm">
            <q-input v-model="regelForm.gueltig_ab" label="Gültig ab *" outlined dense type="date" class="col" />
            <q-input v-model="regelForm.gueltig_bis" label="Gültig bis" outlined dense type="date" class="col" />
          </div>
          <q-input v-model="regelForm.bedingung_abteilung_status"
            label="Nur für Abteilungs-Status (kommagetrennt, leer = alle)"
            outlined dense />
          <div>
            <div class="text-caption text-grey-7 q-mb-xs">
              Bedingung: nur für bestimmte Funktionen (leer = alle). Je Zeile eine
              Funktion mit optionaler Abteilung – leer = vereinsweit.
            </div>
            <div v-for="(e, i) in regelForm.bedingung_eintraege" :key="i"
                 class="row q-col-gutter-sm items-center q-mb-xs">
              <q-select
                v-model="e.funktion"
                :options="funktionOptionen" emit-value map-options
                label="Funktion" outlined dense class="col" />
              <q-select
                v-model="e.abteilung_id"
                :options="abteilungOptions" option-value="id" option-label="name"
                emit-value map-options
                label="Abteilung (leer = vereinsweit)" outlined dense clearable class="col" />
              <q-btn flat dense round icon="close" color="negative"
                @click="regelForm.bedingung_eintraege.splice(i, 1)" />
            </div>
            <q-btn flat dense icon="add" label="Bedingung hinzufügen" color="primary"
              @click="regelForm.bedingung_eintraege.push({ funktion: null, abteilung_id: null })" />
          </div>
          <div>
            <div class="text-caption text-grey-7 q-mb-xs">
              Ausnahmen: Funktionen vom Beitrag ausschließen (leer = keine). Je Zeile eine
              Funktion mit optionaler Abteilung – leer = vereinsweit.
            </div>
            <div v-for="(e, i) in regelForm.ausnahme_eintraege" :key="i"
                 class="row q-col-gutter-sm items-center q-mb-xs">
              <q-select
                v-model="e.funktion"
                :options="funktionOptionen" emit-value map-options
                label="Funktion" outlined dense class="col" />
              <q-select
                v-model="e.abteilung_id"
                :options="abteilungOptions" option-value="id" option-label="name"
                emit-value map-options
                label="Abteilung (leer = vereinsweit)" outlined dense clearable class="col" />
              <q-btn flat dense round icon="close" color="negative"
                @click="regelForm.ausnahme_eintraege.splice(i, 1)" />
            </div>
            <q-btn flat dense icon="add" label="Ausnahme hinzufügen" color="primary"
              @click="regelForm.ausnahme_eintraege.push({ funktion: null, abteilung_id: null })" />
          </div>
          <div class="row q-gutter-sm">
            <q-input v-model.number="regelForm.bedingung_alter_min" label="Alter von (Jahre)"
              outlined dense type="number" min="0" clearable class="col" />
            <q-input v-model.number="regelForm.bedingung_alter_max" label="Alter bis (Jahre)"
              outlined dense type="number" min="0" clearable class="col" />
          </div>
          <div class="text-caption text-grey-6 q-mb-xs">
            Alter am Abrechnungs-Stichtag. Mitglieder ohne gültiges Geburtsdatum werden bei
            gesetzter Altersbedingung nicht berücksichtigt.
          </div>
          <q-select v-model="regelForm.zahler_typ"
            :options="[{label:'Mitglied zahlt selbst (SEPA)',value:'mitglied'},{label:'Abteilung zahlt',value:'abteilung'}]"
            emit-value map-options label="Zahler" outlined dense />
          <q-separator class="q-my-sm" />
          <div class="text-caption text-grey-7">Finanzbuchhaltung (Fibu-Export)</div>
          <div class="row q-gutter-sm">
            <q-input v-model="regelForm.gegenkonto" label="Gegenkonto (Erlöskonto)" outlined dense
              clearable class="col" hint="leer = globaler Default" />
            <q-input v-model="regelForm.steuerschluessel" label="Steuerschlüssel" outlined dense
              clearable class="col" />
          </div>
          <div v-if="regelError" class="text-negative text-caption">{{ regelError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="regelSaving" @click="saveRegel" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Mitglied-Bearbeiten-Dialog (Schlüsselung direkt in der Vorschau korrigieren).
         person-mode: identischer Dialog wie in der Personenliste (Kontakte/Mannschaften-Tabs,
         Mitgliedsnr./E-Mail auf Personenebene ausgeblendet). Ohne userId speichert er über
         den direkten /api/personen/mitglied/{id}-Endpoint (deckt Login- und Nicht-Login-Mitglieder ab). -->
    <MitgliedEditDialog v-model="editMitgliedOpen" person-mode :mitglied-id="editMitgliedId"
      :mitglied-name="editMitgliedName" @saved="ladeVorschau" />
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import MitgliedEditDialog from 'src/components/MitgliedEditDialog.vue'

const $q = useQuasar()
const auth = useAuthStore()

const tab = ref('dashboard')
const heute = new Date().toISOString().slice(0, 10)

function euro(v) {
  return (Number(v) || 0).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' })
}

const kannSchreiben    = computed(() => auth.hasPermission('beitraege.write'))
const kannAbrechnen    = computed(() => auth.hasPermission('beitraege.abrechnen'))

// ── Optionen ───────────────────────────────────────────────
const abteilungOptions = ref([])
const funktionOptionen = ref([])

async function loadFunktionOptionen() {
  try {
    const { data } = await api.get('/api/funktionen')
    funktionOptionen.value = data.map(f => ({ label: f.name, value: f.key }))
  } catch {
    funktionOptionen.value = []
  }
}

function funktionLabel(f) {
  return funktionOptionen.value.find(o => o.value === f)?.label ?? f
}
function abteilungLabel(id) {
  return abteilungOptions.value.find(a => a.id === id)?.name ?? '?'
}
// Einschlüsse als Text: je Funktion mit optionaler Abteilung (index-gleiche Arrays).
function bedingungText(r) {
  const ids = r.bedingung_abteilung_ids || []
  return (r.bedingung_funktionen || [])
    .map((f, i) => funktionLabel(f) + (ids[i] != null ? ` (${abteilungLabel(ids[i])})` : ''))
    .join(', ')
}
// Ausnahmen als Text: je Funktion mit optionaler Abteilung (index-gleiche Arrays).
function ausnahmeText(r) {
  const ids = r.ausnahme_abteilung_ids || []
  return (r.ausnahme_funktionen || [])
    .map((f, i) => funktionLabel(f) + (ids[i] != null ? ` (${abteilungLabel(ids[i])})` : ''))
    .join(', ')
}
const turnusOptions = [
  { label: 'Monatlich',     value: 'monat' },
  { label: 'Vierteljährlich', value: 'quartal' },
  { label: 'Halbjährlich',  value: 'halbjahr' },
  { label: 'Jährlich',      value: 'jahr' },
]
function turnusLabel(t) {
  return { monat: 'Monat', quartal: 'Quartal', halbjahr: 'Halbjahr', jahr: 'Jahr' }[t] ?? t
}
// Die VTB-App kennt zur Sollstellung nur: erzeugt (offen) und ob sie an die Fibu
// übergeben wurde – kein „bezahlt". Zahlung/Ausgleich passiert in der Fibu.
function fibuStatus(row) {
  if (row.status === 'storniert') {
    return row.exportiert_in_export_id
      ? { label: 'storniert (Gegenbuchung an Fibu)', color: 'grey' }
      : { label: 'storniert', color: 'grey' }
  }
  if (row.exportiert_in_export_id) return { label: 'an Fibu übergeben', color: 'indigo' }
  return { label: 'offen', color: 'orange' }
}

// ── Dashboard (Projektion aktuelles Quartal) ───────────────
const dashboard = ref(null)
const dashboardLoading = ref(false)
const dashboardStichtag = ref(heute)
const dashboardColumns = [
  { name: 'abteilung_name', label: 'Bereich',    field: 'abteilung_name', align: 'left' },
  { name: 'summe',          label: 'Summe',       field: r => euro(r.summe), align: 'right' },
  { name: 'anzahl_zahler',  label: 'Zahler',      field: 'anzahl_zahler',  align: 'center' },
  { name: 'anzahl_positionen', label: 'Positionen', field: 'anzahl_positionen', align: 'center' },
]

async function ladeDashboard() {
  dashboardLoading.value = true
  try {
    const { data } = await api.get('/api/beitraege/dashboard',
      { params: { stichtag: dashboardStichtag.value } })
    dashboard.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Dashboard konnte nicht geladen werden' })
  } finally {
    dashboardLoading.value = false
  }
}

function verschiebeQuartal(delta) {
  const d = new Date(dashboardStichtag.value + 'T00:00:00')
  d.setDate(1)
  d.setMonth(d.getMonth() + delta * 3)
  dashboardStichtag.value = d.toISOString().slice(0, 10)
  ladeDashboard()
}

// ── Regeln ─────────────────────────────────────────────────
const regeln = ref([])
const regelnLoading = ref(false)

// Filter nach Abteilung: null = alle, 'verein' = Vereinsbeitrag (ohne Abteilung), sonst abteilung_id
const filterAbteilung = ref(null)
const abteilungFilterOptions = computed(() => [
  { label: 'Verein (alle Mitglieder)', value: 'verein' },
  ...abteilungOptions.value.map(a => ({ label: a.name, value: a.id })),
])
const gefilterteRegeln = computed(() => {
  if (filterAbteilung.value === null) return regeln.value
  if (filterAbteilung.value === 'verein') return regeln.value.filter(r => r.abteilung_id == null)
  // Alle Regeln, die diese Abteilung betreffen: eigene Abteilung, Bedingung auf die
  // Abteilung (Einschluss) oder Ausnahme auf die Abteilung (Ausschluss)
  return regeln.value.filter(r =>
    r.abteilung_id === filterAbteilung.value ||
    (r.bedingung_abteilung_ids || []).includes(filterAbteilung.value) ||
    (r.ausnahme_abteilung_ids || []).includes(filterAbteilung.value)
  )
})
const regelDialogOpen = ref(false)
const regelSaving = ref(false)
const regelError = ref('')
const editingRegel = ref(null)
const regelForm = ref({})

async function loadRegeln() {
  regelnLoading.value = true
  try {
    const { data } = await api.get('/api/beitraege/regeln')
    regeln.value = data
  } finally {
    regelnLoading.value = false
  }
}

function openRegelDialog(r = null) {
  editingRegel.value = r
  regelError.value = ''
  regelForm.value = r ? {
    name: r.name, abteilung_id: r.abteilung_id,
    betrag_pro_monat: r.betrag_pro_monat, einzug_turnus: r.einzug_turnus,
    gueltig_ab: r.gueltig_ab, gueltig_bis: r.gueltig_bis ?? '',
    bedingung_abteilung_status: r.bedingung_abteilung_status ?? '',
    // Index-gleiche Arrays in editierbare Zeilen {funktion, abteilung_id} zippen.
    bedingung_eintraege: (r.bedingung_funktionen ?? []).map((f, i) => ({
      funktion: f,
      abteilung_id: (r.bedingung_abteilung_ids ?? [])[i] ?? null,
    })),
    ausnahme_eintraege: (r.ausnahme_funktionen ?? []).map((f, i) => ({
      funktion: f,
      abteilung_id: (r.ausnahme_abteilung_ids ?? [])[i] ?? null,
    })),
    bedingung_alter_min: r.bedingung_alter_min ?? null,
    bedingung_alter_max: r.bedingung_alter_max ?? null,
    zahler_typ: r.zahler_typ,
    gegenkonto: r.gegenkonto ?? '',
    steuerschluessel: r.steuerschluessel ?? '',
    expected_version: r.version,
  } : {
    name: '', abteilung_id: null,
    betrag_pro_monat: 0, einzug_turnus: 'quartal',
    gueltig_ab: heute, gueltig_bis: '',
    bedingung_abteilung_status: '',
    bedingung_eintraege: [],
    ausnahme_eintraege: [],
    bedingung_alter_min: null,
    bedingung_alter_max: null,
    zahler_typ: 'mitglied',
    gegenkonto: '',
    steuerschluessel: '',
  }
  regelDialogOpen.value = true
}

async function saveRegel() {
  regelSaving.value = true
  regelError.value = ''
  try {
    // Bedingung-/Ausnahme-Zeilen ohne gewählte Funktion verwerfen, dann in index-gleiche Arrays aufspalten.
    const bedingungen = (regelForm.value.bedingung_eintraege || []).filter(e => e.funktion)
    const ausnahmen = (regelForm.value.ausnahme_eintraege || []).filter(e => e.funktion)
    const payload = {
      ...regelForm.value,
      betrag_pro_monat: Number(regelForm.value.betrag_pro_monat),
      gueltig_bis: regelForm.value.gueltig_bis || null,
      bedingung_abteilung_status: regelForm.value.bedingung_abteilung_status || null,
      bedingung_funktionen: bedingungen.map(e => e.funktion),
      bedingung_abteilung_ids: bedingungen.map(e => e.abteilung_id ?? null),
      ausnahme_funktionen: ausnahmen.map(e => e.funktion),
      ausnahme_abteilung_ids: ausnahmen.map(e => e.abteilung_id ?? null),
      bedingung_alter_min: regelForm.value.bedingung_alter_min === '' || regelForm.value.bedingung_alter_min == null ? null : Number(regelForm.value.bedingung_alter_min),
      bedingung_alter_max: regelForm.value.bedingung_alter_max === '' || regelForm.value.bedingung_alter_max == null ? null : Number(regelForm.value.bedingung_alter_max),
    }
    if (editingRegel.value?.id) {
      await api.put(`/api/beitraege/regeln/${editingRegel.value.id}`, payload)
    } else {
      await api.post('/api/beitraege/regeln', payload)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    regelDialogOpen.value = false
    await loadRegeln()
  } catch (e) {
    regelError.value = e.response?.data?.detail || 'Fehler'
  } finally {
    regelSaving.value = false
  }
}

async function deleteRegel(r) {
  $q.dialog({ title: 'Regel löschen', message: `„${r.name}" wirklich löschen?`, cancel: true })
    .onOk(async () => {
      await api.delete(`/api/beitraege/regeln/${r.id}`)
      await loadRegeln()
    })
}

// ── Abrechnung ─────────────────────────────────────────────
const stichtag = ref(heute)
const vorschau = ref([])
const vorschauLoading = ref(false)
const abrechnungLoading = ref(false)
const abrechnungErgebnis = ref(null)

// Rückschau-Einstellung: Quartale vor dem aktuellen, die mitabgerechnet werden.
const quartaleRueckschau = ref(1)
const einstellungenLoading = ref(false)

async function ladeEinstellungen() {
  try {
    const { data } = await api.get('/api/beitraege/einstellungen')
    quartaleRueckschau.value = data.quartale_rueckschau
  } catch {
    quartaleRueckschau.value = 1
  }
}

async function speichereEinstellungen() {
  const wert = Number(quartaleRueckschau.value)
  if (!Number.isInteger(wert) || wert < 0) {
    $q.notify({ type: 'negative', message: 'Quartale-Rückschau muss eine Zahl ≥ 0 sein' })
    return
  }
  einstellungenLoading.value = true
  try {
    const { data } = await api.put('/api/beitraege/einstellungen', { quartale_rueckschau: wert })
    quartaleRueckschau.value = data.quartale_rueckschau
    $q.notify({ type: 'positive', message: 'Rückschau gespeichert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    einstellungenLoading.value = false
  }
}
const vorschauFilterName = ref('')
const vorschauFilterAbteilung = ref(null)
// Vorhandene (bereits_vorhanden) standardmäßig ausblenden, nur per Häkchen zeigen.
const vorschauZeigeVorhandene = ref(false)

const vorschauNeu = computed(() => vorschau.value.filter(p => !p.bereits_vorhanden))
const vorschauDuplikate = computed(() => vorschau.value.filter(p => p.bereits_vorhanden))

// Eindeutiger Zeilen-Key: ein Mitglied kann mehrere Beiträge haben (Vereins- +
// Abteilungsbeitrag), daher reicht mitglied_id allein nicht – sonst rendert
// q-table beim Filtern doppelte/veraltete Zeilen.
function vorschauRowKey(row) {
  return `${row.mitglied_id}-${row.beitragsregel_id}-${row.zeitraum}`
}

// Abteilungs-Optionen aus den Mitgliedschaften der Vorschau-Mitglieder ableiten.
const vorschauAbteilungOptionen = computed(() => {
  const ids = new Set()
  for (const p of vorschau.value) {
    for (const aid of (p.mitglied_abteilung_ids || [])) ids.add(aid)
  }
  const nameById = new Map(abteilungOptions.value.map(a => [a.id, a.name]))
  return [...ids]
    .map(id => ({ label: nameById.get(id) ?? `Abteilung ${id}`, value: id }))
    .sort((a, b) => (a.label > b.label ? 1 : -1))
})

const gefilterteVorschau = computed(() => {
  let rows = vorschau.value
  if (vorschauFilterName.value) {
    const q = vorschauFilterName.value.toLowerCase()
    rows = rows.filter(p => p.mitglied_name.toLowerCase().includes(q))
  }
  // Abteilungsfilter: alle Beiträge von Mitgliedern, die der Abteilung angehören
  // (egal ob Vereins-, eigener oder fremder Abteilungsbeitrag).
  if (vorschauFilterAbteilung.value != null) {
    rows = rows.filter(p => (p.mitglied_abteilung_ids || []).includes(vorschauFilterAbteilung.value))
  }
  return rows
})

// In der Tabelle gezeigte Zeilen: vorhandene nur, wenn das Häkchen gesetzt ist.
const sichtbareVorschau = computed(() =>
  vorschauZeigeVorhandene.value
    ? gefilterteVorschau.value
    : gefilterteVorschau.value.filter(p => !p.bereits_vorhanden),
)

const vorschauColumns = [
  { name: 'mitglied_name',     label: 'Mitglied',     field: 'mitglied_name',     align: 'left' },
  { name: 'beitragsregel_name',label: 'Regel',        field: 'beitragsregel_name',align: 'left' },
  { name: 'betrag',            label: 'Betrag',       field: r => r.betrag.toFixed(2) + ' €', align: 'right' },
  { name: 'monate',            label: 'Monate',       field: r => `${r.anzahl_monate}/${r.monate_im_zeitraum}`, align: 'center' },
  { name: 'zeitraum',          label: 'Zeitraum',     field: 'zeitraum',           align: 'left' },
  { name: 'zahler',            label: 'Zahler',       field: 'zahler_typ',         align: 'left' },
  { name: 'status',            label: 'Status',       field: 'bereits_vorhanden',  align: 'left' },
  { name: 'edit',              label: '',             field: 'edit',               align: 'right' },
]

// Mitglied direkt aus der Vorschau bearbeiten (Schlüsselung prüfen/korrigieren).
const kannMitgliedBearbeiten = computed(() => auth.hasPermission('personen.write'))
const editMitgliedOpen = ref(false)
const editMitgliedId   = ref(null)
const editMitgliedName = ref('')

function openMitgliedEdit(row) {
  editMitgliedId.value = row.mitglied_id
  editMitgliedName.value = row.mitglied_name
  editMitgliedOpen.value = true
}

async function ladeVorschau() {
  vorschauLoading.value = true
  abrechnungErgebnis.value = null
  try {
    const { data } = await api.post('/api/beitraege/vorschau', { stichtag: stichtag.value })
    vorschau.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    vorschauLoading.value = false
  }
}

async function confirmAbrechnung() {
  const zeitraeume = [...new Set(vorschauNeu.value.map(p => p.zeitraum))].sort()
  const zrText = zeitraeume.length ? ` (${zeitraeume.join(', ')})` : ''
  $q.dialog({
    title: 'Abrechnung bestätigen',
    message: `${vorschauNeu.value.length} Sollstellungen anlegen${zrText}?`,
    cancel: true, persistent: true,
  }).onOk(async () => {
    abrechnungLoading.value = true
    try {
      const { data } = await api.post('/api/beitraege/abrechnen', { stichtag: stichtag.value })
      abrechnungErgebnis.value = data
      vorschau.value = []
      vorschauFilterName.value = ''
      vorschauFilterAbteilung.value = null
      $q.notify({ type: 'positive', message: `Abrechnung ${data.zeitraum} abgeschlossen` })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
    } finally {
      abrechnungLoading.value = false
    }
  })
}

// ── Sollstellungen ─────────────────────────────────────────
const sollstellungen = ref([])
const sollLoading = ref(false)
const filterZeitraum = ref('')
const zeitraumOptionen = ref([])
const sollSuche = ref('')

// Client-seitiger Fibu-Status-Filter (die Liste ist je Zeitraum bereits vollständig
// geladen). Semantik deckt sich mit fibuStatus()/dem Status-Chip.
const sollFibuFilter = ref('')
const sollFibuFilterOptionen = [
  { label: 'Alle', value: '' },
  { label: 'Offen', value: 'offen' },
  { label: 'An Fibu übergeben', value: 'exportiert' },
  { label: 'Storniert', value: 'storniert' },
]
const gefilterteSollstellungen = computed(() => {
  const f = sollFibuFilter.value
  if (!f) return sollstellungen.value
  return sollstellungen.value.filter((s) => {
    if (f === 'storniert') return s.status === 'storniert'
    if (f === 'exportiert') return s.status !== 'storniert' && s.exportiert_in_export_id != null
    if (f === 'offen') return s.status !== 'storniert' && s.exportiert_in_export_id == null
    return true
  })
})

const sollColumns = [
  { name: 'mitglied_name',     label: 'Mitglied',    field: 'mitglied_name',     align: 'left' },
  { name: 'beitragsregel_name',label: 'Regel',       field: 'beitragsregel_name',align: 'left' },
  { name: 'betrag_soll',       label: 'Betrag',      field: r => r.betrag_soll.toFixed(2) + ' €', align: 'right' },
  { name: 'faelligkeitsdatum', label: 'Fällig',      field: 'faelligkeitsdatum', align: 'left' },
  { name: 'status',            label: 'Fibu',        field: 'status',            align: 'left' },
  { name: 'actions',           label: '',            field: 'actions',           align: 'right' },
]

async function ladeZeitraeume() {
  try {
    const { data } = await api.get('/api/beitraege/sollstellungen/zeitraeume')
    zeitraumOptionen.value = data
    if (!filterZeitraum.value && data.length) {
      filterZeitraum.value = data[0]
      await ladeSollstellungen()
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Zeiträume konnten nicht geladen werden' })
  }
}

async function ladeSollstellungen() {
  if (!filterZeitraum.value) return
  sollLoading.value = true
  try {
    const { data } = await api.get('/api/beitraege/sollstellungen', { params: { zeitraum: filterZeitraum.value } })
    sollstellungen.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    sollLoading.value = false
  }
}

async function markStorniert(s) {
  $q.dialog({
    title: 'Stornieren?',
    message: `Sollstellung für ${s.mitglied_name} stornieren? Sie bleibt bestehen und wird bei einer erneuten Abrechnung nicht neu erzeugt.`,
    cancel: true,
  })
    .onOk(async () => {
      await api.patch(`/api/beitraege/sollstellungen/${s.id}`)
      await ladeSollstellungen()
    })
}

async function deleteSollstellung(s) {
  $q.dialog({
    title: 'Löschen?',
    message: `Sollstellung für ${s.mitglied_name} in den Papierkorb verschieben? Anders als beim Storno wird sie bei der nächsten Abrechnung wieder neu angelegt.`,
    cancel: true,
    ok: { label: 'Löschen', color: 'negative' },
  })
    .onOk(async () => {
      await api.delete(`/api/beitraege/sollstellungen/${s.id}`)
      await ladeSollstellungen()
      if (papierkorbOffen.value) await ladePapierkorb()
    })
}

// ── Papierkorb (Ticket #52) ────────────────────────────────
const papierkorbOffen = ref(false)
const papierkorbRows = ref([])
const papierkorbLoading = ref(false)
const papierkorbColumns = [
  { name: 'mitglied_name',      label: 'Mitglied',  field: 'mitglied_name',      align: 'left' },
  { name: 'beitragsregel_name', label: 'Regel',     field: 'beitragsregel_name', align: 'left' },
  { name: 'zeitraum',           label: 'Zeitraum',  field: 'zeitraum',           align: 'left' },
  { name: 'betrag_soll',        label: 'Betrag',    field: r => r.betrag_soll.toFixed(2) + ' €', align: 'right' },
  { name: 'actions',            label: '',          field: 'actions',            align: 'right' },
]

async function ladePapierkorb() {
  papierkorbLoading.value = true
  try {
    const { data } = await api.get('/api/beitraege/sollstellungen/papierkorb')
    papierkorbRows.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden des Papierkorbs' })
  } finally {
    papierkorbLoading.value = false
  }
}

async function togglePapierkorb() {
  papierkorbOffen.value = !papierkorbOffen.value
  if (papierkorbOffen.value) await ladePapierkorb()
}

async function restoreSollstellung(s) {
  try {
    await api.post(`/api/beitraege/sollstellungen/${s.id}/restore`)
    await Promise.all([ladePapierkorb(), ladeSollstellungen(), ladeZeitraeume()])
    $q.notify({ type: 'positive', message: 'Sollstellung wiederhergestellt' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Wiederherstellen nicht möglich' })
  }
}

async function loadOptionen() {
  const { data: ab } = await api.get('/api/abteilungen/')
  abteilungOptions.value = ab
}

usePageRefresh(() => Promise.all([loadRegeln(), loadOptionen(), loadFunktionOptionen(), ladeDashboard(),
  ladeZeitraeume(), ladeEinstellungen()]))
onMounted(async () => {
  await Promise.all([loadRegeln(), loadOptionen(), loadFunktionOptionen(), ladeDashboard(),
    ladeZeitraeume(), ladeEinstellungen()])
})
</script>
