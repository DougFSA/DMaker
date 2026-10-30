<script setup lang="ts">
/* A linha do tempo multitrilha: régua, trilhas (V1, V2+, TX, GR, A1, A2+, NAR, MUS e CC) e o cursor. Mostra a vista
   do store do editor e devolve a intenção da pessoa: clicar seleciona, arrastar muda de ordem ou desloca, puxar a
   borda apara, clicar na régua leva o cursor. Toda mudança passa por `editor.applyOp`. O mouse é tratado por
   delegação (um só ouvinte para todos os itens) e só os itens da janela visível existem no documento. */
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import type { TimelineTrack } from '@/api'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useEditorActions } from '@/composables/useEditorActions'
import {
  dragOperation,
  dragPreview,
  type DragMode,
  type DragPreview,
  type DragStart,
  type SnapContext,
} from '@/lib/timelineDrag'
import {
  laneWidth,
  MEDIA_DND_MIME,
  RULER_HEIGHT,
  snapPoints,
  snapTime,
  timeAtX,
  TRACK_HEADER_WIDTH,
  TRACK_ROW_HEIGHT,
  type TrackToggle,
} from '@/lib/timeline'
import { useEditorStore } from '@/stores/editor'
import { usePlayerStore } from '@/stores/player'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import TimelinePlayhead from './TimelinePlayhead.vue'
import TimelineRuler from './TimelineRuler.vue'
import TimelineTimecode from './TimelineTimecode.vue'
import TimelineToolbar from './TimelineToolbar.vue'
import TimelineTrackRow from './TimelineTrackRow.vue'

const editor = useEditorStore()
const player = usePlayerStore()
const timeline = useTimelineStore()
const toasts = useToastsStore()
const actions = useEditorActions()

/** Quanto o mouse precisa andar (pixels) antes de um clique virar arrasto. */
const DRAG_THRESHOLD_PX = 3
/** Folga entre o cursor e a borda da tela ao acompanhá-lo durante a reprodução. */
const FOLLOW_MARGIN_PX = 40

const scrollEl = ref<HTMLElement | null>(null)

const view = computed(() => editor.view)
const tracks = computed(() => view.value?.tracks ?? [])
const total = computed(() => view.value?.total ?? 0)
const selected = computed(() => new Set(editor.selection))
const windowStart = computed(() => timeline.windowLeftPx / timeline.pxPerSec)
const windowEnd = computed(() => timeline.windowRightPx / timeline.pxPerSec)
const contentWidth = computed(() => `${TRACK_HEADER_WIDTH + laneWidth(total.value, timeline.pxPerSec)}px`)

const emptyTitle = computed(() => (editor.viewError ? 'A linha do tempo não abriu' : editor.viewBusy ? 'Calculando a linha do tempo' : 'Sem linha do tempo ainda'))
const emptyDescription = computed(() => editor.viewError || 'As trilhas aparecem quando o projeto estiver calculado.')

/* ---------- rolagem e medidas ---------- */

function syncScroll(): void {
  const element = scrollEl.value
  if (element) timeline.setScroll(element.scrollLeft, element.clientWidth)
}

/** A área rolável e a escala de agora, para traduzir a posição do mouse em tempo. */
function timeAt(clientX: number): number {
  const element = scrollEl.value
  if (!element) return 0
  return timeAtX(clientX, element.getBoundingClientRect().left, element.scrollLeft, timeline.pxPerSec, total.value)
}

function onWheel(event: WheelEvent): void {
  // sem o Ctrl a roda rola a página e as trilhas como sempre
  if (!event.ctrlKey || !scrollEl.value) return
  event.preventDefault()
  const offsetPx = event.clientX - scrollEl.value.getBoundingClientRect().left
  timeline.zoomWheel(event.deltaY < 0 ? 1 : -1, timeAt(event.clientX), offsetPx)
}

// o zoom, o "ajustar" e os botões pedem a rolagem pelo store; ela só pode ser aplicada depois que a largura nova existe
watch(
  () => timeline.scrollRequest,
  async (request) => {
    if (!request) return
    await nextTick()
    const element = scrollEl.value
    if (!element) return
    const px = timeline.pxPerSec
    if (request.kind === 'start') element.scrollLeft = 0
    else if (request.kind === 'center') element.scrollLeft = Math.max(0, TRACK_HEADER_WIDTH + request.seconds * px - element.clientWidth / 2)
    else element.scrollLeft = Math.max(0, TRACK_HEADER_WIDTH + request.seconds * px - request.offsetPx)
    syncScroll()
  },
)

