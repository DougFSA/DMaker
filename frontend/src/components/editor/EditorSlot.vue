<script setup lang="ts">
/* Um encaixe do editor: mostra o painel registrado nele ou, enquanto o painel não existe, um aviso discreto. */
import { computed } from 'vue'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { AUDIO_PANEL, componentOf, type EditorPanelDef } from './panels'

const props = defineProps<{ panel: EditorPanelDef }>()

const audio = useAudioPanelStore()

/** O painel Áudio ocupa o encaixe da linha do tempo enquanto está aberto; fechado, a linha do tempo volta. */
const component = computed(() => componentOf(props.panel.id === 'timeline' && audio.open ? AUDIO_PANEL : props.panel))
</script>

<template>
  <section :class="['slot', { 'slot--empty': !component, 'slot--fill': panel.id === 'timeline' && audio.open }]" :data-panel="panel.id" :data-audio-open="panel.id === 'timeline' && audio.open ? '1' : undefined" :aria-label="panel.id === 'timeline' && audio.open ? 'Áudio' : panel.title">
    <component :is="component" v-if="component" />
    <p v-else class="slot__notice">
      <strong>{{ panel.title }}</strong>
      <span>Este painel ainda não está disponível nesta versão.</span>
    </p>
  </section>
</template>

<style scoped>
.slot {
  min-width: 0;
}

/* o painel Áudio preenche o encaixe: a onda leva o que sobra da altura depois das barras */
.slot--fill {
  height: 100%;
}

.slot--empty {
  display: flex;
  align-items: center;
  padding: var(--space-3) var(--space-4);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.slot__notice {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-1) var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.slot__notice strong {
  font-weight: 600;
  color: var(--color-text-soft);
}
</style>
