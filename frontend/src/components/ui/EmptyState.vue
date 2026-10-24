<script setup lang="ts">
import AppIcon, { type IconName } from './AppIcon.vue'

withDefaults(defineProps<{ title: string; description?: string; icon?: IconName }>(), {
  icon: 'sparkles',
})
</script>

<template>
  <div class="empty">
    <div class="empty__icon"><AppIcon :name="icon" :size="28" /></div>
    <h3 class="empty__title">{{ title }}</h3>
    <p v-if="description" class="empty__description">{{ description }}</p>
    <div v-if="$slots.default" class="empty__actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-7) var(--space-5);
  text-align: center;
}

.empty__icon {
  display: grid;
  place-items: center;
  width: 3.5rem;
  height: 3.5rem;
  border-radius: var(--radius-md);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.empty__title {
  font-size: var(--text-lg);
}

.empty__description {
  max-width: 28rem;
  color: var(--color-text-soft);
}

.empty__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-3);
  margin-top: var(--space-2);
}
</style>
