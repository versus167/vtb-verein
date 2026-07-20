<template>
  <q-page class="q-pa-md">
    <!-- Kopf: Titel + Team-Auswahl -->
    <div class="row items-center q-mb-sm q-gutter-sm">
      <div class="text-h5">Teamtresor</div>
      <q-space />
      <q-select
        v-if="teams.length > 1"
        v-model="selectedTeamId"
        :options="teamOptions"
        emit-value map-options dense outlined
        style="min-width: 200px"
        label="Mannschaft"
      />
    </div>

    <div v-if="!teams.length && geladen" class="text-grey q-mt-lg">
      Kein Teamtresor verfügbar — du stehst in keinem Kader mit Teamtresor.
    </div>

    <!-- Einschalt-Karte: Team ohne Deckel, nur für Kader-Verwalter sichtbar -->
    <q-card v-if="aktuellesTeam && !aktuellesTeam.deckel" class="vtb-karte q-mt-md">
      <q-card-section class="column items-start q-gutter-sm">
        <div class="text-subtitle1 text-weight-bold">
          {{ aktuellesTeam.mannschaft_name }} hat noch keinen Teamtresor
        </div>
        <div class="text-caption text-grey">
          Als Übungsleiter/Betreuer kannst du die mannschaftsinterne Strichliste hier
          einschalten. Gruppen, Artikel und Preise pflegst du danach im Katalog.
        </div>
        <q-btn color="primary" unelevated no-caps icon="sports_bar"
          :label="`Teamtresor für ${aktuellesTeam.mannschaft_name} aktivieren`"
          :loading="saving" @click="einschalten" />
      </q-card-section>
    </q-card>

    <template v-if="deckel">
      <!-- Status-Zeile: Rolle / Deaktiviert (Beträge stehen als Kacheln im Tresen) -->
      <div v-if="istWart || !deckel.aktiv" class="row items-center q-gutter-xs q-mb-md">
        <span v-if="istVerwalter" class="vtb-pill">Verwalter</span>
        <span v-else-if="istWart" class="vtb-pill">Wart</span>
        <span v-if="!deckel.aktiv" class="vtb-pill vtb-pill--warn">deaktiviert</span>
      </div>

      <q-banner v-if="!deckel.aktiv" class="vtb-warnung q-mb-md" rounded dense>
        <template #avatar><q-icon name="pause_circle" size="26px" /></template>
        Der Teamtresor ist deaktiviert — Buchen ist gerade nicht möglich.
      </q-banner>

      <q-tabs v-model="tab" align="left" class="q-mb-md vtb-tabs" no-caps inline-label>
        <q-tab name="tresen" icon="sports_bar" label="Tresen" />
        <q-tab name="salden" icon="leaderboard" label="Salden" />
        <q-tab v-if="istWart" name="katalog" icon="menu_book" label="Katalog" />
        <q-tab v-if="istWart" name="verwalten" icon="settings" label="Verwalten" />
      </q-tabs>

      <!-- ====================== Tresen ====================== -->
      <div v-if="tab === 'tresen'">
        <div v-if="deckel.mein_mitglied_id == null" class="text-grey q-mb-md">
          Du stehst nicht im aktiven Kader dieser Mannschaft und kannst hier nicht
          selbst buchen.
        </div>

        <template v-for="g in tresenGruppen" :key="g.name">
          <div class="text-subtitle2 q-mt-sm q-mb-xs">
            {{ g.name }}
            <span v-if="g.verkaeufer" class="text-caption text-grey">
              · verkauft {{ g.verkaeufer }}</span>
          </div>
          <div v-for="a in g.artikel" :key="a.id"
            class="tt-tresen-row row no-wrap items-stretch q-mb-sm">
            <!-- Tap = 1× buchen; darunter die 24h-Strichliste -->
            <q-btn class="tt-tresen-btn col" unelevated no-caps color="primary" align="left"
              :disable="!deckel.aktiv || deckel.mein_mitglied_id == null || saving"
              @click="bucheKonsum(a)">
              <div class="full-width row items-center no-wrap">
                <div class="col text-left">
                  <div class="text-weight-bold tt-tresen-name">{{ a.name }}</div>
                  <div v-if="a.mein_24h_anzahl" class="tt-tally row items-center no-wrap q-mt-xs">
                    <svg v-for="(k, i) in tallyBundles(a.mein_24h_anzahl)" :key="i"
                      class="tt-tally-svg" width="24" height="20" viewBox="0 0 24 20">
                      <line v-for="s in Math.min(k, 4)" :key="s"
                        :x1="s * 4" y1="2" :x2="s * 4" y2="18" />
                      <line v-if="k === 5" x1="2" y1="17" x2="18" y2="3" />
                    </svg>
                  </div>
                </div>
                <div class="text-weight-bold q-ml-sm">{{ fmtEuro(a.preis) }}</div>
              </div>
            </q-btn>
            <!-- Undo-Zone: letzten eigenen Strich dieses Artikels zurücknehmen -->
            <q-btn class="tt-tresen-del" flat :disable="!a.mein_24h_anzahl || saving"
              @click.stop="undoArtikel(a)">
              <q-icon name="delete" :color="a.mein_24h_anzahl ? 'negative' : 'grey-5'" />
              <q-tooltip>Letzten Strich zurücknehmen</q-tooltip>
            </q-btn>
          </div>
        </template>
        <div v-if="!deckel.artikel.length" class="text-grey q-mt-md">
          Noch keine Artikel im Katalog<template v-if="istWart"> — lege sie im Tab
          „Katalog" an</template>.
        </div>

        <!-- Kacheln: 24h-Deckel + mein Gesamtsaldo -->
        <div v-if="deckel.mein_mitglied_id != null" class="row q-col-gutter-sm q-mt-md">
          <div class="col-6">
            <q-card flat bordered class="text-center q-pa-sm">
              <div class="text-overline text-grey">24h Deckel</div>
              <div class="text-h6 text-positive">{{ fmtEuro(deckel.mein_24h_summe) }}</div>
            </q-card>
          </div>
          <div class="col-6">
            <q-card flat bordered class="text-center q-pa-sm">
              <div class="text-overline text-grey">Gesamtsaldo</div>
              <div class="text-h6"
                :class="Number(deckel.mein_saldo) < 0 ? 'text-negative' : 'text-positive'">
                {{ fmtEuro(deckel.mein_saldo) }}
              </div>
            </q-card>
          </div>
        </div>

        <!-- Zur Rangliste (Salden-Tab) -->
        <q-card flat bordered class="q-mt-sm cursor-pointer" @click="tab = 'salden'">
          <q-item>
            <q-item-section avatar><q-icon name="leaderboard" color="primary" /></q-item-section>
            <q-item-section class="text-weight-medium">Aktuelle Tabelle</q-item-section>
            <q-item-section side><q-icon name="chevron_right" /></q-item-section>
          </q-item>
        </q-card>

        <!-- Zahlung an … (Zahlungsempfänger + Zahlwege aus den Stammdaten) -->
        <q-card v-if="hatZahlwege" class="vtb-karte q-mt-lg">
          <q-card-section>
            <div class="text-overline text-grey">
              Zahlung an {{ deckel.zahlungsempfaenger_name || 'das Team' }}
            </div>
            <q-list dense>
              <q-item v-if="deckel.zahlweg_wero" clickable tag="a"
                :href="deckel.zahlweg_wero" target="_blank" rel="noopener">
                <q-item-section avatar><q-icon name="account_balance" color="primary" /></q-item-section>
                <q-item-section>
                  <q-item-label>WERO Zahlung</q-item-label>
                  <q-item-label caption>{{ deckel.zahlweg_wero }}</q-item-label>
                </q-item-section>
                <q-item-section side><q-icon name="open_in_new" size="16px" /></q-item-section>
              </q-item>
              <q-item v-if="deckel.zahlweg_iban" clickable @click="copyIban">
                <q-item-section avatar><q-icon name="account_balance_wallet" color="primary" /></q-item-section>
                <q-item-section>
                  <q-item-label>Überweisung (IBAN kopieren)</q-item-label>
                  <q-item-label caption>{{ deckel.zahlweg_iban }}</q-item-label>
                </q-item-section>
                <q-item-section side><q-icon name="content_copy" size="16px" /></q-item-section>
              </q-item>
              <q-item v-if="deckel.zahlweg_paypal" clickable tag="a"
                :href="paypalUrl" target="_blank" rel="noopener">
                <q-item-section avatar><q-icon name="payments" color="primary" /></q-item-section>
                <q-item-section>
                  <q-item-label>PayPal Zahlung</q-item-label>
                  <q-item-label caption>{{ deckel.zahlweg_paypal }}</q-item-label>
                </q-item-section>
                <q-item-section side><q-icon name="open_in_new" size="16px" /></q-item-section>
              </q-item>
            </q-list>
            <div class="text-caption text-grey q-mt-xs">
              Gezahlt gilt erst, wenn der Wart die Zahlung gebucht hat.
            </div>
          </q-card-section>
        </q-card>

        <template v-if="meineBuchungen.length">
          <div class="text-subtitle2 q-mt-lg q-mb-sm">Meine letzten Buchungen</div>
          <q-list bordered separator class="rounded-borders">
            <q-item v-for="b in meineBuchungen" :key="b.id">
              <q-item-section>
                <q-item-label>{{ buchungText(b) }}</q-item-label>
                <q-item-label caption>{{ fmtDateTime(b.created_at) }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row items-center q-gutter-sm">
                  <span :class="Number(b.betrag) < 0 ? 'text-negative' : 'text-positive'">
                    {{ fmtEuro(b.betrag) }}
                  </span>
                  <q-btn v-if="b.typ === 'konsum'" flat round dense size="sm"
                    icon="undo" :disable="saving" @click="storno(b)">
                    <q-tooltip>Fehltipp? Buchung stornieren</q-tooltip>
                  </q-btn>
                </div>
              </q-item-section>
            </q-item>
          </q-list>
        </template>
      </div>

      <!-- ====================== Salden ====================== -->
      <div v-if="tab === 'salden'">
        <div class="row items-center q-mb-md">
          <span class="vtb-pill">
            <q-icon name="groups" size="13px" /> Team-Saldo: {{ fmtEuro(teamSaldo) }}
          </span>
        </div>
        <q-list bordered separator class="rounded-borders">
          <q-item v-for="s in salden" :key="s.mitglied_id">
            <q-item-section>
              <q-item-label :class="{ 'text-weight-bold': s.mitglied_id === deckel.mein_mitglied_id }">
                {{ s.mitglied_name }}
              </q-item-label>
              <q-item-label caption>{{ s.buchungen }} Buchungen</q-item-label>
            </q-item-section>
            <q-item-section side>
              <span class="text-weight-bold"
                :class="Number(s.saldo) < 0 ? 'text-negative' : 'text-positive'">
                {{ fmtEuro(s.saldo) }}
              </span>
            </q-item-section>
          </q-item>
        </q-list>
        <div v-if="!salden.length" class="text-grey q-mt-md">Noch keine Buchungen.</div>
      </div>

      <!-- ====================== Katalog (Wart) ====================== -->
      <div v-if="tab === 'katalog' && istWart">
        <div class="row q-mb-md justify-end">
          <q-btn outline color="primary" no-caps rounded icon="create_new_folder"
            label="Neue Gruppe" @click="openGruppeDialog()" />
        </div>

        <q-card v-for="g in katalogGruppen" :key="g.key" flat bordered
          class="tt-gruppe q-mb-md">
          <!-- Dunkle Kopfzeile: Gruppen-Schalter, Name, Verkäufer, bearbeiten, Artikel + -->
          <div class="tt-gruppe__head row items-center no-wrap q-px-sm q-py-xs">
            <q-toggle v-if="g.gruppe" :model-value="!!g.gruppe.aktiv" color="primary"
              dense :disable="saving" @update:model-value="v => toggleGruppeAktiv(g.gruppe, v)">
              <q-tooltip>Gruppe {{ g.gruppe.aktiv ? 'aktiv' : 'inaktiv' }}</q-tooltip>
            </q-toggle>
            <div v-else class="tt-gruppe__spacer" />
            <div class="text-weight-bold text-white ellipsis q-ml-xs">{{ g.name }}</div>
            <q-space />
            <q-select v-if="g.gruppe" :model-value="g.gruppe.verkaeufer_mitglied_id"
              :options="verkaeuferOptionen" emit-value map-options dense dark outlined
              options-dense hide-bottom-space class="tt-verkaeufer" :disable="saving"
              @update:model-value="v => setGruppeVerkaeufer(g.gruppe, v)" />
            <q-btn v-if="g.gruppe" flat round dense color="white" icon="edit"
              @click="openGruppeDialog(g.gruppe)">
              <q-tooltip>Gruppe umbenennen / Sortierung</q-tooltip>
            </q-btn>
            <q-btn v-if="g.gruppe" flat round dense color="white" icon="delete"
              @click="deleteGruppe(g.gruppe)">
              <q-tooltip>Gruppe löschen (muss leer sein)</q-tooltip>
            </q-btn>
            <q-btn flat round dense color="white" icon="add"
              @click="openArtikelDialog(null, g.gruppe?.id ?? null)">
              <q-tooltip>Artikel hinzufügen</q-tooltip>
            </q-btn>
          </div>

          <!-- Artikelzeilen: Schalter, Name (inline), Preis (inline), löschen -->
          <div v-for="a in g.artikel" :key="a.id"
            class="tt-artikel-row row items-center no-wrap q-px-sm q-py-xs q-gutter-sm">
            <q-toggle :model-value="!!a.aktiv" color="primary" dense :disable="saving"
              @update:model-value="v => toggleArtikelAktiv(a, v)">
              <q-tooltip>{{ a.aktiv ? 'aktiv' : 'inaktiv' }}</q-tooltip>
            </q-toggle>
            <q-input :model-value="a.name" dense outlined class="col" :disable="saving"
              @change="v => renameArtikel(a, v)" />
            <q-input :model-value="fmtPreisInput(a.preis)" dense outlined
              inputmode="decimal" class="tt-preis" input-class="text-right"
              :disable="saving" @change="v => repriceArtikel(a, v)" />
            <q-btn flat round dense color="negative" icon="delete"
              :disable="saving" @click="deleteArtikel(a)" />
          </div>
          <div v-if="!g.artikel.length" class="q-px-sm q-py-sm text-caption text-grey">
            keine Artikel — über das <q-icon name="add" size="14px" /> oben hinzufügen
          </div>
        </q-card>

        <div v-if="!katalog.length && !gruppen.length" class="text-grey q-mt-md">
          Noch keine Gruppen/Artikel angelegt — lege zuerst eine Gruppe an.
        </div>
      </div>

      <!-- ====================== Verwalten (Wart/Verwalter) ====================== -->
      <div v-if="tab === 'verwalten' && istWart">
        <!-- Club-Saldo + Mitglieder-Transaktionen (An-/Verkauf, Zahlung) -->
        <q-card flat class="tt-club-head q-mb-sm">
          <div class="row items-center no-wrap q-pa-sm">
            <q-avatar size="34px" color="grey-8" text-color="white" icon="groups" />
            <div class="text-weight-bold text-white q-ml-sm">Club</div>
            <q-space />
            <div class="text-weight-bold"
              :class="Number(deckel.team_saldo) < 0 ? 'text-red-4' : 'text-green-4'">
              {{ fmtEuro(deckel.team_saldo) }}
            </div>
          </div>
        </q-card>

        <q-input v-model="mitgliedSuche" dense outlined class="q-mb-sm"
          placeholder="Mitglied suchen…" clearable>
          <template #prepend><q-icon name="search" /></template>
        </q-input>

        <q-card v-for="m in mitgliederGefiltert" :key="m.mitglied_id" flat bordered
          class="q-mb-sm">
          <div class="row items-center no-wrap q-pa-sm q-gutter-sm">
            <q-avatar size="40px" text-color="white" class="text-weight-bold"
              :style="{ background: avatarColor(m.name) }">{{ initialen(m.name) }}</q-avatar>
            <div class="col" style="min-width: 0">
              <div class="text-weight-medium ellipsis">{{ m.name }}</div>
              <div class="text-caption text-weight-medium"
                :class="m.saldo < 0 ? 'text-negative' : 'text-positive'">
                {{ fmtEuro(m.saldo) }}
              </div>
            </div>
            <q-btn round unelevated color="deep-purple-5" icon="shopping_bag"
              :disable="!deckel.aktiv || saving" @click="openKaufDialog(m)">
              <q-tooltip>An-/Verkauf buchen</q-tooltip>
            </q-btn>
            <q-btn round unelevated color="primary" icon="payments"
              :disable="!deckel.aktiv || saving" @click="openZahlungDialog(m)">
              <q-tooltip>Zahlung buchen</q-tooltip>
            </q-btn>
          </div>
        </q-card>
        <div v-if="!mitgliederGefiltert.length" class="text-grey q-mb-md">
          Keine Mitglieder gefunden.
        </div>

        <div class="text-subtitle2 q-mt-lg q-mb-sm">Alle Buchungen</div>
        <q-list bordered separator class="rounded-borders q-mb-lg">
          <q-item v-for="b in alleBuchungen" :key="b.id">
            <q-item-section>
              <q-item-label>{{ b.mitglied_name }} — {{ buchungText(b) }}</q-item-label>
              <q-item-label caption>
                {{ fmtDateTime(b.created_at) }} · gebucht von {{ b.created_by }}
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <div class="row items-center q-gutter-sm">
                <span :class="Number(b.betrag) < 0 ? 'text-negative' : 'text-positive'">
                  {{ fmtEuro(b.betrag) }}
                </span>
                <q-btn flat round dense size="sm" icon="delete" color="negative"
                  :disable="saving" @click="storno(b)">
                  <q-tooltip>Stornieren{{ b.paar_ref ? ' (ganzes Paar)' : '' }}{{
                    b.typ === 'beitrag' ? ' — Beitrag wird damit erlassen' : '' }}</q-tooltip>
                </q-btn>
              </div>
            </q-item-section>
          </q-item>
        </q-list>
        <div v-if="!alleBuchungen.length" class="text-grey q-mb-lg">Noch keine Buchungen.</div>

        <!-- Nur Kader-Verwalter: Warte, Befreiungen, Stammdaten -->
        <template v-if="istVerwalter">
          <div class="text-subtitle2 q-mb-sm">Warte</div>
          <q-list bordered separator class="rounded-borders q-mb-md">
            <q-item v-for="w in warte" :key="w.mitglied_id">
              <q-item-section>{{ w.mitglied_name }}</q-item-section>
              <q-item-section side>
                <q-btn flat round dense size="sm" icon="close" color="negative"
                  @click="removeWart(w)">
                  <q-tooltip>Wart-Berechtigung entziehen</q-tooltip>
                </q-btn>
              </q-item-section>
            </q-item>
          </q-list>
          <div class="row items-center q-gutter-sm q-mb-lg">
            <q-select v-model="neuerWart" :options="wartKandidaten" emit-value map-options
              dense outlined style="min-width: 220px" label="Mitglied zum Wart ernennen" />
            <q-btn color="primary" unelevated no-caps label="Ernennen"
              :disable="neuerWart == null" @click="addWart" />
          </div>

          <template v-if="deckel.beitrag">
            <div class="text-subtitle2 q-mb-sm">
              Beitragsbefreiungen
              <span class="text-caption text-grey">
                (Monatsbeitrag {{ fmtEuro(deckel.beitrag) }} seit {{ deckel.beitrag_ab }})</span>
            </div>
            <q-list bordered separator class="rounded-borders q-mb-md">
              <q-item v-for="bf in befreiungen" :key="bf.mitglied_id">
                <q-item-section>{{ bf.mitglied_name }}</q-item-section>
                <q-item-section side>
                  <q-btn flat round dense size="sm" icon="close" color="negative"
                    @click="removeBefreiung(bf)">
                    <q-tooltip>Befreiung aufheben</q-tooltip>
                  </q-btn>
                </q-item-section>
              </q-item>
              <q-item v-if="!befreiungen.length">
                <q-item-section class="text-caption text-grey">niemand befreit</q-item-section>
              </q-item>
            </q-list>
            <div class="row items-center q-gutter-sm q-mb-lg">
              <q-select v-model="neueBefreiung" :options="befreiungKandidaten" emit-value
                map-options dense outlined style="min-width: 220px"
                label="Mitglied vom Beitrag befreien" />
              <q-btn color="primary" unelevated no-caps label="Befreien"
                :disable="neueBefreiung == null" @click="addBefreiung" />
            </div>
          </template>

          <div class="text-subtitle2 q-mb-sm">Stammdaten</div>
          <div class="row q-gutter-sm">
            <q-btn outline no-caps color="primary" icon="edit" label="Stammdaten bearbeiten"
              @click="openStammdatenDialog" />
            <q-btn outline no-caps color="negative" icon="power_settings_new"
              label="Teamtresor ausschalten" @click="ausschalten" />
          </div>
        </template>
      </div>
    </template>

    <!-- ====================== Dialoge ====================== -->
    <q-dialog v-model="gruppeDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card style="min-width: 320px">
        <q-card-section class="text-h6">
          {{ gruppeForm.id ? 'Gruppe bearbeiten' : 'Neue Gruppe' }}
        </q-card-section>
        <q-card-section class="q-gutter-sm">
          <q-input v-model="gruppeForm.name" label="Name * (z. B. Getränke)" dense outlined autofocus />
          <q-select v-model="gruppeForm.verkaeufer" :options="verkaeuferOptionen"
            emit-value map-options dense outlined label="Verkäufer" />
          <q-input v-model.number="gruppeForm.sortierung" label="Sortierung" dense outlined
            type="number" />
          <q-toggle v-model="gruppeForm.aktiv" label="Aktiv (am Tresen sichtbar)" />
          <div v-if="dialogError" class="text-negative text-caption">{{ dialogError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Abbrechen" v-close-popup />
          <q-btn color="primary" unelevated no-caps label="Speichern"
            :loading="saving" @click="saveGruppe" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="artikelDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card style="min-width: 320px">
        <q-card-section class="text-h6">
          {{ artikelForm.id ? 'Artikel bearbeiten' : 'Neuer Artikel' }}
        </q-card-section>
        <q-card-section class="q-gutter-sm">
          <q-input v-model="artikelForm.name" label="Name *" dense outlined autofocus />
          <q-input :model-value="fmtPreisInput(artikelForm.preis)" label="Preis (€) *"
            dense outlined inputmode="decimal"
            @change="v => { artikelForm.preis = parsePreis(v) }" />
          <q-select v-model="artikelForm.gruppe" :options="gruppeOptionen" emit-value
            map-options dense outlined label="Gruppe" />
          <q-input v-model.number="artikelForm.sortierung" label="Sortierung" dense outlined
            type="number" />
          <q-toggle v-model="artikelForm.aktiv" label="Aktiv (am Tresen sichtbar)" />
          <div v-if="dialogError" class="text-negative text-caption">{{ dialogError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Abbrechen" v-close-popup />
          <q-btn color="primary" unelevated no-caps label="Speichern"
            :loading="saving" @click="saveArtikel" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="zahlungDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card style="min-width: 340px">
        <q-card-section class="row items-center q-gutter-sm">
          <q-avatar v-if="zahlungForm.name" size="34px" text-color="white"
            class="text-weight-bold" :style="{ background: avatarColor(zahlungForm.name) }">
            {{ initialen(zahlungForm.name) }}</q-avatar>
          <div class="text-h6">Zahlung — {{ zahlungForm.name || '' }}</div>
        </q-card-section>
        <q-card-section class="q-gutter-sm">
          <div class="text-caption text-grey">
            Geld wurde real übergeben: Der Deckel des Zahlers steigt, der des
            Empfängers sinkt (er hält das Geld).
          </div>
          <q-select v-model="zahlungForm.von" :options="mitgliedOptionen" emit-value
            map-options dense outlined label="Zahler *" />
          <q-select v-model="zahlungForm.an" :options="mitgliedOptionen" emit-value
            map-options dense outlined label="Empfänger *" />
          <q-select v-model="zahlungForm.methode" :options="methodeOptionen" emit-value
            map-options dense outlined label="Methode" />
          <q-input :model-value="fmtPreisInput(zahlungForm.betrag)" label="Betrag (€) *"
            dense outlined inputmode="decimal"
            @change="v => { zahlungForm.betrag = parsePreis(v) }" />
          <q-input v-model="zahlungForm.datum" label="Datum" dense outlined
            type="datetime-local" />
          <q-input v-model="zahlungForm.notiz" label="Notiz" dense outlined />
          <div v-if="dialogError" class="text-negative text-caption">{{ dialogError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Abbrechen" v-close-popup />
          <q-btn color="primary" unelevated no-caps label="Verbuchen"
            :loading="saving" @click="saveZahlung" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="kaufDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card style="min-width: 340px">
        <q-card-section class="row items-center q-gutter-sm">
          <q-avatar v-if="kaufForm.name" size="34px" text-color="white"
            class="text-weight-bold" :style="{ background: avatarColor(kaufForm.name) }">
            {{ initialen(kaufForm.name) }}</q-avatar>
          <div class="text-h6">An-/Verkauf — {{ kaufForm.name || '' }}</div>
        </q-card-section>
        <q-card-section class="q-gutter-sm">
          <q-btn-toggle v-model="kaufForm.verkauft" no-caps unelevated spread
            toggle-color="primary" :options="[
              { label: 'kauft von', value: false },
              { label: 'verkauft an', value: true }]" />
          <q-select v-model="kaufForm.gegen" :options="gegenkontoOptionen" emit-value
            map-options dense outlined label="Gegenkonto" />
          <q-input :model-value="fmtPreisInput(kaufForm.betrag)" label="Betrag (€) *"
            dense outlined inputmode="decimal"
            @change="v => { kaufForm.betrag = parsePreis(v) }" />
          <q-input v-model="kaufForm.datum" label="Datum" dense outlined
            type="datetime-local" />
          <q-input v-model="kaufForm.notiz" label="Notiz" dense outlined />
          <div class="text-caption text-grey">{{ kaufHinweis }}</div>
          <div v-if="dialogError" class="text-negative text-caption">{{ dialogError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Abbrechen" v-close-popup />
          <q-btn color="primary" unelevated no-caps label="Verbuchen"
            :loading="saving" @click="saveKauf" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="stammdatenDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card style="min-width: 340px">
        <q-card-section class="text-h6">Teamtresor bearbeiten</q-card-section>
        <q-card-section class="q-gutter-sm">
          <q-input v-model="stammdatenForm.name" label="Name *" dense outlined autofocus />
          <q-toggle v-model="stammdatenForm.aktiv" label="Aktiv (Buchen möglich)" />
          <q-input v-model.number="stammdatenForm.beitrag" dense outlined type="number"
            step="0.50" min="0" label="Mannschaftsbeitrag €/Monat (leer = keiner)" />
          <div class="text-overline text-grey q-mt-sm">Zahlungsempfänger</div>
          <q-select v-model="stammdatenForm.zahlungsempfaenger" :options="verkaeuferOptionen"
            emit-value map-options dense outlined label="Ausgleichszahlungen an" />
          <q-input v-model="stammdatenForm.zahlweg_iban" label="IBAN" dense outlined />
          <q-input v-model="stammdatenForm.zahlweg_wero" label="WERO-Link" dense outlined />
          <q-input v-model="stammdatenForm.zahlweg_paypal" label="PayPal.me-Link" dense outlined />
          <div v-if="dialogError" class="text-negative text-caption">{{ dialogError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Abbrechen" v-close-popup />
          <q-btn color="primary" unelevated no-caps label="Speichern"
            :loading="saving" @click="saveStammdaten" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
defineOptions({ name: 'TeamtresorPage' })

import { ref, computed, watch, onMounted } from 'vue'
import { useQuasar, copyToClipboard } from 'quasar'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'

const $q = useQuasar()
const BASE = '/api/clubdeckel'

const geladen = ref(false)
const saving = ref(false)
const teams = ref([])
const selectedTeamId = ref(null)
const deckel = ref(null)
const tab = ref('tresen')

const meineBuchungen = ref([])
const salden = ref([])
const teamSaldo = ref(0)
const katalog = ref([])
const gruppen = ref([])
const alleBuchungen = ref([])
const warte = ref([])
const befreiungen = ref([])
const kader = ref([])

const dialogError = ref('')
const gruppeDialog = ref(false)
const gruppeForm = ref({})
const artikelDialog = ref(false)
const artikelForm = ref({})
const zahlungDialog = ref(false)
const zahlungForm = ref({})
const kaufDialog = ref(false)
const kaufForm = ref({})
const stammdatenDialog = ref(false)
const stammdatenForm = ref({})
const neuerWart = ref(null)
const neueBefreiung = ref(null)
const mitgliedSuche = ref('')

const methodeOptionen = [
  { label: 'bar', value: 'bar' },
  { label: 'PayPal', value: 'paypal' },
  { label: 'Überweisung', value: 'ueberweisung' },
]

const teamOptions = computed(() =>
  teams.value.map(t => ({ label: t.mannschaft_name, value: t.mannschaft_id })),
)
const aktuellesTeam = computed(() =>
  teams.value.find(t => t.mannschaft_id === selectedTeamId.value) || null,
)
const istWart = computed(() =>
  ['wart', 'verwalten'].includes(deckel.value?.zugriff),
)
const istVerwalter = computed(() => deckel.value?.zugriff === 'verwalten')

const hatZahlwege = computed(() => {
  const d = deckel.value
  return d && (d.zahlweg_iban || d.zahlweg_wero || d.zahlweg_paypal)
})
const paypalUrl = computed(() => {
  const p = deckel.value?.zahlweg_paypal || ''
  return p.startsWith('http') ? p : `https://${p}`
})

// Tresen: aktive Artikel nach Gruppe (Reihenfolge kommt sortiert vom Backend)
const tresenGruppen = computed(() => {
  const result = []
  for (const a of (deckel.value?.artikel || [])) {
    const name = a.gruppe_name || 'Angebot'
    let g = result.find(x => x.name === name)
    if (!g) {
      g = { name, verkaeufer: a.verkaeufer_name || null, artikel: [] }
      result.push(g)
    }
    g.artikel.push(a)
  }
  return result
})

// Katalog: alle Artikel (auch inaktive) nach Gruppe, plus leere Gruppen
const katalogGruppen = computed(() => {
  const result = gruppen.value.map(g => ({
    key: `g${g.id}`, name: g.name, gruppe: g, artikel: [],
  }))
  const ohne = { key: 'ohne', name: 'Ohne Gruppe (Team verkauft)', gruppe: null, artikel: [] }
  for (const a of katalog.value) {
    const g = result.find(x => x.gruppe?.id === a.gruppe_id)
    ;(g || ohne).artikel.push(a)
  }
  if (ohne.artikel.length) result.push(ohne)
  return result
})

const gruppeOptionen = computed(() => [
  { label: 'Ohne Gruppe (Team verkauft)', value: null },
  ...gruppen.value.map(g => ({
    label: `${g.name} (${g.verkaeufer_name || 'Team'})`, value: g.id,
  })),
])

const verkaeuferOptionen = computed(() => [
  { label: 'Team', value: null },
  ...kader.value.map(k => ({ label: k.name, value: k.mitglied_id })),
])

// Zahlungs-/Einkaufs-Ziele: aktiver Kader + Ex-Mitglieder mit Restsaldo
const mitgliedOptionen = computed(() => {
  const opts = kader.value.map(k => ({ label: k.name, value: k.mitglied_id }))
  const bekannt = new Set(opts.map(o => o.value))
  for (const s of salden.value) {
    if (!bekannt.has(s.mitglied_id)) {
      opts.push({ label: `${s.mitglied_name} (nicht mehr im Kader)`, value: s.mitglied_id })
    }
  }
  return opts.sort((a, b) => a.label.localeCompare(b.label))
})

// Wart-Transaktionsliste: aktiver Kader + Ex-Mitglieder mit Restsaldo, mit Saldo
const mitgliederListe = computed(() => {
  const saldoMap = new Map(salden.value.map(s => [s.mitglied_id, Number(s.saldo)]))
  const list = []
  const seen = new Set()
  for (const k of kader.value) {
    list.push({ mitglied_id: k.mitglied_id, name: k.name,
      saldo: saldoMap.get(k.mitglied_id) || 0 })
    seen.add(k.mitglied_id)
  }
  for (const s of salden.value) {
    if (!seen.has(s.mitglied_id)) {
      list.push({ mitglied_id: s.mitglied_id, name: `${s.mitglied_name} (Ex)`,
        saldo: Number(s.saldo) })
    }
  }
  return list.sort((a, b) => a.name.localeCompare(b.name))
})

const mitgliederGefiltert = computed(() => {
  const q = (mitgliedSuche.value || '').trim().toLowerCase()
  return q ? mitgliederListe.value.filter(m => m.name.toLowerCase().includes(q))
    : mitgliederListe.value
})

const gegenkontoOptionen = computed(() => [
  { label: 'Club (Team)', value: null },
  ...mitgliederListe.value
    .filter(m => m.mitglied_id !== kaufForm.value.mitglied)
    .map(m => ({ label: m.name, value: m.mitglied_id })),
])

const kaufHinweis = computed(() => {
  const gegen = kaufForm.value.gegen == null ? 'dem Team'
    : (mitgliederListe.value.find(m => m.mitglied_id === kaufForm.value.gegen)?.name || 'dem Mitglied')
  const name = kaufForm.value.name || 'Das Mitglied'
  return kaufForm.value.verkauft
    ? `${name} verkauft an ${gegen} → Gutschrift auf seinen Deckel.`
    : `${name} kauft von ${gegen} → Belastung auf seinen Deckel.`
})

function initialen(name) {
  const teile = String(name || '').replace(/\(.*\)/, '').trim().split(/\s+/)
  return ((teile[0]?.[0] || '') +
    (teile.length > 1 ? teile[teile.length - 1][0] : '')).toUpperCase() || '?'
}

function avatarColor(name) {
  let h = 0
  for (const c of String(name || '')) h = (h * 31 + c.charCodeAt(0)) % 360
  return `hsl(${h}, 42%, 52%)`
}

function jetztLocal() {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

const wartKandidaten = computed(() =>
  kader.value.filter(k => !k.ist_wart)
    .map(k => ({ label: k.name, value: k.mitglied_id })),
)
const befreiungKandidaten = computed(() => {
  const befreit = new Set(befreiungen.value.map(b => b.mitglied_id))
  return kader.value.filter(k => !befreit.has(k.mitglied_id))
    .map(k => ({ label: k.name, value: k.mitglied_id }))
})

function fmtEuro(v) {
  return Number(v ?? 0).toLocaleString('de-DE',
    { style: 'currency', currency: 'EUR' })
}

// Preisfeld ohne Spinner: als Text mit zwei Nachkommastellen anzeigen (deutsches
// Komma) und beim Parsen Komma wie Punkt akzeptieren.
function fmtPreisInput(v) {
  const n = Number(v)
  return Number.isFinite(n) && v != null && v !== '' ? n.toFixed(2).replace('.', ',') : ''
}

function parsePreis(s) {
  if (s == null || String(s).trim() === '') return NaN
  let t = String(s).trim().replace(/\s/g, '')
  const hasKomma = t.includes(',')
  const hasPunkt = t.includes('.')
  if (hasKomma && hasPunkt) {
    // Das letzte Trennzeichen ist das Dezimalzeichen, der Rest Tausender.
    if (t.lastIndexOf(',') > t.lastIndexOf('.')) t = t.replace(/\./g, '').replace(',', '.')
    else t = t.replace(/,/g, '')
  } else if (hasKomma) {
    t = t.replace(',', '.')
  }
  const n = Number(t)
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : NaN
}

function fmtDateTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('de-DE',
    { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// Strichliste als Fünfer-Bündel: [5,5,2] für 12 (jedes 5er-Bündel = vier Striche
// + Querstrich, gezeichnet als SVG im Template).
function tallyBundles(n) {
  const bundles = []
  let rest = Math.max(0, Math.trunc(Number(n) || 0))
  while (rest > 0) {
    bundles.push(Math.min(5, rest))
    rest -= 5
  }
  return bundles
}

function buchungText(b) {
  if (b.typ === 'konsum') return `${b.menge}× ${b.artikel_name || b.notiz || 'Artikel'}`
  if (b.typ === 'verkauf' && b.artikel_name) return `Verkauf: ${b.menge}× ${b.artikel_name}`
  if (b.typ === 'verkauf') return `Verkauf${b.notiz ? ` · ${b.notiz}` : ''}`
  if (b.typ === 'kauf') return `Kauf${b.notiz ? ` · ${b.notiz}` : ''}`
  if (b.typ === 'einkauf') return `Verkauf ans Team${b.notiz ? ` · ${b.notiz}` : ''}`
  if (b.typ === 'zahlung') return `Zahlung${b.notiz ? ` · ${b.notiz}` : ''}`
  if (b.typ === 'beitrag') return b.notiz || `Mannschaftsbeitrag ${b.beitrag_monat}`
  return b.notiz || b.typ
}

function fehler(e, fallback) {
  $q.notify({ type: 'negative', message: e.response?.data?.detail || fallback })
}

async function copyIban() {
  try {
    await copyToClipboard(deckel.value.zahlweg_iban)
    $q.notify({ type: 'positive', message: 'IBAN kopiert', timeout: 1200 })
  } catch {
    $q.notify({ type: 'negative', message: 'Kopieren nicht möglich' })
  }
}

// ------------------------------------------------------------------ Laden
async function loadTeams() {
  try {
    const { data } = await api.get(`${BASE}/teams`)
    teams.value = data
    if (!data.find(t => t.mannschaft_id === selectedTeamId.value)) {
      const gespeichert = Number(localStorage.getItem('vtb_teamtresor_team'))
      const bevorzugt = data.find(t => t.mannschaft_id === gespeichert && t.deckel)
        || data.find(t => t.deckel) || data[0]
      selectedTeamId.value = bevorzugt ? bevorzugt.mannschaft_id : null
    }
  } catch {
    teams.value = []
  } finally {
    geladen.value = true
  }
}

async function loadDeckel() {
  const team = aktuellesTeam.value
  if (!team?.deckel) {
    deckel.value = null
    return
  }
  try {
    const { data } = await api.get(`${BASE}/${team.deckel.id}`)
    deckel.value = data
  } catch (e) {
    deckel.value = null
    fehler(e, 'Teamtresor konnte nicht geladen werden')
  }
}

async function loadMeineBuchungen() {
  if (!deckel.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/buchungen`, { params: { limit: 10 } })
    meineBuchungen.value = data
  } catch { meineBuchungen.value = [] }
}

async function loadSalden() {
  if (!deckel.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/salden`)
    salden.value = data.mitglieder
    teamSaldo.value = data.team_saldo
  } catch { salden.value = []; teamSaldo.value = 0 }
}

async function loadKatalog() {
  if (!deckel.value || !istWart.value) return
  try {
    const [a, g] = await Promise.all([
      api.get(`${BASE}/${deckel.value.id}/artikel`, { params: { alle: true } }),
      api.get(`${BASE}/${deckel.value.id}/gruppen`),
    ])
    katalog.value = a.data
    gruppen.value = g.data
  } catch { katalog.value = []; gruppen.value = [] }
}

async function loadAlleBuchungen() {
  if (!deckel.value || !istWart.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/buchungen`,
      { params: { alle: true, limit: 100 } })
    alleBuchungen.value = data
  } catch { alleBuchungen.value = [] }
}

async function loadWarte() {
  if (!deckel.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/warte`)
    warte.value = data
  } catch { warte.value = [] }
}

async function loadBefreiungen() {
  if (!deckel.value || !istVerwalter.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/befreiungen`)
    befreiungen.value = data
  } catch { befreiungen.value = [] }
}

async function loadKader() {
  if (!deckel.value || !istWart.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/kader`)
    kader.value = data
  } catch { kader.value = [] }
}

async function loadTabDaten() {
  if (!deckel.value) return
  if (tab.value === 'tresen') await loadMeineBuchungen()
  else if (tab.value === 'salden') await loadSalden()
  else if (tab.value === 'katalog') await Promise.all([loadKatalog(), loadKader()])
  else if (tab.value === 'verwalten') {
    await Promise.all([loadAlleBuchungen(), loadSalden(), loadKader(), loadWarte(),
      loadBefreiungen()])
  }
}

async function refreshAll() {
  await loadTeams()
  await loadDeckel()
  await loadTabDaten()
}

watch(selectedTeamId, async (id) => {
  if (id != null) localStorage.setItem('vtb_teamtresor_team', String(id))
  tab.value = 'tresen'
  await loadDeckel()
  await loadTabDaten()
})

watch(tab, loadTabDaten)

onMounted(refreshAll)
usePageRefresh(refreshAll)

// ------------------------------------------------------------- Einschalten
async function einschalten() {
  const team = aktuellesTeam.value
  if (!team) return
  saving.value = true
  try {
    await api.post(`${BASE}/teams/${team.mannschaft_id}`, {})
    $q.notify({ type: 'positive', message: 'Teamtresor eingeschaltet', timeout: 1200 })
    await refreshAll()
  } catch (e) {
    fehler(e, 'Einschalten fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

// ------------------------------------------------------------------ Tresen
async function bucheKonsum(artikel) {
  saving.value = true
  try {
    const { data } = await api.post(`${BASE}/${deckel.value.id}/konsum`,
      { artikel_id: artikel.id, menge: 1 })
    $q.notify({
      type: 'positive',
      message: `${artikel.name} gebucht (${fmtEuro(data.betrag)})`,
      timeout: 3000,
      actions: [{ label: 'Rückgängig', color: 'white', handler: () => storno(data) }],
    })
    await Promise.all([loadDeckel(), loadMeineBuchungen()])
  } catch (e) {
    fehler(e, 'Buchung fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function storno(buchung) {
  saving.value = true
  try {
    await api.delete(`${BASE}/${deckel.value.id}/buchungen/${buchung.id}`)
    $q.notify({ type: 'positive', message: 'Buchung storniert', timeout: 1200 })
    await Promise.all([loadDeckel(), loadMeineBuchungen(),
      istWart.value ? loadAlleBuchungen() : Promise.resolve(),
      tab.value === 'salden' || tab.value === 'verwalten' ? loadSalden() : Promise.resolve()])
  } catch (e) {
    fehler(e, 'Storno fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function undoArtikel(a) {
  if (!a.mein_24h_anzahl) return
  saving.value = true
  try {
    await api.delete(`${BASE}/${deckel.value.id}/konsum/${a.id}`)
    $q.notify({ type: 'positive', message: `${a.name}: letzter Strich zurückgenommen`,
      timeout: 1200 })
    await Promise.all([loadDeckel(), loadMeineBuchungen()])
  } catch (e) {
    fehler(e, 'Zurücknehmen fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

// ----------------------------------------------------------------- Katalog
function openGruppeDialog(gruppe = null) {
  dialogError.value = ''
  gruppeForm.value = gruppe
    ? { id: gruppe.id, name: gruppe.name, verkaeufer: gruppe.verkaeufer_mitglied_id,
        sortierung: gruppe.sortierung, aktiv: !!gruppe.aktiv, version: gruppe.version }
    : { id: null, name: '', verkaeufer: null, sortierung: 0, aktiv: true }
  gruppeDialog.value = true
}

async function saveGruppe() {
  const f = gruppeForm.value
  if (!f.name?.trim()) {
    dialogError.value = 'Name ist erforderlich.'
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    const payload = { name: f.name.trim(), verkaeufer_mitglied_id: f.verkaeufer,
      aktiv: f.aktiv, sortierung: f.sortierung || 0 }
    if (f.id) {
      await api.put(`${BASE}/${deckel.value.id}/gruppen/${f.id}`,
        { ...payload, expected_version: f.version })
    } else {
      await api.post(`${BASE}/${deckel.value.id}/gruppen`, payload)
    }
    gruppeDialog.value = false
    await Promise.all([loadKatalog(), loadDeckel()])
  } catch (e) {
    dialogError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

function deleteGruppe(gruppe) {
  $q.dialog({
    title: 'Gruppe löschen',
    message: `„${gruppe.name}" löschen? Die Gruppe muss dafür leer sein.`,
    cancel: true,
    ok: { label: 'Löschen', color: 'negative', noCaps: true },
  }).onOk(async () => {
    try {
      await api.delete(`${BASE}/${deckel.value.id}/gruppen/${gruppe.id}`)
      await Promise.all([loadKatalog(), loadDeckel()])
    } catch (e) {
      fehler(e, 'Löschen fehlgeschlagen')
    }
  })
}

function openArtikelDialog(artikel = null, preselectGruppe = undefined) {
  dialogError.value = ''
  artikelForm.value = artikel
    ? { id: artikel.id, name: artikel.name, preis: Number(artikel.preis),
        gruppe: artikel.gruppe_id, sortierung: artikel.sortierung,
        aktiv: !!artikel.aktiv, version: artikel.version }
    : { id: null, name: '', preis: null,
        gruppe: preselectGruppe !== undefined ? preselectGruppe
          : (gruppen.value[0]?.id ?? null),
        sortierung: 0, aktiv: true }
  artikelDialog.value = true
}

// --- Inline-Sofortspeicher im Katalog (Toggle/Name/Preis/Verkäufer) ---
function _artikelPayload(a, patch) {
  return {
    name: a.name, preis: Number(a.preis), gruppe_id: a.gruppe_id,
    aktiv: !!a.aktiv, sortierung: a.sortierung || 0,
    expected_version: a.version, ...patch,
  }
}

async function _saveArtikelInline(a, patch) {
  saving.value = true
  try {
    await api.put(`${BASE}/${deckel.value.id}/artikel/${a.id}`, _artikelPayload(a, patch))
    await Promise.all([loadKatalog(), loadDeckel()])
  } catch (e) {
    fehler(e, 'Speichern fehlgeschlagen')
    await loadKatalog()
  } finally {
    saving.value = false
  }
}

function toggleArtikelAktiv(a, v) {
  if (!!a.aktiv === v) return
  return _saveArtikelInline(a, { aktiv: v })
}

function renameArtikel(a, name) {
  const n = (name || '').trim()
  if (!n || n === a.name) { loadKatalog(); return }
  return _saveArtikelInline(a, { name: n })
}

function repriceArtikel(a, preis) {
  const p = parsePreis(preis)
  if (!(p > 0)) {
    $q.notify({ type: 'negative', message: 'Preis muss größer 0 sein' })
    loadKatalog()
    return
  }
  if (p === Number(a.preis)) return
  return _saveArtikelInline(a, { preis: p })
}

async function _saveGruppeInline(g, patch) {
  saving.value = true
  try {
    await api.put(`${BASE}/${deckel.value.id}/gruppen/${g.id}`, {
      name: g.name, verkaeufer_mitglied_id: g.verkaeufer_mitglied_id,
      aktiv: !!g.aktiv, sortierung: g.sortierung || 0,
      expected_version: g.version, ...patch,
    })
    await Promise.all([loadKatalog(), loadDeckel()])
  } catch (e) {
    fehler(e, 'Speichern fehlgeschlagen')
    await loadKatalog()
  } finally {
    saving.value = false
  }
}

function toggleGruppeAktiv(g, v) {
  if (!!g.aktiv === v) return
  return _saveGruppeInline(g, { aktiv: v })
}

function setGruppeVerkaeufer(g, v) {
  if (g.verkaeufer_mitglied_id === v) return
  return _saveGruppeInline(g, { verkaeufer_mitglied_id: v })
}

async function saveArtikel() {
  const f = artikelForm.value
  if (!f.name?.trim() || !(f.preis > 0)) {
    dialogError.value = 'Name und ein Preis größer 0 sind erforderlich.'
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    const payload = { name: f.name.trim(), preis: f.preis, gruppe_id: f.gruppe,
      aktiv: f.aktiv, sortierung: f.sortierung || 0 }
    if (f.id) {
      await api.put(`${BASE}/${deckel.value.id}/artikel/${f.id}`,
        { ...payload, expected_version: f.version })
    } else {
      await api.post(`${BASE}/${deckel.value.id}/artikel`, payload)
    }
    artikelDialog.value = false
    await Promise.all([loadKatalog(), loadDeckel()])
  } catch (e) {
    dialogError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

function deleteArtikel(artikel) {
  $q.dialog({
    title: 'Artikel löschen',
    message: `„${artikel.name}" aus dem Katalog löschen? Bestehende Buchungen bleiben erhalten.`,
    cancel: true,
    ok: { label: 'Löschen', color: 'negative', noCaps: true },
  }).onOk(async () => {
    try {
      await api.delete(`${BASE}/${deckel.value.id}/artikel/${artikel.id}`)
      await Promise.all([loadKatalog(), loadDeckel()])
    } catch (e) {
      fehler(e, 'Löschen fehlgeschlagen')
    }
  })
}

// --------------------------------------------------------------- Verwalten
function openZahlungDialog(m = null) {
  dialogError.value = ''
  zahlungForm.value = {
    name: m ? m.name : null,
    von: m ? m.mitglied_id : null,
    an: deckel.value.zahlungsempfaenger_mitglied_id,
    methode: 'bar', betrag: null, datum: jetztLocal(), notiz: '',
  }
  zahlungDialog.value = true
}

async function saveZahlung() {
  const f = zahlungForm.value
  if (f.von == null || f.an == null || !(f.betrag > 0)) {
    dialogError.value = 'Zahler, Empfänger und ein Betrag größer 0 sind erforderlich.'
    return
  }
  if (f.von === f.an) {
    dialogError.value = 'Zahler und Empfänger müssen verschieden sein.'
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    await api.post(`${BASE}/${deckel.value.id}/zahlung`, {
      von_mitglied_id: f.von, an_mitglied_id: f.an, betrag: f.betrag,
      methode: f.methode || null, datum: f.datum || null, notiz: f.notiz || null,
    })
    zahlungDialog.value = false
    await Promise.all([loadAlleBuchungen(), loadSalden(), loadDeckel()])
  } catch (e) {
    dialogError.value = e.response?.data?.detail || 'Zahlung fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

function openKaufDialog(m) {
  dialogError.value = ''
  kaufForm.value = { mitglied: m.mitglied_id, name: m.name, verkauft: false,
    gegen: null, betrag: null, datum: jetztLocal(), notiz: '' }
  kaufDialog.value = true
}

async function saveKauf() {
  const f = kaufForm.value
  if (!(f.betrag > 0)) {
    dialogError.value = 'Ein Betrag größer 0 ist erforderlich.'
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    await api.post(`${BASE}/${deckel.value.id}/an-verkauf`, {
      mitglied_id: f.mitglied, verkauft: f.verkauft, gegen_mitglied_id: f.gegen,
      betrag: f.betrag, datum: f.datum || null, notiz: f.notiz || null,
    })
    kaufDialog.value = false
    await Promise.all([loadAlleBuchungen(), loadSalden(), loadDeckel()])
  } catch (e) {
    dialogError.value = e.response?.data?.detail || 'Buchen fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

async function addWart() {
  if (neuerWart.value == null) return
  try {
    await api.put(`${BASE}/${deckel.value.id}/warte/${neuerWart.value}`)
    neuerWart.value = null
    await Promise.all([loadWarte(), loadKader()])
  } catch (e) {
    fehler(e, 'Ernennen fehlgeschlagen')
  }
}

function removeWart(wart) {
  $q.dialog({
    title: 'Wart entfernen',
    message: `${wart.mitglied_name} die Wart-Berechtigung entziehen?`,
    cancel: true,
    ok: { label: 'Entfernen', color: 'negative', noCaps: true },
  }).onOk(async () => {
    try {
      await api.delete(`${BASE}/${deckel.value.id}/warte/${wart.mitglied_id}`)
      await Promise.all([loadWarte(), loadKader()])
    } catch (e) {
      fehler(e, 'Entfernen fehlgeschlagen')
    }
  })
}

async function addBefreiung() {
  if (neueBefreiung.value == null) return
  try {
    await api.put(`${BASE}/${deckel.value.id}/befreiungen/${neueBefreiung.value}`)
    neueBefreiung.value = null
    await loadBefreiungen()
  } catch (e) {
    fehler(e, 'Befreien fehlgeschlagen')
  }
}

function removeBefreiung(befreiung) {
  $q.dialog({
    title: 'Befreiung aufheben',
    message: `${befreiung.mitglied_name} zahlt dann ab dem laufenden Monat wieder Beitrag.`,
    cancel: true,
    ok: { label: 'Aufheben', color: 'negative', noCaps: true },
  }).onOk(async () => {
    try {
      await api.delete(`${BASE}/${deckel.value.id}/befreiungen/${befreiung.mitglied_id}`)
      await loadBefreiungen()
    } catch (e) {
      fehler(e, 'Aufheben fehlgeschlagen')
    }
  })
}

function openStammdatenDialog() {
  dialogError.value = ''
  const d = deckel.value
  stammdatenForm.value = {
    name: d.name, aktiv: !!d.aktiv,
    beitrag: d.beitrag != null ? Number(d.beitrag) : null,
    zahlungsempfaenger: d.zahlungsempfaenger_mitglied_id,
    zahlweg_iban: d.zahlweg_iban || '', zahlweg_wero: d.zahlweg_wero || '',
    zahlweg_paypal: d.zahlweg_paypal || '',
  }
  stammdatenDialog.value = true
}

async function saveStammdaten() {
  const f = stammdatenForm.value
  if (!f.name?.trim()) {
    dialogError.value = 'Name ist erforderlich.'
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    await api.put(`${BASE}/${deckel.value.id}`, {
      name: f.name.trim(), aktiv: f.aktiv,
      beitrag: f.beitrag || null,
      zahlungsempfaenger_mitglied_id: f.zahlungsempfaenger,
      zahlweg_iban: f.zahlweg_iban || null,
      zahlweg_wero: f.zahlweg_wero || null,
      zahlweg_paypal: f.zahlweg_paypal || null,
      expected_version: deckel.value.version,
    })
    stammdatenDialog.value = false
    await refreshAll()
  } catch (e) {
    dialogError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

function ausschalten() {
  $q.dialog({
    title: 'Teamtresor ausschalten',
    message: `Den Teamtresor „${deckel.value.name}" wirklich ausschalten? ` +
      'Buchungen und Salden bleiben in der Historie erhalten.',
    cancel: true,
    ok: { label: 'Ausschalten', color: 'negative', noCaps: true },
  }).onOk(async () => {
    try {
      await api.delete(`${BASE}/${deckel.value.id}`)
      $q.notify({ type: 'positive', message: 'Teamtresor ausgeschaltet', timeout: 1500 })
      deckel.value = null
      await refreshAll()
    } catch (e) {
      fehler(e, 'Ausschalten fehlgeschlagen')
    }
  })
}
</script>

<style lang="scss" scoped>
.tt-artikel-btn {
  min-height: 64px;
}

// Tresen-Zeile: voller Buchungs-Button + Undo-Zone rechts (Screenshot-Optik)
.tt-tresen-row {
  border-radius: 8px;
  overflow: hidden;
}
.tt-tresen-btn {
  border-radius: 8px 0 0 8px;
  min-height: 56px;
  padding: 6px 14px;
}
.tt-tresen-name {
  font-size: 1.05rem;
}
.tt-tresen-del {
  width: 60px;
  border-radius: 0 8px 8px 0;
  background: rgba(193, 0, 21, 0.06);
}
.tt-tally-svg {
  margin-right: 5px;
}
.tt-tally-svg line {
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
}

// Club-Kopf über der Mitgliederliste (Wart-Transaktionen)
.tt-club-head {
  background: #1d2740;
  border-radius: 8px;
}

// Katalog-Karten in Screenshot-Optik: dunkle Kopfzeile je Gruppe
.tt-gruppe {
  overflow: hidden;
}
.tt-gruppe__head {
  background: #1d2740;
  color: #fff;
  min-height: 48px;
}
.tt-gruppe__spacer {
  width: 40px;
}
.tt-verkaeufer {
  min-width: 130px;
  max-width: 170px;
}
.tt-preis {
  width: 96px;
}
.tt-artikel-row + .tt-artikel-row {
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
body.body--dark .tt-artikel-row + .tt-artikel-row {
  border-top-color: rgba(255, 255, 255, 0.08);
}
</style>
