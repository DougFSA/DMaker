<script setup lang="ts">
/* Os controles deslizantes do EQ Gráfico: um por banda de terço de oitava, do mais grave (esquerda) ao mais agudo, cada um
   de -20 a +20 dB. Mexer muda a lista ao vivo (`update:modelValue`) e grava ao soltar (`commit`). Duplo clique no controle
   o leva a 0 dB; **Zerar** leva todos. As frequências vêm do catálogo do servidor (`options`). */
import { computed, ref } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { formatGain } from '@/lib/eqChart'

const props = defineProps<{
  modelValue: number[]
  /** O nome de cada banda ("20", "31.5", "3.15k"), na ordem. */
  labels: string[]
  minimum: number
  maximum: number
  /** O nome do efeito, para os rótulos de leitor de tela. */
  name: string
}>()

const emit = defineEmits<{
  'update:modelValue': [gains: number[]]
  commit: []
}>()

const hovered = ref<number | null>(null)

function bandLabel(index: number): string {
  const label = props.labels[index] ?? String(index + 1)
  return label.endsWith('k') ? `${label.slice(0, -1).replace('.', ',')} kHz` : `${label.replace('.', ',')} Hz`
}

const readout = computed(() => {
  const index = hovered.value
  if (index === null) return 'Arraste um controle; clique duas vezes para zerá-lo.'
  return `Banda de ${bandLabel(index)}: ${formatGain(props.modelValue[index] ?? 0)}`
})

function set(index: number, value: number): void {
  const next = props.modelValue.slice()
  next[index] = Math.round(value * 2) / 2 // meio dB: o que a pessoa lê e o que cabe no desenho
  emit('update:modelValue', next)
}

function onInput(index: number, event: Event): void {
  set(index, Number((event.target as HTMLInputElement).value))
}

function reset(index: number): void {
  set(index, 0)
  emit('commit')
}

function resetAll(): void {
  emit('update:modelValue', props.modelValue.map(() => 0))
  emit('commit')
}

const changed = computed(() => props.modelValue.some((gain) => gain !== 0))
</script>

<template>
  <div class="bands" data-band-sliders>
    <div class="bands__row">
      <div v-for="(gain, index) in modelValue" :key="index" class="bands__band" @pointerenter="hovered = index" @pointerleave="hovered = null">
        <input
          class="bands__slider"
          type="range"
          orient="vertical"
          :min="minimum"
          :max="maximum"
          step="0.5"
          :value="gain"
          :aria-label="`${name}: banda de ${bandLabel(index)}`"
          :aria-valuetext="formatGain(gain)"
          :data-band="index"
          @input="onInput(index, $event)"
          @change="emit('commit')"
          @dblclick="reset(index)"
          @focus="hovered = index"
          @blur="hovered = null"
        />
        <span class="bands__label" aria-hidden="true">{{ labels[index] }}</span>
      </div>
    </div>
    <div class="bands__foot">
      <p class="bands__readout" data-band-readout>{{ readout }}</p>
      <AppButton size="sm" variant="ghost" :disabled="!changed" data-band-reset @click="resetAll">Zerar</AppButton>
    </div>
  </div>
</template>

<style scoped>
.bands {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.bands__row {
  display: grid;
  grid-template-columns: repeat(31, minmax(0, 1fr));
  gap: 1px;
}

.bands__band {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
}

.bands__slider {
  /* um controle vertical: o ganho máximo no alto. `writing-mode` + `direction` é o jeito sem JavaScript */
  width: 1.1rem;
  height: 7rem;
  margin: 0;
  padding: 0;
  writing-mode: vertical-lr;
  direction: rtl;
  accent-color: var(--color-accent);
  cursor: pointer;
}

.bands__label {
  margin-top: 2px;
  font-size: 0.5rem;
  line-height: 1;
  color: var(--color-text-muted);
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  white-space: nowrap;
}

.bands__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.bands__readout {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}
</style>
