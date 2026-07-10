<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Schließanlage</div>
      <q-space />
      <span v-if="status.letzter_sync_at" class="text-caption text-grey-7 q-mr-sm">
        letzter Sync: {{ fmtDateTime(status.letzter_sync_at) }}
      </span>
      <q-btn v-if="status.darf_sync" color="primary" unelevated icon="sync"
        label="Jetzt synchronisieren" :loading="syncing" @click="doSync" />
    </div>

    <q-banner v-if="!status.konfiguriert" class="bg-amber-2 text-amber-10 q-mb-md" rounded dense>
      <template #avatar><q-icon name="warning" /></template>
      Kein TTLock-Konto konfiguriert (TTLOCK_* in der .env). Inventar/Logs können nicht
      synchronisiert werden.
    </q-banner>

    <q-tabs v-model="tab" dense align="left" class="text-grey-8 q-mb-sm" active-color="primary"
      indicator-color="primary">
      <q-tab name="schloesser" icon="meeting_room" label="Schlösser" />
      <q-tab name="chips" icon="badge" label="Chips" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <!-- ====================== Schlösser ====================== -->
    <div v-if="tab === 'schloesser'">
      <q-list bordered separator>
        <q-item v-for="s in schloesser" :key="s.id" clickable @click="openSchloss(s.id)">
          <q-item-section avatar>
            <q-icon name="meeting_room" :color="s.aktiv ? 'primary' : 'grey'" />
          </q-item-section>
          <q-item-section>
            <q-item-label>
              {{ s.name }}
              <q-chip v-if="s.standort" dense size="sm" outline>{{ s.standort }}</q-chip>
              <q-chip v-if="s.abteilung_name" dense size="sm" color="blue-grey-2">{{ s.abteilung_name }}</q-chip>
            </q-item-label>
            <q-item-label caption>
              <span v-if="s.letztes_event_at">
                letzter Vorgang: {{ fmtDateTime(s.letztes_event_at) }}
                <template v-if="recordTypeLabel(s.letztes_event_type)">
                  ({{ recordTypeLabel(s.letztes_event_type) }})
                </template>
              </span>
              <span v-else>noch keine Zutritte</span>
            </q-item-label>
            <q-item-label v-if="offlineSeit(s)" caption class="text-negative">
              <q-icon name="cloud_off" size="12px" /> {{ offlineSeit(s) }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row items-center q-gutter-sm">
              <q-icon :name="onlineIcon(s.gateway_online)" :color="onlineColor(s.gateway_online)" size="14px">
                <q-tooltip>{{ onlineLabel(s.gateway_online) }}<template
                  v-if="s.gateway_online_seit"> · seit {{ fmtDateTime(s.gateway_online_seit) }}</template></q-tooltip>
              </q-icon>
              <span v-if="s.akku_prozent != null" class="row items-center text-caption"
                :class="akkuLow(s.akku_prozent) ? 'text-negative' : 'text-grey-7'">
                <q-icon :name="akkuIcon(s.akku_prozent)" size="18px" /> {{ s.akku_prozent }}%
              </span>
              <q-btn v-if="status.darf_protokoll" flat round :dense="$q.screen.gt.sm"
                :size="$q.screen.lt.md ? 'md' : 'sm'" icon="history"
                color="grey-7" @click.stop="openSchlossLog(s)">
                <q-tooltip>Zutrittslog</q-tooltip>
              </q-btn>
              <!-- „Fernöffnen" ist die Hauptaktion, wenn das Öffnen-Recht da ist: gefüllter,
                   größerer Button statt kleinem Flat-Icon – am Handy sonst kaum sicht-/tippbar (#89). -->
              <q-btn v-if="status.darf_oeffnen" unelevated round color="primary" text-color="white"
                size="md" icon="lock_open" :loading="opening === s.id" @click.stop="doOeffnen(s)">
                <q-tooltip>Fernöffnen</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="schloesser.length === 0" class="text-grey text-center q-py-lg">
        Keine Schlösser. {{ status.darf_sync ? 'Synchronisiere, um das Inventar zu laden.' : '' }}
      </div>
    </div>

    <!-- ====================== Chips ====================== -->
    <div v-if="tab === 'chips'">
      <div class="row q-mb-sm">
        <q-space />
        <q-btn v-if="status.darf_verwalten" color="primary" unelevated icon="add"
          label="Neuer Chip" @click="openChipCreate" />
      </div>
      <q-list bordered separator>
        <q-item v-for="c in chips" :key="c.id" clickable @click="openChip(c.id)">
          <q-item-section avatar>
            <q-icon name="badge" :color="c.status === 'aktiv' ? 'primary' : 'grey'" />
          </q-item-section>
          <q-item-section>
            <q-item-label>
              {{ c.bezeichnung || ('Chip #' + c.id) }}
              <q-chip dense size="sm" outline>Nr. {{ c.kartennummer }}</q-chip>
              <q-chip v-if="c.status !== 'aktiv'" dense size="sm" color="orange-3">{{ c.status }}</q-chip>
            </q-item-label>
            <q-item-label caption>
              <span v-if="c.mitglied_id">ausgegeben an {{ mitgliedName(c) }}</span>
              <span v-else-if="c.aufbewahrungsort">liegt: {{ c.aufbewahrungsort }}</span>
              <span v-else>nicht zugeordnet</span>
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row items-center text-grey-6">
              <q-icon v-if="status.darf_protokoll" name="history" size="18px">
                <q-tooltip>Details &amp; Nutzungs-Log – wo &amp; wann benutzt</q-tooltip>
              </q-icon>
              <q-icon name="chevron_right" size="20px" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="chips.length === 0" class="text-grey text-center q-py-lg">Noch keine Chips erfasst.</div>
    </div>

    <!-- ====================== Schloss-Detail ====================== -->
    <q-dialog v-model="schlossDialog" :maximized="$q.screen.lt.sm">
      <q-card style="min-width:min(680px,96vw)">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ schlossDetail.schloss?.name }}</div>
          <q-space />
          <q-btn v-if="schlossDetail.darf_oeffnen" flat dense icon="lock_open" color="primary"
            :loading="opening === schlossDetail.schloss?.id" @click="doOeffnen(schlossDetail.schloss)">
            <q-tooltip>Fernöffnen</q-tooltip>
          </q-btn>
          <q-btn v-if="schlossDetail.darf_verriegeln" flat dense icon="lock" color="grey-8"
            @click="doVerriegeln(schlossDetail.schloss)">
            <q-tooltip>Fernverriegeln</q-tooltip>
          </q-btn>
          <q-btn v-if="schlossDetail.darf_verwalten" flat dense icon="edit" @click="openSchlossEdit" />
          <q-btn flat dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-list dense>
            <q-item><q-item-section>Standort</q-item-section>
              <q-item-section side>{{ schlossDetail.schloss?.standort || '–' }}</q-item-section></q-item>
            <q-item><q-item-section>Gateway / Online</q-item-section>
              <q-item-section side>{{ onlineLabel(schlossDetail.schloss?.gateway_online) }}</q-item-section></q-item>
            <q-item><q-item-section>Akku</q-item-section>
              <q-item-section side>{{ schlossDetail.schloss?.akku_prozent ?? '–' }}%</q-item-section></q-item>
          </q-list>

          <div class="row items-center q-mt-md">
            <div class="text-subtitle2">Zugeteilte Chips</div>
            <q-space />
            <q-btn v-if="schlossDetail.darf_verwalten" flat dense size="sm" icon="add" color="primary"
              label="Chip anlernen" @click="openBerAnlernenForSchloss" />
          </div>
          <q-list dense bordered separator>
            <q-item v-for="b in schlossDetail.berechtigungen" :key="b.id">
              <q-item-section>
                <q-item-label>{{ b.chip_bezeichnung || ('Chip #' + b.chip_id) }}
                  <span class="text-grey-6">Nr. {{ b.kartennummer }}</span></q-item-label>
                <q-item-label caption>
                  {{ b.mitglied_vorname ? (b.mitglied_vorname + ' ' + (b.mitglied_nachname||'')) : '—' }}
                  <span v-if="b.gueltig_bis">· gültig bis {{ fmtDateTime(b.gueltig_bis) }}</span>
                  <span v-if="b.sync_fehler" class="text-negative">· {{ b.sync_fehler }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row items-center q-gutter-xs no-wrap">
                  <q-chip dense size="sm" :color="syncColor(b.sync_status)">{{ b.sync_status }}</q-chip>
                  <q-btn v-if="schlossDetail.darf_verwalten" flat dense round size="sm" icon="edit_calendar"
                    @click="openBerEdit(b)"><q-tooltip>Gültigkeit ändern</q-tooltip></q-btn>
                  <q-btn v-if="schlossDetail.darf_verwalten" flat dense round size="sm" icon="link_off"
                    color="negative" @click="revokeBer(b)"><q-tooltip>Entziehen</q-tooltip></q-btn>
                </div>
              </q-item-section>
            </q-item>
            <q-item v-if="!schlossDetail.berechtigungen?.length"><q-item-section class="text-grey">
              keine Chips zugeteilt</q-item-section></q-item>
          </q-list>

          <div class="row items-center q-mt-md">
            <div class="text-subtitle2">Befristete App-Öffnung</div>
            <q-space />
            <q-btn v-if="schlossDetail.darf_verwalten" flat dense size="sm" icon="schedule" color="primary"
              label="Befristet erlauben" @click="openAppGrant" />
          </div>
          <q-list dense bordered separator>
            <q-item v-for="a in schlossDetail.app_berechtigungen" :key="a.id">
              <q-item-section>
                <q-item-label>{{ a.user_username || ('User #' + a.user_id) }}</q-item-label>
                <q-item-label caption>
                  {{ a.gueltig_von ? fmtDateTime(a.gueltig_von) : 'ab sofort' }}
                  – {{ a.gueltig_bis ? fmtDateTime(a.gueltig_bis) : 'unbefristet' }}
                  <span v-if="a.grund">· {{ a.grund }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side v-if="schlossDetail.darf_verwalten">
                <q-btn flat dense round size="sm" icon="delete" color="negative"
                  @click="revokeApp(a)" />
              </q-item-section>
            </q-item>
            <q-item v-if="!schlossDetail.app_berechtigungen?.length"><q-item-section class="text-grey">
              keine befristeten App-Berechtigungen</q-item-section></q-item>
          </q-list>

          <div class="row items-center q-mt-md">
            <div class="text-subtitle2">Am Schloss eingerichtet</div>
            <q-space />
            <q-chip dense size="sm" color="grey-3">{{ mirrorCredentials(schlossDetail.credentials).length }}</q-chip>
          </div>
          <div class="text-caption text-grey-6 q-mb-xs">
            Read-only aus der TTLock-Cloud gespiegelt – zeigt Credentials, die nicht über die App
            liefen (IC-Karten siehe oben „Zugeteilte Chips").
          </div>
          <div v-if="!mirrorCredentials(schlossDetail.credentials).length" class="text-grey text-caption q-mb-sm">
            keine Credentials gespiegelt (oder noch kein Sync)
          </div>
          <template v-for="g in credentialGruppen(mirrorCredentials(schlossDetail.credentials))" :key="g.typ">
            <div class="text-caption text-weight-medium text-grey-8 q-mt-sm q-mb-xs">
              <q-icon :name="g.icon" size="16px" class="q-mr-xs" />{{ g.label }} ({{ g.items.length }})
            </div>
            <q-list dense bordered separator>
              <q-item v-for="c in g.items" :key="c.typ + '-' + c.id">
                <q-item-section>
                  <q-item-label>{{ c.name || ('#' + (c.ttlock_credential_id ?? '?')) }}</q-item-label>
                  <q-item-label caption>
                    <span v-if="c.detail">{{ c.detail }} · </span>
                    {{ c.gueltig_bis ? ('gültig bis ' + fmtDateTime(c.gueltig_bis)) : 'unbefristet' }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </template>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ====================== Zutrittslog (Schloss) ====================== -->
    <q-dialog v-model="logDialog" :maximized="$q.screen.lt.sm">
      <q-card style="min-width:min(560px,96vw)">
        <q-card-section class="row items-center">
          <q-icon name="history" class="q-mr-sm" />
          <div class="text-h6">Zutrittslog</div>
          <div v-if="logSchloss" class="text-caption text-grey q-ml-sm">{{ logSchloss.name }}</div>
          <q-space />
          <q-btn flat dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none">
          <div v-if="logDarfProtokoll" class="text-caption text-grey-6 q-mb-xs">
            <q-icon name="privacy_tip" size="14px" /> Personenbezogene Bewegungsdaten –
            nur zweckgebunden einsehen (DSGVO).
          </div>
          <div v-if="logLoading" class="row justify-center q-py-lg">
            <q-spinner size="28px" color="primary" />
          </div>
          <div v-else-if="!logDarfProtokoll" class="text-grey text-caption q-py-sm">
            Kein Recht für das Zutrittsprotokoll (schliessanlage.protokoll).
          </div>
          <q-list v-else dense bordered separator>
            <q-item v-for="it in logItems" :key="it.key">
              <template v-if="it.typ === 'status'">
                <q-item-section avatar>
                  <q-icon :name="onlineIcon(it.online)" :color="onlineColor(it.online)" size="18px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ statusEventLabel(it.online) }}</q-item-label>
                  <q-item-label caption>{{ fmtDateTime(it.geaendert_am) }}</q-item-label>
                </q-item-section>
              </template>
              <template v-else>
                <q-item-section avatar>
                  <q-icon :name="it.erfolg ? 'check_circle' : 'cancel'"
                    :color="it.erfolg ? 'positive' : 'negative'" size="18px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ it.methode }}</q-item-label>
                  <q-item-label caption>{{ fmtDateTime(it.lock_date) }}
                    <span v-if="logWer(it)">· {{ logWer(it) }}</span></q-item-label>
                </q-item-section>
              </template>
            </q-item>
            <q-item v-if="!logItems.length"><q-item-section class="text-grey">
              keine Einträge im Zeitraum</q-item-section></q-item>
          </q-list>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ====================== Chip-Detail ====================== -->
    <q-dialog v-model="chipDialog" :maximized="$q.screen.lt.sm">
      <q-card style="min-width:min(640px,96vw)">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ chipDetail.chip?.bezeichnung || ('Chip #' + chipDetail.chip?.id) }}</div>
          <q-space />
          <q-btn v-if="status.darf_verwalten" flat dense icon="edit" @click="openChipEdit" />
          <q-btn v-if="status.darf_verwalten" flat dense icon="delete" color="negative" @click="deleteChip" />
          <q-btn flat dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none">
          <div class="text-caption text-grey-7">
            Nr. {{ chipDetail.chip?.kartennummer }} ·
            {{ chipDetail.chip?.mitglied_id ? ('ausgegeben an ' + mitgliedName(chipDetail.chip))
               : ('liegt: ' + (chipDetail.chip?.aufbewahrungsort || '—')) }}
          </div>

          <div class="row items-center q-mt-md">
            <div class="text-subtitle2">Öffnet diese Schlösser</div>
            <q-space />
            <q-btn v-if="status.darf_verwalten" flat dense size="sm" icon="add" color="primary"
              label="An Schloss anlernen" @click="openBerAnlernenForChip" />
          </div>
          <q-list dense bordered separator>
            <q-item v-for="b in chipDetail.berechtigungen" :key="b.id">
              <q-item-section>
                <q-item-label>{{ b.schloss_name }}</q-item-label>
                <q-item-label caption v-if="b.gueltig_bis || b.sync_fehler">
                  <span v-if="b.gueltig_bis">gültig bis {{ fmtDateTime(b.gueltig_bis) }}</span>
                  <span v-if="b.sync_fehler" class="text-negative">· {{ b.sync_fehler }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row items-center q-gutter-xs no-wrap">
                  <q-chip dense size="sm" :color="syncColor(b.sync_status)">{{ b.sync_status }}</q-chip>
                  <q-btn v-if="status.darf_verwalten" flat dense round size="sm" icon="edit_calendar"
                    @click="openBerEdit(b)"><q-tooltip>Gültigkeit ändern</q-tooltip></q-btn>
                  <q-btn v-if="status.darf_verwalten" flat dense round size="sm" icon="link_off"
                    color="negative" @click="revokeBer(b)"><q-tooltip>Entziehen</q-tooltip></q-btn>
                </div>
              </q-item-section>
            </q-item>
            <q-item v-if="!chipDetail.berechtigungen?.length"><q-item-section class="text-grey">
              keine Berechtigungen</q-item-section></q-item>
          </q-list>

          <div class="text-subtitle2 q-mt-md">Benutzt (Nutzungs-Log)</div>
          <div v-if="chipDetail.darf_protokoll" class="text-caption text-grey-6 q-mb-xs">
            <q-icon name="privacy_tip" size="14px" /> Personenbezogene Bewegungsdaten –
            nur zweckgebunden einsehen (DSGVO).
          </div>
          <div v-if="!chipDetail.darf_protokoll" class="text-grey text-caption">
            Kein Recht für das Zutrittsprotokoll (schliessanlage.protokoll).
          </div>
          <q-list v-else dense bordered separator>
            <q-item v-for="l in chipDetail.logs" :key="l.id">
              <q-item-section avatar>
                <q-icon :name="l.erfolg ? 'check_circle' : 'cancel'"
                  :color="l.erfolg ? 'positive' : 'negative'" size="18px" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ l.schloss_name }}</q-item-label>
                <q-item-label caption>{{ fmtDateTime(l.lock_date) }} · {{ l.methode }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-if="!chipDetail.logs?.length"><q-item-section class="text-grey">
              noch nicht benutzt</q-item-section></q-item>
          </q-list>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ====================== Chip anlegen/bearbeiten ====================== -->
    <q-dialog v-model="chipFormDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">{{ chipForm.id ? 'Chip bearbeiten' : 'Neuer Chip' }}</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-input v-model="chipForm.kartennummer" label="Kartennummer *" outlined dense
            :readonly="!!chipForm.id" :hint="chipForm.id ? 'Kartennummer ist fix' : ''" />
          <q-input v-model="chipForm.bezeichnung" label="Bezeichnung (z. B. Chip blau 14)" outlined dense />
          <q-select v-model="chipForm.mitglied_id" :options="mitgliedOptions" option-value="id"
            :option-label="mitgliedLabel" emit-value map-options use-input input-debounce="0"
            @filter="filterMitglieder" label="Mitglied (optional)" outlined dense clearable
            :hint="mitglieder.length ? 'Wem ausgegeben – leer = Pool-Chip mit Standort'
              : 'keine Mitglieder geladen'">
            <template #no-option>
              <q-item><q-item-section class="text-grey">kein Treffer</q-item-section></q-item>
            </template>
          </q-select>
          <q-input v-model="chipForm.aufbewahrungsort" label="Standardstandort (wenn nicht ausgegeben)"
            outlined dense />
          <q-select v-model="chipForm.status" :options="['aktiv','gesperrt','verloren']" label="Status"
            outlined dense />
          <div v-if="chipError" class="text-negative text-caption">{{ chipError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" :label="chipForm.id ? 'Speichern' : 'Anlegen'"
            :loading="saving" @click="saveChip" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ====================== Schloss-Stammdaten bearbeiten ====================== -->
    <q-dialog v-model="schlossFormDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">Schloss bearbeiten</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-input v-model="schlossForm.name" label="Name *" outlined dense />
          <q-input v-model="schlossForm.standort" label="Standort" outlined dense />
          <q-select v-model="schlossForm.abteilung_id" :options="abteilungen" option-value="id"
            option-label="name" emit-value map-options clearable label="Abteilung (leer = vereinsweit)"
            outlined dense />
          <q-input v-model="schlossForm.notiz" label="Notiz" outlined dense type="textarea" autogrow />
          <q-toggle v-model="schlossForm.aktiv" label="aktiv" />
          <div v-if="schlossError" class="text-negative text-caption">{{ schlossError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Speichern" :loading="saving" @click="saveSchloss" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ====================== Befristete App-Öffnung vergeben ====================== -->
    <q-dialog v-model="appGrantDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">Befristet öffnen erlauben</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <div class="text-caption text-grey-7">
            Schloss: {{ schlossDetail.schloss?.name }}
          </div>
          <q-select v-model="appGrantForm.user" :options="userOptions" :option-label="o => o && o.username"
            use-input input-debounce="0" fill-input hide-selected @filter="filterUsers"
            label="Benutzer *" outlined dense clearable
            :hint="users.length ? 'nach Benutzername suchen' : 'keine Benutzer geladen'">
            <template #no-option>
              <q-item><q-item-section class="text-grey">kein Treffer</q-item-section></q-item>
            </template>
          </q-select>
          <q-input v-model="appGrantForm.gueltig_von" type="datetime-local" label="Gültig ab"
            outlined dense stack-label hint="Standard: jetzt – anpassbar" />
          <q-select v-model="appGrantForm.dauer" :options="dauerOptionen" emit-value map-options
            label="Gültig bis" outlined dense />
          <q-input v-if="appGrantForm.dauer === 'custom'" v-model="appGrantForm.gueltig_bis_custom"
            type="datetime-local" label="Konkretes Datum/Uhrzeit" outlined dense stack-label />
          <q-input v-model="appGrantForm.grund" label="Grund (optional)" outlined dense />
          <div v-if="appGrantError" class="text-negative text-caption">{{ appGrantError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Erlauben" :loading="saving" @click="saveAppGrant" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ====================== Chip anlernen (Chip ↔ Schloss) ====================== -->
    <q-dialog v-model="berDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:460px'">
        <q-card-section class="text-h6">Chip anlernen</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <div class="text-caption text-grey-7" v-if="berForm.mode === 'chip'">
            Schloss: {{ berForm.schloss_name }}
          </div>
          <div class="text-caption text-grey-7" v-else>Chip: {{ berForm.chip_name }}</div>

          <q-select v-if="berForm.mode === 'chip'" v-model="berForm.chip" :options="chipOptions"
            :option-label="chipLabel" use-input input-debounce="0" fill-input hide-selected
            @filter="filterChips" label="Chip *" outlined dense clearable hint="nach Bezeichnung/Nummer suchen">
            <template #no-option><q-item><q-item-section class="text-grey">kein Treffer</q-item-section></q-item></template>
          </q-select>
          <q-select v-else v-model="berForm.schloss" :options="schlossOptions"
            :option-label="o => o && o.name" use-input input-debounce="0" fill-input hide-selected
            @filter="filterSchloesser" label="Schloss *" outlined dense clearable hint="nach Name suchen">
            <template #no-option><q-item><q-item-section class="text-grey">kein Treffer</q-item-section></q-item></template>
          </q-select>

          <q-input v-model="berForm.gueltig_von" type="datetime-local" label="Gültig ab"
            outlined dense stack-label hint="Standard: jetzt" />
          <q-select v-model="berForm.dauer" :options="dauerOptionen" emit-value map-options
            label="Gültig bis" outlined dense />
          <q-input v-if="berForm.dauer === 'custom'" v-model="berForm.gueltig_bis_custom"
            type="datetime-local" label="Konkretes Datum/Uhrzeit" outlined dense stack-label />
          <div class="text-caption text-grey-6">
            Die IC-Karte wird per Gateway am Schloss angelernt – die Kartennummer muss dem
            Schloss bekannt sein (am Schloss gescannt oder per Leser erfasst).
          </div>
          <div v-if="berError" class="text-negative text-caption">{{ berError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Anlernen" :loading="saving" @click="saveBer" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ====================== Gültigkeit ändern ====================== -->
    <q-dialog v-model="berEditDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">Gültigkeit ändern</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <div class="text-caption text-grey-7">{{ berEditForm.name }}</div>
          <q-input v-model="berEditForm.gueltig_von" type="datetime-local" label="Gültig ab"
            outlined dense stack-label />
          <q-select v-model="berEditForm.dauer" :options="dauerOptionen" emit-value map-options
            label="Gültig bis" outlined dense />
          <q-input v-if="berEditForm.dauer === 'custom'" v-model="berEditForm.gueltig_bis_custom"
            type="datetime-local" label="Konkretes Datum/Uhrzeit" outlined dense stack-label />
          <div v-if="berError" class="text-negative text-caption">{{ berError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Speichern" :loading="saving" @click="saveBerEdit" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { usePageRefresh } from 'src/composables/useRefresh'
import { api } from 'src/boot/axios'

defineOptions({ name: 'SchliessanlagePage' })

const $q = useQuasar()

// recordType → Label (gespiegelt aus app/models/schliessanlage.py, Referenzdaten).
const RECORD_TYPES = {
  1: 'App', 2: 'Parklücke berührt', 3: 'Gateway (remote)', 4: 'Passcode',
  5: 'Parksperre hoch', 6: 'Parksperre runter', 7: 'IC-Karte', 8: 'Fingerprint',
  9: 'Armband', 10: 'mech. Schlüssel', 11: 'Bluetooth-Verriegeln', 12: 'Gateway (remote)',
  29: 'Unerwartet entriegelt', 30: 'Türmagnet zu', 31: 'Türmagnet auf', 32: 'Von innen geöffnet',
  33: 'Verriegelt (Fingerprint)', 34: 'Verriegelt (Passcode)', 35: 'Verriegelt (IC-Karte)',
  36: 'Verriegelt (mech. Schlüssel)', 37: 'Fernbedienung', 44: 'Sabotage-Alarm', 45: 'Auto-Lock',
  46: 'Entriegeln (Unlock-Key)', 47: 'Verriegeln (Lock-Key)', 48: 'Mehrf. Falsch-Passcode',
}
// Unbekannte Eventtypen ohne Label ('' -> Klammerzusatz entfällt) statt kryptischem '?17'.
const recordTypeLabel = (t) => (t == null ? '' : (RECORD_TYPES[t] || ''))

// Credential-Typen am Schloss (read-only Mirror) → Anzeige-Reihenfolge + Icon/Label.
// IC-Karten bewusst NICHT hier: die verwalten wir über die App und zeigen sie oben unter
// „Zugeteilte Chips" (dort einem Mitglied zugeordnet). Im Mirror wären sie nur ein doppelter,
// ärmerer Eintrag → werden über CRED_TYP_APP_MANAGED ausgeblendet.
const CRED_TYP_META = {
  fingerprint: { label: 'Fingerprints', icon: 'fingerprint' },
  passcode: { label: 'Passcodes', icon: 'dialpad' },
  ekey: { label: 'App-/eKeys', icon: 'phonelink_ring' },
}
const CRED_TYP_ORDER = ['fingerprint', 'passcode', 'ekey']
const CRED_TYP_APP_MANAGED = ['ic']   // schon unter „Zugeteilte Chips" sichtbar
function mirrorCredentials(credentials) {
  return (credentials || []).filter((c) => !CRED_TYP_APP_MANAGED.includes(c.typ))
}
function credentialGruppen(credentials) {
  const by = {}
  for (const c of credentials || []) (by[c.typ] ||= []).push(c)
  return CRED_TYP_ORDER
    .filter((t) => by[t]?.length)
    .map((t) => ({ typ: t, ...CRED_TYP_META[t], items: by[t] }))
}

const tab = ref('schloesser')
const status = ref({ konfiguriert: false, darf_verwalten: false, darf_protokoll: false, darf_sync: false, letzter_sync_at: null })
const schloesser = ref([])
const chips = ref([])
const abteilungen = ref([])
const syncing = ref(false)
const saving = ref(false)
const opening = ref(null)

function fmtDateTime(iso) {
  if (!iso) return '–'
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' })
}
const onlineIcon = (o) => (o === true ? 'cloud_done' : o === false ? 'cloud_off' : 'cloud_queue')
const onlineColor = (o) => (o === true ? 'positive' : o === false ? 'negative' : 'grey')
const onlineLabel = (o) => (o === true ? 'Gateway online' : o === false ? 'Gateway offline' : 'unbekannt')
const statusEventLabel = (o) => (o === true ? 'Gateway online' : o === false ? 'Gateway offline' : 'Gateway-Status unbekannt')
// „offline seit …" nur, wenn ein Gateway zugeordnet ist (sonst kein sinnvoller Offline-Bezug)
// und der Status derzeit nicht online ist (#82).
const offlineSeit = (s) => {
  if (s.gateway_online === true || s.ttlock_gateway_id == null || !s.gateway_online_seit) return ''
  const wort = s.gateway_online === false ? 'offline' : 'nicht erreichbar'
  return `${wort} seit ${fmtDateTime(s.gateway_online_seit)}`
}
const akkuIcon = (p) => (p > 80 ? 'battery_full' : p > 40 ? 'battery_5_bar' : p > 20 ? 'battery_3_bar' : 'battery_alert')
const akkuLow = (p) => p != null && p <= 20
const syncColor = (s) => ({ aktiv: 'green-3', pending: 'grey-3', fehler: 'red-3', gesperrt: 'orange-3' }[s] || 'grey-3')
const mitgliedName = (x) => `${x.mitglied_vorname || ''} ${x.mitglied_nachname || ''}`.trim() || ('Mitglied #' + x.mitglied_id)
// Wer hat geöffnet: aufgelöstes Mitglied > Chip-Bezeichnung > Cloud-Credential-Name (key_name)
// > TTLock-Sammelkonto. key_name benennt das Credential (eKey/Fingerprint), ist also
// aussagekräftiger als das geteilte ttlock_username.
const logWer = (l) => (l.mitglied_vorname ? `${l.mitglied_vorname} ${l.mitglied_nachname || ''}`.trim()
  : l.chip_bezeichnung || l.key_name || l.ttlock_username || '')

async function loadStatus() {
  const { data } = await api.get('/api/schliessanlage/status')
  status.value = data
}
async function loadSchloesser() {
  const { data } = await api.get('/api/schliessanlage/schloesser')
  schloesser.value = data
}
async function loadChips() {
  const { data } = await api.get('/api/schliessanlage/chips')
  chips.value = data
}
async function loadAbteilungen() {
  try { const { data } = await api.get('/api/abteilungen/'); abteilungen.value = data }
  catch { abteilungen.value = [] }
}
async function reloadAll() {
  await Promise.all([loadStatus(), loadSchloesser(), loadChips()])
}
usePageRefresh(reloadAll)
onMounted(async () => {
  try { await Promise.all([reloadAll(), loadAbteilungen()]) }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden der Schließanlage' }) }
})

async function doSync() {
  syncing.value = true
  try {
    const { data } = await api.post('/api/schliessanlage/sync')
    let msg = `Sync ok: ${data.schloesser ?? 0} Schlösser, ${data.neu ?? 0} neue Logs`
    if (data.alarme?.length) msg += ` · ⚠️ ${data.alarme.length} Alarm(e)`
    $q.notify({ type: data.alarme?.length ? 'warning' : 'positive', message: msg })
    await reloadAll()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Sync fehlgeschlagen' })
  } finally { syncing.value = false }
}

function doOeffnen(s) {
  if (!s) return
  $q.dialog({
    title: 'Schloss fernöffnen',
    message: `„${s.name}" jetzt per Gateway öffnen?`,
    cancel: true, ok: { label: 'Öffnen', color: 'primary' },
  }).onOk(async () => {
    opening.value = s.id
    try {
      await api.post(`/api/schliessanlage/schloesser/${s.id}/oeffnen`)
      $q.notify({ type: 'positive', message: `„${s.name}" geöffnet` })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Öffnen fehlgeschlagen' })
    } finally { opening.value = null }
  })
}
function doVerriegeln(s) {
  if (!s) return
  $q.dialog({
    title: 'Schloss fernverriegeln',
    message: `„${s.name}" jetzt per Gateway verriegeln?`,
    cancel: true, ok: { label: 'Verriegeln', color: 'grey-8' },
  }).onOk(async () => {
    try {
      await api.post(`/api/schliessanlage/schloesser/${s.id}/verriegeln`)
      $q.notify({ type: 'positive', message: `„${s.name}" verriegelt` })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Verriegeln fehlgeschlagen' })
    }
  })
}

// --- Schloss-Detail/Edit ---
const schlossDialog = ref(false)
const schlossDetail = ref({})
async function openSchloss(id) {
  try {
    const { data } = await api.get(`/api/schliessanlage/schloesser/${id}`)
    schlossDetail.value = data; schlossDialog.value = true
  } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Detail fehlgeschlagen' }) }
}

// --- Zutrittslog je Schloss (separater Lazy-Dialog auf der Kachel) ---
const logDialog = ref(false)
const logSchloss = ref(null)
const logEntries = ref([])
const statusEvents = ref([])
const logDarfProtokoll = ref(false)
const logLoading = ref(false)
// Öffnungen (Bewegungsdaten) und Konnektivitäts-Events zeitlich verschränkt (#82).
const logItems = computed(() => {
  const zutritt = (logEntries.value || []).map(l => ({ ...l, typ: 'zutritt', key: 'z' + l.id, ts: l.lock_date }))
  const status = (statusEvents.value || []).map(e => ({ ...e, typ: 'status', key: 's' + e.id, ts: e.geaendert_am }))
  return [...zutritt, ...status].sort((a, b) => new Date(b.ts || 0) - new Date(a.ts || 0))
})
async function openSchlossLog(s) {
  logSchloss.value = s
  logEntries.value = []
  statusEvents.value = []
  logDarfProtokoll.value = false
  logLoading.value = true
  logDialog.value = true
  try {
    const { data } = await api.get(`/api/schliessanlage/schloesser/${s.id}/logs`)
    logEntries.value = data.logs || []
    statusEvents.value = data.status_events || []
    logDarfProtokoll.value = !!data.darf_protokoll
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Zutrittslog fehlgeschlagen' })
  } finally { logLoading.value = false }
}

const schlossFormDialog = ref(false)
const schlossForm = ref({})
const schlossError = ref('')
function openSchlossEdit() {
  const s = schlossDetail.value.schloss
  schlossForm.value = { id: s.id, name: s.name, standort: s.standort, abteilung_id: s.abteilung_id,
    notiz: s.notiz, aktiv: s.aktiv, version: s.version }
  schlossError.value = ''; schlossFormDialog.value = true
}
async function saveSchloss() {
  if (!schlossForm.value.name) { schlossError.value = 'Name ist erforderlich.'; return }
  saving.value = true; schlossError.value = ''
  try {
    await api.put(`/api/schliessanlage/schloesser/${schlossForm.value.id}`, {
      name: schlossForm.value.name, standort: schlossForm.value.standort || null,
      abteilung_id: schlossForm.value.abteilung_id || null, notiz: schlossForm.value.notiz || null,
      aktiv: schlossForm.value.aktiv, version: schlossForm.value.version,
    })
    schlossFormDialog.value = false; schlossDialog.value = false
    await loadSchloesser()
  } catch (e) { schlossError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen' }
  finally { saving.value = false }
}

// --- Befristete App-Öffnung ---
const appGrantDialog = ref(false)
const appGrantForm = ref({})
const appGrantError = ref('')
const users = ref([])
const userOptions = ref([])
const dauerOptionen = [
  { label: '1 Stunde', value: '1h' },
  { label: '2 Stunden', value: '2h' },
  { label: '4 Stunden', value: '4h' },
  { label: '8 Stunden', value: '8h' },
  { label: '1 Tag', value: '1d' },
  { label: '3 Tage', value: '3d' },
  { label: '1 Woche', value: '7d' },
  { label: 'unbefristet', value: 'none' },
  { label: 'konkretes Datum …', value: 'custom' },
]
const DAUER_MS = { '1h': 36e5, '2h': 72e5, '4h': 144e5, '8h': 288e5, '1d': 864e5, '3d': 2592e5, '7d': 6048e5 }

function nowLocalInput() {
  const d = new Date(); d.setSeconds(0, 0)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
function toLocalInput(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
// datetime-local (lokale Zeit) + Dauer-Preset → {vonIso, bisIso} als UTC-ISO.
function vonBisFromForm(f) {
  const vonIso = f.gueltig_von ? new Date(f.gueltig_von).toISOString() : null
  let bisIso = null
  if (f.dauer === 'custom') {
    bisIso = f.gueltig_bis_custom ? new Date(f.gueltig_bis_custom).toISOString() : null
  } else if (f.dauer !== 'none') {
    const base = f.gueltig_von ? new Date(f.gueltig_von) : new Date()
    bisIso = new Date(base.getTime() + DAUER_MS[f.dauer]).toISOString()
  }
  return { vonIso, bisIso }
}
async function loadUsers() {
  if (users.value.length) return
  try {
    const { data } = await api.get('/api/schliessanlage/users')
    users.value = data; userOptions.value = data
  } catch { users.value = []; userOptions.value = [] }
}
function filterUsers(val, update) {
  const n = (val || '').toLowerCase()
  update(() => {
    userOptions.value = n ? users.value.filter(u => u.username.toLowerCase().includes(n)) : users.value
  })
}
async function openAppGrant() {
  await loadUsers()
  appGrantForm.value = { user: null, gueltig_von: nowLocalInput(), dauer: '1d',
    gueltig_bis_custom: '', grund: '' }
  appGrantError.value = ''; appGrantDialog.value = true
}
async function saveAppGrant() {
  const f = appGrantForm.value
  if (!f.user?.id) { appGrantError.value = 'Bitte einen Benutzer auswählen.'; return }
  // Eindeutige Zeiten als UTC-ISO senden (datetime-local ist lokale Zeit ohne TZ).
  const { vonIso, bisIso } = vonBisFromForm(f)
  saving.value = true; appGrantError.value = ''
  try {
    await api.post(`/api/schliessanlage/schloesser/${schlossDetail.value.schloss.id}/app-berechtigungen`, {
      user_id: f.user.id, gueltig_von: vonIso, gueltig_bis: bisIso, grund: f.grund || null,
    })
    appGrantDialog.value = false
    await openSchloss(schlossDetail.value.schloss.id)
  } catch (e) { appGrantError.value = e.response?.data?.detail || 'Vergabe fehlgeschlagen' }
  finally { saving.value = false }
}
function revokeApp(a) {
  $q.dialog({ title: 'Berechtigung entziehen',
    message: `Befristete App-Öffnung für „${a.user_username || ('User #' + a.user_id)}" entziehen?`,
    cancel: true }).onOk(async () => {
    try {
      await api.delete(`/api/schliessanlage/app-berechtigungen/${a.id}`)
      await openSchloss(schlossDetail.value.schloss.id)
    } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Entzug fehlgeschlagen' }) }
  })
}

// --- Chip anlernen / Berechtigungen (Chip ↔ Schloss) ---
const berDialog = ref(false)
const berForm = ref({})
const berError = ref('')
const chipOptions = ref([])
const schlossOptions = ref([])
const chipLabel = (c) => (c ? `${c.bezeichnung || ('Chip #' + c.id)} (Nr. ${c.kartennummer})` : '')
function filterChips(val, update) {
  const n = (val || '').toLowerCase()
  update(() => { chipOptions.value = n ? chips.value.filter(c => chipLabel(c).toLowerCase().includes(n)) : chips.value })
}
function filterSchloesser(val, update) {
  const n = (val || '').toLowerCase()
  update(() => { schlossOptions.value = n ? schloesser.value.filter(s => (s.name || '').toLowerCase().includes(n)) : schloesser.value })
}
async function openBerAnlernenForSchloss() {
  if (!chips.value.length) await loadChips()
  chipOptions.value = chips.value
  berForm.value = { mode: 'chip', schloss_id: schlossDetail.value.schloss.id,
    schloss_name: schlossDetail.value.schloss.name, chip: null,
    gueltig_von: nowLocalInput(), dauer: 'none', gueltig_bis_custom: '' }
  berError.value = ''; berDialog.value = true
}
function openBerAnlernenForChip() {
  schlossOptions.value = schloesser.value
  const c = chipDetail.value.chip
  berForm.value = { mode: 'schloss', chip_id: c.id,
    chip_name: c.bezeichnung || ('Chip #' + c.id), schloss: null,
    gueltig_von: nowLocalInput(), dauer: 'none', gueltig_bis_custom: '' }
  berError.value = ''; berDialog.value = true
}
async function saveBer() {
  const f = berForm.value
  let chip_id, schloss_id
  if (f.mode === 'chip') {
    if (!f.chip?.id) { berError.value = 'Bitte einen Chip wählen.'; return }
    chip_id = f.chip.id; schloss_id = f.schloss_id
  } else {
    if (!f.schloss?.id) { berError.value = 'Bitte ein Schloss wählen.'; return }
    chip_id = f.chip_id; schloss_id = f.schloss.id
  }
  const { vonIso, bisIso } = vonBisFromForm(f)
  saving.value = true; berError.value = ''
  try {
    await api.post('/api/schliessanlage/berechtigungen',
      { chip_id, schloss_id, gueltig_von: vonIso, gueltig_bis: bisIso })
    berDialog.value = false
    if (f.mode === 'chip') await openSchloss(schloss_id); else await openChip(chip_id)
  } catch (e) { berError.value = e.response?.data?.detail || 'Anlernen fehlgeschlagen' }
  finally { saving.value = false }
}

const berEditDialog = ref(false)
const berEditForm = ref({})
function openBerEdit(b) {
  berEditForm.value = { id: b.id,
    name: `${b.chip_bezeichnung || ('Chip #' + b.chip_id)} @ ${b.schloss_name || ''}`.trim(),
    gueltig_von: b.gueltig_von ? toLocalInput(b.gueltig_von) : nowLocalInput(),
    dauer: b.gueltig_bis ? 'custom' : 'none',
    gueltig_bis_custom: b.gueltig_bis ? toLocalInput(b.gueltig_bis) : '' }
  berError.value = ''; berEditDialog.value = true
}
async function saveBerEdit() {
  const f = berEditForm.value
  const { vonIso, bisIso } = vonBisFromForm(f)
  saving.value = true; berError.value = ''
  try {
    await api.put(`/api/schliessanlage/berechtigungen/${f.id}`,
      { gueltig_von: vonIso, gueltig_bis: bisIso })
    berEditDialog.value = false
    await reloadOffeneDetails()
  } catch (e) { berError.value = e.response?.data?.detail || 'Ändern fehlgeschlagen' }
  finally { saving.value = false }
}
function revokeBer(b) {
  $q.dialog({ title: 'Berechtigung entziehen',
    message: `Chip „${b.chip_bezeichnung || b.kartennummer || ('#' + b.chip_id)}"`
      + ` von Schloss „${b.schloss_name || ''}" entziehen? Die IC-Karte wird vom Schloss entfernt.`,
    cancel: true, ok: { label: 'Entziehen', color: 'negative' } }).onOk(async () => {
    try {
      await api.delete(`/api/schliessanlage/berechtigungen/${b.id}`)
      await reloadOffeneDetails()
    } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Entzug fehlgeschlagen' }) }
  })
}
// Das gerade offene Detail (Schloss und/oder Chip) neu laden.
async function reloadOffeneDetails() {
  if (schlossDialog.value && schlossDetail.value.schloss) await openSchloss(schlossDetail.value.schloss.id)
  if (chipDialog.value && chipDetail.value.chip) await openChip(chipDetail.value.chip.id)
}

// --- Chip-Detail/Edit ---
const chipDialog = ref(false)
const chipDetail = ref({})
async function openChip(id) {
  try {
    const { data } = await api.get(`/api/schliessanlage/chips/${id}`)
    chipDetail.value = data; chipDialog.value = true
  } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Detail fehlgeschlagen' }) }
}
const chipFormDialog = ref(false)
const chipForm = ref({})
const chipError = ref('')
const mitglieder = ref([])
const mitgliedOptions = ref([])
const mitgliedLabel = (m) => (m
  ? `${m.nachname || ''}, ${m.vorname || ''}`.trim() + (m.mitgliedsnummer ? ` (Nr. ${m.mitgliedsnummer})` : '')
  : '')
async function loadMitglieder() {
  if (mitglieder.value.length) return
  try {
    const { data } = await api.get('/api/schliessanlage/mitglieder')
    mitglieder.value = data; mitgliedOptions.value = data
  } catch { mitglieder.value = []; mitgliedOptions.value = [] }
}
function filterMitglieder(val, update) {
  const n = (val || '').toLowerCase()
  update(() => {
    mitgliedOptions.value = n
      ? mitglieder.value.filter(m => mitgliedLabel(m).toLowerCase().includes(n))
      : mitglieder.value
  })
}
async function openChipCreate() {
  await loadMitglieder()
  chipForm.value = { id: null, kartennummer: '', bezeichnung: '', mitglied_id: null,
    aufbewahrungsort: '', status: 'aktiv' }
  chipError.value = ''; chipFormDialog.value = true
}
async function openChipEdit() {
  await loadMitglieder()
  const c = chipDetail.value.chip
  chipForm.value = { id: c.id, kartennummer: c.kartennummer, bezeichnung: c.bezeichnung,
    mitglied_id: c.mitglied_id, aufbewahrungsort: c.aufbewahrungsort, status: c.status, version: c.version }
  chipError.value = ''; chipFormDialog.value = true
}
async function saveChip() {
  if (!chipForm.value.kartennummer) { chipError.value = 'Kartennummer ist erforderlich.'; return }
  saving.value = true; chipError.value = ''
  const payload = {
    bezeichnung: chipForm.value.bezeichnung || null,
    mitglied_id: chipForm.value.mitglied_id || null,
    aufbewahrungsort: chipForm.value.aufbewahrungsort || null,
    status: chipForm.value.status || 'aktiv',
  }
  try {
    if (chipForm.value.id) {
      await api.put(`/api/schliessanlage/chips/${chipForm.value.id}`, { ...payload, version: chipForm.value.version })
    } else {
      await api.post('/api/schliessanlage/chips', { ...payload, kartennummer: chipForm.value.kartennummer })
    }
    chipFormDialog.value = false; chipDialog.value = false
    await loadChips()
  } catch (e) { chipError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen' }
  finally { saving.value = false }
}
function deleteChip() {
  const c = chipDetail.value.chip
  $q.dialog({ title: 'Chip löschen', message: `Chip „${c.bezeichnung || c.kartennummer}" löschen?`, cancel: true })
    .onOk(async () => {
      try {
        await api.delete(`/api/schliessanlage/chips/${c.id}`)
        chipDialog.value = false; await loadChips()
      } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Löschen fehlgeschlagen' }) }
    })
}
</script>
