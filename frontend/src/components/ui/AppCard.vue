<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    subtitle?: string
    /** Card clicável: ganha realce no hover. */
    interactive?: boolean
    flush?: boolean
  }>(),
  {},
)
</script>

<template>
  <section :class="['card', { 'card--interactive': interactive, 'card--flush': flush }]">
    <header v-if="title || $slots.actions || $slots.header" class="card__header">
      <slot name="header">
        <div class="card__heading">
          <h3 class="card__title">{{ title }}</h3>
          <p v-if="subtitle" class="card__subtitle">{{ subtitle }}</p>
        </div>
      </slot>
      <div v-if="$slots.actions" class="card__actions"><slot name="actions" /></div>
    </header>
    <div class="card__body"><slot /></div>
    <footer v-if="$slots.footer" class="card__footer"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  transition:
    border-color var(--transition),
    box-shadow var(--transition),
    transform var(--transition);
}

.card--interactive:hover {
  border-color: var(--color-accent-soft);
  box-shadow: var(--glow-accent);
}

.card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-5) 0;
}

.card__heading {
  min-width: 0;
}

.card__title {
  font-size: var(--text-lg);
}

.card__subtitle {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.card__actions {
  display: flex;
  flex-shrink: 0;
  gap: var(--space-2);
}

.card__body {
  flex: 1;
  min-width: 0;
  padding: var(--space-5);
}

.card--flush .card__body {
  padding: 0;
}

.card--flush .card__header {
  padding-bottom: var(--space-4);
}

.card__footer {
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border);
}
</style>
