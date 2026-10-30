import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import {
  api,
  errorMessage,
  followJob,
  isJobCancelled,
  type FollowedJob,
  type NarrationResult,
  type NarrationStopped,
  type QueueAdded,
  type QueueAudioFormat,
  type UtteranceEvent,
  type VoiceProfile,
} from '@/api'
import type { SelectOption } from '@/components/ui/AppSelect.vue'
import { browserLiveAudio, createLivePlayer, fetchChunkBytes, type LiveAudioFactory, type LivePlayer } from '@/lib/livePlayer'
import { LIVE_MUTED_TEXT, liveStatusText } from '@/lib/livePreview'
import {
  buildNarrationItem,
  HISTORY_LIMIT,
  lastNarrationEnd,
  scriptProblem,
  seedProblem,
  withNarration,
  type NarrationEntry,
} from '@/lib/narration'
import { formatSecondsPrecise, voiceLabel } from '@/lib/speech'
import { useEditorStore } from './editor'
import { useToastsStore } from './toasts'
import { useVoiceStore } from './voice'
import { useWorkspaceStore } from './workspace'

/** Uma narração pronta da sessão: o que foi pedido e onde o arquivo ficou. */
export interface NarrationItem extends NarrationEntry {
  id: number
  voiceName: string
  duration: number
  audioUrl: string
  /** O caminho do arquivo no servidor (o que a spec do projeto aponta). */
  output: string
  at: Date
}

/** Como o roteiro entra na fila: o que a fila pede além da narração em si. */
export interface QueueChoices {
  title: string
  format: QueueAudioFormat
  draft: boolean
}

/** O que a tela mostra do trabalho de gerar: a mesma forma que o `JobRunStatus` lê de um `createJobRun`. */
interface NarrationJob {
  running: boolean
  label: string
  percent: number | null
  startedAtMs: number | null
  cancelling: boolean
  error: string
  cancelled: boolean
}

/** A prévia ao vivo na tela: quantas falas existem, quantas já tocam e se foi parada ou silenciada. */
interface LiveView {
  visible: boolean
  total: number
  ready: number
  playing: number | null
  stoppedAfter: number | null
  muted: boolean
  jobEnded: boolean
}

const QUEUED_LABEL = 'Na fila...'
const STOPPING_LABEL = 'Parando assim que a fala atual terminar'
/** De quanto em quanto tempo a tela confere qual fala está tocando. */
const LIVE_TICK_MS = 150

/**
 * A Narração: o roteiro e as escolhas da voz, o trabalho de gerar (com a prévia ao vivo, fala a fala), o resultado, o
 * histórico da sessão e o que se faz com ele (inserir no projeto aberto, mandar para a fila). Vive na store para
 * o andamento e o que foi preenchido sobreviverem a trocar de aba.
 */
