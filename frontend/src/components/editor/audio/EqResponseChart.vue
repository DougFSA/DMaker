<script setup lang="ts">
/* O gráfico da resposta de frequência de um efeito de equalização: Hz em oitavas (20 Hz a 20 kHz) na horizontal, dB na
   vertical, a curva que o servidor calculou (a mesma conta do render) e, no EQ por Curva, os pontos arrastáveis. Arrastar
   um ponto muda a lista ao vivo (`update:points`) e grava ao soltar (`commit`); clique duplo no fundo acrescenta um ponto,
   clique duplo num ponto o tira, e as setas movem o ponto em foco (frequência em passos de 1/12 de oitava, ganho em 1 dB). */
import { computed, ref } from 'vue'
import type { CurvePoint, EffectResponse } from '@/api'
import {
  CHART_MAX_HZ,
  CHART_MIN_HZ,
  FREQUENCY_TICKS,
  addPoint,
  chartRange,
  curvePath,
  dbTicks,
  dbToY,
  formatFrequency,
  formatGain,
  hzToX,
  movePoint,
  removePoint,
  responseAt,
  xToHz,
  yToDb,
  type DbRange,
} from '@/lib/eqChart'

const props = defineProps<{
  curve: EffectResponse | null
  /** Os pontos arrastáveis (o EQ por Curva); sem eles o gráfico só mostra a curva. */
  points?: CurvePoint[]
  /** Trava a faixa de dB (os pontos arrastáveis precisam dela fixa para o desenho não pular durante o arraste). */
  range?: DbRange
  label: string
}>()

const emit = defineEmits<{
  'update:points': [points: CurvePoint[]]
  commit: []
}>()

/** O tamanho do desenho em unidades do SVG; o CSS o estica à largura do painel. */
const BOX = { width: 480, height: 200 }
/** Um passo de 1/12 de oitava com as setas. */
const KEY_STEP = 2 ** (1 / 12)

const svg = ref<SVGSVGElement | null>(null)
const dragging = ref<number | null>(null)
const focused = ref<number | null>(null)
const readout = ref('')

const editable = computed(() => props.points !== undefined)
const range = computed(() => chartRange(props.curve, props.points ?? [], props.range))
const path = computed(() => curvePath(props.curve, range.value, BOX))
const dbLines = computed(() => dbTicks(range.value).map((db) => ({ db, y: dbToY(db, range.value, BOX.height) })))
const hzLines = computed(() => FREQUENCY_TICKS.map((hz) => ({ hz, x: hzToX(hz, BOX.width) })))
const handles = computed(() =>
  (props.points ?? []).map((point, index) => ({
    index,
    point,
    x: hzToX(point.hz, BOX.width),
    y: dbToY(point.db, range.value, BOX.height),
  })),
)

function frequencyText(hz: number): string {
  return hz >= 1000 ? `${hz / 1000}k` : String(hz)
}

/** O ponto do clique em coordenadas do desenho (o SVG é esticado pelo CSS, então a conta passa pelo retângulo na tela). */
function local(event: PointerEvent | MouseEvent): { x: number; y: number } {
  const box = svg.value?.getBoundingClientRect()
  if (!box || box.width === 0 || box.height === 0) return { x: 0, y: 0 }
  return {
    x: ((event.clientX - box.left) / box.width) * BOX.width,
    y: ((event.clientY - box.top) / box.height) * BOX.height,
  }
}

function describePoint(point: CurvePoint): string {
  return `${formatFrequency(point.hz)}, ${formatGain(point.db)}`
}

function onHandleDown(index: number, event: PointerEvent): void {
  if (!editable.value) return
  event.preventDefault()
  ;(event.currentTarget as Element).setPointerCapture?.(event.pointerId)
  dragging.value = index
  focused.value = index
}

function onMove(event: PointerEvent): void {
  const position = local(event)
  const index = dragging.value
  if (index !== null && props.points) {
    const next = movePoint(props.points, index, xToHz(position.x, BOX.width), yToDb(position.y, range.value, BOX.height))
    emit('update:points', next)
    const moved = next[index]
    if (moved) readout.value = describePoint(moved)
    return
  }
  const hz = xToHz(position.x, BOX.width)
  const gain = responseAt(props.curve, hz)
  readout.value = gain === null ? '' : `${formatFrequency(hz)}, ${formatGain(gain)}`
}

function endDrag(): void {
  if (dragging.value === null) return
  dragging.value = null
  emit('commit')
}

function onBackgroundDouble(event: MouseEvent): void {
  if (!editable.value || !props.points) return
  const position = local(event)
  const hz = xToHz(position.x, BOX.width)
  const gain = props.curve ? (responseAt(props.curve, hz) ?? 0) : 0
  const next = addPoint(props.points, hz, gain)
  if (next.length === props.points.length) return
  emit('update:points', next)
  emit('commit')
}

function onHandleDouble(index: number, event: MouseEvent): void {
  event.stopPropagation()
  if (!props.points) return
  const next = removePoint(props.points, index)
  if (next.length === props.points.length) return
  emit('update:points', next)
  emit('commit')
}