/**
 * Mantém o cursor à vista ao tocar e ao pular para uma emenda, o início ou o fim. Quando ele sai da tela a área
 * rola uma página de uma vez (o cursor passa a ficar na borda de onde veio) em vez de acompanhá-lo a cada quadro:
 * rolar a cada quadro redesenha a janela de itens sessenta vezes por segundo, e uma página por vez descansa o olho.
 */
function keepPlayheadVisible(time: number): void {
  const element = scrollEl.value
  const width = timeline.viewportWidth
  if (!element || width <= 0) return
  const x = TRACK_HEADER_WIDTH + time * timeline.pxPerSec
  const left = timeline.scrollLeft
  if (x < left + TRACK_HEADER_WIDTH + FOLLOW_MARGIN_PX) {
    // saiu pela esquerda (tocando para trás, ou um salto ao começo): o cursor fica perto da borda direita
    element.scrollLeft = Math.max(0, x - width + FOLLOW_MARGIN_PX)
  } else if (x > left + width - FOLLOW_MARGIN_PX) {
    // saiu pela direita: o cursor fica perto da borda esquerda da área das trilhas
    element.scrollLeft = x - TRACK_HEADER_WIDTH - FOLLOW_MARGIN_PX
  } else {
    return
  }
  syncScroll()
}

watch(() => editor.playhead, keepPlayheadVisible, { flush: 'post' })

let resizeObserver: ResizeObserver | null = null

/* ---------- seleção e cursor ---------- */

function snapContext(points: readonly number[]): SnapContext {
  return { points, tolerance: timeline.snapTolerance, total: total.value }
}

function onTrackToggle(trackId: string, field: TrackToggle): void {
  void actions.toggleTrack(field, trackId)
}

let stopSeek: (() => void) | null = null

/** Clicar e arrastar na régua ou numa faixa vazia leva o cursor até lá, encaixando nas bordas. */
function beginSeek(event: MouseEvent): void {
  if (!view.value) return
  stopSeek?.()
  const points = snapPoints(view.value, null, null)
  const seekTo = (clientX: number) => player.seek(snapTime(timeAt(clientX), points, timeline.snapTolerance))
  seekTo(event.clientX)
  const move = (moveEvent: MouseEvent) => seekTo(moveEvent.clientX)
  const up = () => stopSeek?.()
  stopSeek = () => {
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', up)
    stopSeek = null
  }
  document.addEventListener('mousemove', move)
  document.addEventListener('mouseup', up)
}

/* ---------- arrastar e aparar ---------- */

const ghost = shallowRef<{ trackIndex: number; preview: DragPreview } | null>(null)
let activeDrag: { start: DragStart; track: TimelineTrack; startX: number; points: number[]; moved: boolean } | null = null

function onDragMove(event: MouseEvent): void {
  const drag = activeDrag
  if (!drag) return
  if (!drag.moved && Math.abs(event.clientX - drag.startX) < DRAG_THRESHOLD_PX) return
  drag.moved = true
  const deltaSeconds = (event.clientX - drag.startX) / timeline.pxPerSec
  ghost.value = {
    trackIndex: tracks.value.findIndex((track) => track.id === drag.track.id),
    preview: dragPreview(drag.start, drag.track, deltaSeconds, snapContext(drag.points)),
  }
}

async function onDragEnd(): Promise<void> {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
  const drag = activeDrag
  const shown = ghost.value?.preview ?? null
  activeDrag = null
  ghost.value = null
  if (!drag?.moved || !shown) return
  const op = dragOperation(drag.start, drag.track, shown)
  if (!op) return
  const done = await editor.applyOp(op)
  // mover um trecho muda o índice dele: a seleção segue o trecho para o lugar novo
  if (done && op.type === 'move') {
    const moved = editor.view?.tracks.find((track) => track.id === 'V1')?.items[op.to]
    if (moved) editor.select([moved.id])
  }
}

