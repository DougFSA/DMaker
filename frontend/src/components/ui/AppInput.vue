<script setup lang="ts">
/* Campo de texto de uma linha com rótulo, dica e erro. Para números, use AppNumberInput. */
import FormField from './FormField.vue'

withDefaults(
  defineProps<{
    label: string
    type?: 'text' | 'search' | 'url' | 'email'
    hint?: string
    error?: string
    placeholder?: string
    disabled?: boolean
    required?: boolean
    readonly?: boolean
    maxlength?: number
    autocomplete?: string
    hideLabel?: boolean
    id?: string
  }>(),
  { type: 'text', autocomplete: 'off' },
)

const model = defineModel<string>({ default: '' })

function onInput(event: Event): void {
  model.value = (event.target as HTMLInputElement).value
}
</script>

<template>
  <FormField
    v-slot="{ id: inputId, describedBy, invalid }"
    :label="label"
    :hint="hint"
    :error="error"
    :required="required"
    :hide-label="hideLabel"
    :id="id"
  >
    <input
      :id="inputId"
      class="input"
      :type="type"
      :value="model"
      :placeholder="placeholder"
      :disabled="disabled"
      :required="required"
      :readonly="readonly"
      :maxlength="maxlength"
      :autocomplete="autocomplete"
      :aria-describedby="describedBy"
      :aria-invalid="invalid ? 'true' : undefined"
      @input="onInput"
    />
  </FormField>
</template>

<style scoped>
.input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.input[aria-invalid='true'] {
  border-color: var(--color-error);
}
</style>
