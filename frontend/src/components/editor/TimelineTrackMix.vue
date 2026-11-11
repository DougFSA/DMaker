<script setup lang="ts">
/* O ganho e o pan de uma trilha de áudio, num popover do cabeçalho dela. Os dois são da mixagem (`tracks` na spec): o
   ganho em dB sobe ou desce a trilha inteira, o pan a leva do lado esquerdo (-100) ao direito (+100). Mexer no controle
   só mostra o valor; soltar grava, e cada gravação é um passo do desfazer do editor. */
import { computed, ref, watch } from 'vue'
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import type { TimelineTrack } from '@/api'

const props = defineProps<{ track: TimelineTrack }>()
const emit = defineEmits<{ change: [changes: { gain_db?: number; pan?: number }] }>()

/** Os limites da spec para o estado de uma trilha: ganho de -60 a 24 dB e pan de -1 a 1. */
const GAIN_MIN = -60
const GAIN_MAX = 24

const open = ref(false)
const gain = ref(props.track.gain_db ?? 0)
const pan = ref(Math.round((props.track.pan ?? 0) * 100))

// a spec manda: desfazer, recarregar ou outra tela trocam o valor, e o controle acompanha
watch(
  () => [props.track.gain_db, props.track.pan] as const,
  ([nextGain, nextPan]) => {
    gain.value = nextGain ?? 0
    pan.value = Math.round((nextPan ?? 0) * 100)
  },
)

const changed = computed(() => (props.track.gain_db ?? 0) !== 0 || (props.track.pan ?? 0) !== 0)
const gainText = computed(() => `${gain.value > 0 ? '+' : ''}${gain.value.toFixed(1).replace('.', ',')} dB`)
const panText = computed(() => (pan.value === 0 ? 'centro' : pan.value < 0 ? `${-pan.value}% esquerda` : `${pan.value}% direita`))

function clampGain(value: number): number {
  return Math.min(GAIN_MAX, Math.max(GAIN_MIN, Math.round(value * 10) / 10))
}

function commitGain(): void {
  gain.value = clampGain(gain.value)
  if (gain.value !== (props.track.gain_db ?? 0)) emit('change', { gain_db: gain.value })
}

function commitPan(): void {
  const next = Math.min(100, Math.max(-100, pan.value)) / 100
  if (next !== (props.track.pan ?? 0)) emit('change', { pan: next })
}

function reset(): void {
  gain.value = 0
  pan.value = 0
  const changes: { gain_db?: number; pan?: number } = {}
  if ((props.track.gain_db ?? 0) !== 0) changes.gain_db = 0
  if ((props.track.pan ?? 0) !== 0) changes.pan = 0
  if (Object.keys(changes).length > 0) emit('change', changes)
}
</script>

<template>
  <PopoverRoot v-model:open="open">
    <PopoverTrigger as-child>
      <button
        type="button"
        :class="['mix__trigger', { 'mix__trigger--on': changed }]"
        data-track-action="mix"
        :aria-label="`Ganho e pan (${track.id})`"
        :title="`Ganho e pan da trilha ${track.id}`"
        @click.stop
      >
        dB
      </button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent class="mix" align="start" :side-offset="6" :aria-label="`Ganho e pan da trilha ${track.id}`" data-track-mix>
        <label class="mix__row">
          <span class="mix__label">Ganho <output data-mix-gain-text>{{ gainText }}</output></span>
          <input
            v-model.number="gain"
            class="mix__range"
            type="range"
            :min="GAIN_MIN"
            :max="GAIN_MAX"
            step="0.5"
            data-mix-gain
            @change="commitGain"
          />
        </label>
        <label class="mix__row">
          <span class="mix__label">Pan <output data-mix-pan-text>{{ panText }}</output></span>
          <input v-model.number="pan" class="mix__range" type="range" min="-100" max="100" step="5" data-mix-pan @change="commitPan" />
        </label>
        <button type="button" class="mix__reset" data-mix-reset @click="reset">Zerar</button>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>

<style scoped>
.mix__trigger {
  display: inline-grid;
  place-items: center;
  width: 17px;
  height: 17px;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-muted);
  font: inherit;
  font-size: 0.5625rem;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
}

.mix__trigger:hover {
  color: var(--color-text);
  border-color: var(--color-border-strong);
}

.mix__trigger--on {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}
</style>

<style>
.mix {
  z-index: 70;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  width: 15rem;
  padding: var(--space-3);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  font-size: var(--text-sm);
}

.mix:focus {
  outline: none;
}

.mix__row {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.mix__label {
  display: flex;
  justify-content: space-between;
  color: var(--color-text-soft);
}

.mix__label output {
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.mix__range {
  width: 100%;
}

.mix__reset {
  align-self: flex-end;
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-soft);
  font: inherit;
  cursor: pointer;
}

.mix__reset:hover {
  color: var(--color-text);
  border-color: var(--color-border-strong);
}
</style>