function beginDrag(event: MouseEvent, track: TimelineTrack, itemId: string, side: 'in' | 'out' | null): void {
  const item = track.items.find((candidate) => candidate.id === itemId)
  if (!item || !view.value) return
  const mode: DragMode = side ? 'trim' : track.id === 'V1' ? 'move-v1' : 'shift'
  activeDrag = {
    start: { mode, trackId: track.id, item, side, original: { start: item.start, end: item.end } },
    track,
    startX: event.clientX,
    points: snapPoints(view.value, editor.playhead, item.id),
    moved: false,
  }
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
}

function lockedWarning(trackId: string): void {
  toasts.push({ tone: 'error', title: `A trilha ${trackId} está bloqueada (cadeado no cabeçalho).` })
}

function onMouseDown(event: MouseEvent): void {
  if (event.button !== 0 || !(event.target instanceof HTMLElement)) return
  const target = event.target
  if (target.closest('[data-track-action]')) return
  const itemElement = target.closest<HTMLElement>('[data-item-id]')
  if (itemElement) {
    const track = tracks.value.find((candidate) => candidate.id === itemElement.dataset.trackId)
    const itemId = itemElement.dataset.itemId
    if (!track || !itemId) return
    if (track.locked) {
      lockedWarning(track.id)
      return
    }
    const handle = target.closest<HTMLElement>('[data-handle]')?.dataset.handle
    if (handle === 'in' || handle === 'out') {
      // puxar uma alça apara o item sem mudar a seleção
      if (itemElement.dataset.draggable === '1') {
        event.preventDefault()
        beginDrag(event, track, itemId, handle)
      }
      return
    }
    const additive = event.ctrlKey || event.metaKey
    if (!additive) editor.select([itemId])
    else if (selected.value.has(itemId)) editor.select(editor.selection.filter((id) => id !== itemId))
    else editor.select([...editor.selection, itemId])
    if (itemElement.dataset.draggable === '1') {
      event.preventDefault()
      beginDrag(event, track, itemId, null)
    }
    return
  }
  if (target.closest('.lane, [data-ruler]')) {
    event.preventDefault()
    editor.clearSelection()
    beginSeek(event)
  }
}

function onMouseOver(event: MouseEvent): void {
  const id = event.target instanceof HTMLElement ? (event.target.closest<HTMLElement>('[data-track-id]')?.dataset.trackId ?? null) : null
  if (id !== timeline.hoverTrackId) timeline.hoverTrackId = id
}

function onMouseLeave(): void {
  timeline.hoverTrackId = null
}

/* ---------- soltar mídia do painel Mídia ---------- */

function onDragOver(event: DragEvent): void {
  if (timeline.mediaDropHandler && event.dataTransfer?.types.includes(MEDIA_DND_MIME)) event.preventDefault()
}

function onDrop(event: DragEvent): void {
  const handler = timeline.mediaDropHandler
  const payload = event.dataTransfer?.getData(MEDIA_DND_MIME)
  if (!handler || !payload || !view.value) return
  event.preventDefault()
  const trackId = event.target instanceof HTMLElement ? (event.target.closest<HTMLElement>('[data-track-id]')?.dataset.trackId ?? null) : null
  const points = snapPoints(view.value, editor.playhead, null)
  handler(payload, { trackId, time: snapTime(timeAt(event.clientX), points, timeline.snapTolerance) })
}

/* ---------- ciclo de vida ---------- */

const ghostStyle = computed(() => {
  const current = ghost.value
  if (!current) return null
  const { preview } = current
  return {
    top: `${RULER_HEIGHT + current.trackIndex * TRACK_ROW_HEIGHT + 3}px`,
    left: `${TRACK_HEADER_WIDTH + preview.start * timeline.pxPerSec}px`,
    width: `${Math.max(3, (preview.end - preview.start) * timeline.pxPerSec)}px`,
  }
})

const indicatorStyle = computed(() => {
  const current = ghost.value
  if (!current || current.preview.indicatorAt === null) return null
  return {
    top: `${RULER_HEIGHT + current.trackIndex * TRACK_ROW_HEIGHT}px`,
    left: `${TRACK_HEADER_WIDTH + current.preview.indicatorAt * timeline.pxPerSec}px`,
  }
})

