<template>
  <div>
    <!-- Hinterlegte Adressen: volle Zeilen zum Antippen statt einer Dropdown-Liste.
         Am Handy ist eine Adresse zu lang für einen Chip, und ein aufgeklapptes
         Menü verdeckt genau das Feld, das man gerade füllt. -->
    <template v-if="waehlbar.length">
      <div class="text-caption text-grey q-mb-xs">
        Hinterlegte Adressen – zum Übernehmen antippen
      </div>
      <q-list bordered separator class="rounded-borders q-mb-sm">
        <q-item
          v-for="a in waehlbar" :key="a.wert"
          clickable :disable="!!a.belegt_von"
          @click="uebernehmen(a.wert)"
        >
          <q-item-section avatar>
            <q-icon
              :name="istGewaehlt(a.wert) ? 'radio_button_checked' : 'radio_button_unchecked'"
              :color="istGewaehlt(a.wert) ? 'primary' : 'grey-6'"
            />
          </q-item-section>
          <q-item-section>
            <q-item-label class="vtb-mail-wert">{{ a.wert }}</q-item-label>
            <q-item-label v-if="a.belegt_von" caption class="text-orange-9">
              gehört schon zum Zugang von „{{ a.belegt_von }}“
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </template>

    <!-- Ein echtes Eingabefeld, kein Kombifeld: Beim q-select mit
         new-value-mode zählte Getipptes erst nach der Eingabetaste. Wer am Handy
         die Adresse eintippte und direkt auf den Knopf tippte, verlor sie – der
         Knopf blieb grau, ohne dass ersichtlich war, warum (#177). -->
    <q-input
      :model-value="modelValue"
      outlined dense clearable
      :label="label"
      type="email"
      inputmode="email"
      autocapitalize="none"
      autocorrect="off"
      spellcheck="false"
      :rules="[mailRulePflicht]"
      :hint="waehlbar.length ? 'Oder eine andere Adresse eintippen.' : hint"
      @update:model-value="(v) => $emit('update:modelValue', v)"
    >
      <template #prepend><q-icon name="alternate_email" /></template>
    </q-input>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { mailRulePflicht } from 'src/utils/email'

const props = defineProps({
  modelValue: { type: String, default: null },
  // [{ wert, belegt_von }] – die am Mitglied hinterlegten Adressen.
  adressen: { type: Array, default: () => [] },
  label: { type: String, default: 'Mailadresse' },
  hint: { type: String, default: '' },
  // Adresse, die nicht zur Auswahl stehen soll – beim Wechsel ist die bisherige
  // ja gerade der Grund dafür.
  ausser: { type: String, default: null },
})

const emit = defineEmits(['update:modelValue'])

const gleich = (a, b) => String(a || '').trim().toLowerCase() === String(b || '').trim().toLowerCase()

const waehlbar = computed(
  () => props.adressen.filter((a) => !props.ausser || !gleich(a.wert, props.ausser)),
)

const istGewaehlt = (wert) => gleich(wert, props.modelValue)

function uebernehmen (wert) {
  // Nochmaliges Antippen wählt wieder ab – sonst ließe sich eine einmal
  // übernommene Adresse nur noch über das Feld darunter loswerden.
  emit('update:modelValue', istGewaehlt(wert) ? null : wert)
}
</script>

<style scoped>
/* Adressen sind lang und dürfen die Zeile nicht sprengen; umbrochen wird an
   jeder Stelle, weil eine Mailadresse keine Wortgrenzen hat. */
.vtb-mail-wert {
  word-break: break-all;
}
</style>
