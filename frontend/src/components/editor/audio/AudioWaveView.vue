<script setup lang="ts">
/* A onda do painel Áudio: a régua em tempo (e em amostras, quando a janela é pequena), um canal por faixa e, por cima,
   a seleção, o cursor, a agulha da reprodução e o envelope. Todo o mouse passa por aqui: arrastar seleciona, a roda
   aproxima (com Ctrl) ou anda, a régua é onde se arrasta a agulha ouvindo (scrub) e, com a ferramenta de envelope, os
   pontos se arrastam sobre a onda. O que se desenha vem de `useWaveData`; as contas de janela e seleção são de `lib/audioWave`. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AudioWave } from '@/api'
import {
  canDraw,
  clamp,
  PAN_FRACTION,
  sampleTicks,
  showsSampleRuler,
  timeTicks,
  timeToX,
  xToTime,
  snapToSample,
} from '@/lib/audioWave'
import { chainOf, isEnabled } from '@/lib/audioEffects'
import { drawChannels, drawRuler, type WaveColors } from '@/lib/audioWaveDraw'
import {
  ENVELOPE_MAX_DB,
  ENVELOPE_MIN_DB,
  effectsPathOf,
  tidyEnvelope,
  type EnvelopePoint,
} from '@/lib/audioPanelOps'
import { multiToolAt } from '@/lib/audioTools'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useEditorStore } from '@/stores/editor'
import { useThemeStore } from '@/stores/theme'
import { useDrawTool } from '@/composables/useDrawTool'

const props = defineProps<{ data: AudioWave | null }>()
const emit = defineEmits<{ size: [width: number]; scrub: [time: number]; 'scrub-end': [] }>()

const panel = useAudioPanelStore()
const editor = useEditorStore()
const theme = useThemeStore()

const RULER_HEIGHT = 36
/** O ponteiro a até estes pixels de um ponto do envelope ou das bordas da seleção o pega. */
const GRAB_PX = 7
/** O ponteiro precisa andar tantos pixels antes de um clique virar arrasto. */
const DRAG_PX = 3
const EDGE_PAN_PX = 28

const root = ref<HTMLElement | null>(null)
const area = ref<HTMLElement | null>(null)
const rulerCanvas = ref<HTMLCanvasElement | null>(null)
const waveCanvas = ref<HTMLCanvasElement | null>(null)
const width = ref(0)
const height = ref(0)
let observer: ResizeObserver | null = null
let drawFrame = 0

/* ---------- desenho ---------- */

function colors(): WaveColors {
  const style = getComputedStyle(root.value ?? document.documentElement)
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    wave: read('--color-accent-strong', '#18d770'),
    line: read('--color-border-strong', '#39594d'),
    pending: 'rgb(128 128 128 / 0.18)',
    text: read('--color-text-soft', '#9db'),
    sample: read('--color-accent-text', '#08df9c'),
  }
}

function sizeCanvas(canvas: HTMLCanvasElement | null, cssWidth: number, cssHeight: number): CanvasRenderingContext2D | null {
  if (!canvas || cssWidth <= 0 || cssHeight <= 0) return null
  const ratio = window.devicePixelRatio || 1
  const pixelWidth = Math.round(cssWidth * ratio)
  const pixelHeight = Math.round(cssHeight * ratio)
  if (canvas.width !== pixelWidth) canvas.width = pixelWidth
  if (canvas.height !== pixelHeight) canvas.height = pixelHeight
  const ctx = canvas.getContext('2d')
  ctx?.setTransform(ratio, 0, 0, ratio, 0, 0)
  return ctx
}

function paint(): void {
  drawFrame = 0
  const palette = colors()
  const ruler = sizeCanvas(rulerCanvas.value, width.value, RULER_HEIGHT)
  if (ruler) {
    const time = timeTicks(panel.view, width.value)
    const samples = showsSampleRuler(panel.view, width.value, panel.rate) ? sampleTicks(panel.view, width.value, panel.rate) : []
    drawRuler(ruler, width.value, RULER_HEIGHT, time, samples, palette)
  }
  const wave = sizeCanvas(waveCanvas.value, width.value, height.value)
  if (wave) {
    drawChannels(wave, {
      data: props.data,
      view: panel.view,
      width: width.value,
      height: height.value,
      channels: panel.channels,
      colors: palette,
    })
  }
}