// a área rolável só existe com a vista pronta; quando ela aparece (ou volta) os ouvintes entram nela
function watchScrollArea(element: HTMLElement | null, previous?: HTMLElement | null): void {
  previous?.removeEventListener('wheel', onWheel)
  resizeObserver?.disconnect()
  resizeObserver = null
  if (!element) return
  // não passivo: a roda com o Ctrl faz zoom e precisa impedir o zoom da página
  element.addEventListener('wheel', onWheel, { passive: false })
  syncScroll()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(syncScroll)
    resizeObserver.observe(element)
  }
}

watch(scrollEl, watchScrollArea, { immediate: true, flush: 'post' })

onBeforeUnmount(() => {
  stopSeek?.()
  scrollEl.value?.removeEventListener('wheel', onWheel)
  resizeObserver?.disconnect()
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
})
</script>

<template>
  <AppCard class="timeline" flush>
    <template #actions>
      <TimelineTimecode v-if="view" />
    </template>

    <EmptyState v-if="!view" icon="layers" :title="emptyTitle" :description="emptyDescription" />

    <template v-else>
      <TimelineToolbar />

      <div
        ref="scrollEl"
        class="timeline__scroll"
        role="group"
        aria-label="Trilhas do projeto"
        @scroll.passive="syncScroll"
        @mouseleave="onMouseLeave"
      >
        <div
          class="timeline__content"
          :style="{ width: contentWidth }"
          @mousedown="onMouseDown"
          @mouseover="onMouseOver"
          @dragover="onDragOver"
          @drop="onDrop"
        >
          <TimelineRuler
            :total="total"
            :fps="view.fps"
            :px-per-sec="timeline.pxPerSec"
            :window-start="windowStart"
            :window-end="windowEnd"
          />
          <TimelineTrackRow
            v-for="track in tracks"
            :key="track.id"
            :track="track"
            :total="total"
            :px-per-sec="timeline.pxPerSec"
            :window-start="windowStart"
            :window-end="windowEnd"
            :selected="selected"
            @toggle="onTrackToggle"
          />
          <TimelinePlayhead />
          <div v-if="ghostStyle" class="timeline__ghost" :style="ghostStyle" data-ghost="1" />
          <div v-if="indicatorStyle" class="timeline__drop" :style="indicatorStyle" data-drop-indicator="1" />
        </div>
      </div>

      <p class="timeline__hint">
        Ctrl + roda do mouse faz zoom. Arraste um item para mudar de lugar e puxe a borda para aparar. A tecla ? mostra os atalhos.
      </p>
    </template>
  </AppCard>
</template>

<style scoped>
.timeline {
  /* medidas e cores dos blocos: as mesmas nos dois temas, porque o texto dos blocos é sempre branco */
  --tl-header-width: 92px;
  --tl-row-height: 34px;
  --tl-ruler-height: 26px;
  --tl-clip: #1f5c63;
  --tl-image: #2b6e4f;
  --tl-card: #4a4478;
  --tl-video: #8a5a24;
  --tl-text: #8a7a1e;
  --tl-clip-audio: #244a55;
  --tl-track: #24555a;
  --tl-music: #245a4e;
  --tl-narration: #6b3f73;
  --tl-captions: #555a5e;
  --tl-progress: #3a3f44;
  --tl-other: #1f5c63;
}

.timeline__scroll {
  position: relative;
  /* o layout de tela define a variável como `none`: a altura vem do encaixe do painel */
  max-height: var(--editor-timeline-height, min(70vh, 34rem));
  overflow: auto;
  overscroll-behavior: contain;
  background: var(--color-bg-soft);
}

.timeline__content {
  position: relative;
  min-width: 100%;
  user-select: none;
}

.timeline__ghost {
  position: absolute;
  z-index: 5;
  height: calc(var(--tl-row-height) - 6px);
  border: 1px dashed #fff;
  border-radius: 5px;
  background: rgb(255 255 255 / 0.2);
  pointer-events: none;
}

.timeline__drop {
  position: absolute;
  z-index: 5;
  width: 3px;
  height: var(--tl-row-height);
  margin-left: -1px;
  background: var(--color-accent);
  pointer-events: none;
}

.timeline__hint {
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--color-border);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
