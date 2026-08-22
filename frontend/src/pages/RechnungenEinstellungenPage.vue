<template>
  <div>
    <div class="text-subtitle1 q-mb-md">Einstellungen</div>

    <q-card flat bordered class="q-mb-md" style="max-width: 720px">
      <q-card-section>
        <div class="text-subtitle2 q-mb-xs">Standard-Kreditor</div>
        <div class="text-caption text-grey-7 q-mb-md">
          Auf dieses Konto laufen alle Rechnungen, bei denen das Geld
          <b>nicht</b> an den Einreicher zurückgeht, sondern an den
          Rechnungsaussteller. Wird eine Auslage erstattet, bucht der Export
          stattdessen auf das Kreditorkonto des Mitglieds.
        </div>

        <q-input
          v-model="kreditor"
          label="Standard-Kreditor (Kontonummer)"
          outlined dense clearable
          :loading="loading"
          hint="Kontonummer aus eurem Kontenrahmen, z. B. 70999 · steht im Export in Feld 00"
          @keyup.enter="speichern"
        >
          <template #prepend><q-icon name="account_balance" /></template>
        </q-input>

        <q-banner v-if="!kreditor && !loading" dense class="bg-orange-1 q-mt-md" rounded>
          <template #avatar><q-icon name="warning" color="orange" /></template>
          Solange hier nichts steht, lassen sich Rechnungen an externe Aussteller
          nicht exportieren – Erstattungen an Mitglieder dagegen schon.
        </q-banner>
      </q-card-section>

      <q-separator />
      <q-card-actions align="right">
        <q-btn
          label="Speichern" icon="save" color="primary" unelevated no-caps
          :disable="!geaendert" :loading="saving" @click="speichern"
        />
      </q-card-actions>
    </q-card>

    <div class="text-caption text-grey-7" style="max-width: 720px">
      Das <b>Aufwandskonto</b> (Gegenkonto der Buchung) hängt an der Kategorie und
      steht im Reiter <b>Kategorien</b>. Das Kreditorkonto für Erstattungen an
      Mitglieder ergibt sich aus der ÜL-Kreditor-Basis unter
      <b>Finanzen → Fibu-Export</b>.
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { fehlertext } from 'src/composables/useRechnungen'

defineOptions({ name: 'RechnungenEinstellungenPage' })

const $q = useQuasar()

const kreditor = ref('')
const loading = ref(false)
const saving = ref(false)
// Der gespeicherte Stand; daran hängt die Freigabe des Knopfes.
let stand = ''

const geaendert = computed(() => (kreditor.value || '') !== stand)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/api/rechnungen/einstellungen')
    kreditor.value = data.rechnung_kreditor_konto ?? ''
    stand = kreditor.value
  } catch (e) {
    $q.notify({ type: 'negative', message: fehlertext(e, 'Laden fehlgeschlagen') })
  } finally {
    loading.value = false
  }
}

async function speichern() {
  if (!geaendert.value) return
  saving.value = true
  try {
    const { data } = await api.put('/api/rechnungen/einstellungen', {
      rechnung_kreditor_konto: kreditor.value || null,
    })
    kreditor.value = data.rechnung_kreditor_konto ?? ''
    stand = kreditor.value
    $q.notify({ type: 'positive', message: 'Gespeichert.' })
  } catch (e) {
    $q.notify({ type: 'negative', message: fehlertext(e, 'Speichern fehlgeschlagen') })
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
