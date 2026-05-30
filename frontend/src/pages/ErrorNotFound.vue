<template>
  <q-page class="flex flex-center">
    <div class="text-center">
      <div class="text-h1 text-grey-4">404</div>
      <div class="text-h5 q-mb-lg">Seite nicht gefunden</div>
      <q-btn label="Zur Startseite" color="primary" :to="{ name: 'dashboard' }" unelevated />
    </div>
  </q-page>
</template>
