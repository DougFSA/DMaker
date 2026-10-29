<script setup lang="ts">
/* A bancada do editor: os encaixes de mídia, player, filtros e linha do tempo, na grade que o CSS abaixo desenha.
   Cada encaixe é uma área nomeada: o painel que chegar só precisa estar registrado em `panels.ts`. */
import EditorSlot from './EditorSlot.vue'
import { panelsIn } from './panels'

const slots = panelsIn('workbench')
</script>

<template>
  <div class="workbench" aria-label="Bancada do editor">
    <EditorSlot v-for="panel in slots" :key="panel.id" :panel="panel" :style="{ gridArea: panel.id }" />
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) minmax(0, 1fr);
  grid-template-areas:
    'media player filters'
    'timeline timeline timeline';
  gap: var(--space-3);
}

@media (max-width: 900px) {
  .workbench {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'player'
      'timeline'
      'media'
      'filters';
  }
}
</style>