function schedulePaint(): void {
  if (drawFrame) return
  drawFrame = requestAnimationFrame(paint)
}

function measure(): void {
  const element = area.value
  if (!element) return
  const box = element.getBoundingClientRect()
  if (Math.round(box.width) !== width.value) {
    width.value = Math.round(box.width)
    emit('size', width.value)
  }
  height.value = Math.round(box.height)
}

onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && area.value) {
    observer = new ResizeObserver(measure)
    observer.observe(area.value)
  }
  schedulePaint()
})
onBeforeUnmount(() => {
  observer?.disconnect()
  if (drawFrame) cancelAnimationFrame(drawFrame)
  stopDrag()
  draw.cancel()
})

watch(
  () => [props.data, panel.view.start, panel.view.end, width.value, height.value, panel.channels, theme.theme] as const,
  schedulePaint,
)

/* ---------- coordenadas ---------- */

function localX(clientX: number): number {
  const box = area.value?.getBoundingClientRect()
  return clientX - (box?.left ?? 0)
}

function localY(clientY: number): number {
  const box = area.value?.getBoundingClientRect()
  return clientY - (box?.top ?? 0)
}

function timeAtClient(clientX: number): number {
  return clamp(xToTime(localX(clientX), panel.view, width.value), 0, panel.duration)
}

const xOf = (time: number): number => timeToX(time, panel.view, width.value)

/* ---------- envelope ---------- */

/** O primeiro envelope ligado da cadeia do item, que é o que o painel edita. */
const envelope = computed(() => {
  if (!panel.target) return null
  const chain = chainOf(editor.spec, effectsPathOf(panel.target))
  const index = chain.findIndex((effect) => effect.type === 'envelope' && isEnabled(effect))
  if (index < 0) return null
  const raw = (chain[index] as { points?: Array<{ at: number; db: number }> }).points ?? []
  return { index, points: raw.map((point): EnvelopePoint => ({ at: point.at, db: point.db })) }
})

const draft = ref<EnvelopePoint[] | null>(null)
const envelopePoints = computed<EnvelopePoint[]>(() => draft.value ?? envelope.value?.points ?? [])

const dbToY = (db: number): number => ((ENVELOPE_MAX_DB - clamp(db, ENVELOPE_MIN_DB, ENVELOPE_MAX_DB)) / (ENVELOPE_MAX_DB - ENVELOPE_MIN_DB)) * height.value
const yToDb = (y: number): number => ENVELOPE_MAX_DB - clamp(y / Math.max(height.value, 1), 0, 1) * (ENVELOPE_MAX_DB - ENVELOPE_MIN_DB)

const envelopePath = computed(() =>
  envelopePoints.value.map((point) => `${xOf(point.at).toFixed(1)},${dbToY(point.db).toFixed(1)}`).join(' '),
)
const showEnvelope = computed(() => envelopePoints.value.length > 0 || panel.tool === 'envelope')
const showEnvelopePoints = computed(() => panel.tool === 'envelope' || panel.tool === 'multi')
const zeroDbY = computed(() => dbToY(0))

function hitPoint(x: number, y: number): number {
  return envelopePoints.value.findIndex((point) => Math.abs(xOf(point.at) - x) <= GRAB_PX && Math.abs(dbToY(point.db) - y) <= GRAB_PX)
}

/** O ponteiro está sobre a linha do envelope (para a multiferramenta). */
function overEnvelopeLine(x: number, y: number): boolean {
  const points = envelopePoints.value
  if (points.length === 0) return false
  const time = xToTime(x, panel.view, width.value)
  let gain = (points[0] as EnvelopePoint).db
  const first = points[0] as EnvelopePoint
  const last = points[points.length - 1] as EnvelopePoint
  if (time > last.at) gain = last.db
  else if (time >= first.at) {
    for (let index = 1; index < points.length; index += 1) {
      const before = points[index - 1] as EnvelopePoint
      const after = points[index] as EnvelopePoint
      if (time <= after.at) {
        gain = before.db + ((after.db - before.db) * (time - before.at)) / Math.max(after.at - before.at, 1e-9)
        break
      }
    }
  }
  return Math.abs(dbToY(gain) - y) <= GRAB_PX
}

let envelopeDrag: { point: EnvelopePoint; moved: boolean } | null = null

