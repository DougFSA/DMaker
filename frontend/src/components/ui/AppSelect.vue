<script setup lang="ts">
/* Lista de opções com o `<select>` nativo: teclado, leitor de tela e celular já funcionam, e o visual segue os tokens. */
import AppIcon from './AppIcon.vue'
import FormField from './FormField.vue'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

withDefaults(
  defineProps<{
    label: string
    options: SelectOption[]
    /** Com texto, ganha uma primeira opção vazia ("Nenhuma", "Voz automática"...) que limpa a escolha. */
    placeholder?: string
    hint?: string
    error?: string
    disabled?: boolean
    required?: boolean
    hideLabel?: boolean
    id?: string
  }>(),
  {},
)

// v-model no select (e não :value + change): o Vue reaplica a escolha quando as opções chegam depois, como a lista de vozes
const model = defineModel<string>({ default: '' })
</script>

<template>
  <FormField
    v-slot="{ id: selectId, describedBy, invalid }"
    :label="label"
    :hint="hint"
    :error="error"
    :required="required"
    :hide-label="hideLabel"
    :id="id"
  >
    <div class="select">
      <select
        :id="selectId"
        v-model="model"
        class="input select__control"
        :disabled="disabled"
        :required="required"
        :aria-describedby="describedBy"
        :aria-invalid="invalid ? 'true' : undefined"
      >
        <option v-if="placeholder !== undefined" value="">{{ placeholder }}</option>
        <option v-for="option in options" :key="option.value" :value="option.value" :disabled="option.disabled">
          {{ option.label }}
        </option>
      </select>
      <AppIcon name="chevron-down" :size="16" class="select__chevron" />
    </div>
  </FormField>
</template>

<style scoped>
.select {
  position: relative;
  display: flex;
  align-items: center;
}

.select__control {
  appearance: none;
  padding-right: 2.25rem;
  cursor: pointer;
}

.select__control:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.select__control[aria-invalid='true'] {
  border-color: var(--color-error);
}

.select__chevron {
  position: absolute;
  right: var(--space-3);
  color: var(--color-text-muted);
  pointer-events: none;
}
</style>
