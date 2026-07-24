<template>
  <q-page padding :class="{ 'page--dark': $q.dark.isActive }">
    <!-- Kopfzeile -->
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-h5 col">Personen</div>
      <q-btn v-if="auth.hasPermission('personen.delete')" icon="delete_sweep"
        :label="$q.screen.gt.xs ? 'Papierkorb' : undefined" :round="$q.screen.lt.sm"
        flat color="secondary" @click="trashOpen = true">
        <q-tooltip>Gelöschte Personen</q-tooltip>
      </q-btn>
      <q-btn icon="add" :label="$q.screen.gt.xs ? 'Neue Person' : undefined"
        :round="$q.screen.lt.sm" color="primary" unelevated @click="openCreateDialog" />
    </div>

    <!-- Filter -->
    <div class="row q-gutter-sm q-mb-md items-center wrap">
      <q-btn-toggle v-model="filter" :options="filterOptions" unelevated rounded dense no-caps
        toggle-color="primary" class="vtb-segment" />
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
      <q-checkbox v-model="zeigeAusgetretene" label="Ausgetretene anzeigen" dense />
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
      <q-card v-for="(p, index) in sortierteKarten" :key="p.user_id ?? 'm_' + p.mitglied?.id" elevated class="q-mb-md" :class="index % 2 !== 0 ? 'stripe' : ''"
        style="border-radius:14px;overflow:hidden">
        <q-card-section class="q-py-sm q-px-md">
          <div class="row items-center no-wrap q-mb-xs">
            <div class="col">
              <div v-if="p.mitglied" class="text-subtitle2 text-weight-bold">
                {{ p.mitglied.nachname }}, {{ p.mitglied.vorname }}
                <q-chip v-if="p.lizenz_aktuell_gueltig" dense size="sm" color="green-2"
                  text-color="green-9" icon="workspace_premium" class="q-ml-xs q-my-none">Lizenz
                  <q-tooltip>Gültige Trainerlizenz</q-tooltip>
                </q-chip>
              </div>
              <div v-else class="text-subtitle2 text-weight-bold text-grey-7">{{ p.username }}</div>
              <div v-if="p.username" class="text-caption text-grey">{{ p.username }}</div>
              <div v-else class="text-caption text-grey-5">Kein Login</div>
            </div>
            <div class="row items-center q-gutter-xs">
              <q-chip v-if="p.role" dense :color="rolleColor(p.role)" text-color="white" size="sm">
                {{ rolleLabel(p.role) }}
              </q-chip>
              <q-chip v-if="p.mitglied" dense size="sm"
                :color="mitgliedStatusColor(p.mitglied)" :text-color="mitgliedStatusTextColor(p.mitglied)">
                {{ mitgliedStatusLabel(p.mitglied) }}
                <q-tooltip>{{ p.mitglied.art === 'gastspieler' ? 'Gastspieler – kein Vereinsmitglied' : 'Vereinsstatus' }}</q-tooltip>
              </q-chip>
              <q-icon v-if="p.user_id && p.active" name="check_circle" color="positive" size="sm">
                <q-tooltip>Login aktiv</q-tooltip>
              </q-icon>
              <q-icon v-else-if="p.user_id" name="cancel" color="negative" size="sm">
                <q-tooltip>Login inaktiv</q-tooltip>
              </q-icon>
            </div>
          </div>
          <div v-if="p.email" class="text-caption text-grey-7 q-mb-xs">{{ p.email }}</div>
          <div v-if="lizenzInfo(p.mitglied)" class="text-caption row items-center q-gutter-xs q-mb-xs">
            <span class="text-grey-7">Lizenz bis {{ formatDate(p.mitglied.trainerlizenz_gueltig_bis) }}</span>
            <q-chip dense size="sm" :color="lizenzInfo(p.mitglied).color" text-color="white" class="q-my-none">
              {{ lizenzInfo(p.mitglied).label }}
            </q-chip>
          </div>
          <div v-if="p.abteilungen?.length" class="row q-gutter-xs q-mb-xs">
            <q-chip v-for="ab in p.abteilungen" :key="ab.id" dense size="sm"
              :color="abteilungColor(ab.abteilung_id)" text-color="white">
              {{ ab.abteilung_kuerzel || ab.abteilung_name }}<template v-if="istZukuenftig(ab.von)"><q-icon
                name="schedule" size="12px" class="q-ml-xs" /> ab {{ formatDate(ab.von) }}</template>
            </q-chip>
          </div>
          <div v-if="p.funktionen?.length" class="row items-center q-gutter-xs q-mb-xs">
            <q-chip v-for="f in p.funktionen" :key="f.id" dense size="sm"
              color="indigo" text-color="white">
              {{ funktionLabel(f.funktion) }}<span v-if="f.abteilung_name"
                class="text-indigo-2"> · {{ f.abteilung_name }}</span><span
                v-if="istZukuenftig(f.von)" class="text-indigo-2"><q-icon name="schedule"
                size="12px" class="q-ml-xs" /> ab {{ formatDate(f.von) }}</span>
            </q-chip>
          </div>
          <div v-if="p.last_seen" class="text-caption text-grey-5">
            Zuletzt aktiv: {{ formatLastLogin(p.last_seen) }}
          </div>
        </q-card-section>
        <q-separator />
        <!-- Aktions-Icons in Standardgröße (statt dense/sm): am Handy sicher treffbar; wrap erlaubt eine 2. Zeile. -->
        <q-card-actions class="q-px-sm q-py-xs wrap">
          <q-btn v-if="canManageUsers && p.user_id" flat round icon="edit" color="primary"
            @click="openEditUserDialog(p)">
            <q-tooltip>Account bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-if="canManageUsers && p.mitglied && !p.user_id" flat round icon="manage_accounts" color="primary"
            @click="openNutzerDialog(p)">
            <q-tooltip>Login-Account anlegen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat round icon="person" color="teal"
            @click="openEditMitgliedDialog(p)">
            <q-tooltip>Vereinsdaten bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-else-if="p.user_id" flat round icon="person_add" color="teal"
            @click="openAddMitgliedDialog(p)">
            <q-tooltip>Als Vereinsmitglied erfassen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat round icon="group" color="purple"
            @click="openAbteilungenDialog(p)">
            <q-tooltip>Abteilungen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat round icon="badge" color="indigo"
            @click="openFunktionenDialog(p)">
            <q-tooltip>Funktionen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat round icon="contact_phone" color="cyan-8"
            @click="openKontakteDialog(p)">
            <q-tooltip>Kontaktdaten</q-tooltip>
          </q-btn>
          <q-btn v-if="p.mitglied" flat round icon="groups" color="cyan-8"
            @click="openMannschaftenDialog(p)">
            <q-tooltip>Mannschaften</q-tooltip>
          </q-btn>
          <q-btn v-if="p.user_id" flat round icon="security" color="grey"
            @click="$router.push({ name: 'user-permissions', params: { id: p.user_id } })">
            <q-tooltip>Berechtigungen</q-tooltip>
          </q-btn>
          <q-btn v-if="p.user_id || p.mitglied" flat round icon="history" color="grey"
            @click="openHistoryDialog(p)">
            <q-tooltip>Änderungshistorie</q-tooltip>
          </q-btn>
          <q-space />
          <q-btn flat round icon="delete" color="negative"
            :disable="p.user_id === auth.user?.id"
            @click="confirmDelete(p)">
            <q-tooltip>Löschen</q-tooltip>
          </q-btn>
        </q-card-actions>
      </q-card>
    </template>

    <!-- Desktop: Tabelle -->
    <q-table v-else :rows="filteredPersonen" :columns="columns" :row-key="r => r.user_id ?? 'm_' + r.mitglied?.id"
      flat bordered :loading="loading" :rows-per-page-options="[25, 50, 0]"
      v-model:pagination="pagination">

      <template #body-cell-name="props">
        <q-td :props="props">
          <div v-if="props.row.mitglied" class="text-weight-medium">
            {{ props.row.mitglied.nachname }}, {{ props.row.mitglied.vorname }}
            <q-chip v-if="props.row.lizenz_aktuell_gueltig" dense size="sm" color="green-2"
              text-color="green-9" icon="workspace_premium" class="q-ml-xs q-my-none">Lizenz
              <q-tooltip>Gültige Trainerlizenz</q-tooltip>
            </q-chip>
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

      <template #body-cell-eintritt="props">
        <q-td :props="props">
          <q-badge v-if="props.row.mitglied?.austrittsdatum" color="negative" text-color="white">
            {{ props.row.mitglied.austrittsdatum }}
            <q-tooltip>Ausgetreten</q-tooltip>
          </q-badge>
          <span v-else-if="props.row.mitglied?.eintrittsdatum">{{ props.row.mitglied.eintrittsdatum }}</span>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-lizenz_bis="props">
        <q-td :props="props">
          <template v-if="lizenzInfo(props.row.mitglied)">
            <span class="q-mr-sm">{{ formatDate(props.row.mitglied.trainerlizenz_gueltig_bis) }}</span>
            <q-chip dense size="sm" :color="lizenzInfo(props.row.mitglied).color" text-color="white"
              class="q-my-none">
              {{ lizenzInfo(props.row.mitglied).label }}
            </q-chip>
          </template>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-status="props">
        <q-td :props="props" class="text-center">
          <div class="row items-center justify-center no-wrap" style="gap: 4px">
            <!-- Login-Account-Status: nur bei Benutzer-Zeilen (sonst kein Login) -->
            <q-icon v-if="props.row.user_id" :name="props.row.active ? 'check_circle' : 'cancel'"
              :color="props.row.active ? 'positive' : 'negative'" size="sm">
              <q-tooltip>Login {{ props.row.active ? 'aktiv' : 'inaktiv' }}</q-tooltip>
            </q-icon>
            <!-- Vereinsstatus: nur bei Mitglied-Zeilen (Gastspieler mit eigenem Chip) -->
            <q-chip v-if="props.row.mitglied" dense size="sm" class="q-ma-none"
              :color="mitgliedStatusColor(props.row.mitglied)" :text-color="mitgliedStatusTextColor(props.row.mitglied)">
              {{ mitgliedStatusLabel(props.row.mitglied) }}
              <q-tooltip>{{ props.row.mitglied.art === 'gastspieler' ? 'Gastspieler – kein Vereinsmitglied' : 'Vereinsstatus' }}</q-tooltip>
            </q-chip>
            <span v-if="!props.row.user_id && !props.row.mitglied" class="text-grey">—</span>
          </div>
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
            {{ ab.abteilung_kuerzel || ab.abteilung_name }}<template v-if="istZukuenftig(ab.von)"><q-icon
              name="schedule" size="12px" class="q-ml-xs" /> ab {{ formatDate(ab.von) }}</template>
          </q-chip>
        </q-td>
      </template>

      <template #body-cell-funktionen="props">
        <q-td :props="props" style="white-space: normal; max-width: 340px">
          <div v-if="props.row.funktionen?.length" class="row items-center" style="gap: 4px">
            <q-chip v-for="f in props.row.funktionen" :key="f.id" dense size="sm"
              color="indigo" text-color="white" class="q-ma-none">
              {{ funktionLabel(f.funktion) }}<span v-if="f.abteilung_name"
                class="text-indigo-2"> · {{ f.abteilung_name }}</span><span
                v-if="istZukuenftig(f.von)" class="text-indigo-2"><q-icon name="schedule"
                size="12px" class="q-ml-xs" /> ab {{ formatDate(f.von) }}</span>
            </q-chip>
          </div>
          <span v-else class="text-grey">—</span>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" style="white-space: nowrap">
          <q-btn v-if="canManageUsers && props.row.user_id" flat dense round icon="edit" color="primary" size="sm"
            @click="openEditUserDialog(props.row)">
            <q-tooltip>Account bearbeiten</q-tooltip>
          </q-btn>
          <q-btn v-if="canManageUsers && props.row.mitglied && !props.row.user_id" flat dense round icon="manage_accounts" color="primary" size="sm"
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
          <q-btn v-if="props.row.user_id || props.row.mitglied" flat dense round icon="history" color="grey" size="sm"
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
          <q-tab v-if="canManageUsers" name="user" label="Benutzer/Admin" icon="manage_accounts" />
        </q-tabs>
        <q-separator />
        <q-card-section class="q-gutter-sm" style="max-height:70vh;overflow-y:auto">
          <!-- Tab: Vereinsmitglied -->
          <q-tab-panels v-model="createTab" animated>
            <q-tab-panel name="mitglied" class="q-gutter-sm q-pa-none">
              <q-btn-toggle v-model="createForm.art" :options="artOptions"
                unelevated rounded dense no-caps toggle-color="primary" />
              <div v-if="createForm.art === 'gastspieler'" class="text-caption text-grey-6">
                <q-icon name="info" size="xs" /> Gastspieler (Gastspielgenehmigung) sind keine
                Vereinsmitglieder: keine Mitgliedsnummer, keine Beiträge, zählen nicht in der
                Statistik – können aber Abteilungen/Mannschaften zugeordnet werden.
              </div>
              <div class="row q-gutter-sm">
                <q-input v-model="createForm.vorname" label="Vorname *" outlined dense class="col" />
                <q-input v-model="createForm.nachname" label="Nachname *" outlined dense class="col" />
              </div>
              <div class="row q-gutter-sm">
                <!-- Auch Gastspieler haben einen Eintritt: Beginn der Gastspielgenehmigung (Pflicht) -->
                <q-input v-model="createForm.eintrittsdatum" label="Eintrittsdatum *"
                  outlined dense type="date" class="col" />
                <q-input v-model="createForm.geburtsdatum"
                  :label="createForm.art === 'gastspieler' ? 'Geburtsdatum' : 'Geburtsdatum *'"
                  outlined dense type="date" class="col" />
                <q-select v-model="createForm.geschlecht" :options="geschlechtOptions"
                  label="Geschlecht" outlined dense emit-value map-options clearable class="col" />
              </div>
              <q-select v-if="createForm.art !== 'gastspieler'" v-model="createForm.mitglied_status"
                :options="mitgliedStatusOptions" label="Vereinsstatus" outlined dense emit-value map-options />
              <div class="text-caption text-grey-6">
                <q-icon name="info" size="xs" /> Es wird nur ein Mitglied-Datensatz angelegt – kein Benutzer/Login.
                Kontaktdaten (E-Mail, Telefon) später über den Tab „Kontakte".
              </div>
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
              <q-expansion-item v-if="createForm.art !== 'gastspieler'" label="Zahlung / SEPA" dense>
                <div class="q-gutter-sm q-pt-sm">
                  <q-select v-model="createForm.zahlungsart" :options="zahlungsartOptionen"
                    emit-value map-options label="Zahlungsart" outlined dense />
                  <q-input v-model="createForm.iban" label="IBAN" outlined dense :rules="[ibanRule]" />
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
        <!-- Passwort direkt setzen: Umweg, wenn Magic-Link/E-Mail nicht klappt -->
        <q-card-section class="q-gutter-sm">
          <div class="text-subtitle2">Passwort setzen</div>
          <div class="text-caption text-grey-7">
            Umweg, wenn Magic-Link/E-Mail nicht funktioniert – setzt direkt ein Login-Passwort.
          </div>
          <q-input v-model="pwForm.pw1" label="Neues Passwort" outlined dense
            :type="pwShow ? 'text' : 'password'" autocomplete="new-password" hint="mindestens 6 Zeichen">
            <template #append>
              <q-icon :name="pwShow ? 'visibility' : 'visibility_off'" class="cursor-pointer"
                @click="pwShow = !pwShow" />
            </template>
          </q-input>
          <q-input v-model="pwForm.pw2" label="Passwort wiederholen" outlined dense
            :type="pwShow ? 'text' : 'password'" autocomplete="new-password"
            @keyup.enter="onSetPassword" />
          <div v-if="pwError" class="text-negative text-caption">{{ pwError }}</div>
          <div class="row justify-end">
            <q-btn label="Passwort setzen" icon="key" color="primary" outline dense size="sm"
              :loading="pwSaving" :disable="!pwForm.pw1 || !pwForm.pw2" @click="onSetPassword" />
          </div>
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
         Einheitlicher Mitglied-Bearbeiten-Dialog
         (Stammdaten · Abteilungen · Funktionen · Kontakte · Mannschaften)
         ════════════════════════════════════════════════ -->
    <MitgliedEditDialog
      v-model="editOpen"
      person-mode
      :mitglied-id="editMitgliedId"
      :user-id="editUserId"
      :is-new="editIsNew"
      :initial-tab="editTab"
      :mitglied-name="editName"
      @saved="loadPersonen"
    />

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
                :subtitle="`${formatDateTime(h._zeit)} · ${h._by}`"
                :color="h._color" :icon="h._icon">
                <div class="text-caption">
                  <div class="text-weight-medium text-grey-6 q-mb-xs">{{ h._label }}</div>
                  <template v-if="h._diffs && h._diffs.length">
                    <div v-for="d in h._diffs" :key="d.feld">
                      <span class="text-grey">{{ d.feld }}: </span>
                      <template v-if="d.alt != null">
                        <span class="text-strike text-grey-6">{{ d.alt }}</span>
                        <q-icon name="arrow_forward" size="xs" class="q-mx-xs text-grey" />
                      </template>
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

    <!-- Papierkorb-Dialog: gelöschte Personen wiederherstellen -->
    <q-dialog v-model="trashOpen" full-width>
      <q-card>
        <q-card-section class="row items-center">
          <div class="text-h6">Gelöschte Personen</div>
          <q-space />
          <q-btn flat round icon="close" v-close-popup />
        </q-card-section>
        <q-separator />
        <q-card-section>
          <div v-if="deletedLoading" class="row justify-center q-py-lg">
            <q-spinner size="32px" color="primary" />
          </div>
          <div v-else-if="deletedPersonen.length === 0" class="text-grey text-center q-py-lg">
            Keine gelöschten Personen vorhanden.
          </div>
          <q-table
            v-else
            :rows="deletedPersonen"
            :columns="deletedColumns"
            :row-key="r => r.user_id ?? 'm_' + r.mitglied?.id"
            flat
            :rows-per-page-options="[10, 25, 0]"
          >
            <template #body-cell-login="props">
              <q-td :props="props">
                <span v-if="props.row.username">{{ props.row.username }}</span>
                <span v-else class="text-grey-5">— kein Login —</span>
              </q-td>
            </template>
            <template #body-cell-actions="props">
              <q-td :props="props">
                <q-btn
                  flat dense round icon="restore" color="positive" size="sm"
                  title="Wiederherstellen"
                  @click="confirmRestore(props.row)"
                />
              </q-td>
            </template>
          </q-table>
        </q-card-section>
      </q-card>
    </q-dialog>

  </q-page>