async function commitEnvelope(points: EnvelopePoint[]): Promise<void> {
  editor.beginGesture()
  try {
    const done = await panel.applyEnvelope(points, envelope.value?.index ?? null)
    // o gesto direto grava ao soltar (o resto do editor continua pelo Salvar); um 409 já abriu a faixa de escolha do disco
    if (done && editor.dirty) await editor.save({ quiet: true })
  } finally {
    draft.value = null
    editor.endGesture()
  }
}

function startEnvelope(event: MouseEvent, x: number, y: number, time: number): void {
  const points = envelopePoints.value.map((point) => ({ ...point }))
  const hit = hitPoint(x, y)
  if (hit >= 0 && event.altKey) {
    points.splice(hit, 1)
    if (points.length === 0) {
      // sem pontos não há curva: o efeito sai pelo painel Filtros, onde ele continua na cadeia
      return
    }
    void commitEnvelope(points)
    return
  }
  let point: EnvelopePoint
  if (hit >= 0) {
    point = points[hit] as EnvelopePoint
  } else {
    point = { at: time, db: Math.round(yToDb(y) * 10) / 10 }
    points.push(point)
  }
  draft.value = points
  envelopeDrag = { point, moved: hit < 0 }
  document.addEventListener('mousemove', onEnvelopeMove)
  document.addEventListener('mouseup', onEnvelopeUp)
}

function onEnvelopeMove(event: MouseEvent): void {
  if (!envelopeDrag || !draft.value) return
  envelopeDrag.moved = true
  const point = envelopeDrag.point
  point.at = timeAtClient(event.clientX)
  point.db = yToDb(localY(event.clientY))
  draft.value = [...draft.value].sort((a, b) => a.at - b.at)
}

function onEnvelopeUp(): void {
  document.removeEventListener('mousemove', onEnvelopeMove)
  document.removeEventListener('mouseup', onEnvelopeUp)
  const points = draft.value
  const moved = envelopeDrag?.moved ?? false
  envelopeDrag = null
  if (!points || !moved) {
    draft.value = null
    return
  }
  void commitEnvelope(tidyEnvelope(points))
}

/* ---------- selecionar ---------- */

type Drag =
  | { kind: 'select'; anchor: number; startX: number; moved: boolean }
  | { kind: 'zoom'; anchor: number; startX: number; current: number; moved: boolean }
let drag: Drag | null = null
const zoomBand = ref<{ start: number; end: number } | null>(null)

function edgeAt(x: number): 'start' | 'end' | null {
  const selection = panel.selection
  if (!selection) return null
  if (Math.abs(xOf(selection.start) - x) <= GRAB_PX) return 'start'
  if (Math.abs(xOf(selection.end) - x) <= GRAB_PX) return 'end'
  return null
}

function stopDrag(): void {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragUp)
  document.removeEventListener('mousemove', onEnvelopeMove)
  document.removeEventListener('mouseup', onEnvelopeUp)
  drag = null
  zoomBand.value = null
}

function startSelect(event: MouseEvent, x: number, time: number): void {
  if (event.shiftKey) {
    panel.extendTo(time)
    return
  }
  const edge = edgeAt(x)
  const selection = panel.selection
  if (edge && selection) {
    drag = { kind: 'select', anchor: edge === 'start' ? selection.end : selection.start, startX: event.clientX, moved: true }
  } else {
    drag = { kind: 'select', anchor: time, startX: event.clientX, moved: false }
    panel.setCursor(time)
  }
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragUp)
}

function startZoom(event: MouseEvent, time: number): void {
  if (event.shiftKey || event.button === 2) {
    panel.zoomOut(time)
    return
  }
  drag = { kind: 'zoom', anchor: time, startX: event.clientX, current: time, moved: false }
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragUp)
}

function onDragMove(event: MouseEvent): void {
  const current = drag
  if (!current) return
  const x = localX(event.clientX)
  if (!current.moved && Math.abs(event.clientX - current.startX) < DRAG_PX) return
  current.moved = true
  const time = timeAtClient(event.clientX)
  if (current.kind === 'zoom') {
    current.current = time
    zoomBand.value = { start: Math.min(current.anchor, time), end: Math.max(current.anchor, time) }
    return
  }
  panel.select(current.anchor, time)
  if (panel.selection) panel.cursor = panel.selection.start
  // perto da borda a janela anda com o ponteiro, para a seleção poder passar do que está na tela
  const seconds = (panel.view.end - panel.view.start) * (PAN_FRACTION / 8)
  if (x > width.value - EDGE_PAN_PX) panel.pan(seconds)
  else if (x < EDGE_PAN_PX) panel.pan(-seconds)
}

