<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  /** 0 a 100. Sem valor, a barra fica indeterminada (job que ainda não mediu progresso). */
  value?: number | null
  label: string
  tone?: 'accent' | 'error'
}>()

const clamped = computed(() => (props.value == null ? null : Math.min(100, Math.max(0, props.value))))
</script>

<template>
  <div
    :class="['progress', { 'progress--indeterminate': clamped === null, 'progress--error': tone === 'error' }]"
    role="progressbar"
    :aria-label="label"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-valuenow="clamped ?? undefined"
  >
    <div class="progress__fill" :style="clamped === null ? undefined : { width: `${clamped}%` }" />
  </div>
</template>

<style scoped>
.progress {
  position: relative;
  height: 0.5rem;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--color-surface-hover);
}

.progress__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--color-accent-soft), var(--color-accent));
  transition: width 240ms ease;
}

.progress--error .progress__fill {
  background: var(--color-error);
}

.progress--indeterminate .progress__fill {
  width: 40%;
  animation: slide 1.2s ease-in-out infinite;
}

@keyframes slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(260%);
  }
}
</style>
