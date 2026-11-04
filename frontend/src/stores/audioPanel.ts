/* O painel Áudio: o estado dele (qual item está aberto, a janela de tempo, a seleção, o cursor, a ferramenta, o loop e a
   velocidade) e os comandos que mudam o projeto (silenciar, cortar, dividir, marcar, aplicar efeito, envelope). Selecionar
   e dar zoom não tocam a spec; cada comando que a muda é um passo do desfazer do editor (`editor.applyOp`) e segue o
   Salvar, como o resto do editor. A reprodução e a busca da onda moram nos composables do painel, que leem este estado. */
import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'
import { errorMessage } from '@/api'
import type { AudioWave } from '@/api'
import {
  clamp,
  clampView,
  extendSelection,
  fitProject,
  fitSelection,
  normalizeSelection,
  panView,
  revealTime,
  selectionToMarker,
  snapToSample,
  zoomAround,
  ZOOM_STEP,
  type AxisSelection,
  type AxisView,
  type ItemClockInfo,
} from '@/lib/audioWave'
import { DEFAULT_SPECTROGRAM, type SpectrogramSettings } from '@/lib/spectrogram'
import { analysisTargetOf } from '@/lib/spectrum'
import {
  isVoiceTarget,
  planCensorBeep,
  planCut,
  planEffect,
  planEnvelope,
  planLabel,
  planSilence,
  planSplitAt,
  toAxisTime,
  type EnvelopePoint,
} from '@/lib/audioPanelOps'
import { effectContextFor } from '@/lib/audioEffects'
import type { Plan } from '@/lib/editorActions'
import { nextMarker } from '@/lib/markers'
import { useEditorStore, type SelectedItem } from './editor'
import { useToastsStore } from './toasts'

/** As ferramentas do painel: selecionar, envelope, desenhar amostra, zoom, a multiferramenta (que escolhe pelo que está sob o mouse)
 *  e o retângulo espectral (tempo e frequência, no espectrograma). */
export type PanelTool = 'select' | 'envelope' | 'draw' | 'zoom' | 'multi' | 'spectral'

/** A velocidade da reprodução: de um quarto a quatro vezes, em passos que o ouvido reconhece. */
export const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 4] as const

const SPECTROGRAM_KEY = 'dmaker.audio.spectrogram'

function loadSpectrogram(): SpectrogramSettings {
  try {
    const raw = window.localStorage.getItem(SPECTROGRAM_KEY)
    if (raw) return { ...DEFAULT_SPECTROGRAM, ...(JSON.parse(raw) as Partial<SpectrogramSettings>) }
  } catch {
    // sem armazenamento (janela privada) ou valor quebrado: vale o padrão
  }
  return { ...DEFAULT_SPECTROGRAM }
}

