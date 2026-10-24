<script setup lang="ts">
export type BadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'error' | 'info'

withDefaults(defineProps<{ tone?: BadgeTone; dot?: boolean }>(), { tone: 'neutral' })
</script>

<template>
  <span :class="['badge', `badge--${tone}`]">
    <span v-if="dot" class="badge__dot" aria-hidden="true" />
    <slot />
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.15rem 0.6rem;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
}

.badge__dot {
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 50%;
  background: currentColor;
}

.badge--neutral {
  background: var(--color-surface-hover);
  color: var(--color-text-soft);
}

.badge--accent {
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.badge--success {
  background: var(--color-success-bg);
  color: var(--color-success);
}

.badge--warning {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.badge--error {
  background: var(--color-error-bg);
  color: var(--color-error);
}

.badge--info {
  background: var(--color-info-bg);
  color: var(--color-info);
}
</style>
