<script setup lang="ts">
/* Controle deslizante com o valor escrito ao lado (velocidade da narração, volume). Usa o `input range`
   nativo: o teclado (setas, Home, End) e os leitores de tela já funcionam. */
import { computed } from 'vue'
import FormField from './FormField.vue'

const props = withDefaults(
  defineProps<{
    label: string
    min: number
    max: number
    step?: number
    hint?: string
    disabled?: boolean
    /** Como o valor aparece escrito; o padrão usa vírgula decimal. */
    format?: (value: number) => string
    hideLabel?: boolean
    id?: string
  }>(),
  { step: 1 },
)

const model = defineModel<number>({ default: 0 })

const shown = computed(() => (props.format ? props.format(model.value) : String(model.value).replace('.', ',')))

function onInput(event: Event): void {
  model.value = Number((event.target as HTMLInputElement).value)
}
</script>

<template>
  <FormField v-slot="{ id: inputId, describedBy }" :label="label" :hint="hint" :hide-label="hideLabel" :id="id">
    <div class="slider">
      <input
        :id="inputId"
        class="slider__range"
        type="range"
        :min="min"
        :max="max"
        :step="step"
        :value="model"
        :disabled="disabled"
        :aria-valuetext="shown"
        :aria-describedby="describedBy"
        @input="onInput"
      />
      <output class="slider__value" :for="inputId">{{ shown }}</output>
    </div>
  </FormField>
</template>

<style scoped>
.slider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.slider__range {
  flex: 1;
  min-width: 0;
  height: 1.5rem;
  accent-color: var(--color-accent);
  cursor: pointer;
}

.slider__range:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.slider__value {
  min-width: 3.5rem;
  padding: 0.15rem 0.5rem;
  border-radius: var(--radius-pill);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
  font-size: var(--text-sm);
  font-weight: 600;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
</style>
