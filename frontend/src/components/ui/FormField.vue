<script setup lang="ts">
/* Moldura dos controles de formulário: rótulo, dica e erro ligados ao campo por `for` e `aria-describedby`.
   O campo em si entra pelo slot, que recebe o `id` e os atributos de acessibilidade para pôr nele. */
import { computed, useId } from 'vue'

const props = defineProps<{
  label: string
  hint?: string
  error?: string
  required?: boolean
  /** Esconde o rótulo na tela mas o mantém para leitor de tela (campo que já tem um título ao lado). */
  hideLabel?: boolean
  /** Usa este id no campo em vez de um gerado. */
  id?: string
}>()

const generated = useId()
const fieldId = computed(() => props.id ?? `field-${generated}`)
const hintId = computed(() => `${fieldId.value}-hint`)
const errorId = computed(() => `${fieldId.value}-error`)

/** O erro vem primeiro: é o que o leitor de tela precisa ouvir antes da dica. */
const describedBy = computed(() => {
  const ids = [props.error ? errorId.value : null, props.hint ? hintId.value : null].filter(Boolean)
  return ids.length ? ids.join(' ') : undefined
})
</script>

<template>
  <div class="field">
    <label :for="fieldId" :class="['field-label', { 'visually-hidden': hideLabel }]">
      {{ label }}<span v-if="required" class="field-required" aria-hidden="true"> *</span>
    </label>
    <slot :id="fieldId" :describedBy="describedBy" :invalid="!!error" />
    <p v-if="hint" :id="hintId" class="field-hint">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="field-error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.field-required {
  color: var(--color-error);
}

.field-error {
  font-size: var(--text-xs);
  color: var(--color-error);
}
</style>
