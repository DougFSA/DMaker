<script setup lang="ts">
/* A bancada do editor: os encaixes de mídia, player, filtros e linha do tempo, na grade que o CSS abaixo desenha.
   Cada encaixe é uma área nomeada: o painel que chegar só precisa estar registrado em `panels.ts`. Os painéis que a
   pessoa escondeu (botões F e M da linha do tempo) saem da grade, e a coluna deles some junto. */
import { computed } from 'vue'
import { useEditorPanelsStore } from '@/stores/editorPanels'
import EditorSlot from './EditorSlot.vue'
import { panelsIn } from './panels'

const panels = useEditorPanelsStore()

const slots = computed(() => panelsIn('workbench').filter((panel) => !panels.isHidden(panel.id)))
// uma classe por combinação do que está escondido: o CSS troca as colunas da grade
const layoutClass = computed(() => ({
  'workbench--no-media': panels.isHidden('media'),
  'workbench--no-filters': panels.isHidden('filters'),
}))
</script>

<template>
  <div :class="['workbench', layoutClass]" aria-label="Bancada do editor">
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

.workbench--no-media {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  grid-template-areas:
    'player filters'
    'timeline timeline';
}

.workbench--no-filters {
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  grid-template-areas:
    'media player'
    'timeline timeline';
}

.workbench--no-media.workbench--no-filters {
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas:
    'player'
    'timeline';
}

@media (max-width: 900px) {
  .workbench,
  .workbench--no-media,
  .workbench--no-filters,
  .workbench--no-media.workbench--no-filters {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'player'
      'timeline'
      'media'
      'filters';
  }
}
</style>
