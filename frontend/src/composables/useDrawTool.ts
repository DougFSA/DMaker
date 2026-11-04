/* A Draw Tool do painel Áudio: no zoom máximo, onde cada amostra tem pixels de sobra, arrastar o mouse desenha o valor das
   amostras. Não toca no arquivo: ao soltar, o traço vira um efeito `draw` na cadeia do item (valores de um trecho curto,
   com limite, como o Reparar), aplicado pelo estágio de amostras do servidor, e o gesto grava como os outros gestos do
   editor. Enquanto se arrasta, o traço aparece por cima da onda, sem chamar o servidor. */
import { ref, type Ref } from 'vue'
import type { AudioWave } from '@/api'
import {
  bandAt,
  channelAt,
  drawBlocker,
  EFFECT_SAMPLE_RATE,
  strokePixels,
  strokeSamples,
  valueAt,
  type DrawChannel,
  type DrawPoint,
} from '@/lib/audioDraw'
import { clamp, xToTime } from '@/lib/audioWave'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'

export interface DrawToolOptions {
  area: Ref<HTMLElement | null>
  width: Ref<number>
  height: Ref<number>
  data: () => AudioWave | null
}

export function useDrawTool(options: DrawToolOptions) {
  const panel = useAudioPanelStore()
  const editor = useEditorStore()
  const toasts = useToastsStore()

  /** O traço em andamento como linhas de pontos em pixels da área (uma por canal); vazio fora de um gesto. */
  const preview = ref<string[]>([])

  let points: DrawPoint[] = []
  let channel: DrawChannel = 'both'
  let band = 0

  function pointAt(event: MouseEvent): DrawPoint | null {
    const box = options.area.value?.getBoundingClientRect()
    if (!box) return null
    const time = xToTime(event.clientX - box.left, panel.view, options.width.value)
    const frames = Math.round(panel.duration * panel.rate)
    const sample = clamp(Math.round(time * panel.rate), 0, Math.max(frames - 1, 0))
    return { sample, value: valueAt(event.clientY - box.top, options.height.value, panel.channels, band) }
  }

  function redraw(): void {
    const stroke = strokeSamples(points)
    preview.value = stroke
      ? strokePixels(stroke, channel, panel.view, options.width.value, options.height.value, panel.channels, panel.rate)
      : []
  }

  function onMove(event: MouseEvent): void {
    const point = pointAt(event)
    if (!point) return
    points.push(point)
    redraw()
  }

  function stopListening(): void {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.removeEventListener('keydown', onKey)
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return
    event.preventDefault()
    cancel()
  }

  /** Larga o traço sem gravar nada (Esc, ou o painel fechando). */
  function cancel(): void {
    stopListening()
    points = []
    preview.value = []
  }

  async function onUp(event: MouseEvent): Promise<void> {
    stopListening()
    const last = pointAt(event)
    if (last) points.push(last)
    const stroke = strokeSamples(points)
    const drawnChannel = channel
    points = []
    preview.value = []
    if (!stroke) return
    editor.beginGesture()
    try {
      const done = await panel.applyDraw(stroke.first / EFFECT_SAMPLE_RATE, stroke.values, drawnChannel)
      // o gesto direto grava ao soltar (o resto do editor continua pelo Salvar); um 409 já abriu a faixa de escolha do disco
      if (done && editor.dirty) await editor.save({ quiet: true })
    } finally {
      editor.endGesture()
    }
  }

  /** O botão do mouse apertou na onda com a Draw Tool: começa o traço, ou explica por que ainda não dá para desenhar. */
  function start(event: MouseEvent): void {
    const blocker = drawBlocker(panel.view, options.width.value, panel.rate)
    if (blocker) {
      toasts.push({ tone: 'info', title: blocker })
      return
    }
    const box = options.area.value?.getBoundingClientRect()
    if (!box) return
    const y = event.clientY - box.top
    // Shift desenha nos dois canais; sem ele, só no que está sob o mouse
    channel = channelAt(y, options.height.value, panel.channels, event.shiftKey)
    band = bandAt(y, options.height.value, panel.channels)
    points = []
    const first = pointAt(event)
    if (!first) return
    points.push(first)
    redraw()
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    document.addEventListener('keydown', onKey)
  }

  return { preview, start, cancel }
}
