<script setup lang="ts">
/* Campo numérico: o modelo é `number`, ou `null` quando o campo está vazio (o servidor trata ausência como "padrão"). */
import FormField from './FormField.vue'

withDefaults(
  defineProps<{
    label: string
    hint?: string
    error?: string
    placeholder?: string
    disabled?: boolean
    required?: boolean
    min?: number
    max?: number
    /** Passo das setas; `any` aceita qualquer casa decimal. */
    step?: number | 'any'
    /** Unidade mostrada à direita do campo, por exemplo "s" ou "dB". */
    unit?: string
    hideLabel?: boolean
    id?: string
  }>(),
  { step: 'any' },
)

const model = defineModel<number | null>({ default: null })

// o `input number` já entrega o valor com ponto, mesmo quando a pessoa digitou vírgula no navegador em português
function onInput(event: Event): void {
  const text = (event.target as HTMLInputElement).value.trim()
  const parsed = Number(text)
  model.value = text === '' || Number.isNaN(parsed) ? null : parsed
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
    <div class="number">
      <input
        :id="inputId"
        class="input"
        type="number"
        inputmode="decimal"
        :value="model ?? ''"
        :placeholder="placeholder"
        :disabled="disabled"
        :required="required"
        :min="min"
        :max="max"
        :step="step"
        :aria-describedby="describedBy"
        :aria-invalid="invalid ? 'true' : undefined"
        @input="onInput"
      />
      <span v-if="unit" class="number__unit" aria-hidden="true">{{ unit }}</span>
    </div>
  </FormField>
</template>

<style scoped>
.number {
  position: relative;
  display: flex;
  align-items: center;
}

.number__unit {
  position: absolute;
  right: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  pointer-events: none;
}

.number:has(.number__unit) .input {
  padding-right: 3rem;
}

.input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.input[aria-invalid='true'] {
  border-color: var(--color-error);
}
</style>
