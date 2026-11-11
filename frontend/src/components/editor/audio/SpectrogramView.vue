<script setup lang="ts">
/* O espectrograma do painel Áudio: a imagem do servidor (cinza, pintada aqui com o esquema de cores), a régua de frequência
   na escala escolhida e, por cima, a seleção, o cursor e a agulha. Divide com a onda o eixo de tempo, a seleção, o cursor e
   a reprodução, que moram no store do painel. Com a ferramenta "Espectral" o mouse arrasta um retângulo no tempo e na
   frequência (as bordas se arrastam depois); com as outras, arrastar seleciona só o tempo, como na onda. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AudioWave } from '@/api'
import { useSpectrogramData } from '@/composables/useSpectrogramData'
import {
  clamp,
  PAN_FRACTION,
  sampleTicks,
  showsSampleRuler,
  snapToSample,
  timeTicks,
  timeToX,
  xToTime,
} from '@/lib/audioWave'
import { drawRuler, type WaveColors } from '@/lib/audioWaveDraw'
import {
  effectiveBand,
  fractionFrequency,
  frequencyFraction,
  frequencyTicks,
  selectionBox,
} from '@/lib/spectrogram'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useThemeStore } from '@/stores/theme'
import SpectrogramSettings from './SpectrogramSettings.vue'

const props = withDefaults(defineProps<{ data: AudioWave | null; ruler?: boolean }>(), { ruler: true })
const emit = defineEmits<{ size: [width: number]; scrub: [time: number]; 'scrub-end': [] }>()

const panel = useAudioPanelStore()
const theme = useThemeStore()

const RULER_HEIGHT = 36
const GRAB_PX = 7
const DRAG_PX = 3
const EDGE_PAN_PX = 28
const WHEEL_ZOOM = 1.25

const root = ref<HTMLElement | null>(null)
const area = ref<HTMLElement | null>(null)
const rulerCanvas = ref<HTMLCanvasElement | null>(null)
const imageCanvas = ref<HTMLCanvasElement | null>(null)
const width = ref(0)
const height = ref(0)
let observer: ResizeObserver | null = null
let drawFrame = 0

const { frame, error, loading } = useSpectrogramData(width, height)

const settings = computed(() => panel.spectrogram)
const band = computed(() => effectiveBand(settings.value, panel.rate))
const ticks = computed(() => frequencyTicks(settings.value.scale, band.value, height.value))

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

const xOf = (time: number): number => timeToX(time, panel.view, width.value)

function paint(): void {
  drawFrame = 0
  if (props.ruler) {
    const ctx = sizeCanvas(rulerCanvas.value, width.value, RULER_HEIGHT)
    if (ctx) {
      const time = timeTicks(panel.view, width.value)
      const samples = showsSampleRuler(panel.view, width.value, panel.rate) ? sampleTicks(panel.view, width.value, panel.rate) : []
      drawRuler(ctx, width.value, RULER_HEIGHT, time, samples, colors())
    }
  }
  const ctx = sizeCanvas(imageCanvas.value, width.value, height.value)
  if (!ctx) return
  ctx.clearRect(0, 0, width.value, height.value)
  const current = frame.value
  if (!current?.canvas) return
  // a imagem cobre o trecho que o servidor encaixou na grade: ela vai para o lugar certo do eixo, esticada à janela de agora
  const left = xOf(current.image.start)
  const right = xOf(current.image.end)
  ctx.imageSmoothingEnabled = true
  ctx.drawImage(current.canvas, left, 0, Math.max(right - left, 1), height.value)
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
})

watch(() => [frame.value, panel.view.start, panel.view.end, width.value, height.value, theme.theme] as const, schedulePaint)

/* ---------- coordenadas ---------- */

function localX(clientX: number): number {
  return clientX - (area.value?.getBoundingClientRect().left ?? 0)
}

function localY(clientY: number): number {
  return clientY - (area.value?.getBoundingClientRect().top ?? 0)
}

function timeAtClient(clientX: number): number {
  return clamp(xToTime(localX(clientX), panel.view, width.value), 0, panel.duration)
}

/** A frequência (Hz) sob uma altura da área, dentro da faixa mostrada. */
function hzAtY(y: number): number {
  const fraction = clamp(1 - y / Math.max(height.value, 1), 0, 1)
  return clamp(fractionFrequency(settings.value.scale, fraction, band.value), band.value.min, band.value.max)
}

const yOfHz = (hz: number): number => (1 - frequencyFraction(settings.value.scale, hz, band.value)) * height.value

/* ---------- mouse ---------- */

type Drag =
  | { kind: 'rect'; time: number; hz: number; startX: number; startY: number; moved: boolean }
  | { kind: 'edges'; start: boolean; end: boolean; low: boolean; high: boolean }
  | { kind: 'time'; anchor: number; startX: number; moved: boolean }
