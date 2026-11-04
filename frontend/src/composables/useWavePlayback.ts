/* A reprodução do painel Áudio: liga o motor da Web Audio (`lib/audioPlayback`) ao estado do painel. Tocar a seleção (ou
   do cursor ao fim), em loop ou não, a prévia do corte, o scrub e a velocidade; o instante que toca e o nível de cada
   canal ficam à mão da tela, atualizados a cada quadro enquanto algo toca. */
import { onBeforeUnmount, ref, watch } from 'vue'
import { fetchWindow } from '@/api/audioPanel'
import { newAudioContext } from '@/lib/audioContext'
import { cutPreviewSegments, PanelEngine, type MeterReading, type Segment } from '@/lib/audioPlayback'
import { pruneEmpty } from '@/lib/editorPaths'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useEditorStore } from '@/stores/editor'
import { useToastsStore } from '@/stores/toasts'

/** Quanto o scrub espera entre dois pedaços: abaixo disso o ouvido não distingue e o servidor só se cansa. */
const SCRUB_MIN_INTERVAL_MS = 45

interface Plan {
  segments: readonly Segment[]
  /** A reprodução parte do cursor até o fim: mudar a velocidade a retoma de onde está. */
  fromCursor: boolean
}

export function useWavePlayback() {
  const panel = useAudioPanelStore()
  const editor = useEditorStore()
  const toasts = useToastsStore()

  const levels = ref<MeterReading[]>([])
  let engine: PanelEngine | null = null
  let frame = 0
  let plan: Plan | null = null
  let lastScrub = 0

  function ensure(): PanelEngine {
    engine ??= new PanelEngine({
      createContext: newAudioContext,
      duration: () => panel.duration,
      fetchBlock: async (start, end) => {
        const name = editor.name
        const spec = editor.spec
        const target = panel.target
        if (!name || !spec || !target) throw new Error('O projeto não está aberto.')
        return (await fetchWindow(name, pruneEmpty(spec), target, start, end)).data
      },
      onEnded: () => {
        panel.playing = false
        panel.position = null
        stopFrames()
      },
    })
    return engine
  }

  function tick(): void {
    if (!engine || !panel.playing) return
    const here = engine.position()
    panel.position = here
    if (here !== null) panel.reveal(here)
    levels.value = engine.levels()
    frame = requestAnimationFrame(tick)
  }

  function stopFrames(): void {
    if (frame) cancelAnimationFrame(frame)
    frame = 0
    levels.value = []
  }

  async function start(next: Plan): Promise<void> {
    plan = next
    try {
      await ensure().play(next.segments, { loop: panel.loop, rate: panel.speed })
      panel.playing = true
      stopFrames()
      frame = requestAnimationFrame(tick)
    } catch (error) {
      panel.playing = false
      toasts.push({ tone: 'error', title: 'Não foi possível tocar o áudio', description: error instanceof Error ? error.message : String(error) })
    }
  }

  /** Toca a seleção (em loop, se o loop está ligado) ou, sem seleção, do cursor até o fim. */
  function play(): Promise<void> {
    const selection = panel.selection
    if (selection) return start({ segments: [[selection.start, selection.end]], fromCursor: false })
    const from = panel.cursor >= panel.duration - 0.01 ? 0 : panel.cursor
    return start({ segments: [[from, panel.duration]], fromCursor: true })
  }

  /** Para a reprodução. O cursor volta ao ponto de onde se partiu, como o Parar do Audacity. */
  function stop(): void {
    engine?.stop()
    panel.playing = false
    panel.position = null
    stopFrames()
  }

  /** Pausa e deixa o cursor onde a reprodução estava (sem seleção); retomar parte dali. */
  function pause(): void {
    const here = engine?.position() ?? null
    stop()
    if (here !== null && !panel.selection) panel.setCursor(here)
  }

  function toggle(): Promise<void> {
    if (panel.playing) {
      stop()
      return Promise.resolve()
    }
    return play()
  }

  /** "Play cut preview": 2 s antes da seleção e 2 s depois, pulando a seleção. */
  function previewCut(): Promise<void> {
    const selection = panel.selection
    if (!selection) {
      toasts.push({ tone: 'info', title: 'Selecione o trecho que seria cortado para ouvir como ficaria.' })
      return Promise.resolve()
    }
    const segments = cutPreviewSegments(selection, panel.duration)
    if (segments.length === 0) return Promise.resolve()
    return start({ segments, fromCursor: false }).then(() => undefined)
  }

  /** Toca um pedaço curto onde a pessoa arrasta a agulha. Vários pedidos seguidos esperam o intervalo mínimo. */
  function scrub(time: number): void {
    if (panel.playing) return
    const now = performance.now()
    if (now - lastScrub < SCRUB_MIN_INTERVAL_MS) return
    lastScrub = now
    void ensure().scrub(time, panel.speed).catch(() => undefined)
  }

  function endScrub(): void {
    engine?.endScrub()
  }

  // mudar a velocidade ou o loop com algo tocando retoma o mesmo plano com o valor novo
  watch(
    () => [panel.speed, panel.loop] as const,
    () => {
      if (!panel.playing || !plan) return
      const here = engine?.position()
      const resume = plan.fromCursor && here != null ? { ...plan, segments: [[here, panel.duration]] as Segment[] } : plan
      void start(resume)
    },
  )
  // o som mudou (efeito, corte, desfazer, volume): os blocos baixados já não valem, e o que tocava foi trocado debaixo dos pés
  watch(
    () => `${panel.overview?.key ?? ''}|${panel.overview?.gain ?? 1}`,
    (_now, before) => {
      if (before === '|1' || before === undefined) return // a primeira resposta do item não é uma mudança
      engine?.invalidate()
      if (panel.playing) stop()
    },
  )
  watch(
    () => panel.target,
    () => {
      stop()
      engine?.invalidate()
    },
  )

  onBeforeUnmount(() => {
    stopFrames()
    engine?.dispose()
    engine = null
    panel.playing = false
    panel.position = null
  })

  return { levels, play, stop, pause, toggle, previewCut, scrub, endScrub, prefetch: (time: number) => ensure().prefetch(time) }
}
