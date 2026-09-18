<template>
  <q-page padding>
    <div class="text-h5 q-mb-xs">Erste Schritte</div>
    <div class="text-body2 text-grey q-mb-md">
      Das Wichtigste auf einen Blick. Du siehst hier nur die Bereiche, die es für dich auch gibt.
    </div>

    <!-- ── Für alle ────────────────────────────────────────────────────── -->

    <ProfilPanel icon="login" titel="Anmelden & Passwort"
      info="Login-Link, Passwort und der 30-Tage-Haken" class="q-mb-sm" offen>
      <HilfeAnmelden />
    </ProfilPanel>

    <ProfilPanel icon="install_mobile" titel="App aufs Handy holen"
      info="Je nach Gerät und Browser anders" class="q-mb-sm">
      <p>
        Die App lässt sich wie eine richtige App auf dem Gerät ablegen: eigenes Symbol,
        Vollbild ohne Browserleiste und die Zahl offener Aufgaben direkt am Symbol.
      </p>
      <p class="hilfe-wichtig">
        Auf iPhone und iPad funktionieren Push-Nachrichten <b>nur</b>, wenn die App so
        abgelegt ist. Im normalen Browser-Tab kommt dort nichts an.
      </p>
      <p>Wie das geht, hängt vom Browser ab — such dir deinen:</p>
      <q-list dense class="hilfe-liste">
        <q-item v-for="w in installWege" :key="w.titel" class="q-px-none">
          <q-item-section avatar class="hilfe-liste__icon">
            <q-icon :name="w.icon" size="20px" color="primary" />
          </q-item-section>
          <q-item-section>
            <q-item-label class="text-weight-bold">{{ w.titel }}</q-item-label>
            <q-item-label caption class="hilfe-liste__text">{{ w.text }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <p class="text-caption text-grey q-mt-sm">
        Kein <i>App installieren</i> im Menü? Dann ist sie entweder schon abgelegt, oder
        dein Browser bietet es nicht an — mit einem Lesezeichen läuft die App genauso,
        nur eben im Browserfenster.
      </p>
    </ProfilPanel>

    <ProfilPanel icon="notifications" titel="Benachrichtigungen einstellen"
      info="E-Mail, Matrix oder Push — und pro Gerät" class="q-mb-sm">
      <p>
        Unter <b>Mein Profil → Benachrichtigungen</b> legst du deinen <b>Hauptkanal</b> fest:
        E-Mail, Matrix oder nur Push. Darüber kommen zum Beispiel Termin-Erinnerungen und
        Nachrichten zu deinen Tickets.
      </p>
      <p>
        <b>Push schaltest du je Gerät einzeln frei</b> („Push auf diesem Gerät aktivieren“).
        Ein neues Handy weiß also nichts von der Freigabe auf dem alten. Mit
        <i>Test-Nachricht</i> prüfst du sofort, ob es klappt.
      </p>
      <p class="text-caption text-grey">
        Auf dem iPhone vorher die App auf den Home-Bildschirm legen — siehe oben.
      </p>
    </ProfilPanel>

    <ProfilPanel icon="person" titel="Mein Profil" info="Deine Daten, Geräte und Rechte"
      class="q-mb-sm">
      <p>Unter <b>Mein Profil</b> steckt mehr, als der Name vermuten lässt:</p>
      <ul class="hilfe-ul">
        <li><b>Meine Kontaktdaten</b> — Anschrift und Erreichbarkeit aktuell halten.</li>
        <li><b>Meine Bankverbindung</b> — IBAN und SEPA-Einzugserlaubnis für den Beitrag.</li>
        <li><b>Terminkalender</b> — Adresse erzeugen und deine Termine im eigenen
          Kalender abonnieren (Handy, Outlook, Google). Läuft automatisch mit.</li>
        <li><b>Meine Geräte</b> — wo du überall angemeldet bist, einzeln oder alle
          abmeldbar.</li>
        <li><b>Mein Zugang</b> — dein Chip und deine letzten Zutritte.</li>
        <li><b>Meine Berechtigungen</b> — was du in der App darfst und woher das kommt.</li>
      </ul>
    </ProfilPanel>

    <ProfilPanel icon="event" titel="Termine & Zu-/Absagen"
      info="Sobald du in einem Kader stehst" class="q-mb-sm">
      <p>
        Deine nächsten Termine stehen gleich auf der <b>Übersicht</b> — dort kannst du
        direkt zu- oder absagen, ohne die Seite zu wechseln. Alles Weitere unter
        <b>Termine</b>.
      </p>
      <p>
        Bei <b>Absage</b> und <b>Vielleicht</b> ist ein kurzer Kommentar Pflicht. Das ist
        Absicht: Wer plant, muss wissen, woran er ist.
      </p>
      <p>
        Zu Spielen gibt es einen Link zur Route zum Spielort, und vor dem Termin eine
        Erinnerung über deinen Kanal — solange du noch nicht geantwortet hast.
      </p>
      <p class="text-caption text-grey">
        Den Punkt <i>Termine</i> siehst du, sobald du in einem Kader stehst. Fehlt er,
        melde dich bei deinem Trainer oder Betreuer.
      </p>
    </ProfilPanel>

    <ProfilPanel icon="groups" titel="Mannschaften, Teamkasse & Platzbelegung"
      info="Erscheinen, sobald sie für dich freigeschaltet sind" class="q-mb-sm">
      <p>
        <b>Mannschaften</b> zeigt Teams und Kader — wer ist dabei, wer betreut.
      </p>
      <p>
        <b>Teamkasse</b> ist die Strichliste deiner Mannschaft: Wer hat was genommen, wer
        steht wie da. Gibt es nur, wenn dein Team sie nutzt.
      </p>
      <p>
        <b>Platzbelegung</b> beantwortet die häufigste Frage überhaupt: Wer ist wann auf
        welchem Platz?
      </p>
      <p class="text-caption text-grey">
        Diese Punkte tauchen im Menü auf, sobald du im Kader stehst bzw. freigeschaltet
        bist — sonst bleiben sie ausgeblendet.
      </p>
    </ProfilPanel>

    <ProfilPanel icon="confirmation_number" titel="Fragen stellen & Fehler melden"
      info="Tickets kann jeder" class="q-mb-sm">
      <p>
        Unter <b>Tickets</b> kann <b>jedes Mitglied</b> etwas aufmachen — eine Frage, einen
        Fehler, einen Wunsch. Du bekommst eine Nachricht, sobald jemand geantwortet hat,
        und kannst zurückschreiben.
      </p>
      <p>
        Für Probleme mit der App gibt es zusätzlich den <b>Melde-Knopf</b>
        <q-icon name="feedback" size="20px" class="hilfe-symbol" /> oben rechts in der
        Kopfzeile. Der hängt automatisch ein Bild des Bildschirms an — damit muss niemand
        beschreiben, wie es gerade aussah.
      </p>
    </ProfilPanel>

    <ProfilPanel icon="palette" titel="Aussehen & die roten Zahlen"
      info="Drei Ansichten, und was die Punkte bedeuten" class="q-mb-sm">
      <p>
        Über das Symbol oben rechts wählst du zwischen <b>VTB-Look</b>, <b>Hell</b>,
        <b>Dunkel</b> und <i>wie das Gerät</i>. Die Wahl gilt pro Gerät — dein Handy darf
        also dunkel sein und der Rechner hell.
      </p>
      <p>
        Die <b>roten Zahlen</b> an Menüpunkten und Kacheln sind offene Aufgaben, die auf
        <i>dich</i> warten: eine fehlende Rückmeldung, ein Ticket, eine Freigabe. Sind sie
        weg, ist nichts offen.
      </p>
    </ProfilPanel>

    <!-- ── Nur mit passendem Recht ──────────────────────────────────────── -->

    <div v-if="zeigeFachteil" class="text-subtitle1 text-weight-bold q-mt-lg q-mb-sm">
      Für deine Aufgaben im Verein
    </div>

    <ProfilPanel v-if="auth.hasPermission('personen.read')"
      icon="people" titel="Personen" info="Mitgliederdaten pflegen" class="q-mb-sm">
      <p>
        <b>Personen</b> ist die Mitgliederverwaltung: anlegen, suchen, Stammdaten und
        Zuordnungen zu Abteilungen und Mannschaften pflegen.
      </p>
      <p class="text-caption text-grey">
        Gelöscht wird hier nie wirklich — Einträge wandern in den Papierkorb und bleiben
        nachvollziehbar.
      </p>
    </ProfilPanel>

    <ProfilPanel v-if="auth.hasPermission('personen.freischalten') || auth.hasPermission('personen.permissions')"
      icon="how_to_reg" titel="Zugänge" info="Mitglieder für die App freischalten" class="q-mb-sm">
      <p>
        Unter <b>Zugänge</b> schaltest du Mitglieder für die App frei. Sie bekommen eine
        Willkommens-Mail mit einem Login-Link — ein Passwort vergibst du <b>nicht</b>, das
        setzen sie sich bei Bedarf selbst.
      </p>
      <p>
        Kommt die Mail nicht an, lässt sich die Einladung erneut schicken.
      </p>
    </ProfilPanel>

    <ProfilPanel v-if="auth.hasPermission('kassen.verwalten')"
      icon="account_balance_wallet" titel="Kassen & Kassenbuch" info="Buchungen und Berichte"
      class="q-mb-sm">
      <p>
        Unter <b>Kassenverwaltung</b> legst du Kassen an und entscheidest, wer auf welche
        Kasse darf — das läuft <b>je Kasse</b> und nicht über allgemeine Rechte.
      </p>
      <p>
        Im <b>Kassenbuch</b> stehen die Buchungen samt Belegen; Zählungen und Berichte
        hängen daran.
      </p>
    </ProfilPanel>

    <ProfilPanel v-if="auth.hasPermission('beitraege.read')"
      icon="euro" titel="Beiträge" info="Sollstellungen und SEPA" class="q-mb-sm">
      <p>
        <b>Beiträge</b> erzeugt die Sollstellungen aus den Beitragsregeln und daraus die
        SEPA-Datei für die Bank.
      </p>
    </ProfilPanel>

    <ProfilPanel v-if="auth.hasPermission('gebuehren.read')"
      icon="receipt_long" titel="Gebühren" info="Einzelforderungen neben dem Beitrag"
      class="q-mb-sm">
      <p>
        <b>Gebühren</b> sind Forderungen außer der Reihe — Strafen, Umlagen, Einzelposten.
        Sie laufen getrennt vom laufenden Beitrag.
      </p>
    </ProfilPanel>

    <ProfilPanel v-if="hatUebungsleiterZugriff"
      icon="sports" titel="Übungsleiter-Stunden" info="Erfassen, bestätigen, abrechnen"
      class="q-mb-sm">
      <p>
        Unter <b>Übungsleiter</b> trägst du deine Stunden ein — am schnellsten über den
        Kalender, der deine Trainingstermine schon kennt.
      </p>
      <p>
        Eingetragene Stunden gehen zur <b>Bestätigung</b> und werden danach abgerechnet.
      </p>
    </ProfilPanel>

    <ProfilPanel v-if="hatRechnungenZugriff"
      icon="request_quote" titel="Rechnungen" info="Einreichen und freigeben" class="q-mb-sm">
      <p>
        Unter <b>Rechnungen</b> reichst du Auslagen und Rechnungen ein — Beleg abfotografieren
        genügt, den Rest trägst du daneben ein.
      </p>
      <p>
        Danach läuft sie durch die <b>Freigabe</b> und landet im Export für die Buchhaltung.
      </p>
    </ProfilPanel>

    <ProfilPanel v-if="auth.hasPermission('berichte.read')"
      icon="insights" titel="Berichte" info="Zahlen zum Verein" class="q-mb-sm">
      <p>
        <b>Berichte</b> fasst zusammen, was sonst verstreut ist: Mitgliederzahlen,
        Entwicklung, Auswertungen nach Abteilung.
      </p>
    </ProfilPanel>

    <!-- ── Fuß: Anlaufstelle für Fragen ─────────────────────────────────── -->

    <q-card flat bordered class="vtb-karte hilfe-fuss q-mt-lg">
      <q-card-section class="row items-center q-col-gutter-md">
        <div class="col">
          <div class="text-subtitle1 text-weight-bold">Frage offen?</div>
          <div v-if="hilfeBereich" class="text-body2">
            Mach ein Ticket im Bereich <b>„{{ hilfeBereich.name }}“</b> auf<span
              v-if="hilfeBereich.beschreibung"> — {{ hilfeBereich.beschreibung }}</span>.
          </div>
          <div v-else class="text-body2">
            Mach einfach ein Ticket auf — jede Frage ist willkommen.
          </div>
        </div>
        <div class="col-12 col-sm-auto">
          <q-btn unelevated no-caps color="primary" icon="confirmation_number"
            label="Ticket aufmachen" class="full-width"
            @click="router.push({ name: 'tickets' })" />
        </div>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { api } from 'src/boot/axios'
import ProfilPanel from 'components/ProfilPanel.vue'
import HilfeAnmelden from 'components/HilfeAnmelden.vue'

const auth = useAuthStore()
const router = useRouter()

// Die Wege stehen als Daten da, nicht als acht Absätze im Template: Es sind
// gleichförmige Einträge, und einer kommt erfahrungsgemäß immer noch dazu.
const installWege = [
  {
    icon: 'android',
    titel: 'Android mit Chrome oder Edge',
    text: 'Unten erscheint von selbst der Balken „App auf dem Gerät installieren?“. '
      + 'Schon weggeklickt? Dann steht „App installieren“ im Konto-Menü oben rechts.',
  },
  {
    icon: 'ios_share',
    titel: 'iPhone / iPad mit Safari',
    text: 'Hier gibt es keinen Installieren-Knopf: Teilen-Symbol unten antippen und '
      + '„Zum Home-Bildschirm“ wählen.',
  },
  {
    icon: 'more_vert',
    titel: 'Android mit Firefox oder Samsung Internet',
    text: 'Über das Browser-Menü (drei Punkte) → „Zum Startbildschirm hinzufügen“ '
      + 'bzw. „Seite hinzufügen zu → Startbildschirm“.',
  },
  {
    icon: 'desktop_windows',
    titel: 'PC oder Mac mit Chrome oder Edge',
    text: 'Kleines Installieren-Symbol rechts in der Adressleiste, oder Menü → Apps → '
      + '„Diese Seite als App installieren“. Legt auf Wunsch eine Verknüpfung an.',
  },
  {
    icon: 'bookmark',
    titel: 'Anderer Browser',
    text: 'Nicht jeder Browser kann das (z. B. Firefox am PC). Dann ein Lesezeichen '
      + 'setzen oder die Adresse auf den Desktop ziehen — die App läuft genauso.',
  },
]

const hatUebungsleiterZugriff = computed(() =>
  auth.hasPermission('ulstunden.erfassen') ||
  auth.hasPermission('ulstunden.erfassen_fremd') ||
  auth.hasPermission('ulstunden.bestaetigen') ||
  auth.hasPermission('ulstunden.verwalten'),
)

const hatRechnungenZugriff = computed(() =>
  auth.hasPermission('rechnungen.einreichen') ||
  auth.hasPermission('rechnungen.freigeben') ||
  auth.hasPermission('rechnungen.verwalten'),
)

// Nur damit die Zwischenüberschrift nicht über einem leeren Block steht.
const zeigeFachteil = computed(() =>
  auth.hasPermission('personen.read') ||
  auth.hasPermission('personen.freischalten') ||
  auth.hasPermission('personen.permissions') ||
  auth.hasPermission('kassen.verwalten') ||
  auth.hasPermission('beitraege.read') ||
  auth.hasPermission('gebuehren.read') ||
  auth.hasPermission('berichte.read') ||
  hatUebungsleiterZugriff.value ||
  hatRechnungenZugriff.value,
)

// Welcher Ticket-Bereich die Anlaufstelle für App-Fragen ist, entscheidet der
// Admin per Haken in der Ticket-Verwaltung (Spalte `hilfe_hinweis`, Schema v123).
// Bewusst kein Name im Code: In einer zweiten Instanz heißt der Bereich anders
// oder es gibt ihn gar nicht — dann bleibt hier der neutrale Satz stehen.
const hilfeBereich = ref(null)

onMounted(async () => {
  try {
    const { data } = await api.get('/api/tickets/bereiche')
    hilfeBereich.value = data.find((b) => b.hilfe_hinweis) ?? null
  } catch {
    hilfeBereich.value = null
  }
})
</script>

<style scoped lang="scss">
:deep(p) {
  margin-bottom: 10px;
}
:deep(p:last-child) {
  margin-bottom: 0;
}
.hilfe-ul {
  margin: 0;
  padding-left: 20px;
}
.hilfe-ul li {
  margin-bottom: 6px;
}
.hilfe-liste__icon {
  min-width: 0;
  padding-right: 10px;
}
// Quasars `caption` ist auf einzeiliges Beiwerk ausgelegt; hier ist es der
// eigentliche Inhalt und muss umbrechen dürfen. Die FARBE bleibt bewusst die des
// Themes (je Theme gesetzt, im VTB-Look rgba(255,255,255,.65) auf Wappenblau ≈
// 5,8:1) — ein zusätzliches `opacity` hier senkt genau diesen Wert und macht den
// Text auf dem Handy schlechter statt besser. Nicht nochmal versuchen.
.hilfe-liste__text {
  white-space: normal;
  font-size: 0.85rem;
  line-height: 1.45;
}
// Theme „Hell": Quasars Caption-Grau kommt auf der weißen Karte nur auf 3,5:1 und
// reißt damit die 4,5:1 für Fließtext. Für eine einzeilige Unterschrift ginge das
// durch, hier ist es die Anleitung selbst — auf dem Handy in der Sonne der
// Unterschied zwischen lesbar und nicht. VTB und Dunkel liegen von Haus aus bei
// 5,3:1 bzw. 10,4:1 und bleiben deshalb unangetastet.
body.vtb-theme--hell .hilfe-liste__text {
  color: rgba(0, 0, 0, 0.66);
}
// Symbol mitten im Satz: getönte Scheibe wie die Icons der App, damit man es als
// „genau dieses Zeichen suchst du oben" liest und nicht als Aufzählungspunkt.
.hilfe-symbol {
  background: rgba($flaeche-rgb, 0.12);
  border-radius: 50%;
  padding: 3px;
  vertical-align: -6px;
  margin: 0 2px;
}
.hilfe-wichtig {
  border-left: 3px solid $akzent;
  background: rgba($flaeche-rgb, 0.1);
  border-radius: 6px;
  padding: 8px 10px;
}
.hilfe-fuss {
  border-left: 3px solid $akzent;
}
</style>