export const useNarrationStore = defineStore('narration', () => {
  const voices = useVoiceStore()
  const toasts = useToastsStore()
  const workspace = useWorkspaceStore()
  const editor = useEditorStore()

  const text = ref('')
  const speed = ref(1)
  const seed = ref<number | null>(null)
  /** Vazio é o idioma da voz. */
  const language = ref('')
  /** O dicionário de pronúncia que vale; vazio é o da marca da voz. */
  const brand = ref('')

  // todas as vozes, sem o filtro de marca da biblioteca: o roteiro pode usar qualquer uma
  const voiceList = ref<VoiceProfile[]>([])
  const voiceFailure = ref('')
  const voiceOptions = computed<SelectOption[]>(() => voiceList.value.map((voice) => ({ value: voice.id, label: voiceLabel(voice) })))
  /** A voz escolhida na biblioteca, se ela ainda existe; vazio é a voz automática do motor. */
  const voiceId = computed(() => (voiceList.value.some((voice) => voice.id === voices.selectedVoiceId) ? voices.selectedVoiceId : ''))

  const job = reactive<NarrationJob>({
    running: false,
    label: '',
    percent: null,
    startedAtMs: null,
    cancelling: false,
    error: '',
    cancelled: false,
  })
  const live = reactive<LiveView>({
    visible: false,
    total: 0,
    ready: 0,
    playing: null,
    stoppedAfter: null,
    muted: false,
    jobEnded: false,
  })
  const liveText = computed(() => (live.muted ? LIVE_MUTED_TEXT : liveStatusText(live)))

  const history = ref<NarrationItem[]>([])
  const current = ref<NarrationItem | null>(null)
  /** Muda quando o histórico pede para tocar uma narração: a tela toca o player do resultado. */
  const playStamp = ref(0)

  const insertStart = ref<number | null>(null)
  const defaultStart = ref(0)
  const inserting = ref(false)
  const insertNote = ref('')
  const queueing = ref(false)

  /** O editor tem o projeto aberto agora: o cursor dele marca o ponto de inserção e a inserção passa por ele. */
  const editorHoldsProject = computed(
    () => !!workspace.currentProject && editor.name === workspace.currentProject && editor.status === 'ready',
  )
  /** A posição do cursor do editor, em segundos; nulo quando o editor não está com o projeto aberto. */
  const cursorStart = computed(() => (editorHoldsProject.value ? Math.round(editor.playhead * 100) / 100 : null))
  const startAt = computed(() => Math.max(0, insertStart.value ?? cursorStart.value ?? defaultStart.value))
  const canGenerate = computed(
    () => text.value.trim() !== '' && !job.running && seedProblem(seed.value) === '' && scriptProblem(text.value) === '',
  )

  let followed: FollowedJob<NarrationResult> | null = null
  let player: LivePlayer | null = null
  let liveTimer: ReturnType<typeof setInterval> | null = null
  let nextId = 1

  async function loadVoices(): Promise<void> {
    voiceFailure.value = ''
    try {
      voiceList.value = await api.voice.list()
    } catch (failure) {
      voiceList.value = []
      voiceFailure.value = errorMessage(failure)
    }
  }

  function chooseVoice(id: string): void {
    voices.chooseVoice(id)
  }

  /** Os pedidos que a narração e a fila têm em comum, com os campos em branco como `null`. */
  function currentEntry(): NarrationEntry {
    return {
      text: text.value.trim(),
      voiceId: voiceId.value || null,
      speed: speed.value,
      language: language.value || null,
      seed: seed.value,
    }
  }

  // ---------- prévia ao vivo ----------

  function stopTicker(): void {
    if (liveTimer) clearInterval(liveTimer)
    liveTimer = null
  }

  function refreshLive(): void {
    if (!player) return
    live.ready = player.ready()
    live.playing = player.playingIndex()
    if ((live.jobEnded && live.playing === null) || live.stoppedAfter !== null || live.muted) stopTicker()
  }

  function stopLivePreview(): void {
    stopTicker()
    player?.stop()
    player = null
  }

  /** Começa uma prévia ao vivo nova. Roda dentro do clique, que é o que libera o áudio do navegador. */
  function startLivePreview(audio: LiveAudioFactory): void {
    stopLivePreview()
    Object.assign(live, { visible: false, total: 0, ready: 0, playing: null, stoppedAfter: null, muted: false, jobEnded: false })
    const context = audio()
    if (!context) return
    context.resume().catch(() => undefined)
    player = createLivePlayer(context, fetchChunkBytes, () =>
      toasts.push({
        tone: 'error',
        title: 'Uma fala da prévia ao vivo não tocou',
        description: 'O arquivo final não é afetado.',
      }),
    )
    live.visible = true
    liveTimer = setInterval(refreshLive, LIVE_TICK_MS)
  }

  /** Silencia só a prévia ao vivo; a geração continua e o arquivo final sai do mesmo jeito. */
  function muteLive(): void {
    if (!player) return
    live.muted = true
    stopLivePreview()
  }

  function onUtterance(utterance: UtteranceEvent): void {
    if (!player) return
    live.total = utterance.total
    void player.enqueue({ index: utterance.index, url: utterance.audio_url, pauseAfter: utterance.pause_after_s })
  }

  // ---------- gerar e parar ----------

  function remember(entry: NarrationEntry, result: NarrationResult): void {
    const item: NarrationItem = {
      ...entry,
      id: nextId++,
      voiceName: voiceList.value.find((voice) => voice.id === entry.voiceId)?.name ?? 'Voz automática',
      duration: result.duration_s,
      audioUrl: result.audio_url,
      output: result.output,
      at: new Date(),
    }
    history.value = [item, ...history.value].slice(0, HISTORY_LIMIT)
    current.value = item
  }

  /**
   * Gera a narração (um job) e acompanha: o andamento, a prévia ao vivo de cada fala e o resultado. `audio` entrega o
   * contexto de áudio da prévia; os testes entregam um falso.
   */
  async function generate(audio: LiveAudioFactory = browserLiveAudio): Promise<void> {
    if (!canGenerate.value) return
    const entry = currentEntry()
    Object.assign(job, { running: true, label: QUEUED_LABEL, percent: null, startedAtMs: Date.now(), cancelling: false, error: '', cancelled: false })
    startLivePreview(audio)
    try {
      const { job_id } = await api.voice.speak({
        text: entry.text,
        voice: entry.voiceId,
        language: entry.language,
        speed: entry.speed,
        seed: entry.seed,
        brand: brand.value || null,
      })
      followed = followJob<NarrationResult>(job_id, {
        onProgress(progress) {
          if (job.cancelling) return
          if (progress.label) job.label = progress.label
          job.percent = progress.percent ?? null
        },
        onLog(message) {
          // "Aguardando outro trabalho de voz terminar" diz mais que a etapa velha
          if (!job.cancelling) job.label = message
        },
        onUtterance,
      })
      const result = await followed.result
      live.jobEnded = true
      remember(entry, result)
    } catch (failure) {
      live.jobEnded = true
      if (isJobCancelled(failure)) {
        const stopped = (failure.result ?? {}) as Partial<NarrationStopped>
        if (typeof stopped.total === 'number') live.total = stopped.total
        live.stoppedAfter = typeof stopped.ready === 'number' ? stopped.ready : (player?.ready() ?? 0)
        job.cancelled = true
        refreshLive()
      } else {
        stopLivePreview()
        live.visible = false
        job.error = errorMessage(failure)
      }
    } finally {
      followed = null
      job.running = false
      job.cancelling = false
      if (live.visible) refreshLive()
    }
  }

  /** Pede ao servidor que pare entre duas falas; o job termina como "parado" e o que já saiu fica guardado. */
  async function stop(): Promise<void> {
    if (!followed || job.cancelling) return
    job.cancelling = true
    job.label = STOPPING_LABEL
    if (player) {
      // a prévia cala já, sem esperar a fala que ainda está sendo gerada
      live.stoppedAfter = player.ready()
      stopLivePreview()
    }
    try {
      await followed.cancel()
    } catch (failure) {
      job.cancelling = false
      job.error = errorMessage(failure)
    }
  }

  // ---------- resultado e histórico ----------

  function show(item: NarrationItem): void {
    current.value = item
    playStamp.value += 1
  }

  function reuseText(item: NarrationItem): void {
    text.value = item.text
  }

  // ---------- inserir no projeto aberto ----------

  /** Acha onde a próxima narração começa por padrão: depois da última que o projeto aberto já tem. */
  async function refreshDefaultStart(): Promise<void> {
    const project = workspace.currentProject
    if (!project) {
      defaultStart.value = 0
      return
    }
    let start = 0
    try {
      start = lastNarrationEnd(await api.editor.timeline(project))
    } catch {
      // projeto com fonte ausente ou vista indisponível: a narração começa no início, e a pessoa pode mudar o campo
    }
    // a pessoa pode ter aberto outro projeto enquanto a vista carregava
    if (workspace.currentProject === project) defaultStart.value = start
  }

  /**
   * Acrescenta a narração em `audio.narration` do projeto aberto e salva. A spec vem do servidor na hora, porque a
   * que a tela leu antes pode ter mudado. Devolve se entrou; o motivo, quando não, fica em `insertNote`.
   */
  async function insertIntoProject(item: NarrationItem): Promise<boolean> {
    const project = workspace.currentProject
    if (!project) {
      insertNote.value = 'Abra um projeto para inserir a narração nele.'
      return false
    }
    inserting.value = true
    insertNote.value = ''
    const start = startAt.value
    try {
      const inserted = buildNarrationItem(item, start)
      if (editorHoldsProject.value && editor.spec) {
        // o editor é a fonte da verdade enquanto está com o projeto aberto: gravar por fora deixaria a cópia dele
        // velha, e o próximo Salvar apagaria a narração
        editor.replaceSpec(withNarration(editor.spec, inserted))
        if (!(await editor.save())) throw new Error(editor.saveError || 'o projeto não foi salvo')
      } else {
        const detail = await api.projects.get(project)
        await api.editor.saveProject(project, withNarration(detail.spec, inserted))
      }
      insertNote.value = `Narração inserida em ${formatSecondsPrecise(inserted.start)} s do projeto ${project}.`
      toasts.push({ tone: 'success', title: 'Narração inserida', description: insertNote.value })
      insertStart.value = null
      await refreshDefaultStart()
      return true
    } catch (failure) {
      insertNote.value = `Não consegui inserir: ${errorMessage(failure)}`
      toasts.push({ tone: 'error', title: 'Não consegui inserir a narração', description: errorMessage(failure) })
      return false
    } finally {
      inserting.value = false
    }
  }

  // ---------- fila ----------

  /** Manda o roteiro para a fila de narrações longas, que roda em segundo plano, uma por vez. */
  async function sendToQueue(choices: QueueChoices): Promise<QueueAdded | null> {
    const entry = currentEntry()
    if (!entry.text) return null
    queueing.value = true
    try {
      return await api.queue.addText({
        text: entry.text,
        voice: entry.voiceId,
        language: entry.language,
        speed: entry.speed,
        brand: brand.value || null,
        draft: choices.draft,
        format: choices.format,
        ...(choices.title.trim() ? { title: choices.title.trim() } : {}),
      })
    } finally {
      queueing.value = false
    }
  }

  return {
    text,
    speed,
    seed,
    language,
    brand,
    voiceList,
    voiceFailure,
    voiceOptions,
    voiceId,
    job,
    live,
    liveText,
    history,
    current,
    playStamp,
    insertStart,
    defaultStart,
    cursorStart,
    startAt,
    inserting,
    insertNote,
    queueing,
    canGenerate,
    loadVoices,
    chooseVoice,
    generate,
    stop,
    muteLive,
    show,
    reuseText,
    refreshDefaultStart,
    insertIntoProject,
    sendToQueue,
  }
})