</template>

<script setup>
import { ref, computed, watch, onMounted, onActivated, onDeactivated, nextTick } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import MitgliedEditDialog from 'src/components/MitgliedEditDialog.vue'
import { ibanRule, normalizeIban, isValidIban } from 'src/utils/iban'
import { proposeAufnahmegebuehr } from 'src/utils/aufnahmegebuehr'
import { formatDateTime } from 'src/utils/datetime'

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
// Ausgetretene (Austritt in der Vergangenheit) standardmäßig ausblenden – nur per Häkchen sichtbar
const zeigeAusgetretene = ref(false)

// ── Papierkorb (gelöschte Personen) ────────────────────────
const trashOpen = ref(false)
const deletedPersonen = ref([])
const deletedLoading = ref(false)
const deletedColumns = [
  { name: 'name', label: 'Name', align: 'left', sortable: true,
    field: r => (r.mitglied ? `${r.mitglied.nachname}, ${r.mitglied.vorname}` : (r.username || '')) },
  { name: 'login', label: 'Login', align: 'left', field: r => r.username || '' },
  { name: 'email', label: 'E-Mail', align: 'left', field: 'email' },
  { name: 'deleted_at', label: 'Gelöscht am', align: 'left', field: 'deleted_at', sortable: true, format: v => formatDateTime(v) },
  { name: 'deleted_by', label: 'Gelöscht von', align: 'left', field: 'deleted_by' },
  { name: 'actions', label: '', align: 'right', field: 'actions' },
]

