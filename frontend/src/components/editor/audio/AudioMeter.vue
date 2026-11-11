<script setup lang="ts">
/* O medidor de nível da reprodução: uma barra por canal (esquerdo e direito), do piso de -60 dB a 0 dBFS, com o pico
   segurado por um instante e uma luz que acende quando o som clipa. Só mostra o que o motor mediu; parado, as barras
   caem a zero. */
import { computed, ref, watch } from 'vue'
import { meterFraction, METER_FLOOR_DB, type MeterReading } from '@/lib/audioPlayback'

const props = defineProps<{ levels: readonly MeterReading[] }>()

/** Quanto tempo o pico fica segurado antes de começar a cair, e a velocidade da queda (dB por segundo). */
const HOLD_MS = 1200
const FALL_DB_PER_S = 20

const held = ref<number[]>([METER_FLOOR_DB, METER_FLOOR_DB])
const heldAt = ref<number[]>([0, 0])
const clipped = ref(false)

watch(
  () => props.levels,
  (levels) => {
    const now = performance.now()
    levels.forEach((reading, channel) => {
      const current = held.value[channel] ?? METER_FLOOR_DB
      if (reading.peakDb >= current) {
        held.value[channel] = reading.peakDb
        heldAt.value[channel] = now
      } else if (now - (heldAt.value[channel] ?? 0) > HOLD_MS) {
        held.value[channel] = Math.max(reading.peakDb, current - (FALL_DB_PER_S * 16) / 1000)
      }
      if (reading.clipped) clipped.value = true
    })
    if (levels.length === 0) {
      held.value = [METER_FLOOR_DB, METER_FLOOR_DB]
      clipped.value = false
    }
  },
)

const bars = computed(() =>
  [0, 1].map((channel) => {
    const reading = props.levels[channel]
    return {
      name: channel === 0 ? 'E' : 'D',
      level: meterFraction(reading?.peakDb ?? METER_FLOOR_DB),
      average: meterFraction(reading?.rmsDb ?? METER_FLOOR_DB),
      hold: meterFraction(held.value[channel] ?? METER_FLOOR_DB),
    }
  }),
)
const topDb = computed(() => Math.max(...props.levels.map((reading) => reading.peakDb), METER_FLOOR_DB))
const readout = computed(() => (topDb.value <= METER_FLOOR_DB ? '-∞ dB' : `${topDb.value.toFixed(1).replace('.', ',')} dB`))
</script>

<template>
  <div class="meter" role="img" :aria-label="`Medidor de nível: pico ${readout}`" data-audio-meter>
    <div v-for="bar in bars" :key="bar.name" class="meter__row">
      <span class="meter__name">{{ bar.name }}</span>
      <span class="meter__track">
        <span class="meter__peak" :style="{ width: `${bar.level * 100}%` }" />
        <span class="meter__rms" :style="{ width: `${bar.average * 100}%` }" />
        <span class="meter__hold" :style="{ left: `${bar.hold * 100}%` }" />
      </span>
    </div>
    <span class="meter__readout" data-meter-readout>{{ readout }}</span>
    <button
      type="button"
      :class="['meter__clip', { 'meter__clip--on': clipped }]"
      :title="clipped ? 'O som clipou. Clique para apagar o aviso.' : 'Sem clipping'"
      aria-label="Aviso de clipping"
      @click="clipped = false"
    />
  </div>
</template>

<style scoped>
.meter {
  display: grid;
  grid-template-columns: 8rem auto auto;
  grid-template-rows: auto auto;
  align-items: center;
  column-gap: var(--space-2);
  row-gap: 2px;
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.meter__row {
  display: contents;
}

.meter__name {
  display: none;
}

.meter__track {
  position: relative;
  grid-column: 1;
  height: 7px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--color-bg-soft);
  border: 1px solid var(--color-border);
}

.meter__peak {
  position: absolute;
  inset: 0 auto 0 0;
  background: linear-gradient(90deg, var(--color-success) 0 70%, var(--color-warning) 70% 90%, var(--color-error) 90%);
  opacity: 0.45;
}

.meter__rms {
  position: absolute;
  inset: 0 auto 0 0;
  background: linear-gradient(90deg, var(--color-success) 0 70%, var(--color-warning) 70% 90%, var(--color-error) 90%);
}

.meter__hold {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--color-text);
}

.meter__readout {
  grid-column: 2;
  grid-row: 1 / 3;
  min-width: 4.5rem;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.meter__clip {
  grid-column: 3;
  grid-row: 1 / 3;
  width: 0.7rem;
  height: 0.7rem;
  padding: 0;
  border: 1px solid var(--color-border-strong);
  border-radius: 50%;
  background: var(--color-bg-soft);
  cursor: pointer;
}

.meter__clip--on {
  border-color: var(--color-error);
  background: var(--color-error);
}
</style>