function onKey(index: number, event: KeyboardEvent): void {
  const points = props.points
  const point = points?.[index]
  if (!points || !point) return
  const step = event.shiftKey ? 6 : 1
  let hz = point.hz
  let db = point.db
  if (event.key === 'ArrowUp') db += step
  else if (event.key === 'ArrowDown') db -= step
  else if (event.key === 'ArrowLeft') hz /= KEY_STEP
  else if (event.key === 'ArrowRight') hz *= KEY_STEP
  else if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault()
    onHandleDouble(index, new MouseEvent('dblclick'))
    return
  } else return
  event.preventDefault()
  emit('update:points', movePoint(points, index, hz, db))
}

function onKeyUp(event: KeyboardEvent): void {
  if (event.key.startsWith('Arrow')) emit('commit')
}
</script>

<template>
  <figure class="eq-chart" data-eq-chart>
    <div class="eq-chart__plot">
      <svg
        ref="svg"
        class="eq-chart__svg"
        :viewBox="`0 0 ${BOX.width} ${BOX.height}`"
        role="img"
        :aria-label="label"
        preserveAspectRatio="none"
        @pointermove="onMove"
        @pointerup="endDrag"
        @pointercancel="endDrag"
        @pointerleave="readout = dragging === null ? '' : readout"
        @dblclick="onBackgroundDouble"
      >
        <g class="eq-chart__grid" aria-hidden="true">
          <line v-for="line in dbLines" :key="`db${line.db}`" :class="{ 'is-zero': line.db === 0 }" x1="0" :x2="BOX.width" :y1="line.y" :y2="line.y" />
          <line v-for="line in hzLines" :key="`hz${line.hz}`" :x1="line.x" :x2="line.x" y1="0" :y2="BOX.height" />
        </g>
        <path v-if="path" class="eq-chart__curve" :d="path" data-eq-curve />
        <g v-if="editable" class="eq-chart__handles">
          <circle
            v-for="handle in handles"
            :key="handle.index"
            :class="['eq-chart__handle', { 'is-active': dragging === handle.index || focused === handle.index }]"
            :cx="handle.x"
            :cy="handle.y"
            r="7"
            tabindex="0"
            role="slider"
            :aria-label="`Ponto ${handle.index + 1}`"
            :aria-valuetext="describePoint(handle.point)"
            :aria-valuenow="handle.point.db"
            :data-eq-point="handle.index"
            @pointerdown="onHandleDown(handle.index, $event)"
            @dblclick="onHandleDouble(handle.index, $event)"
            @keydown="onKey(handle.index, $event)"
            @keyup="onKeyUp"
            @focus="focused = handle.index"
            @blur="focused = null"
          />
        </g>
      </svg>
      <div class="eq-chart__axis eq-chart__axis--x" aria-hidden="true">
        <span v-for="line in hzLines" :key="line.hz" :style="{ left: `${(line.x / BOX.width) * 100}%` }">{{ frequencyText(line.hz) }}</span>
      </div>
      <div class="eq-chart__axis eq-chart__axis--y" aria-hidden="true">
        <span v-for="line in dbLines" :key="line.db" :style="{ top: `${(line.y / BOX.height) * 100}%` }">{{ line.db > 0 ? '+' : '' }}{{ line.db }}</span>
      </div>
    </div>
    <figcaption class="eq-chart__readout" data-eq-readout aria-live="off">
      {{ readout || (editable ? 'Arraste os pontos; clique duas vezes no fundo para acrescentar e num ponto para tirar.' : `${CHART_MIN_HZ} Hz a ${CHART_MAX_HZ / 1000} kHz, em dB`) }}
    </figcaption>
  </figure>
</template>

<style scoped>
.eq-chart {
  margin: 0;
}

/* o desenho com as legendas dos eixos: o espaço da esquerda é dos dB e o de baixo, dos Hz */
.eq-chart__plot {
  position: relative;
  padding: 0 0 1.1rem 1.75rem;
}

.eq-chart__svg {
  display: block;
  width: 100%;
  aspect-ratio: 12 / 5;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  touch-action: none;
}

.eq-chart__grid line {
  stroke: var(--color-border);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.eq-chart__grid line.is-zero {
  stroke: var(--color-text-muted);
}

.eq-chart__curve {
  fill: none;
  stroke: var(--color-accent);
  stroke-width: 2;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}

.eq-chart__handle {
  fill: var(--color-surface-raised);
  stroke: var(--color-accent);
  stroke-width: 2;
  cursor: grab;
  vector-effect: non-scaling-stroke;
}

.eq-chart__handle.is-active,
.eq-chart__handle:hover {
  fill: var(--color-accent);
}

.eq-chart__handle:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

.eq-chart__axis {
  position: absolute;
  font-size: 0.65rem;
  color: var(--color-text-muted);
  pointer-events: none;
}

.eq-chart__axis--x {
  right: 0;
  bottom: 0;
  left: 1.75rem;
  height: 1rem;
}

.eq-chart__axis--x span {
  position: absolute;
  transform: translateX(-50%);
}

.eq-chart__axis--y {
  top: 0;
  bottom: 1.1rem;
  left: 0;
  width: 1.6rem;
}

.eq-chart__axis--y span {
  position: absolute;
  right: 0.2rem;
  transform: translateY(-50%);
}

.eq-chart__readout {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}
</style>