function onDragUp(event: MouseEvent): void {
  const current = drag
  stopDrag()
  if (!current) return
  if (current.kind === 'zoom') {
    if (current.moved && current.current !== current.anchor) {
      panel.zoomToRange(current.anchor, current.current)
    } else {
      panel.zoomIn(current.anchor)
    }
    return
  }
  // um clique sem arrastar só põe o cursor: a seleção de antes sai
  if (!current.moved) panel.clearSelection()
  void event
}

const draw = useDrawTool({ area, width, height, data: () => props.data })

function onAreaDown(event: MouseEvent): void {
  if (event.button !== 0 && !(event.button === 2 && panel.tool === 'zoom')) return
  root.value?.focus({ preventScroll: true })
  const x = localX(event.clientX)
  const y = localY(event.clientY)
  const time = snapToSample(timeAtClient(event.clientX), panel.rate)
  const tool =
    panel.tool === 'multi'
      ? multiToolAt({ canDraw: canDraw(panel.view, width.value, panel.rate), overEnvelope: overEnvelopeLine(x, y) || hitPoint(x, y) >= 0 })
      : panel.tool
  event.preventDefault()
  if (tool === 'envelope') startEnvelope(event, x, y, time)
  else if (tool === 'draw') draw.start(event)
  else if (tool === 'zoom') startZoom(event, time)
  else startSelect(event, x, time)
}

function onAreaDouble(event: MouseEvent): void {
  if (panel.tool === 'zoom' || panel.tool === 'draw') return
  const x = localX(event.clientX)
  const y = localY(event.clientY)
  if ((panel.tool === 'envelope' || panel.tool === 'multi') && hitPoint(x, y) >= 0) return
  panel.selectAll()
}

/* ---------- a régua: arrastar a agulha ouvindo ---------- */

function onRulerDown(event: MouseEvent): void {
  if (event.button !== 0) return
  event.preventDefault()
  root.value?.focus({ preventScroll: true })
  const move = (at: MouseEvent): void => {
    const time = snapToSample(timeAtClient(at.clientX), panel.rate)
    panel.setCursor(time)
    emit('scrub', time)
  }
  move(event)
  const up = (): void => {
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', up)
    emit('scrub-end')
  }
  document.addEventListener('mousemove', move)
  document.addEventListener('mouseup', up)
}

/* ---------- a roda ---------- */

const WHEEL_ZOOM = 1.25

function onWheel(event: WheelEvent): void {
  event.preventDefault()
  const span = panel.view.end - panel.view.start
  if (event.ctrlKey || event.metaKey) {
    const anchor = timeAtClient(event.clientX)
    panel.zoom(event.deltaY < 0 ? WHEEL_ZOOM : 1 / WHEEL_ZOOM, anchor)
    return
  }
  const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
  panel.pan(Math.sign(delta) * span * PAN_FRACTION * Math.min(Math.abs(delta) / 100, 2))
}

/* ---------- sobreposições ---------- */

const selectionStyle = computed(() => {
  const selection = panel.selection
  if (!selection) return null
  const left = xOf(selection.start)
  const right = xOf(selection.end)
  if (right < 0 || left > width.value) return null
  return { left: `${Math.max(left, 0)}px`, width: `${Math.max(Math.min(right, width.value) - Math.max(left, 0), 1)}px` }
})
const cursorX = computed(() => xOf(panel.cursor))
const playheadX = computed(() => (panel.position === null ? null : xOf(panel.position)))
const cursorVisible = computed(() => cursorX.value >= 0 && cursorX.value <= width.value)
const bandStyle = computed(() => {
  const band = zoomBand.value
  return band ? { left: `${xOf(band.start)}px`, width: `${Math.max(xOf(band.end) - xOf(band.start), 1)}px` } : null
})
const cursorClass = computed(() => `wave--${panel.tool}`)

defineExpose({ focus: () => root.value?.focus({ preventScroll: true }) })
</script>

