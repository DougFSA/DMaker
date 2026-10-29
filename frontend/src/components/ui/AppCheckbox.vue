<script setup lang="ts">
/* Caixa de marcar com rótulo clicável e dica opcional. */
import { computed, useId } from 'vue'

const props = defineProps<{
  label: string
  hint?: string
  disabled?: boolean
  id?: string
}>()

const model = defineModel<boolean>({ default: false })

const generated = useId()
const inputId = computed(() => props.id ?? `check-${generated}`)
const hintId = computed(() => `${inputId.value}-hint`)

function onChange(event: Event): void {
  model.value = (event.target as HTMLInputElement).checked
}
</script>

<template>
  <div class="field">
    <label class="check" :for="inputId">
      <input
        :id="inputId"
        type="checkbox"
        :checked="model"
        :disabled="disabled"
        :aria-describedby="hint ? hintId : undefined"
        @change="onChange"
      />
      <span>{{ label }}</span>
    </label>
    <p v-if="hint" :id="hintId" class="field-hint check__hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.check input:disabled,
.check input:disabled + span {
  opacity: 0.6;
  cursor: not-allowed;
}

.check__hint {
  padding-left: calc(1.1rem + var(--space-2));
}
</style>