let drag: Drag | null = null

function box() {
  const selection = panel.selection
  return selection ? selectionBox(selection, xOf, settings.value, band.value, height.value) : null
}

/** As bordas do retângulo que o ponteiro pega (uma ou duas, nos cantos), ou nada. */
function edgesAt(x: number, y: number): { start: boolean; end: boolean; low: boolean; high: boolean } | null {
  const rectangle = box()
  if (!rectangle) return null
  const insideX = x >= rectangle.left - GRAB_PX && x <= rectangle.right + GRAB_PX
  const insideY = y >= rectangle.top - GRAB_PX && y <= rectangle.bottom + GRAB_PX
  const start = insideY && Math.abs(x - rectangle.left) <= GRAB_PX
  const end = insideY && Math.abs(x - rectangle.right) <= GRAB_PX
  const high = insideX && Math.abs(y - rectangle.top) <= GRAB_PX
  const low = insideX && Math.abs(y - rectangle.bottom) <= GRAB_PX
  return start || end || high || low ? { start, end, low, high } : null
}

function stopDrag(): void {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragUp)
  drag = null
}

function onAreaDown(event: MouseEvent): void {
  if (event.button !== 0 && !(event.button === 2 && panel.tool === 'zoom')) return
  root.value?.focus({ preventScroll: true })
  event.preventDefault()
  const x = localX(event.clientX)
  const y = localY(event.clientY)
  const time = snapToSample(timeAtClient(event.clientX), panel.rate)
  if (panel.tool === 'zoom') {
    if (event.shiftKey || event.button === 2) panel.zoomOut(time)
    else panel.zoomIn(time)
    return
  }
  if (event.shiftKey) {
    panel.extendTo(time)
    return
  }
  if (panel.tool === 'spectral') {
    const edges = edgesAt(x, y)
    drag = edges
      ? { kind: 'edges', ...edges }
      : { kind: 'rect', time, hz: hzAtY(y), startX: event.clientX, startY: event.clientY, moved: false }
    if (!edges) panel.setCursor(time)
  } else {
    drag = { kind: 'time', anchor: time, startX: event.clientX, moved: false }
    panel.setCursor(time)
  }
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragUp)
}

function onDragMove(event: MouseEvent): void {
  const current = drag
  if (!current) return
  const x = localX(event.clientX)
  const time = timeAtClient(event.clientX)
  if (current.kind === 'edges') {
    const selection = panel.selection
    if (!selection || selection.low_hz === undefined || selection.high_hz === undefined) return
    panel.selectSpectral(
      current.start ? time : selection.start,
      current.end ? time : selection.end,
      current.low ? hzAtY(localY(event.clientY)) : selection.low_hz,
      current.high ? hzAtY(localY(event.clientY)) : selection.high_hz,
    )
    return
  }
  if (!current.moved && Math.abs(event.clientX - current.startX) < DRAG_PX && (current.kind === 'time' || Math.abs(event.clientY - current.startY) < DRAG_PX)) return
  current.moved = true
  if (current.kind === 'rect') panel.selectSpectral(current.time, time, current.hz, hzAtY(localY(event.clientY)))
  else panel.select(current.anchor, time)
  if (panel.selection) panel.cursor = panel.selection.start
  // perto da borda a janela anda com o ponteiro, para a seleção poder passar do que está na tela
  const seconds = (panel.view.end - panel.view.start) * (PAN_FRACTION / 8)
  if (x > width.value - EDGE_PAN_PX) panel.pan(seconds)
  else if (x < EDGE_PAN_PX) panel.pan(-seconds)
}

function onDragUp(): void {
  const current = drag
  stopDrag()
  // um clique sem arrastar só põe o cursor: a seleção de antes sai
  if (current && current.kind !== 'edges' && !current.moved) panel.clearSelection()
}

function onAreaDouble(): void {
  if (panel.tool === 'zoom') return
  panel.selectAll()
}

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

function onWheel(event: WheelEvent): void {
  event.preventDefault()
  const span = panel.view.end - panel.view.start
  if (event.ctrlKey || event.metaKey) {
    panel.zoom(event.deltaY < 0 ? WHEEL_ZOOM : 1 / WHEEL_ZOOM, timeAtClient(event.clientX))
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
  const rectangle = box()
  const top = rectangle ? Math.max(rectangle.top, 0) : 0
  const bottom = rectangle ? Math.min(rectangle.bottom, height.value) : height.value
  return {
    left: `${Math.max(left, 0)}px`,
    width: `${Math.max(Math.min(right, width.value) - Math.max(left, 0), 1)}px`,
    top: `${top}px`,
    height: `${Math.max(bottom - top, 1)}px`,
  }
})
const spectral = computed(() => panel.selection?.low_hz !== undefined)
const cursorX = computed(() => xOf(panel.cursor))
const playheadX = computed(() => (panel.position === null ? null : xOf(panel.position)))
const cursorVisible = computed(() => cursorX.value >= 0 && cursorX.value <= width.value)

