<template>
  <!-- Reiner Text, keine Props: Dieselbe Erklärung steht auf der Hilfeseite UND
       im Dialog der Login-Seite. Gerade die Anmelde-Fragen hat man, BEVOR man
       drin ist — stünde die Erklärung nur hinter dem Login, käme sie zu spät. -->
  <div class="hilfe-anmelden">
    <p>
      Zum Anmelden gibt es <b>zwei Wege</b> — am Handy kommt ein dritter dazu. Alle führen
      zum selben Konto, du kannst jederzeit wechseln.
    </p>

    <div class="hilfe-anmelden__weg">
      <div class="text-weight-bold"><q-icon name="mail" size="18px" /> Login-Link (ohne Passwort)</div>
      <p>
        Gib im Reiter <i>Login-Link</i> deinen Benutzernamen oder deine E-Mail-Adresse ein.
        Du bekommst eine Mail mit einem Link, der dich direkt hineinlässt — kein Passwort nötig.
        Der Link gilt <b>7 Tage</b> und lässt sich <b>einmal</b> verwenden.
      </p>
      <p>
        <b>Mit der installierten App am Handy</b> öffnet der Link oft den Browser statt
        der App — du wärst dann im Browser angemeldet, nicht in der App. Dafür steht in
        derselben Mail ein <b>6-stelliger Code</b>: Den tippst du in der App ein, direkt
        unter „E-Mail unterwegs!". Der Code gilt <b>15 Minuten</b>. Link und Code gehören
        zusammen — wer eins davon benutzt, hat beide verbraucht.
      </p>
      <p class="text-caption text-grey">
        Die Mail geht immer an die Adresse, die im Verein hinterlegt ist — nie an die,
        die du gerade eintippst. So kann niemand sonst einen Link auf dein Konto anfordern.
      </p>
    </div>

    <div class="hilfe-anmelden__weg">
      <div class="text-weight-bold"><q-icon name="key" size="18px" /> Passwort</div>
      <p>
        Im Reiter <i>Passwort</i> kannst du dich mit <b>Benutzername oder E-Mail-Adresse</b>
        anmelden — beides funktioniert.
      </p>
      <p>
        Dein Konto startet <b>ohne</b> Passwort; am Anfang kommst du über den Login-Link hinein.
        Ein Passwort setzt du dir selbst unter <b>Mein Profil → Passwort ändern</b>
        (mindestens 6 Zeichen). Der Login-Link bleibt daneben weiter möglich.
      </p>
    </div>

    <div class="hilfe-anmelden__weg">
      <div class="text-weight-bold"><q-icon name="fingerprint" size="18px" /> Fingerabdruck / Face ID (nur am Handy)</div>
      <p>
        Bist du einmal angemeldet, kannst du dein Handy unter
        <b>Mein Profil → Anmeldung per Fingerabdruck</b> einrichten. Danach reicht auf der
        Anmeldeseite ein Tipp auf <i>Mit Fingerabdruck / Face ID</i> — kein Passwort, keine Mail.
        Das klappt im Browser <b>und</b> in der installierten App.
      </p>
      <p>
        Das Einrichten geht zur Sicherheit nur <b>direkt nach dem Anmelden</b> (innerhalb von
        10 Minuten). Bist du schon länger drin, meldest du dich einmal ab und wieder an.
        Du bekommst danach eine Mail, dass ein Passkey eingerichtet wurde.
      </p>
      <p class="text-caption text-grey">
        Dein Fingerabdruck bzw. dein Gesicht verlässt das Handy nie — das Handy bestätigt nur,
        dass du es bist. Statt Finger oder Gesicht nimmt es auch die Geräte-PIN. Jeder, der
        dein Handy entsperren kann, kommt damit also auch in die App.
      </p>
    </div>

    <q-banner dense class="hilfe-anmelden__merk">
      <template #avatar><q-icon name="schedule" /></template>
      <div class="text-weight-bold">Der wichtigste Haken: „Angemeldet bleiben“</div>
      <div>
        Ohne diesen Haken wirst du nach <b>24 Stunden</b> wieder abgemeldet, egal wie viel du
        die App benutzt. Mit Haken bleibst du angemeldet, solange du die App benutzt — erst
        wenn du sie <b>30 Tage</b> lang gar nicht öffnest, musst du dich neu anmelden. Wer
        sich ständig neu anmelden muss, hat meistens einfach den Haken nicht gesetzt. Es gibt
        ihn beim Passwort-Login <i>und</i> beim Öffnen eines Login-Links.
      </div>
      <div class="text-caption q-mt-xs">
        Auf fremden oder geteilten Geräten besser weglassen — oder dort nach dem Benutzen
        abmelden.
      </div>
    </q-banner>

    <p>
      <b>Passwort vergessen?</b> Dafür gibt es bewusst keinen eigenen Weg — nimm den
      Login-Link. Er ist der Ersatz und funktioniert immer, auch wenn du nie ein Passwort
      gesetzt hast.
    </p>
    <p>
      <b>„Zu viele Versuche“?</b> Nach mehreren falschen Passwörtern macht die App für
      15 Minuten zu. Kurz warten — oder in der Zeit einfach den Login-Link nehmen.
    </p>
    <p>
      <b>Handy verloren?</b> Unter <b>Mein Profil → Meine Geräte</b> siehst du alle
      angemeldeten Geräte und kannst mit einem Klick <i>alle anderen abmelden</i>. War das
      Handy für den Fingerabdruck eingerichtet, entferne dort auch den Passkey unter
      <b>Anmeldung per Fingerabdruck</b>.
    </p>
  </div>
</template>

<script setup>
// Bewusst ohne Logik – reine Darstellung.
</script>

<style scoped lang="scss">
.hilfe-anmelden p {
  margin-bottom: 10px;
}
.hilfe-anmelden__weg {
  margin-bottom: 14px;
}
.hilfe-anmelden__weg p {
  margin: 4px 0 0;
}
// Tönung statt Vollfläche: funktioniert auf weißer wie auf dunkler Karte, ohne
// dass der Text in einem der drei Themes unlesbar wird.
.hilfe-anmelden__merk {
  border-radius: 10px;
  border-left: 3px solid $akzent;
  background: rgba($flaeche-rgb, 0.1);
  margin: 14px 0;
}
</style>
