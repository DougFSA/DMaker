<script setup lang="ts">
/* A forma de onda de um item (ou de um pedaço dele, quando a fonte tem várias partes). O canvas cobre só a janela
   visível do item, não o item inteiro: um item de uma hora no zoom máximo teria dezenas de milhares de pixels. Os
   picos vêm do servidor, uma vez por arquivo, e o canvas se refaz quando a janela, o zoom ou a seleção mudam. */
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import type { TimelineItem, Waveform } from '@/api'
import { itemLoops, waveformColumns, waveformWindow, WAVEFORM_HEIGHT_PX, WAVEFORM_MAX_PX } from '@/lib/waveform'
import { useEditorStore } from '@/stores/editor'
import { useTimelineStore } from '@/stores/timeline'
import { useWaveformStore } from '@/stores/waveforms'

const props = defineProps<{
  item: TimelineItem
  /** Qual pedaço do clipe este canvas desenha; nulo para o item inteiro. */
  pieceIndex: number | null
  selected: boolean
}>()

const COLOR = 'rgba(255, 255, 255, 0.5)'
const COLOR_SELECTED = 'rgba(255, 255, 255, 0.88)'
const COLOR_MUTED = 'rgba(255, 255, 255, 0.2)'

const editor = useEditorStore()
const timeline = useTimelineStore()
const waveforms = useWaveformStore()

const canvas = ref<HTMLCanvasElement | null>(null)
const peaks = shallowRef<Waveform | null>(null)

const wave = computed(() => (editor.view ? waveformWindow(editor.view, props.item, props.pieceIndex) : null))

/** Onde o canvas fica dentro do item e o trecho do arquivo que ele mostra; nulo se o pedaço está fora da janela. */
const geometry = computed(() => {
  const current = wave.value
  if (!current?.path) return null
  const px = timeline.pxPerSec
  const visibleStart = Math.max(current.start * px, timeline.windowLeftPx)
  const visibleEnd = Math.min(current.end * px, timeline.windowRightPx)
  if (visibleEnd <= visibleStart) return null
  const width = Math.min(WAVEFORM_MAX_PX, visibleEnd - visibleStart)
  return {
    left: visibleStart - props.item.start * px,
    width,
    fileStart: current.fileTimeAt(visibleStart / px),
    fileEnd: current.fileTimeAt((visibleStart + width) / px),
  }
})

const path = computed(() => (props.item.missing ? null : (wave.value?.path ?? null)))

async function loadPeaks(): Promise<void> {
  const wanted = path.value
  const result = await waveforms.peaks(wanted)
  // o item pode ter mudado de arquivo enquanto o servidor respondia
  if (wanted === path.value) peaks.value = result
}

function paint(): void {
  const element = canvas.value
  const area = geometry.value
  const waveform = peaks.value
  if (!element || !area) return
  const ratio = (typeof window !== 'undefined' && window.devicePixelRatio) || 1
  const width = Math.max(1, Math.round(area.width * ratio))
  const height = Math.max(1, Math.round(WAVEFORM_HEIGHT_PX * ratio))
  if (element.width !== width) element.width = width
  if (element.height !== height) element.height = height
  const context = element.getContext('2d')
  if (!context) return
  context.clearRect(0, 0, width, height)
  if (!waveform) return
  const columns = waveformColumns(width, waveform, area.fileStart, area.fileEnd, itemLoops(props.item))
  context.fillStyle = props.item.muted ? COLOR_MUTED : props.selected ? COLOR_SELECTED : COLOR
  const middle = height / 2
  context.beginPath()
  columns.forEach((amplitude, column) => {
    if (amplitude <= 0) return
    const bar = Math.max(1, amplitude * height)
    context.rect(column, middle - bar / 2, 1, bar)
  })
  context.fill()
}

watch(path, () => void loadPeaks())
watch([geometry, peaks, () => props.selected, () => props.item.muted, () => props.item.extra], paint, { flush: 'post' })
onMounted(() => {
  void loadPeaks()
  paint()
})
</script>

<template>
  <canvas
    v-show="geometry"
    ref="canvas"
    class="waveform"
    :style="geometry ? { left: `${geometry.left}px`, width: `${geometry.width}px`, height: `${WAVEFORM_HEIGHT_PX}px` } : undefined"
    aria-hidden="true"
  />
</template>

<style scoped>
.waveform {
  position: absolute;
  top: 3px;
  pointer-events: none;
}
</style>