export const useAudioPanelStore = defineStore('audioPanel', () => {
  const editor = useEditorStore()
  const toasts = useToastsStore()

  const open = ref(false)
  /** O id do item na vista (`VO-0`) de que o painel foi aberto. */
  const itemId = ref<string | null>(null)
  /** O alvo dos efeitos e das rotas (`audio.voiceover.0`). */
  const target = ref<string | null>(null)
  const title = ref('')
  /** A resposta do item inteiro: a duração, a taxa, o relógio e o andamento da construção. */
  const overview = shallowRef<AudioWave | null>(null)
  const view = ref<AxisView>({ start: 0, end: 0 })
  const selection = ref<AxisSelection | null>(null)
  const cursor = ref(0)
  const tool = ref<PanelTool>('select')
  /** A vista mostrada (`AUDIO_VIEWS`): a onda, e as que outros cards acrescentarem, como o espectrograma. */
  const viewId = ref('wave')
  /** Os ajustes do espectrograma (escala, cores, janela, faixa, ganho e alcance), lembrados entre sessões. */
  const spectrogram = ref<SpectrogramSettings>(loadSpectrogram())
  const loop = ref(false)
  const speed = ref(1)
  const playing = ref(false)
  /** O instante do eixo que está tocando (nulo parado). */
  const position = ref<number | null>(null)
  /** Sobe quando o som do item mudou (efeito, corte, desfazer): a onda e os blocos tocados são pedidos de novo. */
  const soundVersion = ref(0)
  const busy = ref(false)

  const duration = computed(() => overview.value?.duration ?? 0)
  const rate = computed(() => overview.value?.rate ?? 48000)
  const channels = computed(() => overview.value?.channels ?? 2)
  const clock = computed<ItemClockInfo | null>(() => {
    const wave = overview.value
    return wave?.clock ? { start: wave.clock.start, speed: wave.clock.speed, origin: wave.origin } : null
  })
  const ready = computed(() => overview.value !== null && duration.value > 0)

  /* ---------- abrir e fechar ---------- */

  function resetView(): void {
    view.value = fitProject(duration.value)
    selection.value = null
    cursor.value = 0
    position.value = null
    playing.value = false
  }

  /** Abre o painel no item da linha do tempo (o duplo clique ou o botão). Devolve falso se o item não tem som. */
  function openFor(selected: SelectedItem | null): boolean {
    const context = effectContextFor(selected, editor.view)
    if (context.kind !== 'chain' || !selected) {
      toasts.push({ tone: 'info', title: 'Selecione um item com som (áudio de clipe, voz gravada, narração, música ou faixa externa).' })
      return false
    }
    const next = analysisTargetOf(context.chain.listPath)
    if (next === 'output') {
      toasts.push({ tone: 'info', title: 'Selecione um item com som: o painel Áudio edita um item por vez, não a mistura inteira.' })
      return false
    }
    if (open.value && target.value === next) return true
    target.value = next
    itemId.value = selected.item.id
    title.value = context.chain.title
    overview.value = null
    view.value = { start: 0, end: 0 }
    selection.value = null
    cursor.value = 0
    position.value = null
    playing.value = false
    open.value = true
    return true
  }

  function close(): void {
    open.value = false
    target.value = null
    itemId.value = null
    overview.value = null
    playing.value = false
    position.value = null
  }

  /** A primeira resposta do item (ou a de depois de uma edição): guarda a duração e, na primeira vez, mostra tudo. */
  function setOverview(wave: AudioWave): void {
    const first = overview.value === null || overview.value.target !== wave.target
    overview.value = wave
    if (first) resetView()
    else if (view.value.end > wave.duration || view.value.end <= view.value.start) view.value = fitProject(wave.duration)
    if (selection.value && selection.value.end > wave.duration) selection.value = null
  }

  /** O som do item mudou: a onda e os blocos pedem de novo. */
  function soundChanged(): void {
    soundVersion.value += 1
  }

  // outro projeto, outro som: o painel fecha
  watch(
    () => editor.name,
    () => {
      if (open.value) close()
    },
  )

  /* ---------- zoom e rolagem ---------- */

  function setView(next: AxisView): void {
    view.value = next
  }

  function zoom(factor: number, anchor?: number): void {
    const center = anchor ?? cursor.value ?? (view.value.start + view.value.end) / 2
    const inside = center >= view.value.start && center <= view.value.end
    view.value = zoomAround(view.value, factor, inside ? center : (view.value.start + view.value.end) / 2, duration.value, rate.value)
  }

  const zoomIn = (anchor?: number): void => zoom(ZOOM_STEP, anchor)
  const zoomOut = (anchor?: number): void => zoom(1 / ZOOM_STEP, anchor)
  const zoomToProject = (): void => {
    view.value = fitProject(duration.value)
  }
  const zoomToSelection = (): void => {
    view.value = fitSelection(selection.value, duration.value, rate.value)
  }

  /** Mostra exatamente o trecho entre dois instantes (o arrasto da ferramenta de zoom). */
  function zoomToRange(a: number, b: number): void {
    view.value = clampView({ start: Math.min(a, b), end: Math.max(a, b) }, duration.value, rate.value)
  }

  function pan(seconds: number): void {
    view.value = panView(view.value, seconds, duration.value, rate.value)
  }

  /** Deixa o instante à vista (o cursor segue a reprodução e a busca de um marcador). */
  function reveal(time: number): void {
    view.value = revealTime(view.value, time, duration.value, rate.value)
  }

  /* ---------- seleção e cursor ---------- */

  function setCursor(time: number): void {
    cursor.value = snapToSample(clamp(time, 0, duration.value), rate.value)
  }

  function select(start: number, end: number): void {
    selection.value = normalizeSelection(snapToSample(start, rate.value), snapToSample(end, rate.value), duration.value, rate.value)
  }

  /** O retângulo do espectrograma: tempo e frequência (Hz). Selecionar não muda a spec; os efeitos espectrais e o marcador
   *  levam a faixa daqui. Uma faixa de altura zero vira só tempo. */
  function selectSpectral(start: number, end: number, lowHz: number, highHz: number): void {
    const times = normalizeSelection(snapToSample(start, rate.value), snapToSample(end, rate.value), duration.value, rate.value)
    const low = Math.min(lowHz, highHz)
    const high = Math.max(lowHz, highHz)
    if (!times) {
      selection.value = null
      return
    }
    selection.value = high - low >= 1 ? { ...times, low_hz: Math.round(low * 10) / 10, high_hz: Math.round(high * 10) / 10 } : times
  }

  function setSpectrogram(changes: Partial<SpectrogramSettings>): void {
    spectrogram.value = { ...spectrogram.value, ...changes }
    try {
      window.localStorage.setItem(SPECTROGRAM_KEY, JSON.stringify(spectrogram.value))
    } catch {
      // o ajuste vale nesta sessão mesmo sem poder ser lembrado
    }
  }

  function clearSelection(): void {
    selection.value = null
  }

  function selectAll(): void {
    selection.value = normalizeSelection(0, duration.value, duration.value, rate.value)
  }

  /** Shift+clique: estende a seleção até o instante. */
  function extendTo(time: number): void {
    selection.value = extendSelection(selection.value, cursor.value, snapToSample(time, rate.value), duration.value, rate.value)
  }

  /** "Selecionar até o marcador": do cursor ao marcador seguinte (ou ao anterior, quando não há seguinte). */
  function selectToMarker(direction: 1 | -1 = 1): boolean {
    const clockInfo = clock.value
    const timeline = editor.view
    if (!clockInfo || !timeline) return false
    const here = clockInfo.start + (cursor.value - clockInfo.origin) / clockInfo.speed
    const marker = nextMarker(timeline, here, direction)
    if (!marker) {
      toasts.push({ tone: 'info', title: direction > 0 ? 'Não há marcador depois do cursor.' : 'Não há marcador antes do cursor.' })
      return false
    }
    const there = toAxisTime(clockInfo, marker.start)
    selection.value = selectionToMarker(cursor.value, there, duration.value, rate.value)
    return selection.value !== null
  }

  /* ---------- comandos que mudam o projeto ---------- */

  /** Executa um plano como um passo do desfazer do editor; avisa quando o plano é recusado. */
  async function run(plan: Plan): Promise<boolean> {
    if (!plan.ok) {
      toasts.push({ tone: 'error', title: plan.message })
      return false
    }
    busy.value = true
    try {
      const done = await editor.applyOps(plan.ops)
      if (done) soundChanged()
      return done
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não foi possível editar', description: errorMessage(error) })
      return false
    } finally {
      busy.value = false
    }
  }

  const silence = (): Promise<boolean> => (target.value ? run(planSilence(target.value, clock.value, selection.value)) : Promise.resolve(false))

  async function cut(): Promise<boolean> {
    if (!target.value) return false
    const done = await run(planCut(target.value, clock.value, selection.value))
    if (done) selection.value = null
    return done
  }

  /** Bipar a seleção: o item é silenciado no trecho e um Tom de 1 kHz soa no lugar, num passo só. */
  const censor = (): Promise<boolean> => (target.value ? run(planCensorBeep(target.value, clock.value, selection.value)) : Promise.resolve(false))

  const split = (): Promise<boolean> => (target.value ? run(planSplitAt(target.value, clock.value, cursor.value)) : Promise.resolve(false))

  const label = (): Promise<boolean> => run(planLabel(clock.value, selection.value, cursor.value))

  /** Aplica o efeito do catálogo à seleção (ou ao item inteiro, sem seleção). */
  const applyEffect = (type: string, params: Record<string, unknown>): Promise<boolean> =>
    target.value ? run(planEffect(target.value, type, params, selection.value)) : Promise.resolve(false)

  /** Grava a curva do envelope (cria o efeito na primeira vez, troca os pontos nas seguintes). */
  const applyEnvelope = (points: readonly EnvelopePoint[], existingIndex: number | null): Promise<boolean> =>
    target.value ? run(planEnvelope(target.value, clock.value, points, existingIndex)) : Promise.resolve(false)

  /** Grava o traço da Draw Tool: o efeito `draw` com os valores das amostras a partir do instante `start` (tempo do eixo, em microssegundos: arredondar para o milissegundo deslocaria o desenho até 24 amostras). */
  const applyDraw = (start: number, values: readonly number[], channel: string): Promise<boolean> =>
    target.value ? run(planEffect(target.value, 'draw', { start: Math.round(start * 1e6) / 1e6, values: [...values], channel }, null)) : Promise.resolve(false)

  const canSplit = computed(() => !!target.value && isVoiceTarget(target.value))

  /* ---------- reprodução ---------- */

  function setSpeed(next: number): void {
    speed.value = clamp(next, SPEEDS[0], SPEEDS[SPEEDS.length - 1] as number)
  }

  function setTool(next: PanelTool): void {
    tool.value = next
  }

  return {
    open,
    itemId,
    target,
    title,
    overview,
    view,
    selection,
    cursor,
    tool,
    viewId,
    spectrogram,
    loop,
    speed,
    playing,
    position,
    soundVersion,
    busy,
    duration,
    rate,
    channels,
    clock,
    ready,
    canSplit,
    openFor,
    close,
    setOverview,
    soundChanged,
    setView,
    zoomIn,
    zoomOut,
    zoomToProject,
    zoomToSelection,
    zoomToRange,
    zoom,
    pan,
    reveal,
    setCursor,
    select,
    selectSpectral,
    setSpectrogram,
    clearSelection,
    selectAll,
    extendTo,
    selectToMarker,
    silence,
    cut,
    censor,
    split,
    label,
    applyEffect,
    applyEnvelope,
    applyDraw,
    setSpeed,
    setTool,
  }
})
