<template>
  <q-page class="q-pa-md">
    <!-- Team-Auswahl nur bei mehreren Teams; der Titel „Teamkasse" steht schon
         in der App-Kopfzeile — kein doppelter Seitentitel (#126). -->
    <div v-if="teams.length > 1" class="q-mb-md">
      <q-select
        v-model="selectedTeamId"
        :options="teamOptions"
        emit-value map-options dense outlined
        style="max-width: 320px"
        label="Mannschaft"
      />
    </div>

    <div v-if="!teams.length && geladen" class="text-grey q-mt-lg">
      Keine Teamkasse verfügbar — du stehst in keinem Kader mit Teamkasse.
    </div>

    <!-- Einschalt-Karte: Team ohne Deckel, nur für Kader-Verwalter sichtbar -->
    <q-card v-if="aktuellesTeam && !aktuellesTeam.deckel" class="vtb-karte q-mt-md">
      <q-card-section class="column items-start q-gutter-sm">
        <div class="text-subtitle1 text-weight-bold">
          {{ aktuellesTeam.mannschaft_name }} hat noch keine Teamkasse
        </div>
        <div class="text-caption text-grey">
          Als Übungsleiter/Betreuer kannst du die mannschaftsinterne Strichliste hier
          einschalten. Gruppen, Artikel und Preise pflegst du danach im Katalog.
        </div>
        <q-btn color="primary" unelevated no-caps icon="sports_bar"
          :label="`Teamkasse für ${aktuellesTeam.mannschaft_name} aktivieren`"
          :loading="saving" @click="einschalten" />
      </q-card-section>
    </q-card>

    <!-- Admin-Papierkorb: gelöschte Teamkassen wiederherstellen (#125) -->
    <q-expansion-item v-if="istAdmin && papierkorb.length" class="vtb-karte q-mt-md"
      icon="restore_from_trash" :label="`Gelöschte Teamkassen (${papierkorb.length})`"
      header-class="text-weight-medium">
      <q-list separator>
        <q-item v-for="e in papierkorb" :key="e.id">
          <q-item-section>
            <q-item-label>{{ e.mannschaft_name }}</q-item-label>
            <q-item-label caption>
              gelöscht {{ fmtDateTime(e.deleted_at) }} von {{ e.deleted_by }}
              · {{ e.anzahl_buchungen }} Buchung(en)
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn outline no-caps color="primary" icon="restore" label="Wiederherstellen"
              :disable="e.mannschaft_hat_aktiven || saving" @click="wiederherstellen(e)">
              <q-tooltip v-if="e.mannschaft_hat_aktiven">
                Diese Mannschaft hat bereits wieder eine aktive Teamkasse
              </q-tooltip>
            </q-btn>
          </q-item-section>
        </q-item>
      </q-list>
    </q-expansion-item>

    <template v-if="deckel">
      <!-- Status-Zeile: Rolle / Deaktiviert (Beträge stehen als Kacheln im Tresen) -->
      <div v-if="istWart || !deckel.aktiv" class="row items-center q-gutter-xs q-mb-md">
        <span v-if="istVerwalter" class="vtb-pill">Verwalter</span>
        <span v-else-if="istWart" class="vtb-pill">Wart</span>
        <span v-if="!deckel.aktiv" class="vtb-pill vtb-pill--warn">deaktiviert</span>
      </div>

      <q-banner v-if="!deckel.aktiv" class="vtb-warnung q-mb-md" rounded dense>
        <template #avatar><q-icon name="pause_circle" size="26px" /></template>
        Die Teamkasse ist deaktiviert — Buchen ist gerade nicht möglich.
      </q-banner>

      <!-- Tab-Reihe: nur Tresen/Salden/Katalog in der Pille; die Verwaltung liegt
           hinter dem Zahnrad rechts — spart Platz und passt am Handy (#126). -->
      <div class="row items-center no-wrap q-mb-md">
        <!-- Mit den Wart-Reitern wird die Pille am Handy breiter als der Schirm.
             Sie scrollt deshalb in ihrem eigenen Behälter (#167) — die q-page
             selbst darf nie waagerecht scrollen. -->
        <div class="tt-tabs-scroll col">
          <q-tabs v-model="tab" align="left" class="vtb-tabs" no-caps
            :inline-label="$q.screen.gt.xs">
            <q-tab name="tresen" icon="sports_bar" label="Tresen" />
            <!-- Fremdbuchung + Termin-Auswertung am Tresen (#167) -->
            <q-tab v-if="istWart" name="buchen" icon="grid_on" label="Buchen" />
            <q-tab v-if="istWart" name="termin" icon="event_note" label="Termin" />
            <!-- intern weiter 'salden'; Nutzer-Label „Tabelle" (#128) -->
            <q-tab name="salden" icon="leaderboard" label="Tabelle" />
            <q-tab v-if="istWart" name="katalog" icon="menu_book" label="Katalog" />
          </q-tabs>
        </div>
        <q-btn v-if="istWart" round :flat="tab !== 'verwalten'"
          :unelevated="tab === 'verwalten'"
          :color="tab === 'verwalten' ? 'primary' : undefined"
          icon="settings" class="q-ml-sm" @click="tab = 'verwalten'">
          <q-tooltip>Verwaltung</q-tooltip>
        </q-btn>
      </div>

      <!-- ====================== Tresen ====================== -->
      <div v-if="tab === 'tresen'">
        <div v-if="deckel.mein_mitglied_id == null" class="text-grey q-mb-md">
          Du stehst nicht im aktiven Kader dieser Mannschaft und kannst hier nicht
          selbst buchen.
        </div>

        <!-- Worauf der nächste Strich landet (#167). Ohne laufenden Termin steht
             hier nichts — eine Zeile „kein Termin" wäre nur Rauschen. -->
        <div v-if="deckel.laufender_termin" class="row items-center q-gutter-xs q-mb-sm
          text-caption text-grey">
          <q-icon name="event_available" size="16px" />
          <span>gebucht auf: {{ deckel.laufender_termin.label }}</span>
        </div>

        <template v-for="g in tresenGruppen" :key="g.name">
          <div class="text-subtitle2 q-mt-sm q-mb-xs">
            {{ g.name }}
            <span v-if="g.verkaeufer" class="text-caption text-grey">
              · verkauft {{ g.verkaeufer }}</span>
          </div>
          <div v-for="a in g.artikel" :key="a.id"
            class="tt-tresen-row row no-wrap items-stretch q-mb-sm">
            <!-- Tap = 1× buchen; darunter die Strichliste DIESES Termins -->
            <q-btn class="tt-tresen-btn col" unelevated no-caps color="primary" align="left"
              :disable="!deckel.aktiv || deckel.mein_mitglied_id == null || saving"
              @click="bucheKonsum(a)">
              <div class="full-width row items-center no-wrap">
                <div class="col text-left">
                  <div class="text-weight-bold tt-tresen-name">{{ a.name }}</div>
                  <div v-if="a.mein_termin_anzahl" class="tt-tally row items-center no-wrap q-mt-xs">
                    <svg v-for="(k, i) in tallyBundles(a.mein_termin_anzahl)" :key="i"
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
            <q-btn class="tt-tresen-del" flat :disable="!a.mein_termin_anzahl || saving"
              @click.stop="undoArtikel(a)">
              <q-icon name="delete" :color="a.mein_termin_anzahl ? 'negative' : 'grey-5'" />
              <q-tooltip>Letzten Strich zurücknehmen</q-tooltip>
            </q-btn>
          </div>
        </template>
        <div v-if="!deckel.artikel.length" class="text-grey q-mt-md">
          Noch keine Artikel im Katalog<template v-if="istWart"> — lege sie im Tab
          „Katalog" an</template>.
        </div>

        <!-- Kacheln: mein Deckel BEI DIESEM TERMIN + mein Gesamtsaldo. Ohne
             laufenden Termin gibt es keinen Termin-Deckel — dann steht der
             Gesamtsaldo allein. -->
        <div v-if="deckel.mein_mitglied_id != null" class="row q-col-gutter-sm q-mt-md">
          <div v-if="deckel.laufender_termin" class="col-6">
            <q-card flat bordered class="text-center q-pa-sm">
              <div class="text-overline text-grey ellipsis">
                {{ deckel.laufender_termin.label }}
              </div>
              <div class="text-h6 text-positive">{{ fmtEuro(deckel.mein_termin_summe) }}</div>
            </q-card>
          </div>
          <div :class="deckel.laufender_termin ? 'col-6' : 'col-12'">
            <q-card flat bordered class="text-center q-pa-sm">
              <div class="text-overline text-grey">Gesamtsaldo</div>
              <div class="text-h6"
                :class="Number(deckel.mein_saldo) < 0 ? 'text-negative' : 'text-positive'">
                {{ fmtEuro(deckel.mein_saldo) }}
              </div>
            </q-card>
          </div>
        </div>

        <!-- Zahlung an … (Zahlungsempfänger + Zahlwege aus den Stammdaten) -->
        <q-card v-if="hatZahlwege" class="vtb-karte tt-zahlkarte q-mt-lg">
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

      <!-- ============== Buchen: Matrix Mitglied × Artikel (Wart) ============== -->
      <div v-if="tab === 'buchen' && istWart">
        <!-- Nur Termin-Auswahl: Jede Buchung hängt an einem Termin, ein
             Tages-Ausschnitt hätte hier nichts zu bestimmen. -->
        <TerminWahl v-model="buchenTermin" :termine="termine"
          :laufend-id="laufendTerminId" label="Buchen auf" />

        <div v-if="!termine.length" class="text-grey q-mt-md">
          Diese Mannschaft hat noch keine Termine — lege im Bereich „Termine"
          einen an, dann kann hier gebucht werden.
        </div>
        <div v-else-if="!matrix" class="text-grey q-mt-md">Wird geladen …</div>
        <template v-else-if="!matrix.artikel.length">
          <div class="text-grey q-mt-md">
            Noch keine Artikel im Katalog — lege sie im Tab „Katalog" an.
          </div>
        </template>
        <template v-else>
          <!-- Gitter scrollt in sich selbst; die erste Spalte bleibt stehen,
               sonst weiß am Handy niemand mehr, wessen Zeile er antippt.
               Die q-card gibt die Fläche vor — die klebende Spalte erbt sie und
               ist damit in allen drei Themes richtig gefärbt. -->
          <q-card flat bordered class="tt-matrix-karte q-mt-md">
            <table class="tt-matrix">
              <thead>
                <tr>
                  <th class="tt-matrix__name">Mitglied</th>
                  <th v-for="a in matrix.artikel" :key="a.id">
                    <div class="tt-matrix__artikel">
                      <q-icon v-if="a.nur_wart" name="visibility_off" size="14px"
                        class="q-mr-xs">
                        <q-tooltip>Steht nicht am Tresen — nur hier buchbar</q-tooltip>
                      </q-icon>{{ a.name }}
                    </div>
                    <div class="text-caption text-grey">
                      {{ fmtEuro(a.preis) }}
                      <q-icon v-if="a.ausser_dienst" name="history_toggle_off" size="14px">
                        <q-tooltip>Nicht mehr im Angebot — nur noch alte Buchungen</q-tooltip>
                      </q-icon>
                    </div>
                  </th>
                </tr>
                <tr class="tt-matrix__summen">
                  <th class="tt-matrix__name">Σ Team</th>
                  <th v-for="a in matrix.artikel" :key="a.id">
                    <div class="text-weight-bold">{{ a.summe_anzahl }}</div>
                    <div class="text-caption">{{ fmtEuro(a.summe_betrag) }}</div>
                  </th>
                </tr>
              </thead>
              <tbody>
                <!-- Zugesagte stehen oben (#167): So findet der Wart die Leute,
                     die da sind, und sieht, wer von ihnen noch nichts gebucht
                     hat. Abgesagte sind gedämpft und stehen unten. -->
                <tr v-for="m in matrix.mitglieder" :key="m.mitglied_id"
                  :class="{ 'tt-matrix__abgesagt': m.antwort === 'ab' }">
                  <th class="tt-matrix__name">
                    <div class="row items-center no-wrap">
                      <q-icon v-if="m.antwort === 'zu'" name="check_circle"
                        color="positive" size="14px" class="q-mr-xs">
                        <q-tooltip>Hat für diesen Termin zugesagt</q-tooltip>
                      </q-icon>
                      <div class="ellipsis">{{ m.name }}</div>
                    </div>
                    <div class="text-caption text-grey">
                      {{ fmtEuro(m.betrag) }}
                      <span v-if="!m.im_kader"> · nicht im Kader</span>
                      <span v-else-if="m.antwort === 'ab'"> · abgesagt</span>
                    </div>
                  </th>
                  <td v-for="a in matrix.artikel" :key="a.id">
                    <div class="row no-wrap items-center justify-center q-gutter-xs">
                      <q-btn dense unelevated no-caps color="primary"
                        class="tt-matrix__add"
                        :disable="!buchenBuchbar || !deckel.aktiv || saving
                                  || a.ausser_dienst"
                        :label="String(zelle(m.mitglied_id, a.id).anzahl || 0)"
                        @click="matrixBuchen(m, a)" />
                      <q-btn dense flat round size="sm" icon="remove"
                        :color="zelle(m.mitglied_id, a.id).anzahl ? 'negative' : 'grey-5'"
                        :disable="!zelle(m.mitglied_id, a.id).anzahl || saving"
                        @click="matrixZurueck(m, a)" />
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </q-card>

          <q-card flat bordered class="text-center q-pa-sm q-mt-md">
            <div class="text-overline text-grey">Summe im Ausschnitt</div>
            <div class="text-h6">{{ fmtEuro(matrix.gesamt) }}</div>
          </q-card>
        </template>
      </div>

      <!-- ============== Termin: Auswertung (Wart) ============== -->
      <div v-if="tab === 'termin' && istWart">
        <TerminWahl v-model="auswTermin" :termine="termine"
          :laufend-id="laufendTerminId" label="Auswertung für" />

        <template v-if="auswMatrix">
          <div class="row q-col-gutter-sm q-mt-md">
            <div class="col-6">
              <q-card flat bordered class="text-center q-pa-sm">
                <div class="text-overline text-grey">Umsatz</div>
                <div class="text-h6">{{ fmtEuro(auswMatrix.gesamt) }}</div>
              </q-card>
            </div>
            <div class="col-6">
              <q-card flat bordered class="text-center q-pa-sm">
                <div class="text-overline text-grey">Buchungen</div>
                <div class="text-h6">{{ auswBuchungen.length }}</div>
              </q-card>
            </div>
          </div>

          <div class="text-subtitle2 q-mt-lg q-mb-sm">Nach Artikel</div>
          <q-list bordered separator class="rounded-borders">
            <q-item v-for="a in auswArtikel" :key="a.id">
              <q-item-section>
                <q-item-label>
                  {{ a.name }}
                  <q-badge v-if="a.ausser_dienst" outline color="grey"
                    label="nicht mehr im Angebot" class="q-ml-xs" />
                </q-item-label>
                <q-item-label caption>{{ a.summe_anzahl }}× à {{ fmtEuro(a.preis) }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <span class="text-weight-bold">{{ fmtEuro(a.summe_betrag) }}</span>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-if="!auswArtikel.length" class="text-grey q-mt-sm">
            In diesem Ausschnitt wurde nichts konsumiert.
          </div>

          <div class="text-subtitle2 q-mt-lg q-mb-sm">Nach Mitglied</div>
          <q-list bordered separator class="rounded-borders">
            <q-item v-for="m in auswMitglieder" :key="m.mitglied_id">
              <q-item-section>
                <q-item-label>{{ m.name }}</q-item-label>
                <q-item-label caption>{{ m.anzahl }} Artikel</q-item-label>
              </q-item-section>
              <q-item-section side>
                <span class="text-weight-bold">{{ fmtEuro(m.betrag) }}</span>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-if="!auswMitglieder.length" class="text-grey q-mt-sm">
            Noch niemand hat hier gebucht.
          </div>

          <div class="text-subtitle2 q-mt-lg q-mb-sm">
            Buchungen — zum Korrigieren
          </div>
          <q-list bordered separator class="rounded-borders">
            <q-item v-for="b in auswBuchungen" :key="b.id"
              :class="{ 'tt-storniert': b.deleted_at }">
              <q-item-section>
                <q-item-label>{{ b.mitglied_name }}: {{ buchungText(b) }}</q-item-label>
                <q-item-label caption>{{ fmtDateTime(b.created_at) }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row items-center q-gutter-sm">
                  <span :class="[Number(b.betrag) < 0 ? 'text-negative' : 'text-positive',
                                 b.deleted_at ? 'tt-durchgestrichen' : '']">
                    {{ fmtEuro(b.betrag) }}
                  </span>
                  <q-btn v-if="!b.deleted_at" flat round dense size="sm" icon="undo"
                    :disable="saving" @click="stornoImAusschnitt(b)">
                    <q-tooltip>Buchung stornieren</q-tooltip>
                  </q-btn>
                  <q-btn v-else flat round dense size="sm" icon="restore"
                    :disable="saving" @click="restoreImAusschnitt(b)">
                    <q-tooltip>Storno zurücknehmen</q-tooltip>
                  </q-btn>
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-if="!auswBuchungen.length" class="text-grey q-mt-sm">
            Keine Buchungen in diesem Ausschnitt.
          </div>
        </template>
      </div>

      <!-- ====================== Salden ====================== -->
      <div v-if="tab === 'salden'">
        <!-- Bestand der Teamkasse prominent — das ist der Kassenstand der
             mannschaftsinternen Strichliste, NICHT die Vereinskasse (#127). -->
        <q-card flat bordered class="text-center q-pa-md q-mb-md">
          <div class="text-overline text-grey">Teamkassen-Bestand</div>
          <div class="text-h5 text-weight-bold"
            :class="Number(teamSaldo) < 0 ? 'text-negative' : 'text-positive'">
            {{ fmtEuro(teamSaldo) }}
          </div>
          <div class="text-caption text-grey">Kassenstand der Mannschaft in der Teamkasse</div>
        </q-card>

        <!-- Bank (Zahlungsempfänger) abgesetzt: verwahrt das Bargeld, gehört
             nicht in die Schulden-Rangliste (#127). -->
        <q-card v-if="bankEintrag" flat bordered class="tt-bank-card q-mb-md">
          <q-item>
            <q-item-section avatar>
              <q-avatar size="40px" color="vtb-gelb" text-color="primary" icon="account_balance" />
            </q-item-section>
            <q-item-section>
              <q-item-label class="text-weight-bold">
                {{ bankEintrag.mitglied_name }}
                <q-badge color="vtb-gelb" text-color="primary" label="Bank" class="q-ml-xs" />
              </q-item-label>
              <q-item-label caption>verwahrt die Mannschaftskasse (Ausgleich läuft hierher)</q-item-label>
            </q-item-section>
            <q-item-section side>
              <span class="text-weight-bold text-h6">{{ fmtEuro(bankEintrag.saldo) }}</span>
            </q-item-section>
          </q-item>
        </q-card>

        <q-list bordered separator class="rounded-borders">
          <q-item v-for="s in saldenOhneBank" :key="s.mitglied_id">
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
        <div v-if="!saldenOhneBank.length" class="text-grey q-mt-md">
          Noch keine Buchungen.
        </div>
      </div>

      <!-- ====================== Katalog (Wart) ====================== -->
      <div v-if="tab === 'katalog' && istWart">
        <!-- Zeitraum des KATALOGS (#167, v100): Er bestimmt, welche Speisekarte
             hier steht — und worauf sich jede Änderung bezieht. Ein Umschalter
             für alle Gruppen, damit man das Sortiment eines Events als Ganzes
             vor sich hat. -->
        <div class="row items-center q-gutter-sm q-mb-md">
          <div class="row items-center no-wrap" style="min-width: 260px; max-width: 400px">
            <q-btn flat round dense icon="chevron_left"
              :disable="katalogZielId(-1) === null"
              @click="waehleKatalogTermin(katalogZielId(-1))">
              <q-tooltip>Vorheriger Spieltag</q-tooltip>
            </q-btn>
            <q-select :model-value="katalogTermin ?? null" :options="katalogTerminOptionen"
              emit-value map-options dense outlined options-dense class="col"
              label="Speisekarte für"
              @update:model-value="waehleKatalogTermin" />
            <q-btn flat round dense icon="chevron_right"
              :disable="katalogZielId(1) === null"
              @click="waehleKatalogTermin(katalogZielId(1))">
              <q-tooltip>Nächster Spieltag</q-tooltip>
            </q-btn>
          </div>
          <q-space />
          <q-btn outline color="primary" no-caps rounded icon="create_new_folder"
            label="Neue Gruppe" @click="openGruppeDialog()" />
        </div>
        <q-banner v-if="katalogTermin" class="vtb-warnung q-mb-md" rounded dense>
          <template #avatar><q-icon name="edit_calendar" size="22px" /></template>
          Änderungen an Gruppen und Artikeln gelten
          <b>ab {{ katalogTerminLabel }}</b> und für alle späteren Spieltage.
          Frühere behalten ihren Stand.
        </q-banner>

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
            <div v-if="g.gruppe" class="text-caption text-white q-mr-sm ellipsis">
              verkauft {{ g.gruppe.verkaeufer_name || 'das Team' }}
              <span v-if="standUebernommen(g.gruppe)" class="tt-gruppe__erbe">
                · Stand von {{ g.gruppe.gilt_ab_label }}
                <q-tooltip>
                  Für diesen Spieltag ist nichts Eigenes hinterlegt — es gilt der
                  letzte frühere Stand. Eine Änderung legt hier einen neuen an.
                </q-tooltip>
              </span>
            </div>
            <q-btn v-if="g.gruppe" flat round dense color="white" icon="edit"
              @click="openGruppenStand(g.gruppe)">
              <q-tooltip>Name/Verkäufer ab einem Spieltag ändern</q-tooltip>
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
          <div v-for="a in g.artikel" :key="a.id" class="tt-artikel">
            <div class="tt-artikel-row row items-center no-wrap q-px-sm q-py-xs q-gutter-sm">
              <q-toggle :model-value="!!a.aktiv" color="primary" dense :disable="saving"
                @update:model-value="v => toggleArtikelAktivStand(a, v)">
                <q-tooltip>{{ a.aktiv ? 'aktiv' : 'inaktiv' }}</q-tooltip>
              </q-toggle>
              <q-input :model-value="a.name" dense outlined class="col" :disable="saving"
                @change="v => renameArtikelStand(a, v)" />
              <q-input :model-value="fmtPreisInput(a.preis)" dense outlined
                inputmode="decimal" class="tt-preis" input-class="text-right"
                :disable="saving" @change="v => repriceArtikel(a, v)" />
              <!-- Am Tresen sichtbar oder nur in der Buchen-Matrix des Warts?
                   (#167) Posten wie „Wäsche" trägt der Wart nach dem Spiel für
                   die Beteiligten ein — in der Selbstbedienung stünden sie im Weg. -->
              <q-btn flat round dense :disable="saving"
                :color="a.nur_wart ? 'primary' : 'grey-6'"
                :icon="a.nur_wart ? 'visibility_off' : 'storefront'"
                @click="toggleArtikelNurWart(a, !a.nur_wart)">
                <q-tooltip>
                  {{ a.nur_wart ? 'Nur der Wart bucht ihn — nicht am Tresen'
                                : 'Am Tresen sichtbar' }}
                </q-tooltip>
              </q-btn>
              <q-btn flat round dense color="negative" icon="delete"
                :disable="saving" @click="deleteArtikel(a)" />
            </div>
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
        <!-- Überschrift zur Orientierung: man kommt übers Zahnrad hierher (#126) -->
        <div class="text-subtitle1 text-weight-bold row items-center q-mb-sm">
          <q-icon name="settings" class="q-mr-xs" /> Verwaltung
        </div>
        <!-- Unter-Tabs: Verwalten in Mannschaft · History · Stammdaten teilen (#126) -->
        <q-tabs v-model="verwaltenTab" dense no-caps :inline-label="$q.screen.gt.xs"
          align="left" active-color="primary" indicator-color="primary" class="q-mb-md">
          <q-tab name="mannschaft" icon="groups" label="Mannschaft" />
          <q-tab name="events" icon="redeem" label="Sammlungen" />
          <q-tab name="history" icon="receipt_long" label="History" />
          <q-tab v-if="istVerwalter" name="stammdaten" icon="tune" label="Stammdaten" />
        </q-tabs>

        <!-- ---------- Mannschaftsliste: Club-Saldo + Mitglieder-Transaktionen ---------- -->
        <div v-if="verwaltenTab === 'mannschaft'">
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

          <div v-if="istVerwalter && deckel.beitrag"
            class="row items-center q-mb-sm text-caption text-grey-8">
            <q-icon name="how_to_reg" color="green-6" size="18px" class="q-mr-xs" />
            Beitrag aktiv: <b class="q-mx-xs">{{ beitragAktivAnzahl }} / {{ kader.length }}</b>
            · {{ fmtEuro(deckel.beitrag) }}/Monat{{ deckel.beitrag_ab ? ` ab ${deckel.beitrag_ab}` : '' }}
          </div>

          <q-input v-model="mitgliedSuche" dense outlined class="q-mb-sm"
            placeholder="Mitglied suchen…" clearable>
            <template #prepend><q-icon name="search" /></template>
          </q-input>

          <!-- Zeile klickbar: springt in die auf das Mitglied gefilterte History
               (#129); die Aktions-Buttons stoppen das Bubbling. -->
          <q-card v-for="m in mitgliederGefiltert" :key="m.mitglied_id" flat bordered
            class="q-mb-sm cursor-pointer" @click="openHistoryFuer(m)">
            <q-tooltip>Buchungen von {{ m.name }} anzeigen</q-tooltip>
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
              <q-btn v-if="istVerwalter && deckel.beitrag && m.imKader" round unelevated
                size="sm"
                :color="befreitSet.has(m.mitglied_id) ? 'grey-4' : 'green-5'"
                :text-color="befreitSet.has(m.mitglied_id) ? 'grey-8' : 'white'"
                :icon="befreitSet.has(m.mitglied_id) ? 'money_off' : 'how_to_reg'"
                :disable="saving" @click.stop="toggleBeitrag(m)">
                <q-tooltip>{{ befreitSet.has(m.mitglied_id)
                  ? 'Beitrag inaktiv — aktivieren' : 'Beitrag aktiv — deaktivieren' }}</q-tooltip>
              </q-btn>
              <!-- Sammlungs-Opt-out (#181): gilt für ALLE Sammlungen dieser
                   Teamkasse, nicht für eine einzelne — deshalb steht er hier
                   am Mitglied und nicht am Event. -->
              <q-btn v-if="m.imKader" round unelevated size="sm"
                :color="sammlungAusSet.has(m.mitglied_id) ? 'grey-4' : 'teal-5'"
                :text-color="sammlungAusSet.has(m.mitglied_id) ? 'grey-8' : 'white'"
                :icon="sammlungAusSet.has(m.mitglied_id) ? 'do_not_disturb_on' : 'volunteer_activism'"
                :disable="saving" @click.stop="toggleSammlung(m)">
                <q-tooltip>{{ sammlungAusSet.has(m.mitglied_id)
                  ? 'Macht bei Sammlungen nicht mit — wieder aufnehmen'
                  : 'Macht bei Sammlungen mit — dauerhaft ausnehmen' }}</q-tooltip>
              </q-btn>
              <q-btn round unelevated color="deep-purple-5" icon="shopping_bag"
                :disable="!deckel.aktiv || saving" @click.stop="openKaufDialog(m)">
                <q-tooltip>An-/Verkauf buchen</q-tooltip>
              </q-btn>
              <q-btn round unelevated color="primary" icon="payments"
                :disable="!deckel.aktiv || saving" @click.stop="openZahlungDialog(m)">
                <q-tooltip>Zahlung buchen</q-tooltip>
              </q-btn>
            </div>
          </q-card>
          <div v-if="!mitgliederGefiltert.length" class="text-grey q-mb-md">
            Keine Mitglieder gefunden.
          </div>
        </div>

        <!-- ---------- Sammlungen: einmalige Umlage auf den Kader (#181) ---------- -->
        <div v-if="verwaltenTab === 'events'">
          <div class="text-caption text-grey-8 q-mb-sm">
            Einmalige Umlage auf den ganzen Kader — „5 € von allen fürs Geschenk".
            Gebucht wird gegen den Club; wer die Auslage hatte, holt sie sich über
            An-/Verkauf zurück. Wer generell nicht mitmacht, steht im Reiter
            „Mannschaft" auf <q-icon name="do_not_disturb_on" size="14px" />.
          </div>
          <q-btn color="primary" unelevated no-caps icon="add" label="Neue Sammlung"
            class="q-mb-md" :disable="!deckel.aktiv || saving" @click="openEventDialog()" />

          <q-card v-for="e in events" :key="e.id" flat bordered class="q-mb-sm">
            <div class="q-pa-sm">
              <div class="row items-center no-wrap q-gutter-xs">
                <div class="col" style="min-width: 0">
                  <div class="text-weight-medium ellipsis">{{ e.name }}</div>
                  <div class="text-caption text-grey-8 ellipsis">
                    {{ fmtEuro(e.betrag) }} je Kopf<template v-if="e.fuer_name">
                      · für {{ e.fuer_name }}</template>
                  </div>
                </div>
                <q-chip v-if="e.gebucht_anzahl" dense square color="green-1"
                  text-color="green-10" icon="check">
                  {{ e.gebucht_anzahl }}× · {{ fmtEuro(e.gebucht_summe) }}
                </q-chip>
                <q-chip v-else dense square color="grey-3" text-color="grey-9">
                  offen
                </q-chip>
              </div>
              <div class="text-caption text-grey q-mt-xs">
                <template v-if="e.gebucht_anzahl">
                  zuletzt gebucht {{ fmtDateTime(e.gebucht_am) }}
                </template>
                <template v-else-if="teilnehmerAnzahl(e)">
                  {{ teilnehmerAnzahl(e) }} von {{ kader.length }} zahlen mit
                  · Summe {{ fmtEuro(teilnehmerAnzahl(e) * Number(e.betrag)) }}
                </template>
                <template v-else>
                  Niemand zahlt mit — alle ausgenommen oder Kader leer.
                </template>
              </div>
              <div class="row items-center q-gutter-xs q-mt-sm">
                <q-btn v-if="!e.gebucht_anzahl" color="primary" unelevated dense no-caps
                  icon="playlist_add_check" label="Buchen" class="q-px-sm"
                  :disable="!deckel.aktiv || saving || !teilnehmerAnzahl(e)"
                  @click="bucheEvent(e)" />
                <q-btn v-else color="primary" outline dense no-caps icon="playlist_add"
                  label="Nachbuchen" class="q-px-sm"
                  :disable="!deckel.aktiv || saving" @click="bucheEvent(e)">
                  <q-tooltip>Bucht nur, wer noch keine Zeile hat</q-tooltip>
                </q-btn>
                <q-btn v-if="e.gebucht_anzahl" color="negative" outline dense no-caps
                  icon="undo" label="Storno" class="q-px-sm"
                  :disable="saving" @click="stornoEvent(e)">
                  <q-tooltip>Nimmt alle Buchungen dieser Sammlung zurück</q-tooltip>
                </q-btn>
                <q-space />
                <q-btn flat round dense icon="edit" :disable="saving"
                  @click="openEventDialog(e)">
                  <q-tooltip>Bearbeiten</q-tooltip>
                </q-btn>
                <q-btn flat round dense icon="delete" color="negative"
                  :disable="saving || !!e.gebucht_anzahl" @click="deleteEvent(e)">
                  <q-tooltip>{{ e.gebucht_anzahl
                    ? 'Erst stornieren' : 'Sammlung löschen' }}</q-tooltip>
                </q-btn>
              </div>
            </div>
          </q-card>
          <div v-if="!events.length" class="text-grey q-mb-md">
            Noch keine Sammlung angelegt.
          </div>
        </div>

        <!-- ---------- History: alle Buchungen ---------- -->
        <div v-if="verwaltenTab === 'history'">
          <!-- Volltextsuche + Filter auf ein Mitglied (#129) + Stornierte
               einblenden (#127); .row wickelt am Handy um, bewusst ohne
               q-gutter (Overflow-Falle) -->
          <div class="row items-center q-mb-sm">
            <q-input v-model="historySuche" dense outlined clearable debounce="400"
              class="q-mr-sm q-mb-xs" style="min-width: 180px; max-width: 280px"
              placeholder="Buchungstext suchen…">
              <template #prepend><q-icon name="search" /></template>
            </q-input>
            <q-select v-model="historyMitglied" :options="mitgliedOptionen" emit-value
              map-options dense outlined clearable options-dense class="q-mb-xs"
              style="min-width: 200px; max-width: 280px" label="Mitglied filtern" />
            <q-space />
            <q-toggle v-model="stornosZeigen" dense size="sm" label="Stornierte anzeigen" />
          </div>
          <q-list bordered separator class="rounded-borders q-mb-lg">
            <q-item v-for="b in alleBuchungen" :key="b.id"
              :class="{ 'tt-storniert': b.deleted_at }">
              <q-item-section>
                <q-item-label>
                  {{ b.mitglied_name }} — {{ buchungText(b) }}
                  <q-badge v-if="b.deleted_at" color="grey-6" label="storniert"
                    class="q-ml-xs" />
                </q-item-label>
                <q-item-label caption>
                  {{ fmtDateTime(b.created_at) }} · gebucht von {{ b.created_by }}
                  <template v-if="b.deleted_at">
                    · storniert {{ fmtDateTime(b.deleted_at) }} von {{ b.deleted_by }}
                  </template>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row items-center q-gutter-sm">
                  <span :class="[Number(b.betrag) < 0 ? 'text-negative' : 'text-positive',
                    { 'tt-durchgestrichen': b.deleted_at }]">
                    {{ fmtEuro(b.betrag) }}
                  </span>
                  <q-btn v-if="!b.deleted_at" flat round dense size="sm" icon="delete"
                    color="negative" :disable="saving" @click="storno(b)">
                    <q-tooltip>Stornieren{{ b.paar_ref ? ' (ganzes Paar)' : '' }}{{
                      b.typ === 'beitrag' ? ' — Beitrag wird damit erlassen' : '' }}</q-tooltip>
                  </q-btn>
                  <q-btn v-else flat round dense size="sm" icon="restore" color="primary"
                    :disable="saving" @click="restoreBuchung(b)">
                    <q-tooltip>Storno rückgängig{{ b.paar_ref ? ' (ganzes Paar)' : '' }}</q-tooltip>
                  </q-btn>
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-if="!alleBuchungen.length" class="text-grey q-mb-lg">Noch keine Buchungen.</div>
        </div>

        <!-- ---------- Stammdaten (nur Kader-Verwalter): Warte + Stammdaten ---------- -->
        <div v-if="verwaltenTab === 'stammdaten' && istVerwalter">
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

          <!-- Stammdaten direkt bearbeitbar (man ist ja schon im Stammdaten-Tab),
               kein Umweg über einen Dialog mehr. -->
          <div class="text-subtitle2 q-mb-sm">Stammdaten</div>
          <q-card flat bordered class="q-pa-md q-mb-md">
            <div class="q-gutter-sm">
              <q-input v-model="stammdatenForm.name" label="Name *" dense outlined />
              <q-toggle v-model="stammdatenForm.aktiv" label="Aktiv (Buchen möglich)" />
              <q-input v-model.number="stammdatenForm.beitrag" dense outlined type="number"
                step="0.50" min="0" label="Mannschaftsbeitrag €/Monat (leer = keiner)"
                hint="Gilt ab dem nächsten Monatsersten — auch eine Betragsänderung wirkt erst im Folgemonat" />
              <div class="text-overline text-grey q-mt-sm">Zahlungsempfänger (Bank)</div>
              <q-select v-model="stammdatenForm.zahlungsempfaenger" :options="verkaeuferOptionen"
                emit-value map-options dense outlined label="Ausgleichszahlungen an" />
              <q-input v-model="stammdatenForm.zahlweg_iban" label="IBAN" dense outlined />
              <q-input v-model="stammdatenForm.zahlweg_wero" label="WERO-Link" dense outlined />
              <q-input v-model="stammdatenForm.zahlweg_paypal" label="PayPal.me-Link" dense outlined />
              <div v-if="stammdatenError" class="vtb-fehler q-mt-sm">
                <q-icon name="warning" /> {{ stammdatenError }}
              </div>
              <div class="row q-mt-sm">
                <q-btn color="primary" unelevated no-caps label="Speichern"
                  :loading="saving" @click="saveStammdaten" />
              </div>
            </div>
          </q-card>

          <q-btn v-if="istAdmin" outline no-caps color="negative" icon="delete_forever"
            label="Teamkasse löschen" @click="loeschen" />
        </div>
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
          <q-toggle v-model="artikelForm.aktiv" label="Aktiv (im Angebot)" />
          <q-toggle v-model="artikelForm.nurWart"
            label="Nur der Wart bucht ihn (nicht am Tresen)" />
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

    <!-- Sammlung anlegen/bearbeiten (#181). Betrag und Ausnahme sind nach dem
         Buchen gesperrt: Sonst behauptete die Liste etwas anderes als die schon
         gebuchten Zeilen. Zum Korrigieren erst stornieren. -->
    <q-dialog v-model="eventDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card style="min-width: 340px">
        <q-card-section class="text-h6">
          {{ eventForm.id ? 'Sammlung bearbeiten' : 'Neue Sammlung' }}
        </q-card-section>
        <q-card-section class="q-gutter-sm">
          <q-input v-model="eventForm.name" dense outlined autofocus
            label="Anlass * (z. B. 60. Geburtstag Klaus)" />
          <q-input :model-value="fmtPreisInput(eventForm.betrag)" dense outlined
            label="Betrag je Kopf (€) *" inputmode="decimal" :disable="eventForm.gesperrt"
            @change="v => { eventForm.betrag = parsePreis(v) }" />
          <q-select v-model="eventForm.fuer" :options="fuerOptionen" emit-value map-options
            dense outlined options-dense clearable :disable="eventForm.gesperrt"
            label="Für wen gesammelt wird (zahlt nicht mit)" />
          <div class="text-caption text-grey">{{ eventHinweis }}</div>
          <div v-if="dialogError" class="text-negative text-caption">{{ dialogError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Abbrechen" v-close-popup />
          <q-btn color="primary" unelevated no-caps label="Speichern"
            :loading="saving" @click="saveEvent" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Gruppe bearbeiten (#167, v100): Name und Verkäufer. Ab wann das gilt,
         steht NICHT hier — das kommt aus dem Katalog-Zeitraum oben, damit es
         für diese Angabe nur einen Ort gibt. -->
    <q-dialog v-model="standDialog">
      <q-card style="min-width: 340px; max-width: 480px">
        <q-card-section class="text-subtitle1 text-weight-bold">
          Gruppe „{{ standGruppe?.name }}"
        </q-card-section>
        <q-card-section class="column q-gutter-sm">
          <q-input v-model="standForm.gruppeName" label="Name der Gruppe *" dense outlined />
          <q-select v-model="standForm.verkaeufer" :options="verkaeuferOptionen"
            emit-value map-options dense outlined options-dense label="Verkäufer" />
          <div class="text-caption text-grey">
            Gilt ab <b>{{ katalogTerminLabel }}</b> und für alle späteren Spieltage.
          </div>
          <div v-if="dialogError" class="text-negative text-caption">{{ dialogError }}</div>

          <template v-if="standListe.length > 1">
            <div class="text-subtitle2 q-mt-sm">Stände dieser Gruppe</div>
            <q-list bordered separator class="rounded-borders">
              <q-item v-for="st in standListe" :key="st.id">
                <q-item-section>
                  <q-item-label>{{ st.name }}</q-item-label>
                  <q-item-label caption>
                    gilt ab {{ st.gilt_ab_label }}
                    · verkauft {{ st.verkaeufer_name || 'das Team' }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </template>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat no-caps label="Abbrechen" v-close-popup />
          <q-btn color="primary" unelevated no-caps label="Speichern"
            :loading="saving" @click="saveStand" />
        </q-card-actions>
      </q-card>
    </q-dialog>

  </q-page>
</template>

<script setup>
defineOptions({ name: 'TeamkassePage' })

import { ref, computed, watch, onMounted } from 'vue'
import { useQuasar, copyToClipboard } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import { usePageRefresh } from 'src/composables/useRefresh'
import TerminWahl from 'components/TeamkasseTerminWahl.vue'

const $q = useQuasar()
const auth = useAuthStore()
const istAdmin = computed(() => auth.user?.role === 'admin')
const BASE = '/api/clubdeckel'

const geladen = ref(false)
const saving = ref(false)
const teams = ref([])
const papierkorb = ref([])
const selectedTeamId = ref(null)
const deckel = ref(null)
const tab = ref('tresen')
const verwaltenTab = ref('mannschaft')

const meineBuchungen = ref([])
const salden = ref([])
const teamSaldo = ref(0)
const katalog = ref([])
const gruppen = ref([])
const alleBuchungen = ref([])
const stornosZeigen = ref(false)  // History: stornierte Buchungen einblenden (#127)

// Termin-Zuordnung, Matrix und Auswertung (#167). Beide Reiter beziehen sich
// auf einen TERMIN — einen Tages-Ausschnitt gibt es nicht mehr, weil jede
// Buchung ohnehin an einem Termin hängt.
const termine = ref([])
const laufendTerminId = ref(null)
const buchenTermin = ref(null)
const auswTermin = ref(null)
const matrix = ref(null)       // Tab „Buchen"
const auswMatrix = ref(null)   // Tab „Termin"
const auswBuchungen = ref([])
// Sortiments-Stände je Gruppe (#167, v100)
// Zeitraum des Katalogs. undefined = „noch nicht gewählt" (dann setzt
// loadTermine die Vorgabe), null = „Aktuell", sonst die Termin-id.
const katalogTermin = ref(undefined)
const naechsterTerminId = ref(null)
const standDialog = ref(false)
const standGruppe = ref(null)
const standForm = ref({ gruppeName: '', verkaeufer: null })
const standListe = ref([])
const historyMitglied = ref(null)  // History: auf ein Mitglied gefiltert (#129)
const historySuche = ref('')       // History: Volltextsuche im Buchungstext (#129)
const warte = ref([])
const befreiungen = ref([])
const kader = ref([])
// Sammlungen (#181) + der generelle „macht nicht mit"-Haken je Mitglied
const events = ref([])
const eventOptOuts = ref([])

const dialogError = ref('')
const gruppeDialog = ref(false)
const gruppeForm = ref({})
const artikelDialog = ref(false)
const artikelForm = ref({})
const zahlungDialog = ref(false)
const zahlungForm = ref({})
const kaufDialog = ref(false)
const kaufForm = ref({})
const eventDialog = ref(false)
const eventForm = ref({})
const stammdatenForm = ref({})
const stammdatenError = ref('')  // Inline-Fehler im Stammdaten-Tab (kein Dialog mehr)
const neuerWart = ref(null)
const mitgliedSuche = ref('')

const methodeOptionen = [
  { label: 'bar', value: 'bar' },
  { label: 'unbar', value: 'unbar' },
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
    list.push({ mitglied_id: k.mitglied_id, name: k.name, imKader: true,
      saldo: saldoMap.get(k.mitglied_id) || 0 })
    seen.add(k.mitglied_id)
  }
  for (const s of salden.value) {
    if (!seen.has(s.mitglied_id)) {
      list.push({ mitglied_id: s.mitglied_id, name: `${s.mitglied_name} (Ex)`,
        imKader: false, saldo: Number(s.saldo) })
    }
  }
  return list.sort((a, b) => a.name.localeCompare(b.name))
})

// Salden-Ansicht (#127): Die „Bank" (Zahlungsempfänger) verwahrt das Geld — ihr
// negativer Saldo ist verwahrtes Bargeld, kein Schulden-Rang. Deshalb aus der
// Rangliste herausgezogen und separat gezeigt.
const bankMitgliedId = computed(() => deckel.value?.zahlungsempfaenger_mitglied_id ?? null)
const bankEintrag = computed(() => {
  if (bankMitgliedId.value == null) return null
  const s = salden.value.find(x => x.mitglied_id === bankMitgliedId.value)
  return s || {
    mitglied_id: bankMitgliedId.value,
    mitglied_name: deckel.value?.zahlungsempfaenger_name || 'Bank',
    saldo: 0, buchungen: 0,
  }
})
const saldenOhneBank = computed(() =>
  salden.value.filter(s => s.mitglied_id !== bankMitgliedId.value),
)

// Beitrag „aktiv" = Kader-Mitglied ohne Befreiung (Opt-out). Der Sammellauf bucht
// den Monatsbeitrag am Monatsersten für genau diese Mitglieder.
const befreitSet = computed(() => new Set(befreiungen.value.map(b => b.mitglied_id)))
const beitragAktivAnzahl = computed(() =>
  kader.value.filter(k => !befreitSet.value.has(k.mitglied_id)).length)

// Sammlungen (#181): „macht generell nicht mit" gilt am DECKEL, also für jede
// Sammlung. Wer mitzahlt, ist der Kader minus diese Menge minus der, für den
// gesammelt wird — dieselbe Rechnung, die das Backend beim Buchen anstellt.
const sammlungAusSet = computed(() =>
  new Set(eventOptOuts.value.map(o => o.mitglied_id)))

function teilnehmerAnzahl(e) {
  return kader.value.filter(k => !sammlungAusSet.value.has(k.mitglied_id)
    && k.mitglied_id !== e.fuer_mitglied_id).length
}

const fuerOptionen = computed(() =>
  kader.value.map(k => ({ label: k.name, value: k.mitglied_id })))

const eventHinweis = computed(() => {
  const f = eventForm.value
  if (f.gesperrt) return 'Schon gebucht — nur der Anlass lässt sich noch ändern.'
  const anzahl = teilnehmerAnzahl({ fuer_mitglied_id: f.fuer })
  const betrag = Number(f.betrag)
  const summe = Number.isFinite(betrag) ? fmtEuro(anzahl * betrag) : '—'
  return `${anzahl} von ${kader.value.length} zahlen mit · Summe ${summe}`
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
  // artikel_name/gegen_name sind eingefrorene Snapshots (Zeitpunkt der Buchung).
  const note = b.notiz ? ` · ${b.notiz}` : ''
  const von = b.gegen_name ? ` von ${b.gegen_name}` : ''
  const an = b.gegen_name ? ` an ${b.gegen_name}` : ''
  if (b.typ === 'konsum') {
    // Regelfall = Kauf vom Team; nur einen Mitglieds-Verkäufer extra ausweisen.
    const verk = b.gegen_name && b.gegen_name !== 'Team' ? ` · von ${b.gegen_name}` : ''
    return `${b.menge}× ${b.artikel_name || 'Artikel'}${verk}`
  }
  if (b.typ === 'verkauf' && b.artikel_name) return `Verkauf: ${b.menge}× ${b.artikel_name}${an}`
  if (b.typ === 'verkauf') return `Verkauf${an}${note}`
  if (b.typ === 'kauf') return `Kauf${von}${note}`
  if (b.typ === 'einkauf') return `Verkauf${an}${note}`
  if (b.typ === 'zahlung') {
    const dir = Number(b.betrag) >= 0 ? an : von   // +Betrag = Zahler, −Betrag = Empfänger
    return `Zahlung${dir}${note}`
  }
  if (b.typ === 'beitrag') return b.notiz || `Mannschaftsbeitrag ${b.beitrag_monat}`
  // Sammlung (#181): notiz ist der eingefrorene Anlass — auch dann noch lesbar,
  // wenn die Sammlung längst umbenannt oder geprunt ist.
  if (b.typ === 'event') return `Sammlung: ${b.notiz || 'ohne Anlass'}`
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
      const gespeichert = Number(localStorage.getItem('vtb_teamkasse_team'))
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
    fehler(e, 'Teamkasse konnte nicht geladen werden')
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
    const params = { termin_id: katalogTermin.value || undefined }
    const [a, g] = await Promise.all([
      api.get(`${BASE}/${deckel.value.id}/artikel`,
        { params: { ...params, alle: true } }),
      api.get(`${BASE}/${deckel.value.id}/gruppen`, { params }),
    ])
    katalog.value = a.data
    gruppen.value = g.data
  } catch { katalog.value = []; gruppen.value = [] }
}

async function loadAlleBuchungen() {
  if (!deckel.value || !istWart.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/buchungen`,
      { params: { alle: true, limit: 100, mit_storniert: stornosZeigen.value,
                  mitglied_id: historyMitglied.value ?? undefined,
                  suche: historySuche.value?.trim() || undefined } })
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

async function loadEvents() {
  if (!deckel.value || !istWart.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/events`)
    events.value = data
  } catch { events.value = [] }
}

async function loadEventOptOuts() {
  if (!deckel.value || !istWart.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/event-opt-out`)
    eventOptOuts.value = data
  } catch { eventOptOuts.value = [] }
}

async function loadKader() {
  if (!deckel.value || !istWart.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/kader`)
    kader.value = data
  } catch { kader.value = [] }
}

// ------------------------------------------- Termin, Matrix, Auswertung (#167)
/** Query-Parameter des gewählten Ausschnitts. Ohne Termin gibt es nichts zu
 *  zeigen — die Aufrufer laden dann gar nicht erst. */
function terminParams(terminId) {
  return terminId != null ? { termin_id: terminId } : null
}

/** Gebucht wird immer auf einen Termin — ohne gewählten Termin gibt es nichts,
 *  dem der Strich zugeordnet werden könnte. */
const buchenBuchbar = computed(() => buchenTermin.value != null)

function zelle(mitgliedId, artikelId) {
  return matrix.value?.zellen?.[`${mitgliedId}:${artikelId}`] || { anzahl: 0 }
}

// ------------------------------------------------ Zeitraum des Katalogs (#167)
// Auswahl: „Aktuell" plus die Spieltage. Ein Punkt markiert die Spieltage, für
// die schon ein eigener Stand hinterlegt ist.
const katalogTerminOptionen = computed(() => {
  const gepflegt = new Set(gruppen.value.flatMap(g => g.stand_termine || []))
  return [
    { label: 'Aktuell (Tresen)', value: null },
    ...termine.value.map(t => ({
      // ● = für diesen Spieltag ist schon ein eigener Stand hinterlegt
      label: (gepflegt.has(t.id) ? `● ${t.label}` : t.label)
        + (t.id === naechsterTerminId.value ? ' · nächstes' : ''),
      value: t.id,
    })),
  ]
})

function waehleKatalogTermin(wert) {
  katalogTermin.value = wert
  loadKatalog()
}

/** Spieltage entlang der ZEITACHSE. Die Liste vom Backend kommt jüngste zuerst;
 *  geblättert wird aber vorwärts/rückwärts in der Zeit. */
const katalogIdsChrono = computed(() => [...termine.value]
  .sort((a, b) => (a.beginn || '').localeCompare(b.beginn || ''))
  .map(t => t.id))

/** Ziel eines Schritts (−1 = vorheriger, +1 = nächster) oder null am Rand.
 *  „Aktuell (Tresen)" ist kein Spieltag und liegt deshalb nirgends in der
 *  Reihe: Von dort aus landet ein Schritt vorwärts auf dem nächsten Ereignis
 *  — derselbe Bezugspunkt, mit dem der Katalog aufmacht — und einer zurück auf
 *  dem davor. */
function katalogZielId(schritt) {
  const ids = katalogIdsChrono.value
  const jetzt = ids.indexOf(katalogTermin.value ?? null)
  const anker = ids.indexOf(naechsterTerminId.value)
  const ziel = jetzt >= 0 ? jetzt + schritt
    : anker >= 0 ? anker + (schritt > 0 ? 0 : -1)
      : (schritt > 0 ? 0 : ids.length - 1)
  return ziel >= 0 && ziel < ids.length ? ids[ziel] : null
}

const katalogTerminLabel = computed(() => {
  if (!katalogTermin.value) return 'jetzt'
  return termine.value.find(t => t.id === katalogTermin.value)?.label ?? 'dem Spieltag'
})

/** Zeigt diese Gruppe einen geerbten Stand? Dann ist für den gewählten Zeitraum
 *  noch nichts Eigenes hinterlegt und eine Änderung legt hier einen neuen an. */
function standUebernommen(gruppe) {
  return !!katalogTermin.value
    && gruppe.gilt_ab_termin_id !== katalogTermin.value
}

const auswArtikel = computed(() =>
  (auswMatrix.value?.artikel || []).filter(a => a.summe_anzahl > 0))
const auswMitglieder = computed(() =>
  (auswMatrix.value?.mitglieder || []).filter(m => m.anzahl > 0))

async function loadTermine() {
  if (!deckel.value) return
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/termine`)
    termine.value = data.termine
    laufendTerminId.value = data.laufend_id
    naechsterTerminId.value = data.naechster_id
    // Vorgabe des Katalogs: das nächste Ereignis. Geändert wird die Speisekarte
    // in aller Regel kurz vor oder zu Beginn des Events — nicht rückwirkend.
    if (katalogTermin.value === undefined) {
      katalogTermin.value = data.naechster_id ?? null
    }
    // Vorbelegung ist der aktuelle Termin — derselbe, auf den auch der Tresen
    // bucht. Ein Rückfall auf „den jüngsten aus der Liste" wäre falsch: Die
    // Liste reicht in die Zukunft, und ein Strich landete dann auf einem Spiel,
    // das noch gar nicht stattgefunden hat. Ohne laufenden Termin ist das
    // nächste Ereignis die sinnvollste Vorgabe.
    const vorgabe = data.laufend_id ?? data.naechster_id ?? data.termine[0]?.id ?? null
    if (buchenTermin.value == null) buchenTermin.value = vorgabe
    if (auswTermin.value == null) auswTermin.value = vorgabe
  } catch { termine.value = []; laufendTerminId.value = null }
}

async function loadMatrix() {
  if (!deckel.value || !istWart.value) return
  const params = terminParams(buchenTermin.value)
  if (!params) { matrix.value = null; return }
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/matrix`, { params })
    matrix.value = data
  } catch { matrix.value = null }
}

async function loadAuswertung() {
  if (!deckel.value || !istWart.value) return
  const params = terminParams(auswTermin.value)
  if (!params) { auswMatrix.value = null; auswBuchungen.value = []; return }
  try {
    const [m, b] = await Promise.all([
      api.get(`${BASE}/${deckel.value.id}/matrix`, { params }),
      api.get(`${BASE}/${deckel.value.id}/buchungen`,
        { params: { ...params, alle: true, limit: 200, mit_storniert: true } }),
    ])
    auswMatrix.value = m.data
    auswBuchungen.value = b.data
  } catch { auswMatrix.value = null; auswBuchungen.value = [] }
}

async function matrixBuchen(mitglied, artikel) {
  saving.value = true
  try {
    await api.post(`${BASE}/${deckel.value.id}/konsum`, {
      artikel_id: artikel.id, menge: 1, mitglied_id: mitglied.mitglied_id,
      // Immer ausdrücklich auf den gewählten Termin — im Buchen-Gitter gibt es
      // keinen anderen Bezug.
      termin_id: buchenTermin.value,
    })
    await Promise.all([loadMatrix(), loadDeckel()])
  } catch (e) {
    fehler(e, 'Buchung fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function matrixZurueck(mitglied, artikel) {
  saving.value = true
  try {
    await api.delete(`${BASE}/${deckel.value.id}/konsum/${artikel.id}`,
      { params: { mitglied_id: mitglied.mitglied_id,
                  ...terminParams(buchenTermin.value) } })
    await Promise.all([loadMatrix(), loadDeckel()])
  } catch (e) {
    fehler(e, 'Zurücknehmen fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function stornoImAusschnitt(buchung) {
  saving.value = true
  try {
    await api.delete(`${BASE}/${deckel.value.id}/buchungen/${buchung.id}`)
    await loadAuswertung()
  } catch (e) {
    fehler(e, 'Stornieren fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function restoreImAusschnitt(buchung) {
  saving.value = true
  try {
    await api.post(`${BASE}/${deckel.value.id}/buchungen/${buchung.id}/restore`)
    await loadAuswertung()
  } catch (e) {
    fehler(e, 'Wiederherstellen fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function loadTabDaten() {
  if (!deckel.value) return
  if (tab.value === 'tresen') await loadMeineBuchungen()
  else if (tab.value === 'salden') await loadSalden()
  else if (tab.value === 'katalog') {
    await Promise.all([loadTermine(), loadKader()])
    await loadKatalog()
  }
  else if (tab.value === 'buchen') {
    await loadTermine()
    await loadMatrix()
  } else if (tab.value === 'termin') {
    await loadTermine()
    await loadAuswertung()
  } else if (tab.value === 'verwalten') {
    await Promise.all([loadAlleBuchungen(), loadSalden(), loadKader(), loadWarte(),
      loadBefreiungen(), loadEvents(), loadEventOptOuts()])
  }
}

async function loadPapierkorb() {
  if (!istAdmin.value) return
  try {
    const { data } = await api.get(`${BASE}/papierkorb`)
    papierkorb.value = data
  } catch { papierkorb.value = [] }
}

async function refreshAll() {
  await loadTeams()
  await loadDeckel()
  await loadTabDaten()
  await loadPapierkorb()
}

watch(selectedTeamId, async (id) => {
  if (id != null) localStorage.setItem('vtb_teamkasse_team', String(id))
  tab.value = 'tresen'
  verwaltenTab.value = 'mannschaft'
  historyMitglied.value = null
  historySuche.value = ''
  // Termine gehören zur Mannschaft — der Ausschnitt des alten Teams passt nicht.
  termine.value = []
  laufendTerminId.value = null
  katalogTermin.value = undefined
  buchenTermin.value = null
  auswTermin.value = null
  matrix.value = null
  auswMatrix.value = null
  await loadDeckel()
  await loadTabDaten()
})

watch(tab, loadTabDaten)
watch(stornosZeigen, loadAlleBuchungen)  // #127: Ein-/Ausblenden neu laden
watch(historyMitglied, loadAlleBuchungen)  // #129: Mitglieder-Filter neu laden
watch(historySuche, loadAlleBuchungen)     // #129: Volltextsuche (Input debounced)
watch(buchenTermin, loadMatrix)                            // #167
watch(auswTermin, loadAuswertung)                          // #167

// #129: Klick auf ein Mitglied in der Mannschaftsliste → gefilterte History
function openHistoryFuer(m) {
  historyMitglied.value = m.mitglied_id
  verwaltenTab.value = 'history'
}
// Stammdaten-Unter-Tab: Inline-Formular mit den aktuellen Deckel-Werten füllen
watch(verwaltenTab, (v) => {
  if (v === 'stammdaten') initStammdatenForm()
})

onMounted(refreshAll)
usePageRefresh(refreshAll)

// ------------------------------------------------------------- Einschalten
async function einschalten() {
  const team = aktuellesTeam.value
  if (!team) return
  saving.value = true
  try {
    await api.post(`${BASE}/teams/${team.mannschaft_id}`, {})
    $q.notify({ type: 'positive', message: 'Teamkasse eingeschaltet', timeout: 1200 })
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

async function restoreBuchung(buchung) {
  saving.value = true
  try {
    await api.post(`${BASE}/${deckel.value.id}/buchungen/${buchung.id}/restore`)
    $q.notify({ type: 'positive', message: 'Buchung wiederhergestellt', timeout: 1200 })
    await Promise.all([loadDeckel(), loadMeineBuchungen(), loadAlleBuchungen(),
      tab.value === 'salden' || tab.value === 'verwalten' ? loadSalden() : Promise.resolve()])
  } catch (e) {
    fehler(e, 'Wiederherstellen fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function undoArtikel(a) {
  if (!a.mein_termin_anzahl) return
  saving.value = true
  try {
    // Auf den laufenden Termin eingegrenzt — die Strichliste zeigt genau ihn,
    // also muss auch das Zurücknehmen dort greifen.
    await api.delete(`${BASE}/${deckel.value.id}/konsum/${a.id}`,
      { params: { termin_id: deckel.value.laufender_termin?.id } })
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
        aktiv: !!artikel.aktiv, nurWart: !!artikel.nur_wart,
        version: artikel.version }
    : { id: null, name: '', preis: null,
        gruppe: preselectGruppe !== undefined ? preselectGruppe
          : (gruppen.value[0]?.id ?? null),
        sortierung: 0, aktiv: true, nurWart: false }
  artikelDialog.value = true
}

// --- Inline-Sofortspeicher im Katalog (Toggle/Name/Preis) ---
// Änderungen am Sortiment beziehen sich IMMER auf den Katalog-Zeitraum oben
// (#167, v100). Dadurch bleibt das Bearbeiten inline und schnell: Der Wart stellt
// einmal ein, welche Speisekarte er vor sich hat, und ändert dann frei darin.
function repriceArtikel(a, preis) {
  const p = parsePreis(preis)
  if (!(p > 0)) {
    $q.notify({ type: 'negative', message: 'Preis muss größer 0 sein' })
    loadKatalog()
    return
  }
  if (p === Number(a.preis)) return
  return _saveArtikelStand(a, { preis: p })
}

function renameArtikelStand(a, name) {
  const n = (name || '').trim()
  if (!n || n === a.name) { loadKatalog(); return }
  return _saveArtikelStand(a, { name: n })
}

/** Am Tresen sichtbar ⇄ nur in der Buchen-Matrix (#167). Gehört wie Preis und
 *  Bezeichnung zum Stand des gewählten Spieltags. */
function toggleArtikelNurWart(a, v) {
  return _saveArtikelStand(a, { nur_wart: v })
}

function toggleArtikelAktivStand(a, v) {
  if (!!a.aktiv === v) return
  return _saveArtikelStand(a, { aktiv: v })
}

/** Wurde beim gewählten Spieltag schon gebucht? Dann fragen, ob die vorhandenen
 *  Striche mit umgestellt werden sollen (#167) — der klassische Fall „zu spät
 *  eingetragen, es wurde schon getippt". Ohne Buchungen keine Rückfrage.
 *  Liefert `null`, wenn der Nutzer abbricht. */
async function _uebernahmeFrage() {
  if (!katalogTermin.value) return false
  let stand
  try {
    const { data } = await api.get(`${BASE}/${deckel.value.id}/sortiment-status`,
      { params: { termin_id: katalogTermin.value } })
    stand = data
  } catch { return false }
  if (!stand.buchungen) return false
  return new Promise(resolve => {
    $q.dialog({
      title: 'Es wurde hier schon gebucht',
      message: `Bei ${katalogTerminLabel.value} sind bereits ` +
        `${stand.buchungen} Strich(e) über ${fmtEuro(stand.betrag)} gebucht. ` +
        'Sollen die auf den neuen Stand umgestellt werden — also mit neuem ' +
        'Preis, neuer Bezeichnung und neuem Verkäufer?',
      options: {
        type: 'radio',
        model: 'ja',
        items: [
          { label: 'Ja, bestehende Striche umstellen', value: 'ja' },
          { label: 'Nein, erst ab jetzt gelten lassen', value: 'nein' },
        ],
      },
      cancel: { label: 'Abbrechen', flat: true, noCaps: true },
      ok: { label: 'Weiter', color: 'primary', unelevated: true, noCaps: true },
    }).onOk(wahl => resolve(wahl === 'ja')).onCancel(() => resolve(null))
  })
}

async function _saveArtikelStand(a, patch) {
  const uebernehmen = await _uebernahmeFrage()
  if (uebernehmen === null) { loadKatalog(); return }
  saving.value = true
  try {
    const { data } = await api.put(`${BASE}/${deckel.value.id}/artikel/${a.id}`, {
      name: a.name, preis: Number(a.preis), gruppe_id: a.gruppe_id,
      aktiv: !!a.aktiv, nur_wart: !!a.nur_wart, sortierung: a.sortierung || 0,
      ab_termin_id: katalogTermin.value ?? null, expected_version: a.version,
      bestand_uebernehmen: uebernehmen,
      ...patch,
    })
    _meldeUmstellung(data)
    await Promise.all([loadKatalog(), loadDeckel()])
  } catch (e) {
    fehler(e, 'Speichern fehlgeschlagen')
    loadKatalog()   // Eingabefeld auf den gespeicherten Stand zurücksetzen
  } finally {
    saving.value = false
  }
}

function _meldeUmstellung(data) {
  if (data?.umgestellt) {
    $q.notify({ type: 'positive', timeout: 2500,
      message: `${data.umgestellt} bestehende Buchung(en) umgestellt` })
  }
}

/** Gruppen-Dialog: Name und Verkäufer. Der Spieltag steht NICHT hier — er kommt
 *  aus dem Katalog-Zeitraum, damit es nur einen Ort für diese Angabe gibt. */
async function openGruppenStand(gruppe) {
  standGruppe.value = gruppe
  standForm.value = {
    gruppeName: gruppe.name,
    verkaeufer: gruppe.verkaeufer_mitglied_id ?? null,
  }
  dialogError.value = ''
  standListe.value = []
  standDialog.value = true
  await ladeStaende(gruppe.id)
}

async function ladeStaende(gruppeId) {
  try {
    const { data } = await api.get(
      `${BASE}/${deckel.value.id}/gruppen/${gruppeId}/staende`)
    standListe.value = data
  } catch { standListe.value = [] }
}

async function saveStand() {
  const f = standForm.value
  const g = standGruppe.value
  if (!f.gruppeName.trim()) {
    dialogError.value = 'Name ist erforderlich.'
    return
  }
  const uebernehmen = await _uebernahmeFrage()
  if (uebernehmen === null) return
  saving.value = true
  dialogError.value = ''
  try {
    const { data } = await api.put(`${BASE}/${deckel.value.id}/gruppen/${g.id}`, {
      name: f.gruppeName.trim(), verkaeufer_mitglied_id: f.verkaeufer,
      aktiv: !!g.aktiv, sortierung: g.sortierung || 0,
      ab_termin_id: katalogTermin.value ?? null, expected_version: g.version,
      bestand_uebernehmen: uebernehmen,
    })
    _meldeUmstellung(data)
    standDialog.value = false
    await Promise.all([loadKatalog(), loadDeckel()])
  } catch (e) {
    dialogError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
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
  // Auch das Ein-/Ausschalten gehört zum Stand des gewählten Zeitraums.
  return _saveGruppeInline(g, { aktiv: v, ab_termin_id: katalogTermin.value ?? null })
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
      aktiv: f.aktiv, nur_wart: !!f.nurWart, sortierung: f.sortierung || 0 }
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

// „Beitrag aktiv"-Schalter je Mitglied (Opt-out): aktiv → Befreiung setzen,
// befreit → Befreiung aufheben. Wirkt ab dem laufenden Monat.
async function toggleBeitrag(m) {
  const istAktiv = !befreitSet.value.has(m.mitglied_id)
  try {
    if (istAktiv) await api.put(`${BASE}/${deckel.value.id}/befreiungen/${m.mitglied_id}`)
    else await api.delete(`${BASE}/${deckel.value.id}/befreiungen/${m.mitglied_id}`)
    await loadBefreiungen()
    $q.notify({ type: 'positive', timeout: 1000,
      message: istAktiv ? `${m.name}: Beitrag deaktiviert`
        : `${m.name}: Beitrag aktiv` })
  } catch (e) {
    fehler(e, 'Änderung fehlgeschlagen')
  }
}

// „Macht bei Sammlungen mit"-Schalter je Mitglied (#181): an → Opt-out setzen,
// ausgenommen → Opt-out aufheben. Wirkt auf alle künftigen Sammlungen; schon
// gebuchte Zeilen bleiben stehen (dafür gibt es den Storno).
async function toggleSammlung(m) {
  const machtMit = !sammlungAusSet.value.has(m.mitglied_id)
  try {
    if (machtMit) await api.put(`${BASE}/${deckel.value.id}/event-opt-out/${m.mitglied_id}`)
    else await api.delete(`${BASE}/${deckel.value.id}/event-opt-out/${m.mitglied_id}`)
    await loadEventOptOuts()
    $q.notify({ type: 'positive', timeout: 1000,
      message: machtMit ? `${m.name}: nimmt an Sammlungen nicht mehr teil`
        : `${m.name}: nimmt wieder an Sammlungen teil` })
  } catch (e) {
    fehler(e, 'Änderung fehlgeschlagen')
  }
}

// ------------------------------------------------------------- Sammlungen
function openEventDialog(event = null) {
  dialogError.value = ''
  eventForm.value = event
    ? { id: event.id, name: event.name, betrag: Number(event.betrag),
        fuer: event.fuer_mitglied_id, version: event.version,
        gesperrt: !!event.gebucht_anzahl }
    : { id: null, name: '', betrag: null, fuer: null, gesperrt: false }
  eventDialog.value = true
}

async function saveEvent() {
  const f = eventForm.value
  if (!f.name?.trim()) {
    dialogError.value = 'Anlass ist erforderlich.'
    return
  }
  if (!Number.isFinite(Number(f.betrag)) || Number(f.betrag) <= 0) {
    dialogError.value = 'Betrag muss größer als 0 sein.'
    return
  }
  saving.value = true
  try {
    const body = { name: f.name.trim(), betrag: Number(f.betrag),
      fuer_mitglied_id: f.fuer ?? null }
    if (f.id) await api.put(`${BASE}/${deckel.value.id}/events/${f.id}`,
      { ...body, expected_version: f.version })
    else await api.post(`${BASE}/${deckel.value.id}/events`, body)
    eventDialog.value = false
    await loadEvents()
  } catch (e) {
    dialogError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

async function bucheEvent(e) {
  saving.value = true
  try {
    const { data } = await api.post(`${BASE}/${deckel.value.id}/events/${e.id}/buchen`)
    $q.notify({ type: data.gebucht ? 'positive' : 'info', timeout: 1600,
      message: data.gebucht
        ? `${e.name}: ${data.gebucht} Buchungen angelegt`
        : `${e.name}: alle Teilnehmer waren schon gebucht` })
    await Promise.all([loadEvents(), loadDeckel(), loadSalden(), loadAlleBuchungen()])
  } catch (err) {
    fehler(err, 'Buchen fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function stornoEvent(e) {
  saving.value = true
  try {
    const { data } = await api.post(`${BASE}/${deckel.value.id}/events/${e.id}/storno`)
    $q.notify({ type: 'positive', timeout: 1600,
      message: `${e.name}: ${data.storniert} Buchungen storniert` })
    await Promise.all([loadEvents(), loadDeckel(), loadSalden(), loadAlleBuchungen()])
  } catch (err) {
    fehler(err, 'Storno fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

async function deleteEvent(e) {
  saving.value = true
  try {
    await api.delete(`${BASE}/${deckel.value.id}/events/${e.id}`)
    $q.notify({ type: 'positive', message: 'Sammlung gelöscht', timeout: 1200 })
    await loadEvents()
  } catch (err) {
    fehler(err, 'Löschen fehlgeschlagen')
  } finally {
    saving.value = false
  }
}

function initStammdatenForm() {
  const d = deckel.value
  if (!d) return
  stammdatenError.value = ''
  stammdatenForm.value = {
    name: d.name, aktiv: !!d.aktiv,
    beitrag: d.beitrag != null ? Number(d.beitrag) : null,
    zahlungsempfaenger: d.zahlungsempfaenger_mitglied_id,
    zahlweg_iban: d.zahlweg_iban || '', zahlweg_wero: d.zahlweg_wero || '',
    zahlweg_paypal: d.zahlweg_paypal || '',
  }
}

async function saveStammdaten() {
  const f = stammdatenForm.value
  if (!f.name?.trim()) {
    stammdatenError.value = 'Name ist erforderlich.'
    return
  }
  saving.value = true
  stammdatenError.value = ''
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
    $q.notify({ type: 'positive', message: 'Stammdaten gespeichert', timeout: 1200 })
    await refreshAll()
    initStammdatenForm()  // Formular auf den gespeicherten Stand zurücksetzen
  } catch (e) {
    stammdatenError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
}

// Admin: kompletter Soft-Delete (über den Papierkorb wiederherstellbar).
function loeschen() {
  $q.dialog({
    title: 'Teamkasse löschen',
    message: `Die Teamkasse „${deckel.value.name}" komplett löschen? ` +
      'Buchungen, Katalog, Warte und Beiträge werden entfernt. ' +
      'Als Admin kannst du ihn über den Papierkorb wiederherstellen.',
    cancel: true,
    ok: { label: 'Löschen', color: 'negative', noCaps: true },
  }).onOk(async () => {
    try {
      await api.delete(`${BASE}/${deckel.value.id}`)
      $q.notify({ type: 'positive', message: 'Teamkasse gelöscht', timeout: 1500 })
      deckel.value = null
      await refreshAll()
    } catch (e) {
      fehler(e, 'Löschen fehlgeschlagen')
    }
  })
}

// Admin: eine gelöschte Teamkasse aus dem Papierkorb wiederherstellen.
function wiederherstellen(eintrag) {
  $q.dialog({
    title: 'Teamkasse wiederherstellen',
    message: `Die gelöschte Teamkasse von „${eintrag.mannschaft_name}" ` +
      'komplett wiederherstellen (inkl. Buchungen, Katalog, Warte)?',
    cancel: true,
    ok: { label: 'Wiederherstellen', color: 'primary', noCaps: true },
  }).onOk(async () => {
    try {
      await api.post(`${BASE}/papierkorb/${eintrag.id}/restore`)
      $q.notify({ type: 'positive', message: 'Teamkasse wiederhergestellt', timeout: 1500 })
      selectedTeamId.value = eintrag.mannschaft_id
      await refreshAll()
    } catch (e) {
      fehler(e, 'Wiederherstellen fehlgeschlagen')
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
// Hinweis in der Gruppen-Kopfzeile, dass der gezeigte Stand von einem früheren
// Spieltag geerbt ist — gedämpft, weil es der Normalfall ist.
.tt-gruppe__erbe {
  opacity: 0.65;
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

// Zahlweg-Karte: lange URLs (WERO/PayPal) bzw. die IBAN dürfen die Karte NICHT
// sprengen (#126) — sonst wird die ganze q-page überbreit und scrollt am Handy.
// Captions einzeilig kürzen; die Links bleiben klickbar, die IBAN tap-kopierbar.
.tt-zahlkarte :deep(.q-item__section--main) {
  min-width: 0;
}
.tt-zahlkarte :deep(.q-item__label--caption) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

// Am Handy stapelt :inline-label die Tabs (Icon über Label). Zusätzlich weniger
// Polster/kleinere Labels, damit die vtb-tabs-Pille (scrollt nicht) mit allen
// Reitern nebeneinander passt (#126).
@media (max-width: 599px) {
  .vtb-tabs :deep(.q-tab) {
    padding: 0 10px;
  }
  .vtb-tabs :deep(.q-tab__label) {
    font-size: 11px;
  }
}

// Stornierte History-Zeilen gedimmt, Betrag durchgestrichen (#127)
.tt-storniert {
  opacity: 0.6;
}
.tt-durchgestrichen {
  text-decoration: line-through;
}

// Bank-Karte (Zahlungsempfänger) in den Salden mit gelbem Akzent abgesetzt (#127)
.tt-bank-card {
  border-left: 4px solid $akzent;
}

// ── Buchungsmatrix (#167) ────────────────────────────────────────────────────
// Die Tab-Pille wird mit den Wart-Reitern breiter als ein Handy-Schirm. Sie
// scrollt in sich; die Scrollbar selbst bleibt unsichtbar, sonst frisst sie
// Höhe unter den Tabs.
.tt-tabs-scroll {
  overflow-x: auto;
  scrollbar-width: none;
  min-width: 0;
}
.tt-tabs-scroll::-webkit-scrollbar {
  display: none;
}

// Gitter Mitglied × Artikel: scrollt waagerecht in seinem eigenen Behälter,
// damit die q-page das nie tut. Die Namensspalte bleibt beim Scrollen stehen —
// ohne sie weiß niemand mehr, wessen Zeile er antippt.
//
// Die Kopf- und Summenzeile heben sich über Linien und Fettschrift ab, NICHT
// über eine Hintergrundtönung: Eine klebende Zelle muss deckend sein, und eine
// Tönung ließe sich mit dem geerbten Kartenhintergrund nicht sauber überlagern.
// Linien tragen den Unterschied in allen drei Themes ohne Sonderregeln.
// WICHTIG: Die Karte behält ihren eigenen (themengefärbten) Hintergrund. Ein
// `background: inherit` HIER würde vom Seitengrund erben — im Theme „VTB" also
// Gelb statt Wappenblau. Erben dürfen nur die Nachfahren, damit die Kette bis
// zur klebenden Zelle die Kartenfläche transportiert.
.tt-matrix-karte {
  overflow-x: auto;
}
.tt-matrix {
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
  background: inherit;

  tr {
    background: inherit;
  }
  th,
  td {
    padding: 6px 8px;
    text-align: center;
    white-space: nowrap;
    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  }
  thead th {
    font-weight: 600;
  }
  .tt-matrix__summen th {
    border-bottom-width: 2px;
    border-bottom-color: rgba(0, 0, 0, 0.24);
  }
  tbody tr:last-child th,
  tbody tr:last-child td {
    border-bottom: none;
  }
}
.tt-matrix__name {
  position: sticky;
  left: 0;
  z-index: 1;
  text-align: left !important;
  min-width: 130px;
  max-width: 170px;
  overflow: hidden;
  // Deckend über den durchscrollenden Spalten – erbt die Fläche der q-card und
  // stimmt damit in „Hell" (weiß), „VTB" (Wappenblau) und „Dunkel" (Navy).
  background: inherit;
  border-right: 1px solid rgba(0, 0, 0, 0.08);
}
.tt-matrix thead .tt-matrix__name {
  z-index: 2;
}
.tt-matrix__artikel {
  font-weight: 600;
}
// Abgesagte bleiben bedienbar (jemand kommt doch), treten aber zurück.
.tt-matrix__abgesagt {
  opacity: 0.55;
}
.tt-matrix__add {
  min-width: 40px;
}

// Auf dunklen Flächen (Theme „Dunkel" und „VTB") tragen helle Linien.
body.body--dark,
body.vtb-theme--vtb {
  .tt-matrix th,
  .tt-matrix td {
    border-bottom-color: rgba(255, 255, 255, 0.12);
  }
  .tt-matrix .tt-matrix__summen th {
    border-bottom-color: rgba(255, 255, 255, 0.34);
  }
  .tt-matrix__name {
    border-right-color: rgba(255, 255, 255, 0.12);
  }
}
</style>
