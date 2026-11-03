<script setup lang="ts">
/* Um bloco recolhível da aba Propriedades (Saída, Fontes, Trechos...): título, contagem e ações no cabeçalho. */
import { useId } from 'vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppIcon from '@/components/ui/AppIcon.vue'

defineProps<{ title: string; count?: number; description?: string }>()
const open = defineModel<boolean>('open', { default: true })

const bodyId = `section-${useId()}`
</script>

<template>
  <section class="section">
    <header class="section__head">
      <button type="button" class="section__toggle" :aria-expanded="open" :aria-controls="bodyId" @click="open = !open">
        <AppIcon :name="open ? 'chevron-down' : 'chevron-right'" :size="18" />
        <h3 class="section__title">{{ title }}</h3>
        <AppBadge v-if="count !== undefined">{{ count }}</AppBadge>
      </button>
      <div v-if="$slots.actions" class="section__actions"><slot name="actions" /></div>
    </header>
    <div v-if="open" :id="bodyId" class="section__body">
      <p v-if="description" class="section__description">{{ description }}</p>
      <slot />
    </div>
  </section>
</template>

<style scoped>
.section {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.section__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
}

.section__toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2) var(--space-1) 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text);
}

.section__toggle:hover {
  color: var(--color-accent-text);
}

.section__title {
  font-size: var(--text-md);
}

.section__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.section__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: 0 var(--space-4) var(--space-4);
}

.section__description {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>
