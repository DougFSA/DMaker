/* A vista da linha do tempo: o zoom, o encaixe, a janela visível (rolagem e largura), a trilha sob o mouse e os
   pedidos de rolagem que o zoom e o "ajustar" fazem ao painel. O cursor e a seleção ficam no store do editor; aqui só
   mora o que é da tela da linha do tempo, para o teclado, a barra de ferramentas e o painel mexerem no mesmo zoom. */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import {
  clampZoom,
  DEFAULT_PX_PER_SEC,
  fitZoom,
  SNAP_PX,
  TRACK_HEADER_WIDTH,
  WHEEL_ZOOM_STEP,
  ZOOM_STEP,
} from '@/lib/timeline'
import { useEditorStore } from './editor'

/** A janela de itens desenhados anda em blocos deste tamanho (pixels), para rolar não refazer a lista a cada pixel. */
export const WINDOW_CHUNK_PX = 400
/** Largura assumida enquanto o painel ainda não foi medido (e nos testes, onde nada tem largura). */
const FALLBACK_VIEWPORT_PX = 1200

/** Onde a linha do tempo está sob o ponteiro: a trilha e o instante (já encaixado). */
export interface TimelineHit {
  trackId: string | null
  time: number
}

/** Quem trata um arquivo do painel Mídia solto na linha do tempo (o painel registra; sem ele, soltar não faz nada). */
export type MediaDropHandler = (payload: string, hit: TimelineHit) => void

export type ScrollRequest =
  | { token: number; kind: 'start' }
  | { token: number; kind: 'center'; seconds: number }
  /** Mantém o instante `seconds` na mesma posição da tela (`offsetPx` desde a borda esquerda da área rolável). */
  | { token: number; kind: 'anchor'; seconds: number; offsetPx: number }

type ScrollRequestInput = ScrollRequest extends infer Each ? (Each extends { token: number } ? Omit<Each, 'token'> : never) : never

export const useTimelineStore = defineStore('timeline', () => {
  const editor = useEditorStore()

  const pxPerSec = ref(DEFAULT_PX_PER_SEC)
  const snapEnabled = ref(true)
  /** O botão "Ripple": só o rótulo muda. A V1 sempre fecha as lacunas, e o servidor decide isso. */
  const rippleAlways = ref(false)
  const hoverTrackId = ref<string | null>(null)
  const scrollLeft = ref(0)
  const viewportWidth = ref(0)
  const scrollRequest = ref<ScrollRequest | null>(null)
  const mediaDropHandler = ref<MediaDropHandler | null>(null)
  let requestToken = 0

  const effectiveViewport = computed(() => (viewportWidth.value > 0 ? viewportWidth.value : FALLBACK_VIEWPORT_PX))
  /** Até quantos segundos o encaixe atrai (zero com o encaixe desligado). */
  const snapTolerance = computed(() => (snapEnabled.value ? SNAP_PX / pxPerSec.value : 0))
  /** A janela visível da área das trilhas, em pixels da área, arredondada para blocos e com um bloco de folga. */
  const windowLeftPx = computed(
    () => Math.max(0, Math.floor((scrollLeft.value - TRACK_HEADER_WIDTH) / WINDOW_CHUNK_PX) * WINDOW_CHUNK_PX - WINDOW_CHUNK_PX),
  )
  const windowRightPx = computed(
    () => Math.ceil((scrollLeft.value + effectiveViewport.value) / WINDOW_CHUNK_PX) * WINDOW_CHUNK_PX + WINDOW_CHUNK_PX,
  )

  function request(next: ScrollRequestInput): void {
    requestToken += 1
    scrollRequest.value = { ...next, token: requestToken } as ScrollRequest
  }

  /** Muda o zoom. Com `seconds`, o painel rola para esse instante ficar no meio; com `anchor`, ele fica onde estava na tela. */
  function setZoom(next: number, focus?: { seconds: number; offsetPx?: number }): void {
    const clamped = clampZoom(next)
    if (clamped === pxPerSec.value) return
    pxPerSec.value = clamped
    if (!focus) return
    if (focus.offsetPx === undefined) request({ kind: 'center', seconds: focus.seconds })
    else request({ kind: 'anchor', seconds: focus.seconds, offsetPx: focus.offsetPx })
  }

  function zoomIn(): void {
    setZoom(pxPerSec.value * ZOOM_STEP, { seconds: editor.playhead })
  }

  function zoomOut(): void {
    setZoom(pxPerSec.value / ZOOM_STEP, { seconds: editor.playhead })
  }

  /** Um clique da roda com o Ctrl: aproxima ou afasta mantendo o instante sob o ponteiro no mesmo lugar. */
  function zoomWheel(direction: 1 | -1, seconds: number, offsetPx: number): void {
    setZoom(direction > 0 ? pxPerSec.value * WHEEL_ZOOM_STEP : pxPerSec.value / WHEEL_ZOOM_STEP, { seconds, offsetPx })
  }

  /** Faz o vídeo inteiro caber na largura da tela e volta ao começo. */
  function zoomFit(): void {
    pxPerSec.value = fitZoom(editor.total, effectiveViewport.value - TRACK_HEADER_WIDTH)
    request({ kind: 'start' })
  }

  function toggleSnap(): boolean {
    snapEnabled.value = !snapEnabled.value
    return snapEnabled.value
  }

  function toggleRipple(): boolean {
    rippleAlways.value = !rippleAlways.value
    return rippleAlways.value
  }

  function setScroll(left: number, width: number): void {
    scrollLeft.value = left
    viewportWidth.value = width
  }

  /** O painel Mídia registra aqui o que fazer ao receber um arquivo arrastado; devolve como desregistrar. */
  function onMediaDrop(handler: MediaDropHandler): () => void {
    mediaDropHandler.value = handler
    return () => {
      if (mediaDropHandler.value === handler) mediaDropHandler.value = null
    }
  }

  // outro projeto, outra escala: o zoom e a rolagem do anterior não valem
  watch(
    () => editor.name,
    () => {
      pxPerSec.value = DEFAULT_PX_PER_SEC
      scrollLeft.value = 0
      hoverTrackId.value = null
      scrollRequest.value = null
    },
  )

  return {
    pxPerSec,
    snapEnabled,
    rippleAlways,
    hoverTrackId,
    scrollLeft,
    viewportWidth,
    scrollRequest,
    mediaDropHandler,
    effectiveViewport,
    snapTolerance,
    windowLeftPx,
    windowRightPx,
    setZoom,
    zoomIn,
    zoomOut,
    zoomWheel,
    zoomFit,
    toggleSnap,
    toggleRipple,
    setScroll,
    onMediaDrop,
  }
})
