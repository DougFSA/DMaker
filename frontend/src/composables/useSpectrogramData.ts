/* A imagem do espectrograma do painel Áudio: pede ao servidor o PNG em tons de cinza da janela de tempo que está na tela e
   repete o pedido quando a janela, o tamanho, os ajustes, o som ou a spec mudam. A resposta velha não sobrescreve a nova, e
   a imagem de agora fica na tela, esticada para a janela, até a nova chegar. O cinza é guardado: trocar o esquema de cores
   repinta sem pedir de novo. */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch, type Ref } from 'vue'
import { errorMessage } from '@/api'
import type { SpectrogramImage } from '@/api'
import { fetchSpectrogram } from '@/api/audioPanel'
import { columnsFor } from '@/composables/useWaveData'
import { colorize, effectiveBand, palette } from '@/lib/spectrogram'
import { pruneEmpty } from '@/lib/editorPaths'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useEditorStore } from '@/stores/editor'

/** Espera de silêncio antes de pedir a imagem de uma janela: a roda do mouse faz dezenas de passos por segundo. */
export const SPECTROGRAM_DEBOUNCE_MS = 120
/** De quanto em quanto tempo se pergunta de novo enquanto os efeitos do item são aplicados. */
export const SPECTROGRAM_RETRY_MS = 600
const MIN_ROWS = 64
const MAX_ROWS = 512

/** A imagem pronta para desenhar: o cinza do servidor e o trecho que ela cobre. */
export interface SpectrogramFrame {
  image: SpectrogramImage
  /** A imagem em cores, na tabela do esquema escolhido (nulo onde o canvas não existe, como nos testes). */
  canvas: HTMLCanvasElement | null
  /** O cinza (RGBA, vermelho = nível) para repintar sem pedir de novo. */
  gray: Uint8ClampedArray | null
  width: number
  height: number
}

async function decode(blob: Blob): Promise<{ gray: Uint8ClampedArray; width: number; height: number } | null> {
  if (typeof createImageBitmap !== 'function') return null
  const bitmap = await createImageBitmap(blob)
  const canvas = document.createElement('canvas')
  canvas.width = bitmap.width
  canvas.height = bitmap.height
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return null
  ctx.drawImage(bitmap, 0, 0)
  const { width, height } = bitmap // `close()` zera o tamanho do bitmap: ele é lido antes
  const pixels = ctx.getImageData(0, 0, width, height)
  bitmap.close?.()
  return { gray: pixels.data, width, height }
}

export function paintFrame(frame: SpectrogramFrame, scheme: Parameters<typeof palette>[0]): void {
  if (!frame.canvas || !frame.gray) return
  const ctx = frame.canvas.getContext('2d')
  if (!ctx) return
  const colored = new Uint8ClampedArray(frame.gray)
  colorize(colored, palette(scheme))
  ctx.putImageData(new ImageData(colored, frame.width, frame.height), 0, 0)
}

export function useSpectrogramData(width: Ref<number>, height: Ref<number>) {
  const panel = useAudioPanelStore()
  const editor = useEditorStore()

  const frame = shallowRef<SpectrogramFrame | null>(null)
  const error = ref('')
  const loading = ref(false)

  let ticket = 0
  let debounce: ReturnType<typeof setTimeout> | null = null
  let retry: ReturnType<typeof setTimeout> | null = null
  let disposed = false

  function clearTimers(): void {
    if (debounce) clearTimeout(debounce)
    if (retry) clearTimeout(retry)
    debounce = null
    retry = null
  }

  async function request(): Promise<void> {
    if (retry) clearTimeout(retry)
    retry = null
    const name = editor.name
    const spec = editor.spec
    const target = panel.target
    const view = panel.view
    if (!name || !spec || !target || disposed || !(view.end > view.start) || width.value <= 0) return
    const settings = panel.spectrogram
    const band = effectiveBand(settings, panel.rate)
    const mine = ++ticket
    loading.value = true
    try {
      const image = await fetchSpectrogram(name, pruneEmpty(spec), {
        target,
        start: view.start,
        end: view.end,
        columns: columnsFor(width.value, typeof window === 'undefined' ? 1 : window.devicePixelRatio),
        rows: Math.min(MAX_ROWS, Math.max(MIN_ROWS, Math.round(height.value))),
        scale: settings.scale,
        window: settings.window,
        window_size: settings.windowSize,
        gain_db: settings.gainDb,
        range_db: settings.rangeDb,
        min_hz: band.min,
        max_hz: band.max,
      })
      if (mine !== ticket || target !== panel.target) return
      if (image === null) {
        retry = setTimeout(() => void request(), SPECTROGRAM_RETRY_MS)
        return
      }
      const decoded = await decode(image.blob)
      if (mine !== ticket || target !== panel.target) return
      let next: SpectrogramFrame
      if (decoded) {
        const canvas = document.createElement('canvas')
        canvas.width = decoded.width
        canvas.height = decoded.height
        next = { image, canvas, gray: decoded.gray, width: decoded.width, height: decoded.height }
        paintFrame(next, settings.scheme)
      } else {
        next = { image, canvas: null, gray: null, width: image.columns, height: image.rows }
      }
      frame.value = next
      error.value = ''
    } catch (failure) {
      if (mine !== ticket) return
      error.value = errorMessage(failure)
    } finally {
      if (mine === ticket) loading.value = false
    }
  }

  function schedule(): void {
    if (debounce) clearTimeout(debounce)
    debounce = setTimeout(() => void request(), SPECTROGRAM_DEBOUNCE_MS)
  }

  // o que muda a imagem: a janela de tempo, o tamanho, os ajustes (menos a cor), o som e a spec
  watch(
    () =>
      [
        panel.target,
        panel.view.start,
        panel.view.end,
        width.value,
        height.value,
        panel.soundVersion,
        editor.specJson,
        JSON.stringify({ ...panel.spectrogram, scheme: '' }),
      ].join('|'),
    schedule,
  )
  // trocar só o esquema de cores repinta o cinza que já veio
  watch(
    () => panel.spectrogram.scheme,
    (scheme) => {
      if (!frame.value) return
      paintFrame(frame.value, scheme)
      frame.value = { ...frame.value }
    },
  )

  onMounted(() => schedule())
  onBeforeUnmount(() => {
    disposed = true
    ticket += 1
    clearTimers()
  })

  return { frame, error, loading, refresh: request }
}
