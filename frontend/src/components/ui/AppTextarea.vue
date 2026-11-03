<script setup lang="ts">
/* Texto de várias linhas (roteiro de narração, texto da gravação), com contagem de caracteres opcional. */
import { computed } from 'vue'
import FormField from './FormField.vue'

const props = withDefaults(
  defineProps<{
    label: string
    rows?: number
    hint?: string
    error?: string
    placeholder?: string
    disabled?: boolean
    required?: boolean
    /** Limite de caracteres; com ele, a contagem aparece sob o campo. */
    maxlength?: number
    hideLabel?: boolean
    id?: string
  }>(),
  { rows: 4 },
)

const model = defineModel<string>({ default: '' })

const counter = computed(() => (props.maxlength ? `${model.value.length} de ${props.maxlength} caracteres` : ''))

function onInput(event: Event): void {
  model.value = (event.target as HTMLTextAreaElement).value
}
</script>

<template>
  <FormField
    v-slot="{ id: areaId, describedBy, invalid }"
    :label="label"
    :hint="hint"
    :error="error"
    :required="required"
    :hide-label="hideLabel"
    :id="id"
  >
    <textarea
      :id="areaId"
      class="input textarea"
      :rows="rows"
      :value="model"
      :placeholder="placeholder"
      :disabled="disabled"
      :required="required"
      :maxlength="maxlength"
      :aria-describedby="describedBy"
      :aria-invalid="invalid ? 'true' : undefined"
      @input="onInput"
    />
    <p v-if="counter" class="textarea__count" aria-live="polite">{{ counter }}</p>
  </FormField>
</template>

<style scoped>
.textarea {
  min-height: 5rem;
  resize: vertical;
  line-height: 1.5;
}

.textarea:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.textarea[aria-invalid='true'] {
  border-color: var(--color-error);
}

.textarea__count {
  align-self: flex-end;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
