<script setup lang="ts">
import AppIcon from './AppIcon.vue'

defineProps<{ label: string; placeholder: string; id: string }>()
const query = defineModel<string>({ default: '' })
</script>

<template>
  <div class="search">
    <AppIcon name="search" :size="18" />
    <label class="visually-hidden" :for="id">{{ label }}</label>
    <input
      :id="id"
      v-model="query"
      class="search__input"
      type="search"
      :placeholder="placeholder"
      autocomplete="off"
    />
  </div>
</template>

<style scoped>
.search {
  position: relative;
  display: flex;
  flex: 1;
  align-items: center;
  min-width: 14rem;
  max-width: 28rem;
  color: var(--color-text-muted);
}

.search > svg {
  position: absolute;
  left: var(--space-3);
  pointer-events: none;
}

.search__input {
  width: 100%;
  min-height: 2.75rem;
  padding: 0.5rem var(--space-4) 0.5rem 2.5rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
  color: var(--color-text);
}

.search__input:hover {
  border-color: var(--color-border-strong);
}

.search__input:focus-visible {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-bg);
}
</style>