// ── Sortierung ─────────────────────────────────────────────
// Native Quasar-Tabellensortierung (über pagination). Start: „Zuletzt bearbeitet" absteigend (neueste zuerst).
const pagination = ref({ sortBy: 'last_edited', descending: true, page: 1, rowsPerPage: 25 })

// "Nur Lizenz": beim Wechsel automatisch nach Ablaufdatum aufsteigend sortieren
// (früheste/abgelaufene zuerst); beim Verlassen zurück auf "zuletzt bearbeitet".
watch(filter, (nun, vorher) => {
  if (nun === 'lizenz') {
    pagination.value = { ...pagination.value, sortBy: 'lizenz_bis', descending: false, page: 1 }
  } else if (vorher === 'lizenz') {
    pagination.value = { ...pagination.value, sortBy: 'last_edited', descending: true, page: 1 }
  }
})

// Sortierschlüssel der Name-Spalte: Nachname + Vorname (Mitglied) bzw. Benutzername.
function nameKey(p) {
  return p.mitglied
    ? `${p.mitglied.nachname} ${p.mitglied.vorname}`
    : (p.username || '')
}

const filterOptions = [
  { label: 'Alle', value: 'alle' },
  { label: 'Nur Mitglieder', value: 'mitglieder' },
  { label: 'Nur Benutzer', value: 'benutzer' },
  { label: 'Nur Lizenz', value: 'lizenz' },
  { label: 'Gastspieler', value: 'gastspieler' },
]

