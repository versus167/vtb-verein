<template>
  <q-page padding :class="{ 'page--dark': $q.dark.isActive }">
    <!-- Kopfzeile -->
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Personen</div>
      <q-btn icon="add" :label="$q.screen.gt.xs ? 'Neue Person' : undefined"
        :round="$q.screen.lt.sm" color="primary" unelevated @click="openCreateDialog" />
    </div>

    <!-- Filter -->
    <div class="row q-gutter-sm q-mb-md items-center wrap">
      <q-btn-toggle v-model="filter" :options="filterOptions" unelevated dense
        toggle-color="primary" color="white" text-color="primary" />
      <q-select v-model="abteilungFilter" :options="alleAbteilungen" 
        option-value="id" option-label="name" emit-value map-options label="Abteilung"
        outlined dense clearable style="min-width: 180px" />
      <q-select v-model="funktionFilter" :options="funktionOptionen" 
        option-value="value" option-label="label" emit-value map-options label="Funktion"
        outlined dense clearable style="min-width: 180px" />
      <q-input v-model="search" placeholder="Suche..." outlined dense clearable
        style="min-width: 200px">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-btn flat dense icon="filter_alt" color="primary" @click="resetAllFilters">
        <q-tooltip>Alle Filter zurücksetzen</q-tooltip>
      </q-btn>
    </div>

    <!-- Mobile/Tablet: Kacheln -->
    <template v-if="$q.screen.lt.md">
      <div v-if="loading" class="row justify-center q-py-xl">
        <q-spinner size="40px" color="primary" />
      </div>
      <div v-else-if="filteredPersonen.length === 0" class="text-center text-grey q-py-xl">
        Keine Personen gefunden.
      </div>
      <q-card v-for="(p, index) in sortedPersonen" :key="p.user_id ?? 'm_' + p.mitglied?.id" elevated class="q-mb-md" :class="index % 2 !== 0 ? 'stripe' : ''"
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
              :color="abteilungColor(ab.abteilung_id)" text-color="white">
              {{ ab.abteilung_kuerzel || ab.abteilung_name }}
            </q-chip>
          </div>
          <div v-if="p.funktionen?.length" class="row items-center q-gutter-xs q-mb-xs">
            <q-chip v-for="f in p.funktionen" :key="f.id" dense size="sm"
              color="indigo" text-color="white">
              {{ funktionLabel(f.funktion) }}<span v-if="f.abteilung_name"
                class="text-indigo-2"> · {{ f.abteilung_name }}</span>
            </q-chip>
          </div>
          <div v-if="p.last_seen" class="text-caption text-grey-5">
            Zuletzt aktiv: {{ formatLastLogin(p.last_seen) }}
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions class="q-px-sm q-py-xs">
          <q-btn v-if="p.user_id" flat dense round icon="edit" color="primary" size="sm"
            @click="openEditUserDialog(p)">
            <q-tooltip>Account bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied && !p.user_id" flat dense round icon="manage_accounts" color="primary" size="sm"
            @click="openNutzerDialog(p)">
            <q-tooltip>Login-Account anlegen</q-tooltip>
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
          <q-btn v-if="p.mitglied" flat dense round icon="contact_phone" color="cyan-8" size="sm"
            @click="openKontakteDialog(p)">
            <q-tooltip>Kontaktdaten</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat dense round icon="groups" color="cyan-8" size="sm"
            @click="openMannschaftenDialog(p)">
            <q-tooltip>Mannschaften</q-tooltip>
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
    <q-table v-else :rows="sortedPersonen" :columns="columns" :row-key="r => r.user_id ?? 'm_' + r.mitglied?.id"
      flat bordered :loading="loading" :rows-per-page-options="[25, 50, 0]"
      @update:sort="onSortChange">

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

      <template #body-cell-rolle="props">
        <q-td :props="props">
          <q-chip v-if="props.row.role" dense :color="rolleColor(props.row.role)" text-color="white" size="sm">
            {{ rolleLabel(props.row.role) }}
          </q-chip>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-last_seen="props">
        <q-td :props="props">
          <span v-if="props.row.last_seen" class="text-caption">
            {{ formatLastLogin(props.row.last_seen) }}
            <q-tooltip>{{ new Date(props.row.last_seen).toLocaleString('de-DE') }}</q-tooltip>
          </span>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-last_edited="props">
        <q-td :props="props">
          <span v-if="props.row.last_edited" class="text-caption">
            {{ formatDate(props.row.last_edited) }}
            <q-tooltip>{{ new Date(props.row.last_edited).toLocaleString('de-DE') }}</q-tooltip>
          </span>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-abteilungen="props">
        <q-td :props="props">
          <q-chip v-for="ab in props.row.abteilungen" :key="ab.id" dense size="sm"
            :color="abteilungColor(ab.abteilung_id)" text-color="white" class="q-mr-xs">
            {{ ab.abteilung_kuerzel || ab.abteilung_name }}
          </q-chip>
        </q-td>
      </template>

      <template #body-cell-funktionen="props">
        <q-td :props="props" style="white-space: normal; max-width: 340px">
          <div v-if="props.row.funktionen?.length" class="row items-center" style="gap: 4px">
            <q-chip v-for="f in props.row.funktionen" :key="f.id" dense size="sm"
              color="indigo" text-color="white" class="q-ma-none">
              {{ funktionLabel(f.funktion) }}<span v-if="f.abteilung_name"
                class="text-indigo-2"> · {{ f.abteilung_name }}</span>
            </q-chip>
          </div>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" style="white-space: nowrap">
          <q-btn v-if="props.row.user_id" flat dense round icon="edit" color="primary" size="sm"
            @click="openEditUserDialog(props.row)">
            <q-tooltip>Account bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-if="props.row.mitglied && !props.row.user_id" flat dense round icon="manage_accounts" color="primary" size="sm"
            @click="openNutzerDialog(props.row)">
            <q-tooltip>Login-Account anlegen</q-tooltip>
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
          <q-btn v-if="props.row.mitglied" flat dense round icon="contact_phone" color="cyan-8" size="sm"
            @click="openKontakteDialog(props.row)">
            <q-tooltip>Kontaktdaten</q-tooltip>
          </q-btn>
          <q-btn v-if="props.row.mitglied" flat dense round icon="groups" color="cyan-8" size="sm"
            @click="openMannschaftenDialog(props.row)">
            <q-tooltip>Mannschaften</q-tooltip>
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
              <div v-if="createForm.email" class="row items-center q-gutter-sm">
                <q-toggle v-if="canAssignAdmin" class="self-center"
                  :model-value="createForm.role === 'admin'"
                  @update:model-value="v => createForm.role = v ? 'admin' : 'mitglied'"
                  label="Administrator" />
                <q-space />
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
              <div class="row items-center q-gutter-sm">
                <q-toggle v-if="canAssignAdmin" class="self-center"
                  :model-value="createForm.role === 'admin'"
                  @update:model-value="v => createForm.role = v ? 'admin' : 'mitglied'"
                  label="Administrator" />
                <q-space />
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
          <q-toggle v-if="canAssignAdmin"
            :model-value="editUserForm.role === 'admin'"
            @update:model-value="v => editUserForm.role = v ? 'admin' : 'mitglied'"
            label="Administrator (uneingeschränkter Zugriff)" />
          <div v-else-if="editUserForm.role === 'admin'" class="text-caption text-grey-7">
            <q-icon name="shield" size="xs" class="q-mr-xs" />Administrator – nur ein Administrator kann dieses Recht ändern
          </div>
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
         Login-Account für bestehendes Mitglied anlegen
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="nutzerOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:420px'">
        <q-card-section class="text-h6">Login-Account anlegen</q-card-section>
        <q-card-section v-if="nutzerPerson" class="text-caption text-grey q-pt-none">
          für {{ nutzerPerson.mitglied?.nachname }}, {{ nutzerPerson.mitglied?.vorname }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="nutzerForm.email" label="E-Mail *" outlined dense type="email"
            hint="Login per Magic-Link an diese Adresse" />
          <q-toggle v-if="canAssignAdmin"
            :model-value="nutzerForm.role === 'admin'"
            @update:model-value="v => nutzerForm.role = v ? 'admin' : 'mitglied'"
            label="Administrator (uneingeschränkter Zugriff)" />
          <q-toggle v-model="nutzerForm.active" label="Aktiv (Magic-Link versenden)" />
          <div v-if="nutzerError" class="text-negative text-caption">{{ nutzerError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Anlegen" color="primary" unelevated :loading="nutzerSaving" @click="onSaveNutzer" />
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
              <q-input v-model="funktionForm.von" label="Von *" outlined dense type="date" class="col" />
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
         Kontakte-Dialog (mehrere E-Mails/Telefonnummern)
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="kontakteOpen" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:500px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Kontaktdaten</div>
          <div v-if="aktivPerson" class="text-caption text-grey q-ml-sm">
            {{ aktivPerson.mitglied?.nachname }}, {{ aktivPerson.mitglied?.vorname }}
          </div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-inner-loading :showing="kontakteLoading" />
          <div v-if="!kontakteLoading && kontakte.length === 0"
            class="text-grey text-center q-py-md">Keine Kontaktdaten erfasst.</div>
          <q-list separator>
            <q-item v-for="k in kontakte" :key="k.id">
              <q-item-section avatar>
                <q-icon :name="kontaktIcon(k.typ)" color="cyan-8" />
              </q-item-section>
              <q-item-section>
                <q-item-label>
                  {{ k.wert }}
                  <q-chip v-if="k.ist_primaer" dense size="xs" color="cyan-8" text-color="white" class="q-ml-xs">primär</q-chip>
                </q-item-label>
                <q-item-label caption>
                  {{ typLabel(k.typ) }}<span v-if="k.label"> · {{ k.label }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row q-gutter-xs">
                  <q-btn v-if="!k.ist_primaer" flat dense round icon="star" color="amber-8" size="sm"
                    @click="setPrimaer(k)"><q-tooltip>Als primär setzen</q-tooltip></q-btn>
                  <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openEditKontakt(k)" />
                  <q-btn flat dense round icon="delete" color="negative" size="sm" @click="deleteKontakt(k)" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <q-btn flat icon="add" label="Kontakt hinzufügen" color="primary" class="q-mt-sm"
            @click="openAddKontakt" />
          <!-- Formular -->
          <div v-if="kontaktFormOpen" class="q-mt-md q-gutter-sm">
            <q-select v-model="kontaktForm.typ" :options="kontaktTypOptionen"
              option-value="value" option-label="label" emit-value map-options
              label="Typ *" outlined dense />
            <q-input v-model="kontaktForm.wert" label="Wert *" outlined dense
              :type="kontaktForm.typ === 'email' ? 'email' : 'text'" />
            <q-input v-model="kontaktForm.label" label="Bezeichnung (optional, z.B. privat)" outlined dense />
            <q-toggle v-model="kontaktForm.ist_primaer" label="Primärer Kontakt dieses Typs" color="cyan-8" />
            <div class="row q-gutter-sm">
              <q-btn flat label="Abbrechen" @click="kontaktFormOpen = false" />
              <q-btn unelevated :label="editingKontaktId ? 'Speichern' : 'Hinzufügen'"
                color="primary" :loading="kontaktSaving" @click="onSaveKontakt" />
            </div>
          </div>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ════════════════════════════════════════════════
         Mannschaften-Dialog (Teams eines Mitglieds)
         ════════════════════════════════════════════════ -->
    <q-dialog v-model="mannschaftenOpen" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:500px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Mannschaften</div>
          <div v-if="aktivPerson" class="text-caption text-grey q-ml-sm">
            {{ aktivPerson.mitglied?.nachname }}, {{ aktivPerson.mitglied?.vorname }}
          </div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-inner-loading :showing="mannschaftenLoading" />
          <div v-if="!mannschaftenLoading && mitgliedTeams.length === 0"
            class="text-grey text-center q-py-md">In keiner Mannschaft.</div>
          <q-list separator>
            <q-item v-for="t in mitgliedTeams" :key="t.id">
              <q-item-section avatar><q-icon name="groups" color="cyan-8" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ t.mannschaft_name }}</q-item-label>
                <q-item-label caption>
                  <q-chip dense size="xs" :color="teamRolleColor(t.rolle)" text-color="white">{{ teamRolleLabel(t.rolle) }}</q-chip>
                  <span v-if="t.abteilung_name" class="q-mx-xs">{{ t.abteilung_name }}</span>
                  <span>{{ t.von }} – {{ t.bis ?? 'heute' }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row q-gutter-xs">
                  <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openEditTeam(t)" />
                  <q-btn flat dense round icon="delete" color="negative" size="sm" @click="removeTeam(t)" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <q-btn flat icon="add" label="Zu Mannschaft hinzufügen" color="primary" class="q-mt-sm"
            @click="openAddTeam" />
          <!-- Formular -->
          <div v-if="teamFormOpen" class="q-mt-md q-gutter-sm">
            <q-select v-if="!editingTeamId" v-model="teamForm.mannschaft_id" :options="alleMannschaften"
              option-value="id" :option-label="t => `${t.name} (${t.abteilung_name})`" emit-value map-options
              use-input input-debounce="0" @filter="filterTeams" label="Mannschaft *" outlined dense />
            <q-select v-model="teamForm.rolle" :options="teamRolleOptionen" option-value="value" option-label="label"
              emit-value map-options label="Rolle *" outlined dense />
            <div class="row q-gutter-sm">
              <q-input v-model="teamForm.von" label="Von *" outlined dense type="date" class="col" />
              <q-input v-model="teamForm.bis" label="Bis" outlined dense type="date" class="col" />
            </div>
            <div class="row q-gutter-sm">
              <q-btn flat label="Abbrechen" @click="teamFormOpen = false" />
              <q-btn unelevated :label="editingTeamId ? 'Speichern' : 'Hinzufügen'"
                color="primary" :loading="teamSaving" @click="onSaveTeam" />
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
                    <template v-for="(v, k) in h._full" :key="k">
                      <div v-if="v">
                        <span class="text-grey">{{ k }}: </span>{{ v }}
                      </div>
                    </template>
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
import { ref, computed, onMounted, onActivated, onDeactivated, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

// Name wird für <keep-alive :include="['PersonenPage']"> im MainLayout benötigt,
// damit der Listen-Zustand beim Zurückkehren erhalten bleibt.
defineOptions({ name: 'PersonenPage' })

const $q = useQuasar()
const router = useRouter()
const auth = useAuthStore()

// Scrollposition über Navigation hinweg merken (keep-alive cached den Rest).
// requestAnimationFrame, damit der Restore nach dem router-scrollBehavior
// (das nach oben scrollt) läuft.
let savedScrollY = 0
onDeactivated(() => { savedScrollY = window.scrollY })
onActivated(() => {
  nextTick(() => requestAnimationFrame(() => window.scrollTo(0, savedScrollY)))
})

// ── Daten ──────────────────────────────────────────────────
const personen = ref([])
const loading = ref(false)
const filter = ref('alle')
const search = ref('')
const abteilungFilter = ref(null)
const funktionFilter = ref(null)
const alleAbteilungen = ref([])

// ── Sortierung ─────────────────────────────────────────────
const sortColumn = ref(null)
const sortDirection = ref('asc')

const filterOptions = [
  { label: 'Alle', value: 'alle' },
  { label: 'Nur Mitglieder', value: 'mitglieder' },
  { label: 'Nur Benutzer', value: 'benutzer' },
]

// Spalten sind tab-abhängig: Im Tab "Nur Benutzer" interessieren Rolle und
// letzte Aktivität statt Geburtstag/Eintritt (Ticket #14).
const columns = computed(() => {
  const istBenutzer = filter.value === 'benutzer'
  const cols = [
    { name: 'name',  label: 'Name',   field: 'username', align: 'left', sortable: true },
    { name: 'email', label: 'E-Mail', field: 'email',    align: 'left', sortable: true },
  ]
  if (istBenutzer) {
    cols.push({ name: 'rolle', label: 'Rolle', field: 'role', align: 'left', sortable: true })
  } else {
    cols.push(
      { name: 'geburtsdatum', label: 'Geburtstag', field: r => r.mitglied?.geburtsdatum, align: 'left', sortable: true },
      { name: 'eintritt',     label: 'Eintritt',   field: r => r.mitglied?.eintrittsdatum, align: 'left', sortable: true },
    )
  }
  cols.push({ name: 'status', label: 'Status', field: 'active', align: 'center', sortable: true })
  if (istBenutzer) {
    cols.push({ name: 'last_seen', label: 'Zuletzt aktiv', field: 'last_seen', align: 'left', sortable: true })
  }
  cols.push(
    { name: 'last_edited', label: 'Zuletzt bearbeitet', field: 'last_edited', align: 'left', sortable: true },
    { name: 'abteilungen', label: 'Abteilungen',  field: 'abteilungen', align: 'left' },
    { name: 'funktionen',  label: 'Funktionen',   field: 'funktionen',  align: 'left' },
    { name: 'actions',     label: '',             field: 'actions',  align: 'right', style: 'width: 200px' },
  )
  return cols
})

const filteredPersonen = computed(() => {
  let list = personen.value
  
  // Basis-Filter
  if (filter.value === 'mitglieder') list = list.filter(p => p.mitglied)
  if (filter.value === 'benutzer')   list = list.filter(p => p.user_id)
  
  // Abteilung-Filter (nur bei "Alle" oder "Mitglieder", da reine Benutzer keine Abteilungen haben)
  if (abteilungFilter.value != null) {
    const abteilungsIds = [abteilungFilter.value]
    list = list.filter(p => 
      (p.abteilungen || []).some(ab => abteilungsIds.includes(ab.abteilung_id))
    )
  }
  
  // Funktion-Filter (nur bei "Alle" oder "Mitglieder", da reine Benutzer keine Funktionen haben)
  if (funktionFilter.value != null) {
    const funktionKeys = [funktionFilter.value]
    list = list.filter(p => 
      (p.funktionen || []).some(f => funktionKeys.includes(f.funktion))
    )
  }
  
  // Textsuche
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter(p =>
      (p.username ?? '').toLowerCase().includes(q) ||
      (p.email ?? '').toLowerCase().includes(q) ||
      (p.mitglied?.vorname ?? '').toLowerCase().includes(q) ||
      (p.mitglied?.nachname ?? '').toLowerCase().includes(q) ||
      String(p.mitglied?.mitgliedsnummer ?? '').includes(q)
    )
  }
  return list
})

// Sortierte Liste
const sortedPersonen = computed(() => {
  const list = filteredPersonen.value
  if (!sortColumn.value) return list
  
  return [...list].sort((a, b) => {
    let aVal, bVal
    
    // Spezialbehandlung für verschachtelte Felder
    switch (sortColumn.value) {
      case 'name':
        aVal = (a.mitglied?.nachname || a.username || '').toLowerCase()
        bVal = (b.mitglied?.nachname || b.username || '').toLowerCase()
        break
      case 'geburtsdatum':
        aVal = a.mitglied?.geburtsdatum || ''
        bVal = b.mitglied?.geburtsdatum || ''
        break
      case 'eintritt':
        aVal = a.mitglied?.eintrittsdatum || ''
        bVal = b.mitglied?.eintrittsdatum || ''
        break
      case 'last_edited':
        aVal = a.last_edited || ''
        bVal = b.last_edited || ''
        break
      case 'rolle':
        aVal = a.role || ''
        bVal = b.role || ''
        break
      case 'last_seen':
        aVal = a.last_seen || ''
        bVal = b.last_seen || ''
        break
      default:
        aVal = a[sortColumn.value] ?? ''
        bVal = b[sortColumn.value] ?? ''
    }
    
    if (aVal < bVal) return sortDirection.value === 'asc' ? -1 : 1
    if (aVal > bVal) return sortDirection.value === 'asc' ? 1 : -1
    return 0
  })
})

// Filter zurücksetzen (nur Abteilungs- und Funktionsfilter, nicht Basis-Filter)
function resetAllFilters() {
  abteilungFilter.value = null
  funktionFilter.value = null
  search.value = ''
}

// Sortierung ändern
function onSortChange(details) {
  sortColumn.value = details.sortBy
  sortDirection.value = details.descending ? 'desc' : 'asc'
}

// ── Hilfsfunktionen ────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('de-DE')
}

// ── Optionen ───────────────────────────────────────────────
// Seit Stufe D (siehe BERECHTIGUNGEN.md) gibt es nur noch 'admin'/'mitglied'.
// Statt einer Rollen-Auswahl ein Administrator-Schalter (nur für Admins sichtbar).
const canAssignAdmin = computed(() => auth.user?.role === 'admin')
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
  return { admin: 'Admin', mitglied: 'Mitglied' }[role] ?? role
}
function rolleColor(role) {
  return { admin: 'negative', mitglied: 'teal' }[role] ?? 'grey'
}
function abteilungStatusColor(s) {
  return { aktiv: 'positive', passiv: 'grey', trainer: 'blue', vorstand: 'purple', ehrenmitglied: 'amber' }[s] ?? 'grey'
}

// Farbpalette für Abteilungs-IDs (deterministisch pro Abteilung)
const abteilungColors = ['primary', 'secondary', 'accent', 'positive', 'negative', 'info', 'warning', 'amber', 'purple', 'blue-8', 'cyan-8', 'teal-8', 'green-8', 'orange-8', 'red-8', 'pink-8']
function abteilungColor(abteilungId) {
  if (!abteilungId) return 'grey'
  return abteilungColors[abteilungId % abteilungColors.length]
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

// ── Login-Account für bestehendes Mitglied anlegen ─────────
const nutzerOpen   = ref(false)
const nutzerSaving = ref(false)
const nutzerError  = ref('')
const nutzerPerson = ref(null)
const nutzerForm   = ref({ email: '', role: 'mitglied', active: true })

function openNutzerDialog(row) {
  nutzerPerson.value = row
  nutzerError.value = ''
  nutzerForm.value = {
    email: row.mitglied?.email ?? '',   // Primär-E-Mail vorbelegen, falls vorhanden
    role: 'mitglied',
    active: true,
  }
  nutzerOpen.value = true
}

async function onSaveNutzer() {
  if (!nutzerForm.value.email.trim()) {
    nutzerError.value = 'E-Mail ist erforderlich.'
    return
  }
  nutzerSaving.value = true
  nutzerError.value = ''
  try {
    await api.post(`/api/personen/mitglied/${nutzerPerson.value.mitglied.id}/nutzer`, nutzerForm.value)
    $q.notify({ type: 'positive', message: 'Login-Account angelegt' })
    nutzerOpen.value = false
    await loadPersonen()
  } catch (e) {
    nutzerError.value = e.response?.data?.detail || 'Fehler beim Anlegen'
  } finally {
    nutzerSaving.value = false
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
    if (alleAbteilungen.value.length === 0) {
      alleAbteilungen.value = ab
    }
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

async function loadAlleAbteilungen() {
  try {
    const { data } = await api.get('/api/abteilungen/')
    alleAbteilungen.value = data
  } catch {
    alleAbteilungen.value = []
  }
}

function funktionLabel(f) {
  if (!f) return ''
  const found = funktionOptionen.value.find(o => o.value === f)
  return found?.label ?? f
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
    if (alleAbteilungen.value.length === 0) {
      alleAbteilungen.value = ab
    }
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
  if (!funktionForm.value.von) {
    $q.notify({ type: 'negative', message: 'Bitte ein „Von"-Datum angeben (Zeitraum ist Pflicht).' })
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
    await loadPersonen()   // Liste sofort aktualisieren
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
    await loadPersonen()   // Liste sofort aktualisieren
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

// ── Kontaktdaten (mehrere E-Mails/Telefonnummern) ──────────
const kontakteOpen     = ref(false)
const kontakteLoading  = ref(false)
const kontakte         = ref([])
const kontaktFormOpen  = ref(false)
const kontaktSaving    = ref(false)
const editingKontaktId      = ref(null)
const editingKontaktVersion = ref(null)
const kontaktForm = ref({ typ: 'email', wert: '', label: '', ist_primaer: false })

const kontaktTypOptionen = [
  { label: 'E-Mail', value: 'email' },
  { label: 'Telefon', value: 'telefon' },
  { label: 'Mobil', value: 'mobil' },
  { label: 'Fax', value: 'fax' },
]

function typLabel(t) {
  return kontaktTypOptionen.find(o => o.value === t)?.label ?? t
}

function kontaktIcon(t) {
  return { email: 'mail', telefon: 'call', mobil: 'smartphone', fax: 'fax' }[t] ?? 'contact_phone'
}

async function openKontakteDialog(row) {
  aktivPerson.value = row
  kontaktFormOpen.value = false
  kontakteOpen.value = true
  kontakteLoading.value = true
  try {
    const { data } = await api.get(`/api/mitglieder/${row.mitglied.id}/kontakte`)
    kontakte.value = data
  } finally {
    kontakteLoading.value = false
  }
}

function openAddKontakt() {
  editingKontaktId.value = null
  kontaktForm.value = { typ: 'email', wert: '', label: '', ist_primaer: false }
  kontaktFormOpen.value = true
}

function openEditKontakt(k) {
  editingKontaktId.value = k.id
  editingKontaktVersion.value = k.version
  kontaktForm.value = { typ: k.typ, wert: k.wert, label: k.label ?? '', ist_primaer: k.ist_primaer }
  kontaktFormOpen.value = true
}

async function reloadKontakte() {
  const { data } = await api.get(`/api/mitglieder/${aktivPerson.value.mitglied.id}/kontakte`)
  kontakte.value = data
}

async function onSaveKontakt() {
  if (!kontaktForm.value.typ || !kontaktForm.value.wert.trim()) {
    $q.notify({ type: 'negative', message: 'Typ und Wert sind erforderlich.' })
    return
  }
  kontaktSaving.value = true
  const mitgliedId = aktivPerson.value.mitglied.id
  try {
    if (editingKontaktId.value) {
      await api.put(`/api/mitglieder/${mitgliedId}/kontakte/${editingKontaktId.value}`, {
        typ: kontaktForm.value.typ,
        wert: kontaktForm.value.wert.trim(),
        label: kontaktForm.value.label || null,
        ist_primaer: kontaktForm.value.ist_primaer,
        expected_version: editingKontaktVersion.value,
      })
    } else {
      await api.post(`/api/mitglieder/${mitgliedId}/kontakte`, {
        typ: kontaktForm.value.typ,
        wert: kontaktForm.value.wert.trim(),
        label: kontaktForm.value.label || null,
        ist_primaer: kontaktForm.value.ist_primaer,
      })
    }
    kontaktFormOpen.value = false
    await reloadKontakte()
    await loadPersonen()   // primäre E-Mail/Telefon in der Liste aktualisieren
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    kontaktSaving.value = false
  }
}

async function setPrimaer(k) {
  try {
    await api.put(`/api/mitglieder/${aktivPerson.value.mitglied.id}/kontakte/${k.id}/primaer`)
    await reloadKontakte()
    await loadPersonen()   // primäre E-Mail/Telefon in der Liste aktualisieren
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

async function deleteKontakt(k) {
  const mitgliedId = aktivPerson.value.mitglied.id
  try {
    await api.delete(`/api/mitglieder/${mitgliedId}/kontakte/${k.id}`)
    kontakte.value = kontakte.value.filter(x => x.id !== k.id)
    await loadPersonen()   // primäre E-Mail/Telefon in der Liste aktualisieren
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

// ── Mannschaften (Teams eines Mitglieds) ───────────────────
const mannschaftenOpen    = ref(false)
const mannschaftenLoading = ref(false)
const mitgliedTeams       = ref([])
const alleMannschaften    = ref([])
const alleMannschaftenAll = ref([])
const teamFormOpen        = ref(false)
const teamSaving          = ref(false)
const editingTeamId       = ref(null)
const editingTeamMannschaft = ref(null)
const editingTeamVersion  = ref(null)
const teamForm = ref({ mannschaft_id: null, rolle: 'spieler', von: '', bis: '' })

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

async function openMannschaftenDialog(row) {
  aktivPerson.value = row
  teamFormOpen.value = false
  mannschaftenOpen.value = true
  mannschaftenLoading.value = true
  try {
    const [{ data: teams }, { data: alle }] = await Promise.all([
      api.get(`/api/mitglieder/${row.mitglied.id}/mannschaften`),
      alleMannschaftenAll.value.length ? Promise.resolve({ data: null }) : api.get('/api/mannschaften'),
    ])
    mitgliedTeams.value = teams
    if (alle) alleMannschaftenAll.value = alle
    alleMannschaften.value = alleMannschaftenAll.value
  } finally {
    mannschaftenLoading.value = false
  }
}
function openAddTeam() {
  editingTeamId.value = null
  teamForm.value = { mannschaft_id: null, rolle: 'spieler', von: '', bis: '' }
  teamFormOpen.value = true
}
function openEditTeam(t) {
  editingTeamId.value = t.id
  editingTeamMannschaft.value = t.mannschaft_id
  editingTeamVersion.value = t.version
  teamForm.value = { mannschaft_id: t.mannschaft_id, rolle: t.rolle, von: t.von ?? '', bis: t.bis ?? '' }
  teamFormOpen.value = true
}
async function reloadTeams() {
  const { data } = await api.get(`/api/mitglieder/${aktivPerson.value.mitglied.id}/mannschaften`)
  mitgliedTeams.value = data
}
async function onSaveTeam() {
  if (!editingTeamId.value && !teamForm.value.mannschaft_id) {
    $q.notify({ type: 'negative', message: 'Bitte eine Mannschaft wählen.' }); return
  }
  if (!teamForm.value.von) {
    $q.notify({ type: 'negative', message: 'Bitte ein „Von"-Datum angeben.' }); return
  }
  teamSaving.value = true
  const mid = aktivPerson.value.mitglied.id
  try {
    if (editingTeamId.value) {
      await api.put(`/api/mannschaften/${editingTeamMannschaft.value}/mitglieder/${editingTeamId.value}`, {
        rolle: teamForm.value.rolle, von: teamForm.value.von || null,
        bis: teamForm.value.bis || null, expected_version: editingTeamVersion.value,
      })
    } else {
      await api.post(`/api/mannschaften/${teamForm.value.mannschaft_id}/mitglieder`, {
        mitglied_id: mid, rolle: teamForm.value.rolle,
        von: teamForm.value.von || null, bis: teamForm.value.bis || null,
      })
    }
    teamFormOpen.value = false
    await reloadTeams()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    teamSaving.value = false
  }
}
async function removeTeam(t) {
  try {
    await api.delete(`/api/mannschaften/${t.mannschaft_id}/mitglieder/${t.id}`)
    mitgliedTeams.value = mitgliedTeams.value.filter(x => x.id !== t.id)
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
  loadAlleAbteilungen()
})
</script>

<style scoped>
/* Zebra-Streifen – hell. Im Darkmode (page--dark) dunkler Überzug statt
   Hellgrau, damit weiße Schrift lesbar bleibt. */
:deep(.q-table tbody tr:nth-child(even) td) {
  background-color: #f5f5f5;
}
.page--dark :deep(.q-table tbody tr:nth-child(even) td) {
  background-color: rgba(255, 255, 255, 0.07);
}

.stripe {
  background-color: #f5f5f5;
}
.page--dark .stripe {
  background-color: #2d2d2d;
}
</style>
