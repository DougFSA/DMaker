<script setup lang="ts">
/* O gráfico do espectro de frequência em SVG, sem biblioteca: a curva (nível em dB por frequência), a grade e um cursor
   que mostra a frequência, a nota musical mais próxima (lá 4 = 440 Hz) e o nível sob ele. O mouse, o toque e as setas
   do teclado movem o cursor; ele começa no pico. As contas estão em `lib/spectrum.ts`. */
import { computed, ref, watch } from 'vue'
import type { SpectrumAnalysis } from '@/api'
import {
  curvePath,
  formatDb,
  formatHz,
  formatNote,
  frequencyAtX,
  frequencyTicks,
  levelAt,
  levelTicks,
  noteOf,
  spectrumRange,
  xOfFrequency,
  yOfLevel,
  type PlotBox,
} from '@/lib/spectrum'

const props = defineProps<{ analysis: SpectrumAnalysis }>()

const WIDTH = 640
const HEIGHT = 320
const box: PlotBox = { left: 48, right: WIDTH - 12, top: 12, bottom: HEIGHT - 44 }

const axis = computed(() => props.analysis.axis)
const range = computed(() => spectrumRange(props.analysis.curve, axis.value))
const path = computed(() => curvePath(props.analysis.curve, axis.value, range.value, box))
const xTicks = computed(() => frequencyTicks(axis.value, range.value))
const yTicks = computed(() => levelTicks(range.value))

/** A frequência sob o cursor; começa no pico e volta a ele quando a análise muda. */
const cursorHz = ref(props.analysis.peak_hz)
watch(
  () => props.analysis,
  (analysis) => {
    cursorHz.value = analysis.peak_hz
  },
)

const cursor = computed(() => {
  const frequency = Math.min(Math.max(cursorHz.value, range.value.lowHz), range.value.highHz)
  // no pico vale o nível refinado do servidor (o tom entre duas divisões); fora dele, o da curva
  const level = frequency === props.analysis.peak_hz ? props.analysis.peak_db : levelAt(props.analysis.curve, frequency)
  const note = noteOf(frequency)
  return {
    frequency,
    level,
    note: note ? formatNote(note) : null,
    x: xOfFrequency(frequency, axis.value, range.value, box),
    y: yOfLevel(level, range.value, box),
  }
})

const svg = ref<SVGSVGElement | null>(null)

/** A posição do ponteiro em unidades do SVG (o `viewBox` escala com a largura do painel). */
function placeCursor(event: PointerEvent): void {
  const element = svg.value
  if (!element) return
  const rect = element.getBoundingClientRect()
  if (rect.width === 0) return
  const x = ((event.clientX - rect.left) / rect.width) * WIDTH
  cursorHz.value = frequencyAtX(x, axis.value, range.value, box)
}

/** Uma setinha anda 1% do eixo; Shift anda 10%; Home e End vão às pontas e P volta ao pico. */
function onKey(event: KeyboardEvent): void {
  const step = event.shiftKey ? 0.1 : 0.01
  const here = xOfFrequency(cursorHz.value, axis.value, range.value, box)
  const move = (pixels: number) => frequencyAtX(here + pixels, axis.value, range.value, box)
  const width = box.right - box.left
  if (event.key === 'ArrowLeft') cursorHz.value = move(-step * width)
  else if (event.key === 'ArrowRight') cursorHz.value = move(step * width)
  else if (event.key === 'Home') cursorHz.value = range.value.lowHz
  else if (event.key === 'End') cursorHz.value = range.value.highHz
  else if (event.key.toLowerCase() === 'p') cursorHz.value = props.analysis.peak_hz
  else return
  event.preventDefault()
}

const readout = computed(() => {
  const parts = [formatHz(cursor.value.frequency)]
  if (cursor.value.note) parts.push(cursor.value.note)
  parts.push(formatDb(cursor.value.level))
  return parts.join(' · ')
})
</script>

<template>
  <figure class="plot">
    <p class="plot__readout" role="status" aria-live="polite" data-spectrum-readout>{{ readout }}</p>
    <svg
      ref="svg"
      class="plot__svg"
      :viewBox="`0 0 ${WIDTH} ${HEIGHT}`"
      role="img"
      tabindex="0"
      :aria-label="`Espectro de frequência. ${analysis.summary} Use as setas para mover o cursor.`"
      data-spectrum-plot
      @pointerdown="placeCursor"
      @pointermove="placeCursor"
      @keydown="onKey"
    >
      <rect :x="box.left" :y="box.top" :width="box.right - box.left" :height="box.bottom - box.top" class="plot__area" />
      <g class="plot__grid">
        <g v-for="tick in xTicks" :key="`x${tick}`">
          <line :x1="xOfFrequency(tick, axis, range, box)" :x2="xOfFrequency(tick, axis, range, box)" :y1="box.top" :y2="box.bottom" />
          <text :x="xOfFrequency(tick, axis, range, box)" :y="box.bottom + 16" text-anchor="middle">
            {{ tick >= 1000 ? `${tick / 1000}k` : tick }}
          </text>
        </g>
        <g v-for="tick in yTicks" :key="`y${tick}`">
          <line :x1="box.left" :x2="box.right" :y1="yOfLevel(tick, range, box)" :y2="yOfLevel(tick, range, box)" />
          <text :x="box.left - 6" :y="yOfLevel(tick, range, box) + 4" text-anchor="end">{{ tick }}</text>
        </g>
      </g>
      <path :d="path" class="plot__curve" data-spectrum-curve />
      <g class="plot__cursor" data-spectrum-cursor>
        <line :x1="cursor.x" :x2="cursor.x" :y1="box.top" :y2="box.bottom" />
        <circle :cx="cursor.x" :cy="cursor.y" r="4" />
      </g>
      <text :x="(box.left + box.right) / 2" :y="HEIGHT - 4" class="plot__label" text-anchor="middle">Frequência (Hz)</text>
      <text :x="4" :y="(box.top + box.bottom) / 2" class="plot__label">dB</text>
    </svg>
  </figure>
</template>

<style scoped>
.plot {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
}

.plot__readout {
  min-height: 1.5em;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  color: var(--color-text);
}

.plot__svg {
  width: 100%;
  height: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  cursor: crosshair;
  touch-action: none;
}

.plot__svg:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

.plot__area {
  fill: var(--color-bg-soft);
}

.plot__grid line {
  stroke: var(--color-border);
  stroke-width: 1;
}

.plot__grid text,
.plot__label {
  font-size: 11px;
  fill: var(--color-text-muted);
}

.plot__curve {
  fill: none;
  stroke: var(--color-accent);
  stroke-width: 1.6;
  stroke-linejoin: round;
}

.plot__cursor line {
  stroke: var(--color-text-soft);
  stroke-dasharray: 4 3;
}

.plot__cursor circle {
  fill: var(--color-accent);
  stroke: var(--color-surface);
  stroke-width: 2;
}
</style>
