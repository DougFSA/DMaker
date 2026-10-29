<script setup lang="ts">
/* Um encaixe do editor: mostra o painel registrado nele ou, enquanto o painel não existe, um aviso discreto. */
import { computed } from 'vue'
import { componentOf, type EditorPanelDef } from './panels'

const props = defineProps<{ panel: EditorPanelDef }>()

const component = computed(() => componentOf(props.panel))
</script>

<template>
  <section :class="['slot', { 'slot--empty': !component }]" :data-panel="panel.id" :aria-label="panel.title">
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
