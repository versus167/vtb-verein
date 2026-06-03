<template>
  <q-page padding>
    <!-- Kopfzeile -->
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Personen</div>
      <q-btn icon="add" :label="$q.screen.gt.xs ? 'Neue Person' : undefined"
        :round="$q.screen.lt.sm" color="primary" unelevated @click="openCreateDialog" />
    </div>

    <!-- Filter -->
    <div class="row q-gutter-sm q-mb-md items-center">
      <q-btn-toggle v-model="filter" :options="filterOptions" unelevated dense
        toggle-color="primary" color="white" text-color="primary" />
      <q-input v-model="search" placeholder="Suche..." outlined dense clearable
        style="min-width: 200px">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
    </div>

    <!-- Mobile/Tablet: Kacheln -->
    <template v-if="$q.screen.lt.md">
      <div v-if="loading" class="row justify-center q-py-xl">
        <q-spinner size="40px" color="primary" />
      </div>
      <div v-else-if="filteredPersonen.length === 0" class="text-center text-grey q-py-xl">
        Keine Personen gefunden.
      </div>
      <q-card v-for="p in filteredPersonen" :key="p.user_id ?? 'm_' + p.mitglied?.id" elevated class="q-mb-md"
        style="border-radius:14px;overflow:hidden">
        <q-card-section class="q-py-sm q-px-md">
          <div class="row items-center no-wrap q-mb-xs">
            <div class="col">
              <div v-if="p.mitglied" class="text-subtitle2 text-weight-bold">
                {{ p.mitglied.nachname }}, {{ p.mitglied.vorname }}
              </div>
              <div v-else class="text-subtitle2 text-weight-bold text-grey-7">{{ p.username }}</div>
              <div v-if="p.username" class="text-caption text-grey">{{ p.username }}</div>
              <div v-else class="text-caption text-grey-5">Kein Login</div>
            </div>
            <div class="row items-center q-gutter-xs">
              <q-chip v-if="p.role" dense :color="rolleColor(p.role)" text-color="white" size="sm">
                {{ rolleLabel(p.role) }}
              </q-chip>
              <q-icon v-if="p.user_id && p.active" name="check_circle" color="positive" size="sm" />
              <q-icon v-else-if="p.user_id" name="cancel" color="negative" size="sm" />
            </div>
          </div>
          <div v-if="p.email" class="text-caption text-grey-7 q-mb-xs">{{ p.email }}</div>
          <div v-if="p.abteilungen?.length" class="row q-gutter-xs q-mb-xs">
            <q-chip v-for="ab in p.abteilungen" :key="ab.id" dense size="sm"
              :color="abteilungStatusColor(ab.status)" text-color="white">
              {{ ab.abteilung_kuerzel || ab.abteilung_name }}
            </q-chip>
          </div>
          <div v-if="p.last_login" class="text-caption text-grey-5">
            Zuletzt aktiv: {{ formatLastLogin(p.last_login) }}
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions class="q-px-sm q-py-xs">
          <q-btn v-if="p.user_id" flat dense round icon="edit" color="primary" size="sm"
            @click="openEditUserDialog(p)">
            <q-tooltip>Account bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat dense round icon="person" color="teal" size="sm"
            @click="openEditMitgliedDialog(p)">
            <q-tooltip>Vereinsdaten bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-else-if="p.user_id" flat dense round icon="person_add" color="teal" size="sm"
            @click="openAddMitgliedDialog(p)">
            <q-tooltip>Als Vereinsmitglied erfassen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat dense round icon="group" color="purple" size="sm"
            @click="openAbteilungenDialog(p)">
            <q-tooltip>Abteilungen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat dense round icon="badge" color="indigo" size="sm"
            @click="openFunktionenDialog(p)">
            <q-tooltip>Funktionen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.user_id" flat dense round icon="security" color="grey" size="sm"
            @click="$router.push({ name: 'user-permissions', params: { id: p.user_id } })">
            <q-tooltip>Berechtigungen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.user_id" flat dense round icon="history" color="grey" size="sm"
            @click="openHistoryDialog(p)">
            <q-tooltip>Änderungshistorie</q-tooltip>
          </q-btn>
          <q-space />
          <q-btn flat dense round icon="delete" color="negative" size="sm"
            :disable="p.user_id === auth.user?.id"
            @click="confirmDelete(p)">
            <q-tooltip>Löschen</q-tooltip>
          </q-btn>
        </q-card-actions>
      </q-card>
    </template>

    <!-- Desktop: Tabelle -->
    <q-table v-else :rows="filteredPersonen" :columns="columns" :row-key="r => r.user_id ?? 'm_' + r.mitglied?.id"
      flat bordered :loading="loading" :rows-per-page-options="[25, 50, 0]">

      <template #body-cell-name="props">
        <q-td :props="props">
          <div v-if="props.row.mitglied" class="text-weight-medium">
            {{ props.row.mitglied.nachname }}, {{ props.row.mitglied.vorname }}
          </div>
          <div v-else class="text-grey-7">{{ props.row.username }}</div>
          <div class="text-caption text-grey">{{ props.row.username }}</div>
        </q-td>
      </template>

      <template #body-cell-mitgliedsnr="props">
        <q-td :props="props">
          <span v-if="props.row.mitglied?.mitgliedsnummer">{{ props.row.mitglied.mitgliedsnummer }}</span>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-rolle="props">
        <q-td :props="props">
          <q-chip dense :color="rolleColor(props.row.role)" text-color="white" size="sm">
            {{ rolleLabel(props.row.role) }}
          </q-chip>
        </q-td>
      </template>

      <template #body-cell-status="props">
        <q-td :props="props" class="text-center">
          <q-icon v-if="props.row.active" name="check_circle" color="positive" size="sm">
            <q-tooltip>Aktiv</q-tooltip>
          </q-icon>
          <q-icon v-else name="cancel" color="negative" size="sm">
            <q-tooltip>Inaktiv</q-tooltip>
          </q-icon>
        </q-td>
      </template>

      <template #body-cell-last_login="props">
        <q-td :props="props">
          <span v-if="props.row.last_login" class="text-caption">
            {{ formatLastLogin(props.row.last_login) }}
            <q-tooltip>{{ new Date(props.row.last_login).toLocaleString('de-DE') }}</q-tooltip>
          </span>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-abteilungen="props">
        <q-td :props="props">
          <q-chip v-for="ab in props.row.abteilungen" :key="ab.id" dense size="sm"
            :color="abteilungStatusColor(ab.status)" text-color="white" class="q-mr-xs">
            {{ ab.abteilung_kuerzel || ab.abteilung_name }}
          </q-chip>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" style="white-space: nowrap">
          <q-btn v-if="props.row.user_id" flat dense round icon="edit" color="primary" size="sm"
            @click="openEditUserDialog(props.row)">
            <q-tooltip>Account bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-if="props.row.mitglied" flat dense round icon="person" color="teal" size="sm"
            @click="openEditMitgliedDialog(props.row)">
            <q-tooltip>Vereinsdaten bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-else-if="props.row.user_id" flat dense round icon="person_add" color="teal" size="sm"
            @click="openAddMitgliedDialog(props.row)">
            <q-tooltip>Als Vereinsmitglied erfassen</q-tooltip>
          </q-btn>
          <q-btn v-if="props.row.mitglied" flat dense round icon="group" color="purple" size="sm"
            @click="openAbteilungenDialog(props.row)">
            <q-tooltip>Abteilungen</q-tooltip>
          </q-btn>
          <q-btn v-if="props.row.mitglied" flat dense round icon="badge" color="indigo" size="sm"
            @click="openFunktionenDialog(props.row)">
            <q-tooltip>Funktionen</q-tooltip>
          </q-btn>
          <q-btn v-if="props.row.user_id" flat dense round icon="security" color="grey" size="sm"
            @click="$router.push({ name: 'user-permissions', params: { id: props.row.user_id } })">
            <q-tooltip>Berechtigungen</q-tooltip>
          </q-btn>
          <q-btn v-if="props.row.user_id" flat dense round icon="history" color="grey" size="sm"
            @click="openHistoryDialog(props.row)">
            <q-tooltip>Änderungshistorie</q-tooltip>
          </q-btn>
          <q-btn flat dense round icon="delete" color="negative" size="sm"
            :disable="props.row.user_id === auth.user?.id"
            @click="confirmDelete(props.row)">
            <q-tooltip>Löschen</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- ════════════════════════════════════════════════
         Neue Person anlegen
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="createOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:520px;max-width:680px'">
        <q-card-section class="text-h6">Neue Person</q-card-section>
        <q-separator />
        <q-tabs v-model="createTab" dense align="left" class="q-px-md">
          <q-tab name="mitglied" label="Vereinsmitglied" icon="person" />
          <q-tab name="user" label="Benutzer/Admin" icon="manage_accounts" />
        </q-tabs>
        <q-separator />
        <q-card-section class="q-gutter-sm" style="max-height:70vh;overflow-y:auto">
          <!-- Tab: Vereinsmitglied -->
          <q-tab-panels v-model="createTab" animated>
            <q-tab-panel name="mitglied" class="q-gutter-sm q-pa-none">
              <div class="row q-gutter-sm">
                <q-input v-model="createForm.vorname" label="Vorname *" outlined dense class="col" />
                <q-input v-model="createForm.nachname" label="Nachname *" outlined dense class="col" />
              </div>
              <q-input v-model="createForm.email" label="E-Mail (optional)" outlined dense type="email" />
              <div v-if="!createForm.email" class="text-caption text-grey-6">
                <q-icon name="info" size="xs" /> Ohne E-Mail: kein Login möglich, nur Mitglied-Datensatz
              </div>
              <div v-if="createForm.email" class="row q-gutter-sm">
                <q-select v-model="createForm.role" :options="rolleOptions" label="Rolle"
                  outlined dense emit-value map-options class="col" />
                <q-toggle v-model="createForm.active" label="Aktiv" class="self-center" />
              </div>
              <q-input v-model="createForm.eintrittsdatum" label="Eintrittsdatum" outlined dense type="date" />
              <q-select v-model="createForm.mitglied_status" :options="mitgliedStatusOptions"
                label="Vereinsstatus" outlined dense emit-value map-options />
              <q-input v-model="createForm.password" label="Passwort (optional)" outlined dense
                type="password" hint="Leer lassen → Login per Magic-Link" />
              <q-expansion-item label="Adresse" dense>
                <div class="q-gutter-sm q-pt-sm">
                  <q-input v-model="createForm.strasse" label="Straße" outlined dense />
                  <div class="row q-gutter-sm">
                    <q-input v-model="createForm.plz" label="PLZ" outlined dense style="width:100px" />
                    <q-input v-model="createForm.ort" label="Ort" outlined dense class="col" />
                  </div>
                  <q-input v-model="createForm.land" label="Land" outlined dense />
                </div>
              </q-expansion-item>
              <q-expansion-item label="Zahlung / SEPA" dense>
                <div class="q-gutter-sm q-pt-sm">
                  <q-input v-model="createForm.zahlungsart" label="Zahlungsart" outlined dense />
                  <q-input v-model="createForm.iban" label="IBAN" outlined dense />
                  <q-input v-model="createForm.bic" label="BIC" outlined dense />
                  <q-input v-model="createForm.kontoinhaber" label="Kontoinhaber" outlined dense />
                </div>
              </q-expansion-item>
            </q-tab-panel>

            <!-- Tab: Benutzer/Admin -->
            <q-tab-panel name="user" class="q-gutter-sm q-pa-none">
              <q-input v-model="createForm.username" label="Benutzername *" outlined dense />
              <q-input v-model="createForm.email" label="E-Mail *" outlined dense type="email" />
              <div class="row q-gutter-sm">
                <q-select v-model="createForm.role" :options="rolleOptionsAdmin" label="Rolle"
                  outlined dense emit-value map-options class="col" />
                <q-toggle v-model="createForm.active" label="Aktiv" class="self-center" />
              </div>
              <q-input v-model="createForm.password" label="Passwort (optional)" outlined dense type="password" />
            </q-tab-panel>
          </q-tab-panels>
          <div v-if="createError" class="text-negative text-caption">{{ createError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Anlegen" color="primary" unelevated :loading="createSaving" @click="onCreate" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ════════════════════════════════════════════════
         User-Daten bearbeiten
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="editUserOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:420px'">
        <q-card-section class="text-h6">Account bearbeiten</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="editUserForm.username" label="Benutzername" outlined dense />
          <q-input v-model="editUserForm.email" label="E-Mail" outlined dense type="email" />
          <q-select v-model="editUserForm.role" :options="rolleOptionsAll" label="Rolle"
            outlined dense emit-value map-options />
          <q-toggle v-model="editUserForm.active" label="Aktiv" />
          <div v-if="editUserError" class="text-negative text-caption">{{ editUserError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="editUserSaving" @click="onSaveUser" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ════════════════════════════════════════════════
         Mitglied-Daten bearbeiten
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="editMitgliedOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:520px;max-width:680px'">
        <q-card-section class="text-h6">{{ editMitgliedIsNew ? 'Als Vereinsmitglied erfassen' : 'Vereinsdaten bearbeiten' }}</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm" style="max-height:70vh;overflow-y:auto">
          <div class="row q-gutter-sm">
            <q-input v-model="editMitgliedForm.vorname" label="Vorname *" outlined dense class="col" />
            <q-input v-model="editMitgliedForm.nachname" label="Nachname *" outlined dense class="col" />
          </div>
          <q-input v-model="editMitgliedForm.telefon" label="Telefon" outlined dense />
          <q-input v-model="editMitgliedForm.geburtsdatum" label="Geburtsdatum" outlined dense type="date" />
          <div class="row q-gutter-sm">
            <q-input v-model="editMitgliedForm.eintrittsdatum" label="Eintrittsdatum" outlined dense type="date" class="col" />
            <q-input v-model="editMitgliedForm.austrittsdatum" label="Austrittsdatum" outlined dense type="date" class="col" />
          </div>
          <q-select v-model="editMitgliedForm.status" :options="mitgliedStatusOptions"
            label="Vereinsstatus" outlined dense emit-value map-options />
          <q-input v-model="editMitgliedForm.strasse" label="Straße" outlined dense />
          <div class="row q-gutter-sm">
            <q-input v-model="editMitgliedForm.plz" label="PLZ" outlined dense style="width:100px" />
            <q-input v-model="editMitgliedForm.ort" label="Ort" outlined dense class="col" />
          </div>
          <q-input v-model="editMitgliedForm.land" label="Land" outlined dense />
          <q-input v-model="editMitgliedForm.zahlungsart" label="Zahlungsart" outlined dense />
          <q-input v-model="editMitgliedForm.iban" label="IBAN" outlined dense />
          <q-input v-model="editMitgliedForm.bic" label="BIC" outlined dense />
          <q-input v-model="editMitgliedForm.kontoinhaber" label="Kontoinhaber" outlined dense />
          <div v-if="editMitgliedError" class="text-negative text-caption">{{ editMitgliedError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="editMitgliedSaving" @click="onSaveMitglied" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ════════════════════════════════════════════════
         Abteilungen-Dialog (übernommen aus MitgliederPage)
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="abteilungenOpen" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:500px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Abteilungen</div>
          <div v-if="aktivPerson" class="text-caption text-grey q-ml-sm">
            {{ aktivPerson.mitglied?.nachname }}, {{ aktivPerson.mitglied?.vorname }}
          </div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-inner-loading :showing="abteilungenLoading" />
          <div v-if="!abteilungenLoading && zuordnungen.length === 0"
            class="text-grey text-center q-py-md">Keine Abteilungszuordnungen.</div>
          <q-list separator>
            <q-item v-for="z in zuordnungen" :key="z.id">
              <q-item-section>
                <q-item-label>{{ z.abteilung_name }}</q-item-label>
                <q-item-label caption>
                  <q-chip dense size="xs" :color="abteilungStatusColor(z.status)" text-color="white">{{ z.status }}</q-chip>
                  <span v-if="z.von || z.bis" class="q-ml-xs">{{ z.von ?? '?' }} – {{ z.bis ?? 'heute' }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row q-gutter-xs">
                  <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openEditZuordnung(z)" />
                  <q-btn flat dense round icon="delete" color="negative" size="sm" @click="deleteZuordnung(z)" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <q-btn flat icon="add" label="Abteilung hinzufügen" color="primary" class="q-mt-sm"
            @click="openAddZuordnung" />
          <!-- Formular -->
          <div v-if="zuordnungFormOpen" class="q-mt-md q-gutter-sm">
            <q-select v-model="zuordnungForm.abteilung_id" :options="alleAbteilungen"
              :option-value="a => a.id" :option-label="a => a.name" emit-value map-options
              label="Abteilung *" outlined dense :readonly="!!editingZuordnungId" />
            <q-select v-model="zuordnungForm.status" :options="abteilungZuordnungStatusOptions"
              label="Status" outlined dense emit-value map-options />
            <div class="row q-gutter-sm">
              <q-input v-model="zuordnungForm.von" label="Von" outlined dense type="date" class="col" />
              <q-input v-model="zuordnungForm.bis" label="Bis" outlined dense type="date" class="col" />
            </div>
            <div class="row q-gutter-sm">
              <q-btn flat label="Abbrechen" @click="zuordnungFormOpen = false" />
              <q-btn unelevated :label="editingZuordnungId ? 'Speichern' : 'Hinzufügen'"
                color="primary" :loading="zuordnungSaving" @click="onSaveZuordnung" />
            </div>
          </div>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ════════════════════════════════════════════════
         Funktionen-Dialog
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="funktionenOpen" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:500px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Funktionen</div>
          <div v-if="aktivPerson" class="text-caption text-grey q-ml-sm">
            {{ aktivPerson.mitglied?.nachname }}, {{ aktivPerson.mitglied?.vorname }}
          </div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-inner-loading :showing="funktionenLoading" />
          <div v-if="!funktionenLoading && funktionen.length === 0"
            class="text-grey text-center q-py-md">Keine Funktionen zugewiesen.</div>
          <q-list separator>
            <q-item v-for="f in funktionen" :key="f.id">
              <q-item-section>
                <q-item-label>{{ funktionLabel(f.funktion) }}</q-item-label>
                <q-item-label caption>
                  <span v-if="f.abteilung_name" class="q-mr-sm">{{ f.abteilung_name }}</span>
                  <span v-if="f.von || f.bis">{{ f.von ?? '?' }} – {{ f.bis ?? 'heute' }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row q-gutter-xs">
                  <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openEditFunktion(f)" />
                  <q-btn flat dense round icon="delete" color="negative" size="sm" @click="deleteFunktion(f)" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <q-btn flat icon="add" label="Funktion hinzufügen" color="primary" class="q-mt-sm"
            @click="openAddFunktion" />
          <!-- Formular -->
          <div v-if="funktionFormOpen" class="q-mt-md q-gutter-sm">
            <q-select v-model="funktionForm.funktion" :options="funktionOptionen"
              option-value="value" option-label="label" emit-value map-options
              label="Funktion *" outlined dense :readonly="!!editingFunktionId" />
            <q-select v-model="funktionForm.abteilung_id" :options="alleAbteilungen"
              :option-value="a => a.id" :option-label="a => a.name" emit-value map-options
              label="Abteilung (leer = vereinsweit)" outlined dense clearable />
            <div class="row q-gutter-sm">
              <q-input v-model="funktionForm.von" label="Von" outlined dense type="date" class="col" />
              <q-input v-model="funktionForm.bis" label="Bis" outlined dense type="date" class="col" />
            </div>
            <div class="row q-gutter-sm">
              <q-btn flat label="Abbrechen" @click="funktionFormOpen = false" />
              <q-btn unelevated :label="editingFunktionId ? 'Speichern' : 'Hinzufügen'"
                color="primary" :loading="funktionSaving" @click="onSaveFunktion" />
            </div>
          </div>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ════════════════════════════════════════════════
         History-Dialog
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="historyOpen" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:540px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Änderungshistorie</div>
          <div v-if="historyPerson" class="text-caption text-grey q-ml-sm">
            {{ historyPerson.mitglied ? `${historyPerson.mitglied.nachname}, ${historyPerson.mitglied.vorname}` : historyPerson.username }}
          </div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <div v-if="historyLoading" class="row justify-center q-py-md"><q-spinner size="32px" color="primary" /></div>
          <div v-else-if="historyEntries.length === 0" class="text-grey text-center q-py-md">Keine Einträge.</div>
          <q-timeline v-else color="grey" layout="dense">
            <template v-for="(h, idx) in historyEntries" :key="idx">
              <q-timeline-entry
                :subtitle="`${h._zeit?.slice(0,16).replace('T',' ')} · ${h._by}`"
                :color="h._color" :icon="h._icon">
                <div class="text-caption">
                  <div class="text-weight-medium text-grey-6 q-mb-xs">{{ h._label }}</div>
                  <template v-if="h._diffs && h._diffs.length">
                    <div v-for="d in h._diffs" :key="d.feld">
                      <span class="text-grey">{{ d.feld }}: </span>
                      <span class="text-strike text-grey-6">{{ d.alt }}</span>
                      <q-icon name="arrow_forward" size="xs" class="q-mx-xs text-grey" />
                      <span class="text-weight-medium">{{ d.neu }}</span>
                    </div>
                  </template>
                  <template v-else-if="h._full">
                    <div v-for="(v, k) in h._full" :key="k" v-if="v">
                      <span class="text-grey">{{ k }}: </span>{{ v }}
                    </div>
                  </template>
                </div>
              </q-timeline-entry>
            </template>
          </q-timeline>
        </q-card-section>
      </q-card>
    </q-dialog>

  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

const $q = useQuasar()
const router = useRouter()
const auth = useAuthStore()

// ── Daten ──────────────────────────────────────────────────
const personen = ref([])
const loading = ref(false)
const filter = ref('alle')
const search = ref('')

const filterOptions = [
  { label: 'Alle', value: 'alle' },
  { label: 'Nur Mitglieder', value: 'mitglieder' },
  { label: 'Nur Benutzer', value: 'benutzer' },
]

const columns = [
  { name: 'name',        label: 'Name',        field: 'username', align: 'left' },
  { name: 'email',       label: 'E-Mail',       field: 'email',    align: 'left' },
  { name: 'mitgliedsnr', label: 'Mitgliedsnr.', field: r => r.mitglied?.mitgliedsnummer, align: 'left' },
  { name: 'rolle',       label: 'Rolle',        field: 'role',     align: 'left' },
  { name: 'status',      label: 'Status',       field: 'active',      align: 'center' },
  { name: 'last_login',  label: 'Zuletzt aktiv', field: 'last_login', align: 'left' },
  { name: 'abteilungen', label: 'Abteilungen',  field: 'abteilungen', align: 'left' },
  { name: 'actions',     label: '',             field: 'actions',  align: 'right', style: 'width: 200px' },
]

const filteredPersonen = computed(() => {
  let list = personen.value
  if (filter.value === 'mitglieder') list = list.filter(p => p.mitglied)
  if (filter.value === 'benutzer')   list = list.filter(p => !p.mitglied)
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter(p =>
      p.username.toLowerCase().includes(q) ||
      p.email.toLowerCase().includes(q) ||
      (p.mitglied?.vorname ?? '').toLowerCase().includes(q) ||
      (p.mitglied?.nachname ?? '').toLowerCase().includes(q) ||
      String(p.mitglied?.mitgliedsnummer ?? '').includes(q)
    )
  }
  return list
})

// ── Optionen ───────────────────────────────────────────────
const rolleOptions = [
  { label: 'Mitglied',    value: 'mitglied' },
  { label: 'Bearbeiter',  value: 'user' },
  { label: 'Nur Lesen',   value: 'readonly' },
]
const rolleOptionsAdmin = [
  { label: 'Administrator', value: 'admin' },
  { label: 'Bearbeiter',    value: 'user' },
  { label: 'Nur Lesen',     value: 'readonly' },
  { label: 'Speziell',      value: 'special' },
]
const rolleOptionsAll = [...rolleOptions, ...rolleOptionsAdmin.filter(o => !rolleOptions.find(r => r.value === o.value))]
const mitgliedStatusOptions = [
  { label: 'Aktiv',           value: 'aktiv' },
  { label: 'Passiv',          value: 'passiv' },
  { label: 'Ausgetreten',     value: 'ausgetreten' },
]
const abteilungZuordnungStatusOptions = ['aktiv', 'passiv', 'trainer', 'vorstand', 'ehrenmitglied']

function formatLastLogin(iso) {
  const diff = Date.now() - new Date(iso).getTime()
  const min  = Math.floor(diff / 60000)
  if (min < 1)   return 'gerade eben'
  if (min < 60)  return `vor ${min} Min.`
  const h = Math.floor(min / 60)
  if (h < 24)    return `vor ${h} Std.`
  const d = Math.floor(h / 24)
  if (d < 30)    return `vor ${d} Tag${d === 1 ? '' : 'en'}`
  const m = Math.floor(d / 30)
  if (m < 12)    return `vor ${m} Monat${m === 1 ? '' : 'en'}`
  const y = Math.floor(d / 365)
  return `vor ${y} Jahr${y === 1 ? '' : 'en'}`
}

function rolleLabel(role) {
  return { admin: 'Admin', user: 'Bearbeiter', readonly: 'Nur Lesen', mitglied: 'Mitglied', special: 'Speziell' }[role] ?? role
}
function rolleColor(role) {
  return { admin: 'negative', user: 'primary', readonly: 'grey', mitglied: 'teal', special: 'purple' }[role] ?? 'grey'
}
function abteilungStatusColor(s) {
  return { aktiv: 'positive', passiv: 'grey', trainer: 'blue', vorstand: 'purple', ehrenmitglied: 'amber' }[s] ?? 'grey'
}

// ── Laden ──────────────────────────────────────────────────
async function loadPersonen() {
  loading.value = true
  try {
    const { data } = await api.get('/api/personen/')
    personen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
}

// ── Anlegen ────────────────────────────────────────────────
const createOpen   = ref(false)
const createTab    = ref('mitglied')
const createSaving = ref(false)
const createError  = ref('')
const createForm   = ref({})

function openCreateDialog() {
  createTab.value = 'mitglied'
  createError.value = ''
  createForm.value = {
    vorname: '', nachname: '', email: '', role: 'mitglied', active: true,
    password: '', username: '',
    eintrittsdatum: '', mitglied_status: 'aktiv',
    strasse: '', plz: '', ort: '', land: '',
    zahlungsart: '', iban: '', bic: '', kontoinhaber: '',
  }
  createOpen.value = true
}

async function onCreate() {
  createError.value = ''
  createSaving.value = true
  try {
    const payload = { ...createForm.value, status: createForm.value.mitglied_status }
    if (createTab.value === 'user') {
      delete payload.vorname; delete payload.nachname
    } else {
      delete payload.username
    }
    await api.post('/api/personen/', payload)
    $q.notify({ type: 'positive', message: 'Person angelegt' })
    createOpen.value = false
    await loadPersonen()
  } catch (e) {
    createError.value = e.response?.data?.detail || 'Fehler beim Anlegen'
  } finally {
    createSaving.value = false
  }
}

// ── User bearbeiten ────────────────────────────────────────
const editUserOpen   = ref(false)
const editUserSaving = ref(false)
const editUserError  = ref('')
const editUserForm   = ref({})
const editingUserId  = ref(null)

function openEditUserDialog(row) {
  editingUserId.value = row.user_id
  editUserError.value = ''
  editUserForm.value = {
    username: row.username, email: row.email,
    role: row.role, active: row.active,
    expected_version: row.user_version,
  }
  editUserOpen.value = true
}

async function onSaveUser() {
  editUserSaving.value = true
  editUserError.value = ''
  try {
    await api.put(`/api/personen/${editingUserId.value}/user`, editUserForm.value)
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    editUserOpen.value = false
    await loadPersonen()
  } catch (e) {
    editUserError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    editUserSaving.value = false
  }
}

// ── Mitglied bearbeiten ────────────────────────────────────
const editMitgliedOpen   = ref(false)
const editMitgliedSaving = ref(false)
const editMitgliedError  = ref('')
const editMitgliedForm   = ref({})
const editingMitgliedUserId = ref(null)
const editMitgliedIsNew  = ref(false)

function openAddMitgliedDialog(row) {
  editingMitgliedUserId.value = row.user_id
  editMitgliedIsNew.value = true
  editMitgliedError.value = ''
  editMitgliedForm.value = {
    vorname: '', nachname: '', geburtsdatum: '', telefon: '',
    eintrittsdatum: '', austrittsdatum: '',
    status: 'aktiv', zahlungsart: '',
    strasse: '', plz: '', ort: '', land: '',
    iban: '', bic: '', kontoinhaber: '',
    expected_version: 1,
  }
  editMitgliedOpen.value = true
}

function openEditMitgliedDialog(row) {
  editingMitgliedUserId.value = row.user_id
  editMitgliedIsNew.value = false
  editMitgliedError.value = ''
  const m = row.mitglied
  editMitgliedForm.value = {
    vorname: m.vorname, nachname: m.nachname, geburtsdatum: m.geburtsdatum ?? '',
    telefon: m.telefon ?? '',
    eintrittsdatum: m.eintrittsdatum ?? '', austrittsdatum: m.austrittsdatum ?? '',
    status: m.status, zahlungsart: m.zahlungsart ?? '',
    strasse: m.strasse ?? '', plz: m.plz ?? '', ort: m.ort ?? '', land: m.land ?? '',
    iban: m.iban ?? '', bic: m.bic ?? '', kontoinhaber: m.kontoinhaber ?? '',
    expected_version: m.version,
  }
  editMitgliedOpen.value = true
}

async function onSaveMitglied() {
  editMitgliedSaving.value = true
  editMitgliedError.value = ''
  try {
    if (editMitgliedIsNew.value) {
      await api.post(`/api/personen/${editingMitgliedUserId.value}/mitglied`, editMitgliedForm.value)
    } else {
      await api.put(`/api/personen/${editingMitgliedUserId.value}/mitglied`, editMitgliedForm.value)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    editMitgliedOpen.value = false
    await loadPersonen()
  } catch (e) {
    editMitgliedError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    editMitgliedSaving.value = false
  }
}

// ── Löschen ────────────────────────────────────────────────
function confirmDelete(row) {
  const name = row.mitglied ? `${row.mitglied.vorname} ${row.mitglied.nachname}` : row.username
  $q.dialog({ title: 'Person löschen', message: `„${name}" wirklich löschen?`, cancel: true, persistent: true })
    .onOk(async () => {
      try {
        if (row.user_id) {
          await api.delete(`/api/personen/${row.user_id}`)
        } else {
          await api.delete(`/api/personen/mitglied/${row.mitglied.id}`)
        }
        $q.notify({ type: 'positive', message: 'Gelöscht' })
        await loadPersonen()
      } catch (e) {
        $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen' })
      }
    })
}

// ── Abteilungen ────────────────────────────────────────────
const abteilungenOpen    = ref(false)
const abteilungenLoading = ref(false)
const aktivPerson        = ref(null)
const zuordnungen        = ref([])
const alleAbteilungen    = ref([])
const zuordnungFormOpen  = ref(false)
const zuordnungSaving    = ref(false)
const editingZuordnungId = ref(null)
const editingZuordnungVersion = ref(null)
const zuordnungForm      = ref({ abteilung_id: null, status: 'aktiv', von: '', bis: '' })

async function openAbteilungenDialog(row) {
  aktivPerson.value = row
  zuordnungFormOpen.value = false
  abteilungenOpen.value = true
  abteilungenLoading.value = true
  try {
    const [{ data: z }, { data: ab }] = await Promise.all([
      api.get(`/api/mitglieder/${row.mitglied.id}/abteilungen`),
      api.get('/api/abteilungen/'),
    ])
    zuordnungen.value = z
    alleAbteilungen.value = ab
  } finally {
    abteilungenLoading.value = false
  }
}

function openAddZuordnung() {
  editingZuordnungId.value = null
  zuordnungForm.value = { abteilung_id: null, status: 'aktiv', von: '', bis: '' }
  zuordnungFormOpen.value = true
}

function openEditZuordnung(z) {
  editingZuordnungId.value = z.id
  editingZuordnungVersion.value = z.version
  zuordnungForm.value = { abteilung_id: z.abteilung_id, status: z.status, von: z.von ?? '', bis: z.bis ?? '' }
  zuordnungFormOpen.value = true
}

async function onSaveZuordnung() {
  zuordnungSaving.value = true
  const mitgliedId = aktivPerson.value.mitglied.id
  try {
    if (editingZuordnungId.value) {
      await api.put(`/api/mitglieder/${mitgliedId}/abteilungen/${editingZuordnungId.value}`, {
        status: zuordnungForm.value.status,
        von: zuordnungForm.value.von || null,
        bis: zuordnungForm.value.bis || null,
        expected_version: editingZuordnungVersion.value,
      })
    } else {
      await api.post(`/api/mitglieder/${mitgliedId}/abteilungen`, {
        abteilung_id: zuordnungForm.value.abteilung_id,
        status: zuordnungForm.value.status,
        von: zuordnungForm.value.von || null,
        bis: zuordnungForm.value.bis || null,
      })
    }
    zuordnungFormOpen.value = false
    const { data } = await api.get(`/api/mitglieder/${mitgliedId}/abteilungen`)
    zuordnungen.value = data
    await loadPersonen()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    zuordnungSaving.value = false
  }
}

async function deleteZuordnung(z) {
  const mitgliedId = aktivPerson.value.mitglied.id
  try {
    await api.delete(`/api/mitglieder/${mitgliedId}/abteilungen/${z.id}`)
    zuordnungen.value = zuordnungen.value.filter(x => x.id !== z.id)
    await loadPersonen()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

// ── Funktionen ─────────────────────────────────────────────
const funktionenOpen    = ref(false)
const funktionenLoading = ref(false)
const funktionen        = ref([])
const funktionFormOpen  = ref(false)
const funktionSaving    = ref(false)
const editingFunktionId      = ref(null)
const editingFunktionVersion = ref(null)
const funktionForm      = ref({ funktion: null, abteilung_id: null, von: '', bis: '' })

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

async function openFunktionenDialog(row) {
  aktivPerson.value = row
  funktionFormOpen.value = false
  funktionenOpen.value = true
  funktionenLoading.value = true
  try {
    const [{ data: fns }, { data: ab }] = await Promise.all([
      api.get(`/api/mitglieder/${row.mitglied.id}/funktionen`),
      alleAbteilungen.value.length ? Promise.resolve({ data: alleAbteilungen.value }) : api.get('/api/abteilungen/'),
    ])
    funktionen.value = fns
    alleAbteilungen.value = ab
  } finally {
    funktionenLoading.value = false
  }
}

function openAddFunktion() {
  editingFunktionId.value = null
  funktionForm.value = { funktion: null, abteilung_id: null, von: '', bis: '' }
  funktionFormOpen.value = true
}

function openEditFunktion(f) {
  editingFunktionId.value = f.id
  editingFunktionVersion.value = f.version
  funktionForm.value = { funktion: f.funktion, abteilung_id: f.abteilung_id, von: f.von ?? '', bis: f.bis ?? '' }
  funktionFormOpen.value = true
}

async function onSaveFunktion() {
  if (!funktionForm.value.funktion) {
    $q.notify({ type: 'negative', message: 'Bitte eine Funktion auswählen.' })
    return
  }
  funktionSaving.value = true
  const mitgliedId = aktivPerson.value.mitglied.id
  try {
    if (editingFunktionId.value) {
      await api.put(`/api/mitglieder/${mitgliedId}/funktionen/${editingFunktionId.value}`, {
        funktion: funktionForm.value.funktion,
        abteilung_id: funktionForm.value.abteilung_id || null,
        von: funktionForm.value.von || null,
        bis: funktionForm.value.bis || null,
        expected_version: editingFunktionVersion.value,
      })
    } else {
      await api.post(`/api/mitglieder/${mitgliedId}/funktionen`, {
        funktion: funktionForm.value.funktion,
        abteilung_id: funktionForm.value.abteilung_id || null,
        von: funktionForm.value.von || null,
        bis: funktionForm.value.bis || null,
      })
    }
    funktionFormOpen.value = false
    const { data } = await api.get(`/api/mitglieder/${mitgliedId}/funktionen`)
    funktionen.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    funktionSaving.value = false
  }
}

async function deleteFunktion(f) {
  const mitgliedId = aktivPerson.value.mitglied.id
  try {
    await api.delete(`/api/mitglieder/${mitgliedId}/funktionen/${f.id}`)
    funktionen.value = funktionen.value.filter(x => x.id !== f.id)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

// ── History ────────────────────────────────────────────────
const historyOpen    = ref(false)
const historyLoading = ref(false)
const historyPerson  = ref(null)
const historyEntries = ref([])

const USER_DIFF_FIELDS = [
  { key: 'username',  label: 'Benutzername' },
  { key: 'email',     label: 'E-Mail' },
  { key: 'role',      label: 'Rolle' },
  { key: 'active',    label: 'Status', fmt: v => v ? 'aktiv' : 'inaktiv' },
]
const MITGLIED_DIFF_FIELDS = [
  { key: 'vorname',      label: 'Vorname' },
  { key: 'nachname',     label: 'Nachname' },
  { key: 'email',        label: 'Kontakt-E-Mail' },
  { key: 'telefon',      label: 'Telefon' },
  { key: 'strasse',      label: 'Straße' },
  { key: 'plz',          label: 'PLZ' },
  { key: 'ort',          label: 'Ort' },
  { key: 'land',         label: 'Land' },
  { key: 'status',       label: 'Vereinsstatus' },
  { key: 'iban',         label: 'IBAN' },
  { key: 'kontoinhaber', label: 'Kontoinhaber' },
  { key: 'eintrittsdatum', label: 'Eintrittsdatum' },
  { key: 'austrittsdatum', label: 'Austrittsdatum' },
]

function diffEntries(prev, curr, fields) {
  if (!prev) return []
  return fields
    .filter(f => String(prev[f.key] ?? '') !== String(curr[f.key] ?? ''))
    .map(f => ({
      feld: f.label,
      alt:  f.fmt ? f.fmt(prev[f.key]) : (prev[f.key] ?? '—'),
      neu:  f.fmt ? f.fmt(curr[f.key]) : (curr[f.key] ?? '—'),
    }))
}

async function openHistoryDialog(row) {
  historyPerson.value = row
  historyEntries.value = []
  historyOpen.value = true
  historyLoading.value = true
  try {
    const { data } = await api.get(`/api/personen/${row.user_id}/history`)

    const userEvents = data.user.map((h, i) => ({
      _typ: 'user', _zeit: h.updated_at, _by: h.updated_by,
      _color: h.deleted_at ? 'negative' : h.version === 1 ? 'positive' : 'primary',
      _icon: h.deleted_at ? 'person_off' : h.version === 1 ? 'person_add' : 'manage_accounts',
      _label: h.deleted_at ? 'Account gelöscht' : h.version === 1 ? 'Account angelegt' : 'Account geändert',
      _diffs: diffEntries(data.user[i - 1], h, USER_DIFF_FIELDS),
      _full: h.version === 1 ? { Benutzername: h.username, 'E-Mail': h.email, Rolle: h.role } : null,
    }))

    const mitgliedEvents = data.mitglied.map((h, i) => ({
      _typ: 'mitglied', _zeit: h.updated_at, _by: h.updated_by,
      _color: h.deleted_at ? 'negative' : h.version === 1 ? 'teal' : 'primary',
      _icon: h.deleted_at ? 'person_off' : h.version === 1 ? 'badge' : 'edit',
      _label: h.deleted_at ? 'Mitglied-Datensatz gelöscht' : h.version === 1 ? 'Mitglied angelegt' : 'Vereinsdaten geändert',
      _diffs: diffEntries(data.mitglied[i - 1], h, MITGLIED_DIFF_FIELDS),
      _full: h.version === 1 ? { Vorname: h.vorname, Nachname: h.nachname, Status: h.status } : null,
    }))

    // Abteilungs-Zuordnungen gruppiert nach id
    const abteilungById = {}
    for (const h of (data.abteilungen ?? [])) {
      if (!abteilungById[h.id]) abteilungById[h.id] = []
      abteilungById[h.id].push(h)
    }
    const ABTEILUNG_DIFF_FIELDS = [
      { key: 'status', label: 'Status' },
      { key: 'von',    label: 'Von' },
      { key: 'bis',    label: 'Bis' },
    ]
    const abteilungEvents = []
    for (const versions of Object.values(abteilungById)) {
      versions.forEach((h, i) => {
        abteilungEvents.push({
          _typ: 'abteilung', _zeit: h.updated_at, _by: h.updated_by,
          _color: h.deleted_at ? 'negative' : h.version === 1 ? 'purple' : 'primary',
          _icon: h.deleted_at ? 'group_remove' : h.version === 1 ? 'group_add' : 'edit',
          _label: h.deleted_at
            ? `Abteilung verlassen: ${h.abteilung_name}`
            : h.version === 1
              ? `Abteilung beigetreten: ${h.abteilung_name}`
              : `Abteilung geändert: ${h.abteilung_name}`,
          _diffs: diffEntries(versions[i - 1], h, ABTEILUNG_DIFF_FIELDS),
          _full: h.version === 1 ? { Status: h.status, Von: h.von, Bis: h.bis } : null,
        })
      })
    }

    const all = [...userEvents, ...mitgliedEvents, ...abteilungEvents].sort((a, b) => {
      const ta = a._zeit ?? '', tb = b._zeit ?? ''
      return ta < tb ? -1 : ta > tb ? 1 : 0
    })
    historyEntries.value = all.reverse()
  } catch {
    $q.notify({ type: 'negative', message: 'Historie konnte nicht geladen werden.' })
  } finally {
    historyLoading.value = false
  }
}

onMounted(() => {
  loadPersonen()
  loadFunktionOptionen()
})
</script>
