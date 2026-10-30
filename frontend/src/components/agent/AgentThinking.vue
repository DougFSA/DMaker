<script setup lang="ts">
/* O raciocínio do modelo: fica recolhido, porque a resposta é o que importa, e a pessoa abre se quiser ler. */
import type { ThinkingItem } from '@/lib/agent'

defineProps<{ item: ThinkingItem }>()
</script>

<template>
  <details class="think" :data-streaming="item.streaming">
    <summary class="think__summary">{{ item.streaming ? 'Pensando...' : 'Raciocínio' }}</summary>
    <p class="think__text">{{ item.text }}</p>
  </details>
</template>

<style scoped>
.think {
  max-width: min(46rem, 100%);
  padding: var(--space-2) var(--space-4);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-md);
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.think__summary {
  cursor: pointer;
  font-weight: 600;
}

.think__summary:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

.think[data-streaming='true'] .think__summary {
  animation: breathe 1.6s ease-in-out infinite;
}

.think__text {
  margin-top: var(--space-2);
  max-height: 16rem;
  overflow-y: auto;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@keyframes breathe {
  50% {
    opacity: 0.55;
  }
}
</style>