defineExpose({ focus: () => root.value?.focus({ preventScroll: true }), yOfHz })
</script>

<template>
  <div
    ref="root"
    :class="['spectrogram', `spectrogram--${panel.tool}`]"
    tabindex="0"
    role="application"
    aria-label="Espectrograma do áudio. Com a ferramenta Espectral, arraste para marcar um retângulo de tempo e frequência."
    data-audio-spectrogram
    @wheel="onWheel"
  >
    <div v-if="ruler" class="spectrogram__ruler" :style="{ height: `${RULER_HEIGHT}px` }" data-spectrogram-ruler @mousedown="onRulerDown">
      <canvas ref="rulerCanvas" class="spectrogram__canvas" aria-hidden="true" />
      <span v-if="cursorVisible" class="spectrogram__ruler-mark" :style="{ left: `${cursorX}px` }" />
    </div>
    <div ref="area" class="spectrogram__area" data-spectrogram-area @mousedown="onAreaDown" @dblclick="onAreaDouble" @contextmenu="panel.tool === 'zoom' ? $event.preventDefault() : undefined">
      <canvas ref="imageCanvas" class="spectrogram__canvas" aria-hidden="true" data-spectrogram-image />
      <ul class="spectrogram__ticks" aria-hidden="true">
        <li v-for="tick in ticks" :key="tick.hz" :style="{ top: `${(1 - tick.fraction) * height}px` }" data-frequency-tick>{{ tick.label }}</li>
      </ul>
      <div v-if="selectionStyle" :class="['spectrogram__selection', { 'is-spectral': spectral }]" :style="selectionStyle" data-selection data-spectral-selection />
      <div v-if="cursorVisible" class="spectrogram__cursor" :style="{ left: `${cursorX}px` }" data-cursor />
      <div v-if="playheadX !== null" class="spectrogram__playhead" :style="{ left: `${playheadX}px` }" data-playhead />
      <p v-if="!frame && !error" class="spectrogram__empty" role="status">{{ loading ? 'Calculando o espectrograma...' : 'Lendo o áudio...' }}</p>
      <p v-if="error" class="spectrogram__empty spectrogram__empty--error" role="alert" data-spectrogram-error>{{ error }}</p>
      <SpectrogramSettings />
    </div>
  </div>
</template>

<style scoped>
.spectrogram {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 9rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  outline: none;
  user-select: none;
}

.spectrogram:focus-visible {
  border-color: var(--color-focus);
  box-shadow: 0 0 0 1px var(--color-focus);
}

.spectrogram__ruler {
  position: relative;
  flex: none;
  border-bottom: 1px solid var(--color-border);
  cursor: ew-resize;
}

.spectrogram__ruler-mark {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--color-warning);
  pointer-events: none;
}

.spectrogram__area {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  background: #000;
  cursor: text;
}

.spectrogram--spectral .spectrogram__area,
.spectrogram--envelope .spectrogram__area,
.spectrogram--draw .spectrogram__area {
  cursor: crosshair;
}

.spectrogram--zoom .spectrogram__area {
  cursor: zoom-in;
}

.spectrogram__canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.spectrogram__ticks {
  position: absolute;
  inset: 0 auto 0 0;
  margin: 0;
  padding: 0;
  list-style: none;
  pointer-events: none;
}

.spectrogram__ticks li {
  position: absolute;
  left: 0;
  padding: 0 var(--space-1);
  border-top: 1px solid rgb(255 255 255 / 0.25);
  color: rgb(255 255 255 / 0.85);
  font-size: 10px;
  line-height: 1;
  text-shadow: 0 0 3px #000;
  transform: translateY(-50%);
}

.spectrogram__selection {
  position: absolute;
  background: rgb(143 163 255 / 0.22);
  border-left: 1px solid var(--color-info);
  border-right: 1px solid var(--color-info);
  pointer-events: none;
}

.spectrogram__selection.is-spectral {
  border: 1px solid var(--color-info);
  box-shadow: 0 0 0 1px rgb(0 0 0 / 0.5);
}

.spectrogram__cursor,
.spectrogram__playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  pointer-events: none;
}

.spectrogram__cursor {
  background: var(--color-warning);
}

.spectrogram__playhead {
  width: 2px;
  background: #fff;
}

.spectrogram__empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  margin: 0;
  color: rgb(255 255 255 / 0.7);
  font-size: var(--text-sm);
  pointer-events: none;
}

.spectrogram__empty--error {
  color: var(--color-error);
}
</style>