// Trainerlizenz-Status eines Mitglieds für die Ampel in der "Nur Lizenz"-Ansicht.
// Baut ausschließlich auf dem Lizenzfenster [von, bis] auf (nur gemeinsam gesetzt, #63).
// Rückgabe null = keine Lizenz hinterlegt. Schwelle "läuft bald ab": 90 Tage.
const LIZENZ_WARN_TAGE = 90
function lizenzInfo(m) {
  const bis = m?.trainerlizenz_gueltig_bis
  if (!bis) return null
  const von = m?.trainerlizenz_gueltig_von
  const heute = heuteIso()
  if (von && von > heute) {
    return { color: 'blue-grey', label: `ab ${formatDate(von)}` }
  }
  if (bis < heute) {
    return { color: 'negative', label: 'abgelaufen' }
  }
  const tage = Math.round((new Date(bis) - new Date(heute)) / 86400000)
  if (tage <= LIZENZ_WARN_TAGE) {
    return { color: 'orange', label: `noch ${tage} Tg.` }
  }
  return { color: 'positive', label: 'gültig' }
}

// Spalten sind tab-abhängig: Im Tab "Nur Benutzer" interessieren Rolle und
// letzte Aktivität statt Geburtstag/Eintritt (Ticket #14).
const columns = computed(() => {
  const istBenutzer = filter.value === 'benutzer'
  const nameCol = { name: 'name', label: 'Name', align: 'left', sortable: true,
    field: r => (r.mitglied ? `${r.mitglied.nachname}, ${r.mitglied.vorname}` : r.username || ''),
    sort: (a, b, rowA, rowB) => nameKey(rowA).localeCompare(nameKey(rowB), 'de', { sensitivity: 'base' }) }

  // "Nur Lizenz": fokussierte, nach Ablauf sortierbare Trainerlizenz-Liste (#70).
  if (filter.value === 'lizenz') {
    return [
      nameCol,
      { name: 'qualifikation', label: 'Qualifikation', align: 'left', sortable: true,
        field: r => r.mitglied?.qualifikation || '' },
      { name: 'lizenz_nr', label: 'Lizenz-Nr.', align: 'left', sortable: true,
        field: r => r.mitglied?.trainerlizenz_nr || '' },
      { name: 'lizenz_von', label: 'Gültig von', align: 'left', sortable: true,
        field: r => r.mitglied?.trainerlizenz_gueltig_von || '', format: v => formatDate(v) },
      { name: 'lizenz_bis', label: 'Gültig bis', align: 'left', sortable: true,
        field: r => r.mitglied?.trainerlizenz_gueltig_bis || '' },
      { name: 'abteilungen', label: 'Abteilungen', field: 'abteilungen', align: 'left' },
      { name: 'actions', label: '', field: 'actions', align: 'right', style: 'width: 200px' },
    ]
  }

  const cols = [
    nameCol,
    { name: 'email', label: 'E-Mail', field: 'email',    align: 'left', sortable: true },
  ]
  if (istBenutzer) {
    cols.push({ name: 'rolle', label: 'Rolle', field: 'role', align: 'left', sortable: true })
  } else {
    cols.push(
      { name: 'geburtsdatum', label: 'Geburtstag', field: r => r.mitglied?.geburtsdatum, align: 'left', sortable: true },
      { name: 'eintritt',     label: 'Eintritt/Austritt', field: r => r.mitglied?.austrittsdatum || r.mitglied?.eintrittsdatum, align: 'left', sortable: true },
    )
  }
  cols.push({ name: 'status', label: 'Status', align: 'center', sortable: true,
    field: r => (r.mitglied
      ? (r.mitglied.art === 'gastspieler' ? 'gastspieler' : r.mitglied.status)
      : (r.active ? 'aktiv' : 'inaktiv')) })
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

// Lokales Heute als ISO-Datum (YYYY-MM-DD) für den Austritts-Vergleich.
function heuteIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// Ausgetreten = Austrittsdatum gesetzt UND in der Vergangenheit (am Austrittstag
// selbst noch Mitglied → `<` heute). Konsistent zur Statistik-Dashboard-Definition.
function istAusgetreten(p) {
  const aus = p.mitglied?.austrittsdatum
  return !!aus && aus < heuteIso()
}

const filteredPersonen = computed(() => {
  let list = personen.value

  // Basis-Filter ("Nur Mitglieder" = echte Vereinsmitglieder, ohne Gastspieler)
  if (filter.value === 'mitglieder') list = list.filter(p => p.mitglied && p.mitglied.art !== 'gastspieler')
  if (filter.value === 'benutzer')   list = list.filter(p => p.user_id)
  // "Nur Lizenz": Mitglieder mit hinterlegtem Trainerlizenz-Fenster (#70)
  if (filter.value === 'lizenz')     list = list.filter(p => p.mitglied?.trainerlizenz_gueltig_bis)
  if (filter.value === 'gastspieler') list = list.filter(p => p.mitglied?.art === 'gastspieler')

  // Ausgetretene standardmäßig ausblenden (nur per Häkchen sichtbar)
  if (!zeigeAusgetretene.value) list = list.filter(p => !istAusgetreten(p))
  
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

// Karten-Ansicht (mobil) hat keine Spaltenköpfe → feste Sortierung. In der "Nur Lizenz"-
// Ansicht nach Ablaufdatum aufsteigend (wie die Tabelle), sonst „Zuletzt bearbeitet" absteigend.
const sortierteKarten = computed(() => {
  const list = [...filteredPersonen.value]
  if (filter.value === 'lizenz') {
    return list.sort((a, b) => String(a.mitglied?.trainerlizenz_gueltig_bis || '')
      .localeCompare(String(b.mitglied?.trainerlizenz_gueltig_bis || '')))
  }
  return list.sort((a, b) => String(b.last_edited || '').localeCompare(String(a.last_edited || '')))
})

// Filter zurücksetzen (nur Abteilungs- und Funktionsfilter, nicht Basis-Filter)
function resetAllFilters() {
  abteilungFilter.value = null
  funktionFilter.value = null
  search.value = ''
}

// ── Hilfsfunktionen ────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('de-DE')
}

// Zuordnung (Abteilung/Funktion), deren Beginndatum in der Zukunft liegt? Solche werden
// in der Liste bereits angezeigt und mit „ab <Beginndatum>" gekennzeichnet (Ticket #91).
function istZukuenftig(von) {
  return !!von && von > heuteIso()
}

// ── Optionen ───────────────────────────────────────────────
// Seit Stufe D (siehe BERECHTIGUNGEN.md) gibt es nur noch 'admin'/'mitglied'.
// Statt einer Rollen-Auswahl ein Administrator-Schalter (nur für Admins sichtbar).
const canAssignAdmin = computed(() => auth.user?.role === 'admin')
// Login-Accounts darf nur anlegen, wer Berechtigungen vergeben darf.
const canManageUsers = computed(() => auth.hasPermission('personen.permissions'))
const mitgliedStatusOptions = [
  { label: 'Aktiv',           value: 'aktiv' },
  { label: 'Passiv',          value: 'passiv' },
  { label: 'Ausgetreten',     value: 'ausgetreten' },
]

// Personenart bei der Neuanlage: Gastspieler (Gastspielgenehmigung) sind keine
// Vereinsmitglieder – ohne Mitgliedsnummer/Eintritt/Zahlung, ohne Beiträge/Statistik.
const artOptions = [
  { label: 'Vereinsmitglied', value: 'mitglied' },
  { label: 'Gastspieler', value: 'gastspieler' },
]

const geschlechtOptions = [
  { label: 'männlich', value: 'm' },
  { label: 'weiblich', value: 'w' },
  { label: 'divers',   value: 'd' },
]

// Lastschrift steuert den SEPA-Einzug im Fibu-Export (Feld 36); Standard = Lastschrift.
const zahlungsartOptionen = [
  { label: 'Lastschrift', value: 'lastschrift' },
  { label: 'Sonstiges', value: 'sonstiges' },
]

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

// Vereinsstatus eines Mitglieds (aktiv/passiv/ausgetreten) – getrennt vom
// Account-Aktiv-Flag (Login). 'aktiv' wird als "Vereinsmitglied" angezeigt.
// Gastspieler (art='gastspieler') sind keine Vereinsmitglieder und bekommen
// statt des Vereinsstatus einen eigenen Chip in Vereinsgelb.
function mitgliedStatusLabel(m) {
  if (m?.art === 'gastspieler') return 'Gastspieler'
  return { aktiv: 'Vereinsmitglied', passiv: 'Passiv', ausgetreten: 'Ausgetreten' }[m?.status] ?? (m?.status || '—')
}
function mitgliedStatusColor(m) {
  if (m?.art === 'gastspieler') return 'vtb-gelb'
  return { aktiv: 'positive', passiv: 'grey', ausgetreten: 'negative' }[m?.status] ?? 'grey'
}
// Gelb nie mit weißem Text (Vereinsfarben-Konvention) → Gast-Chip in Blau auf Gelb.
function mitgliedStatusTextColor(m) {
  return m?.art === 'gastspieler' ? 'primary' : 'white'
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

// ── Papierkorb ─────────────────────────────────────────────
async function loadDeleted() {
  deletedLoading.value = true
  try {
    const { data } = await api.get('/api/personen/deleted')
    deletedPersonen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden des Papierkorbs' })
  } finally {
    deletedLoading.value = false
  }
}

// Papierkorb beim Öffnen laden
watch(trashOpen, (open) => { if (open) loadDeleted() })

function confirmRestore(row) {
  const name = row.mitglied
    ? `${row.mitglied.nachname}, ${row.mitglied.vorname}`
    : (row.username || 'Person')
  $q.dialog({
    title: 'Wiederherstellen',
    message: `"${name}" wiederherstellen?`,
    cancel: true,
  }).onOk(async () => {
    try {
      if (row.user_id) {
        await api.post(`/api/personen/${row.user_id}/restore`)
      } else {
        await api.post(`/api/personen/mitglied/${row.mitglied.id}/restore`)
      }
      $q.notify({ type: 'positive', message: 'Wiederhergestellt' })
      await Promise.all([loadPersonen(), loadDeleted()])
      if (deletedPersonen.value.length === 0) trashOpen.value = false
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Wiederherstellen' })
    }
  })
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
    eintrittsdatum: '', geburtsdatum: '', mitglied_status: 'aktiv', art: 'mitglied', geschlecht: null,
    strasse: '', plz: '', ort: '', land: '',
    zahlungsart: 'lastschrift', iban: '', bic: '', kontoinhaber: '',
  }
  createOpen.value = true
}

async function onCreate() {
  createError.value = ''
  // Eintrittsdatum ist auch bei Gastspielern Pflicht (Beginn der Gastspielgenehmigung);
  // nur das Geburtsdatum bleibt für Gastspieler optional.
  const istGast = createForm.value.art === 'gastspieler'
  if (createTab.value === 'mitglied' && !createForm.value.eintrittsdatum) {
    createError.value = 'Eintrittsdatum ist erforderlich.'
    return
  }
  if (createTab.value === 'mitglied' && !istGast && !createForm.value.geburtsdatum) {
    createError.value = 'Geburtsdatum ist erforderlich.'
    return
  }
  createForm.value.iban = normalizeIban(createForm.value.iban)
  if (createForm.value.iban && !isValidIban(createForm.value.iban)) {
    createError.value = 'Ungültige IBAN – bitte Format und Prüfziffer prüfen.'
    return
  }
  createSaving.value = true
  try {
    const payload = { ...createForm.value, status: createForm.value.mitglied_status }
    if (createTab.value === 'user') {
      delete payload.vorname; delete payload.nachname
    } else {
      // Vereinsmitglied: nur Mitglied-Datensatz, kein Login/Benutzer – Login-Felder nicht senden
      delete payload.username
      delete payload.email
      delete payload.role
      delete payload.active
      delete payload.password
    }
    const eintritt = createForm.value.eintrittsdatum
    const { data } = await api.post('/api/personen/', payload)
    $q.notify({ type: 'positive', message: 'Person angelegt' })
    createOpen.value = false
    await loadPersonen()
    // Ticket #43: nach der Grundanlage eines Vereinsmitglieds direkt in den erweiterten
    // Dialog wechseln, damit Abteilungen/Funktionen/Kontakte/Mannschaften sofort erfasst
    // werden können (nur wenn ein Mitglied-Datensatz entstanden ist – nicht beim User-Tab).
    if (data?.mitglied?.id) {
      openMitgliedDialog(data, 'stammdaten')
      // Ticket #42: passende Vereins-Aufnahmegebühr zum Eintrittsdatum vorschlagen
      // (Gastspieler treten nicht ein → keine Aufnahmegebühr).
      if (!istGast) {
        await proposeAufnahmegebuehr($q, { mitgliedId: data.mitglied.id, abteilungId: null, datum: eintritt })
      }
    }
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

// Passwort direkt setzen (im Account-Dialog)
const pwForm   = ref({ pw1: '', pw2: '' })
const pwShow   = ref(false)
const pwSaving = ref(false)
const pwError  = ref('')

function openEditUserDialog(row) {
  editingUserId.value = row.user_id
  editUserError.value = ''
  editUserForm.value = {
    username: row.username, email: row.email,
    role: row.role, active: row.active,
    expected_version: row.user_version,
  }
  pwForm.value = { pw1: '', pw2: '' }
  pwShow.value = false
  pwError.value = ''
  editUserOpen.value = true
}

async function onSetPassword() {
  if (pwForm.value.pw1.length < 6) { pwError.value = 'Mindestens 6 Zeichen'; return }
  if (pwForm.value.pw1 !== pwForm.value.pw2) { pwError.value = 'Passwörter stimmen nicht überein'; return }
  pwError.value = ''
  pwSaving.value = true
  try {
    await api.post(`/api/users/${editingUserId.value}/password`, { new_password: pwForm.value.pw1 })
    $q.notify({ type: 'positive', message: `Passwort für „${editUserForm.value.username}" gesetzt` })
    pwForm.value = { pw1: '', pw2: '' }
  } catch (e) {
    pwError.value = e.response?.data?.detail || 'Fehler beim Setzen des Passworts'
  } finally {
    pwSaving.value = false
  }
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

// ── Mitglied bearbeiten (einheitlicher Dialog) ─────────────
// Stammdaten/Abteilungen/Funktionen/Kontakte/Mannschaften laufen jetzt über die
// gemeinsame Komponente MitgliedEditDialog (person-mode). Die Zeilen-Icons öffnen
// denselben Dialog am jeweils passenden Tab.
const editOpen       = ref(false)
const editMitgliedId = ref(null)
const editUserId     = ref(null)
const editIsNew      = ref(false)
const editTab        = ref('stammdaten')
const editName       = ref('')

function openMitgliedDialog(row, tabName) {
  editMitgliedId.value = row.mitglied?.id ?? null
  editUserId.value = row.user_id ?? null
  editIsNew.value = false
  editTab.value = tabName
  editName.value = row.mitglied ? `${row.mitglied.nachname}, ${row.mitglied.vorname}` : (row.username ?? '')
  editOpen.value = true
}

function openEditMitgliedDialog(row) { openMitgliedDialog(row, 'stammdaten') }
function openAbteilungenDialog(row)  { openMitgliedDialog(row, 'abteilungen') }
function openFunktionenDialog(row)   { openMitgliedDialog(row, 'funktionen') }
function openKontakteDialog(row)     { openMitgliedDialog(row, 'kontakte') }
function openMannschaftenDialog(row) { openMitgliedDialog(row, 'mannschaften') }

// Neu-Anlage eines Mitgliedsatzes für einen bestehenden Login-User
function openAddMitgliedDialog(row) {
  editMitgliedId.value = null
  editUserId.value = row.user_id
  editIsNew.value = true
  editTab.value = 'stammdaten'
  editName.value = row.username ?? ''
  editOpen.value = true
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

// ── Funktions-/Abteilungs-Kataloge (Filter + Chip-Labels in der Liste) ──
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
  { key: 'telegram_id',       label: 'Telegram-ID' },
  { key: 'matrix_id',         label: 'Matrix-ID' },
  { key: 'preferred_contact', label: 'Bevorzugter Kanal',
    fmt: v => ({ email: 'E-Mail', matrix: 'Matrix', telegram: 'Telegram' }[v] ?? (v || '—')) },
]
const GESCHLECHT_LABELS = { m: 'männlich', w: 'weiblich', d: 'divers' }
const MITGLIED_DIFF_FIELDS = [
  { key: 'mitgliedsnummer', label: 'Mitgliedsnummer' },
  { key: 'vorname',      label: 'Vorname' },
  { key: 'nachname',     label: 'Nachname' },
  { key: 'geburtsdatum', label: 'Geburtsdatum' },
  { key: 'geschlecht',   label: 'Geschlecht', fmt: v => v ? (GESCHLECHT_LABELS[v] ?? v) : '—' },
  { key: 'email',        label: 'Kontakt-E-Mail' },
  { key: 'telefon',      label: 'Telefon' },
  { key: 'strasse',      label: 'Straße' },
  { key: 'plz',          label: 'PLZ' },
  { key: 'ort',          label: 'Ort' },
  { key: 'land',         label: 'Land' },
  { key: 'status',       label: 'Vereinsstatus' },
  { key: 'zahlungsart',  label: 'Zahlungsart' },
  { key: 'iban',         label: 'IBAN' },
  { key: 'bic',          label: 'BIC' },
  { key: 'kontoinhaber', label: 'Kontoinhaber' },
  { key: 'eintrittsdatum', label: 'Eintrittsdatum' },
  { key: 'austrittsdatum', label: 'Austrittsdatum' },
  { key: 'abgerechnet_bis', label: 'Abgerechnet bis' },
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

const FUNKTION_DIFF_FIELDS = [
  { key: 'funktion',       label: 'Funktion' },
  { key: 'abteilung_name', label: 'Abteilung' },
  { key: 'von',            label: 'Von' },
  { key: 'bis',            label: 'Bis' },
]
const KONTAKT_DIFF_FIELDS = [
  { key: 'typ',         label: 'Typ' },
  { key: 'wert',        label: 'Wert' },
  { key: 'label',       label: 'Bezeichnung' },
  { key: 'ist_primaer', label: 'Primär', fmt: v => v ? 'ja' : 'nein' },
]
const MANNSCHAFT_DIFF_FIELDS = [
  { key: 'rolle', label: 'Rolle' },
  { key: 'von',   label: 'Von' },
  { key: 'bis',   label: 'Bis' },
]

// Versionierte Zuordnungs-Historie (Funktion/Kontakt/Mannschaft): je Eintrag (id) die
// Versionen gruppieren und in Timeline-Events (Hinzugefügt/Geändert/Entfernt + Diffs) wandeln.
function versionedEvents(rows, fields, { icon, makeLabel, fullFn }) {
  const byId = {}
  for (const h of (rows ?? [])) (byId[h.id] ??= []).push(h)
  const out = []
  for (const versions of Object.values(byId)) {
    versions.forEach((h, i) => {
      const phase = h.deleted_at ? 'del' : h.version === 1 ? 'new' : 'chg'
      out.push({
        _zeit: h.updated_at, _by: h.updated_by,
        _color: phase === 'del' ? 'negative' : phase === 'new' ? 'teal' : 'primary',
        _icon: icon[phase],
        _label: makeLabel(phase, h),
        _diffs: diffEntries(versions[i - 1], h, fields),
        _full: phase === 'new' && fullFn ? fullFn(h) : null,
      })
    })
  }
  return out
}

async function openHistoryDialog(row) {
  historyPerson.value = row
  historyEntries.value = []
  historyOpen.value = true
  historyLoading.value = true
  try {
    // Mit Login-Account → user-basierte Historie, sonst (Mitglied ohne Login) per mitglied_id.
    const url = row.user_id
      ? `/api/personen/${row.user_id}/history`
      : `/api/personen/mitglied/${row.mitglied.id}/history`
    const { data } = await api.get(url)

    const userEvents = data.user.map((h, i) => {
      const diffs = diffEntries(data.user[i - 1], h, USER_DIFF_FIELDS)
      // Passwortänderung als Hinweis (kein Wert, nur „geändert") – Flag kommt vom Backend.
      if (h.passwort_geaendert) diffs.push({ feld: 'Passwort', alt: null, neu: 'geändert' })
      return {
        _typ: 'user', _zeit: h.updated_at, _by: h.updated_by,
        _color: h.deleted_at ? 'negative' : h.version === 1 ? 'positive' : 'primary',
        _icon: h.deleted_at ? 'person_off' : h.version === 1 ? 'person_add' : 'manage_accounts',
        _label: h.deleted_at ? 'Account gelöscht' : h.version === 1 ? 'Account angelegt' : 'Account geändert',
        _diffs: diffs,
        _full: h.version === 1 ? { Benutzername: h.username, 'E-Mail': h.email, Rolle: h.role } : null,
      }
    })

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

    const funktionEvents = versionedEvents(data.funktionen, FUNKTION_DIFF_FIELDS, {
      icon: { del: 'badge', new: 'badge', chg: 'edit' },
      makeLabel: (phase, h) => {
        const name = h.abteilung_name ? `${h.funktion} (${h.abteilung_name})` : h.funktion
        return phase === 'del' ? `Funktion entfernt: ${name}`
          : phase === 'new' ? `Funktion hinzugefügt: ${name}` : `Funktion geändert: ${name}`
      },
      fullFn: h => ({ Abteilung: h.abteilung_name, Von: h.von, Bis: h.bis }),
    })
    const kontaktEvents = versionedEvents(data.kontakte, KONTAKT_DIFF_FIELDS, {
      icon: { del: 'contact_phone', new: 'contact_phone', chg: 'edit' },
      makeLabel: (phase, h) => {
        const name = h.label ? `${h.typ} (${h.label})` : h.typ
        return phase === 'del' ? `Kontakt entfernt: ${name}`
          : phase === 'new' ? `Kontakt hinzugefügt: ${name}` : `Kontakt geändert: ${name}`
      },
      fullFn: h => ({ Wert: h.wert, Bezeichnung: h.label, Primär: h.ist_primaer ? 'ja' : '' }),
    })
    const mannschaftEvents = versionedEvents(data.mannschaften, MANNSCHAFT_DIFF_FIELDS, {
      icon: { del: 'group_remove', new: 'group_add', chg: 'edit' },
      makeLabel: (phase, h) => phase === 'del' ? `Mannschaft verlassen: ${h.mannschaft_name}`
        : phase === 'new' ? `Mannschaft beigetreten: ${h.mannschaft_name}` : `Mannschaft geändert: ${h.mannschaft_name}`,
      fullFn: h => ({ Rolle: h.rolle, Von: h.von, Bis: h.bis }),
    })

    const all = [...userEvents, ...mitgliedEvents, ...abteilungEvents,
      ...funktionEvents, ...kontaktEvents, ...mannschaftEvents].sort((a, b) => {
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

usePageRefresh(() => Promise.all([loadPersonen(), loadFunktionOptionen(), loadAlleAbteilungen()]))
onMounted(() => {
  loadPersonen()
  loadFunktionOptionen()
  loadAlleAbteilungen()
})
</script>

<style scoped>
/* Zebra-Streifen: Tabellen sind in beiden Modi dunkelblaue Flächen —
   heller Überzug statt Hellgrau, damit die weiße Schrift lesbar bleibt
   (Hellgrau + weißer Text = unsichtbare Zeilen, Ticket #102). */
:deep(.q-table tbody tr:nth-child(even) td) {
  background-color: rgba(255, 255, 255, 0.07);
}
.page--dark :deep(.q-table tbody tr:nth-child(even) td) {
  background-color: rgba(255, 255, 255, 0.07);
}

/* Zebra der Karten-Liste: auf Wappenblau ein etwas hellerer Blauton.
   body-Prefix nötig, um die globale Karten-Farbe zu überstimmen. */
body:not(.body--dark) .q-card.stripe {
  background-color: #0b4099;
}
.page--dark .stripe {
  /* Navy-Ton passend zum dunklen Theme (statt Neutralgrau) */
  background-color: #16264a;
}
</style>
