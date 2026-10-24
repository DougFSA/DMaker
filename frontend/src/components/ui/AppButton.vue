<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

const props = withDefaults(
  defineProps<{
    variant?: ButtonVariant
    size?: 'sm' | 'md'
    loading?: boolean
    disabled?: boolean
    /** Link externo ou arquivo (use `download` para baixar). */
    href?: string
    download?: string | boolean
    /** Rota interna do Vue Router. */
    to?: RouteLocationRaw
    type?: 'button' | 'submit'
    iconOnly?: boolean
  }>(),
  { variant: 'secondary', size: 'md', type: 'button', download: false },
)

const classes = computed(() => [
  'btn',
  `btn--${props.variant}`,
  `btn--${props.size}`,
  { 'btn--icon': props.iconOnly, 'btn--loading': props.loading },
])
const inactive = computed(() => props.disabled || props.loading)
</script>

<template>
  <RouterLink v-if="to && !inactive" :to="to" :class="classes"><slot /></RouterLink>
  <a
    v-else-if="href && !inactive"
    :href="href"
    :download="download === false ? undefined : download === true ? '' : download"
    :class="classes"
  >
    <slot />
  </a>
  <button
    v-else
    :type="type"
    :class="classes"
    :disabled="inactive"
    :aria-busy="loading ? 'true' : undefined"
  >
    <span v-if="loading" class="btn__spinner" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 2.5rem;
  padding: 0.5rem 1.1rem;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  font-size: var(--text-sm);
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
  text-decoration: none;
  transition:
    background var(--transition),
    border-color var(--transition),
    color var(--transition),
    box-shadow var(--transition),
    transform var(--transition);
}

.btn:hover {
  text-decoration: none;
}

.btn:active:not(:disabled) {
  transform: translateY(1px);
}

.btn--sm {
  min-height: 2rem;
  padding: 0.3rem 0.85rem;
  font-size: var(--text-xs);
}

.btn--icon {
  width: 2.5rem;
  padding: 0;
}

.btn--icon.btn--sm {
  width: 2rem;
}

.btn--primary {
  background: var(--color-accent);
  color: var(--color-on-accent);
}

.btn--primary:hover:not(:disabled) {
  background: var(--color-accent-strong);
  box-shadow: var(--glow-accent);
}

.btn--secondary {
  background: var(--color-surface-raised);
  border-color: var(--color-border-strong);
  color: var(--color-text);
}

.btn--secondary:hover:not(:disabled) {
  background: var(--color-surface-hover);
  border-color: var(--color-accent-soft);
}

.btn--ghost {
  background: transparent;
  color: var(--color-text-soft);
}

.btn--ghost:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.btn--danger {
  background: var(--color-error-bg);
  border-color: var(--color-error);
  color: var(--color-error);
}

.btn:disabled,
.btn--loading {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn--loading {
  cursor: progress;
}

.btn__spinner {
  width: 0.9rem;
  height: 0.9rem;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
