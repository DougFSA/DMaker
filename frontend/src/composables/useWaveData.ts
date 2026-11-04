/* Os dados da onda que o painel Áudio desenha: pede ao servidor os picos da janela de tempo que está na tela (ou as
   amostras, no zoom máximo) e repete o pedido quando a janela, a largura, o som ou a spec mudam. Resposta velha não
   sobrescreve a nova, e uma onda ainda em construção é consultada de novo até ficar pronta. A resposta mais recente
   fica em `data`; a tela desenha o que há, esticado para a janela de agora, enquanto a nova não chega. */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch, type Ref } from 'vue'
import { errorMessage } from '@/api'
import type { AudioWave } from '@/api'
import { fetchWave } from '@/api/audioPanel'
import { pruneEmpty } from '@/lib/editorPaths'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useEditorStore } from '@/stores/editor'

/** Espera de silêncio antes de pedir a onda de uma janela: a roda do mouse faz dezenas de passos por segundo. */
export const WAVE_DEBOUNCE_MS = 60
/** De quanto em quanto tempo uma onda em construção é consultada. */
export const WAVE_POLL_MS = 400
const MIN_COLUMNS = 64
const MAX_COLUMNS = 4096
const FALLBACK_COLUMNS = 512

/** Quantas colunas pedir para uma largura de tela: uma por pixel do dispositivo, dentro do que a rota aceita. */
export function columnsFor(width: number, pixelRatio: number): number {
  if (!(width > 0)) return FALLBACK_COLUMNS
  return Math.min(MAX_COLUMNS, Math.max(MIN_COLUMNS, Math.round(width * Math.max(pixelRatio, 1))))
}

export function useWaveData(width: Ref<number>) {
  const panel = useAudioPanelStore()
  const editor = useEditorStore()

  const data = shallowRef<AudioWave | null>(null)
  const error = ref('')
  const loading = ref(false)

  let ticket = 0
  let debounce: ReturnType<typeof setTimeout> | null = null
  let poll: ReturnType<typeof setTimeout> | null = null
  let lastKey = ''
  let disposed = false

  function clearTimers(): void {
    if (debounce) clearTimeout(debounce)
    if (poll) clearTimeout(poll)
    debounce = null
    poll = null
  }

  async function request(): Promise<void> {
    if (poll) clearTimeout(poll)
    poll = null
    const name = editor.name
    const spec = editor.spec
    const target = panel.target
    if (!name || !spec || !target || disposed) return
    const view = panel.view
    const whole = !(view.end > view.start)
    const columns = columnsFor(width.value, typeof window === 'undefined' ? 1 : window.devicePixelRatio)
    const key = `${target}|${whole ? 'all' : `${view.start}|${view.end}`}|${columns}|${panel.soundVersion}|${editor.specJson}`
    const mine = ++ticket
    loading.value = true
    try {
      const wave = await fetchWave(name, pruneEmpty(spec), {
        target,
        start: whole ? 0 : view.start,
        end: whole ? null : view.end,
        columns,
      })
      if (mine !== ticket || target !== panel.target) return
      data.value = wave
      error.value = wave.state === 'failed' ? (wave.error ?? 'Não foi possível ler o áudio.') : ''
      lastKey = wave.state === 'ready' ? key : ''
      panel.setOverview(wave)
      if (wave.state === 'building') poll = setTimeout(() => void request(), WAVE_POLL_MS)
    } catch (failure) {
      if (mine !== ticket) return
      data.value = null
      error.value = errorMessage(failure)
      lastKey = ''
    } finally {
      if (mine === ticket) loading.value = false
    }
  }

  function schedule(): void {
    if (debounce) clearTimeout(debounce)
    debounce = setTimeout(() => void request(), WAVE_DEBOUNCE_MS)
  }

  watch(
    () => [panel.target, panel.view.start, panel.view.end, width.value, panel.soundVersion, editor.specJson] as const,
    () => {
      // a resposta que acabou de chegar já cobre a janela: ela só ajustou a visão ao áudio inteiro
      const view = panel.view
      const columns = columnsFor(width.value, typeof window === 'undefined' ? 1 : window.devicePixelRatio)
      const current = data.value
      const covered =
        current?.state === 'ready' &&
        lastKey !== '' &&
        current.target === panel.target &&
        current.columns === columns &&
        Math.abs(current.start - view.start) < 1e-9 &&
        Math.abs(current.end - view.end) < 1e-9 &&
        lastKey.endsWith(`|${panel.soundVersion}|${editor.specJson}`)
      if (!covered) schedule()
    },
  )

  onMounted(() => void request())
  onBeforeUnmount(() => {
    disposed = true
    ticket += 1
    clearTimers()
  })

  return { data, error, loading, refresh: request }
}
