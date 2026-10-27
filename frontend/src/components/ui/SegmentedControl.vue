<script setup lang="ts" generic="T extends string">
import AppIcon, { type IconName } from './AppIcon.vue'

export interface SegmentOption<V extends string> {
  value: V
  /** Texto do botão; com `icon`, vira só o rótulo acessível. */
  label: string
  icon?: IconName
}

defineProps<{ options: SegmentOption<T>[]; label: string }>()
const selected = defineModel<T>({ required: true })
</script>

<template>
  <div class="segmented" role="group" :aria-label="label">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      :class="{ 'is-on': selected === option.value, 'is-icon': !!option.icon }"
      :aria-pressed="selected === option.value"
      :aria-label="option.icon ? option.label : undefined"
      :title="option.icon ? option.label : undefined"
      @click="selected = option.value"
    >
      <AppIcon v-if="option.icon" :name="option.icon" :size="18" />
      <template v-else>{{ option.label }}</template>
    </button>
  </div>
</template>

<style scoped>
.segmented {
  display: inline-flex;
  padding: 0.2rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
}

.segmented button {
  display: grid;
  place-items: center;
  min-width: 2.25rem;
  min-height: 2.25rem;
  padding: 0 var(--space-4);
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-soft);
  transition:
    background var(--transition),
    color var(--transition);
}

.segmented button.is-icon {
  padding: 0;
}

.segmented button:hover:not(.is-on) {
  color: var(--color-text);
}

.segmented button.is-on {
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}
</style>
