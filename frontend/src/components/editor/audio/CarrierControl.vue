<script setup lang="ts">
/* A portadora do Vocoder: o som que a voz modula. O gerador padrão é o Tom (uma onda numa frequência), e é o que se edita
   aqui, a onda e a frequência; outro gerador (ruído, pluck...) a spec aceita, e a tela só o mostra, para quem o pôs pela IA
   ou pela CLI. O número digitado só vale ao sair do campo, um passo do desfazer. */
import { computed, ref, watch } from 'vue'
import type { CarrierValue } from '@/api'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'

const WAVEFORMS = [
  { value: 'sawtooth', label: 'Dente de serra' },
  { value: 'square', label: 'Quadrada' },
  { value: 'sine', label: 'Senoidal' },
  { value: 'square_bandlimited', label: 'Quadrada sem aliasing' },
]
const MIN_HZ = 1
const MAX_HZ = 20000

const props = defineProps<{ modelValue: CarrierValue; label: string; hint?: string }>()
const emit = defineEmits<{ commit: [value: CarrierValue] }>()

const isTone = computed(() => props.modelValue.generator === 'tone')
const waveform = computed(() => String(props.modelValue.params.waveform ?? 'sawtooth'))
const stored = computed(() => Number(props.modelValue.params.frequency_hz ?? 110))
const typed = ref<number | null>(stored.value)
watch(stored, (value) => (typed.value = value))

function change(partial: Record<string, number | string>): void {
  emit('commit', { generator: 'tone', params: { ...props.modelValue.params, ...partial } })
}

function commitFrequency(): void {
  if (typed.value === null) {
    typed.value = stored.value
    return
  }
  const value = Math.min(Math.max(typed.value, MIN_HZ), MAX_HZ)
  typed.value = value
  if (value !== stored.value) change({ frequency_hz: value })
}
</script>

<template>
  <div class="carrier">
    <template v-if="isTone">
      <AppSelect
        :label="`${label}: onda`"
        :model-value="waveform"
        :options="WAVEFORMS"
        :hint="hint"
        data-carrier="waveform"
        @update:model-value="(value: string) => change({ waveform: value })"
      />
      <AppNumberInput
        :label="`${label}: frequência`"
        :model-value="typed"
        :min="MIN_HZ"
        :max="MAX_HZ"
        step="any"
        unit="Hz"
        data-carrier="frequency"
        @update:model-value="(value: number | null) => (typed = value)"
        @focusout="commitFrequency"
      />
    </template>
    <p v-else class="carrier__other" data-carrier="other">
      {{ label }}: gerador <strong>{{ modelValue.generator }}</strong> (para trocar, use a IA ou a CLI).
    </p>
  </div>
</template>

<style scoped>
.carrier {
  display: contents;
}
.carrier__other {
  grid-column: 1 / -1;
  margin: 0;
  font-size: var(--text-sm, 0.875rem);
  color: var(--color-text-muted, inherit);
}
</style>