<template>
  <div
    ref="root"
    :class="['wave', cursorClass]"
    tabindex="0"
    role="application"
    aria-label="Onda do áudio. Arraste para selecionar, Espaço toca, Ctrl mais roda aproxima."
    data-audio-wave
    @wheel="onWheel"
  >
    <div class="wave__ruler" :style="{ height: `${RULER_HEIGHT}px` }" data-wave-ruler @mousedown="onRulerDown">
      <canvas ref="rulerCanvas" class="wave__canvas" aria-hidden="true" />
      <span v-if="cursorVisible" class="wave__ruler-mark" :style="{ left: `${cursorX}px` }" />
    </div>
    <div
      ref="area"
      class="wave__area"
      data-wave-area
      @mousedown="onAreaDown"
      @dblclick="onAreaDouble"
      @contextmenu="panel.tool === 'zoom' ? $event.preventDefault() : undefined"
    >
      <canvas ref="waveCanvas" class="wave__canvas" aria-hidden="true" />
      <div v-if="selectionStyle" class="wave__selection" :style="selectionStyle" data-selection />
      <div v-if="zoomBand" class="wave__selection wave__selection--zoom" :style="bandStyle ?? undefined" />
      <div v-if="cursorVisible" class="wave__cursor" :style="{ left: `${cursorX}px` }" data-cursor />
      <div v-if="playheadX !== null" class="wave__playhead" :style="{ left: `${playheadX}px` }" data-playhead />
      <svg v-if="showEnvelope && width > 0" class="wave__envelope" :width="width" :height="height" aria-hidden="true">
        <line class="wave__zero-db" x1="0" :x2="width" :y1="zeroDbY" :y2="zeroDbY" />
        <polyline v-if="envelopePoints.length > 1" class="wave__curve" :points="envelopePath" />
        <template v-if="showEnvelopePoints">
          <circle
            v-for="(point, index) in envelopePoints"
            :key="index"
            class="wave__point"
            :cx="xOf(point.at)"
            :cy="dbToY(point.db)"
            r="5"
            data-envelope-point
          />
        </template>
      </svg>
      <svg v-if="draw.preview.value.length > 0" class="wave__envelope" :width="width" :height="height" aria-hidden="true">
        <polyline v-for="(line, index) in draw.preview.value" :key="index" class="wave__curve wave__curve--draw" :points="line" />
      </svg>
      <p v-if="!props.data" class="wave__empty">Lendo o áudio...</p>
    </div>
  </div>
</template>

<style scoped>
.wave {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  /* poucos pixels de onda não servem para editar: a barra de rolagem do painel entra antes disto */
  min-height: 9rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  outline: none;
  user-select: none;
}

.wave:focus-visible {
  border-color: var(--color-focus);
  box-shadow: 0 0 0 1px var(--color-focus);
}

.wave__ruler {
  position: relative;
  flex: none;
  border-bottom: 1px solid var(--color-border);
  cursor: ew-resize;
}

.wave__ruler-mark {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--color-warning);
  pointer-events: none;
}

.wave__area {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  cursor: text;
}

.wave--zoom .wave__area {
  cursor: zoom-in;
}

.wave--envelope .wave__area,
.wave--draw .wave__area {
  cursor: crosshair;
}

.wave__canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.wave__ruler .wave__canvas {
  height: 100%;
}

.wave__selection {
  position: absolute;
  top: 0;
  bottom: 0;
  background: rgb(143 163 255 / 0.28);
  border-left: 1px solid var(--color-info);
  border-right: 1px solid var(--color-info);
  pointer-events: none;
}

.wave__selection--zoom {
  background: var(--color-accent-bg);
  border-color: var(--color-accent-text);
}

.wave__cursor,
.wave__playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  pointer-events: none;
}

.wave__cursor {
  background: var(--color-warning);
}

.wave__playhead {
  width: 2px;
  background: var(--color-text);
}

.wave__envelope {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.wave__zero-db {
  stroke: var(--color-warning);
  stroke-dasharray: 3 4;
  opacity: 0.45;
}

.wave__curve {
  fill: none;
  stroke: var(--color-warning);
  stroke-width: 2;
}

.wave__curve--draw {
  stroke: var(--color-accent-text);
}

.wave__point {
  fill: var(--color-surface);
  stroke: var(--color-warning);
  stroke-width: 2;
}

.wave__empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  pointer-events: none;
}
</style>
