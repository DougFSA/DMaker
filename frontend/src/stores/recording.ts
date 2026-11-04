/* A gravação do microfone no projeto: o estado da janela "Gravar" (dispositivo, formato, monitorar, gravar sobre o vídeo,
   punch-in, hora marcada, ativada por som) e o ciclo de uma gravação. O som cru vem da captura (`lib/recordingCapture`), é
   cortado em pedaços de um segundo e mandado ao servidor na hora (`lib/recordingUpload`), então fechar a aba no meio não
   perde nada; ao parar, o servidor junta os pedaços e a operação que ele devolve entra na spec como um passo do desfazer.

   Duas conversas com o resto da tela: o player (a prévia toca enquanto grava, e o relógio dela dá o instante da gravação) e o
   painel Áudio (a seleção de uma voz gravada é o trecho do punch-in). */
import { defineStore } from 'pinia'
import { computed, reactive, ref, shallowRef } from 'vue'
import { ApiError, errorMessage } from '@/api'
import { recordingsApi } from '@/api/recordings'
import type { PunchRange, RecordingStatus } from '@/api/types/recordings'
import { isVoiceTarget, toProjectTime } from '@/lib/audioPanelOps'
import type { MeterReading } from '@/lib/audioPlayback'
import {
  BLOCK_FRAMES,
  CaptureError,
  captureEngine,
  type CaptureBlock,
  type CaptureSession,
  type InputDevice,
} from '@/lib/recordingCapture'
import {
  calibrationCorrection,
  compensatedStart,
  findDelay,
  makeClick,
  MIN_CALIBRATION_CONFIDENCE,
  PreviewClock,
  readCalibration,
  roundTime,
  totalLatency,
  webAudioLatency,
  writeCalibration,
} from '@/lib/recordingLatency'
import { parseLocalDateTime, resolveSchedule } from '@/lib/recordingSchedule'
import { ChunkUploader } from '@/lib/recordingUpload'
import { blockPeakDb, concat, interleave, readLevels } from '@/lib/pcm'
import { DEFAULT_GATE, SoundGate } from '@/lib/soundGate'
import { readStored, writeStored } from '@/lib/storage'
import { useAudioPanelStore } from './audioPanel'
import { useEditorStore } from './editor'
import { usePlayerStore } from './player'
import { useToastsStore } from './toasts'

const SETTINGS_KEY = 'dmaker.recording.settings'
/** Os pedaços têm um segundo de som: o servidor guarda cada um na hora. */
const CHUNK_SECONDS = 1
const CALIBRATION_SECONDS = 1.6
const CLICK_AFTER_SECONDS = 0.4

export type RecordPhase = 'idle' | 'monitoring' | 'waiting' | 'recording' | 'saving'

export const SAMPLE_RATES = [44100, 48000] as const

export interface RecordSettings {
  deviceId: string
  channels: 1 | 2
  sampleRate: number
  /** A prévia toca enquanto grava, e a gravação cai no lugar certo do vídeo. */
  overVideo: boolean
  /** Regrava a seleção do painel Áudio (o punch-in) em vez de acrescentar uma voz nova; vale para uma gravação só. */
  punchIn: boolean
  /** Escutar o microfone pelo fone enquanto grava (com o alto-falante, dá microfonia). */
  listen: boolean
  /** Segundos da prévia que tocam antes do trecho do punch-in. */
  prerollSeconds: number
  soundActivated: boolean
  thresholdDb: number
  waitSeconds: number
  scheduled: boolean
  /** Os campos do `datetime-local` e da duração (em minutos) da gravação com hora marcada. */
  startAt: string
  endAt: string
  durationMinutes: number | null
}

const DEFAULTS: RecordSettings = {
  deviceId: '',
  channels: 1,
  sampleRate: 48000,
  overVideo: true,
  punchIn: false,
  listen: false,
  prerollSeconds: 3,
  soundActivated: false,
  thresholdDb: DEFAULT_GATE.thresholdDb,
  waitSeconds: DEFAULT_GATE.waitMs / 1000,
  scheduled: false,
  startAt: '',
  endAt: '',
  durationMinutes: null,
}

/** O que fica lembrado entre sessões: o dispositivo e o formato. O agendamento e o gatilho valem para uma gravação só. */
const REMEMBERED: Array<keyof RecordSettings> = ['deviceId', 'channels', 'sampleRate', 'overVideo', 'prerollSeconds']

function loadSettings(): RecordSettings {
  const stored = readStored(SETTINGS_KEY)
  if (!stored) return { ...DEFAULTS }
  try {
    const parsed = JSON.parse(stored) as Partial<RecordSettings>
    const picked = Object.fromEntries(REMEMBERED.filter((key) => key in parsed).map((key) => [key, parsed[key]]))
    return { ...DEFAULTS, ...picked }
  } catch {
    return { ...DEFAULTS }
  }
}

/** A conta da gravação em andamento. */
interface Live {
  session: CaptureSession
  uploader: ChunkUploader
  clock: PreviewClock
  gate: SoundGate | null
  blocks: Map<number, CaptureBlock>
  blockIndex: number
  /** O que falta completar do pedaço de um segundo. */
  pending: Float32Array[]
  pendingFrames: number
  seq: number
  framesWritten: number
  capturedFrames: number
  recordingId: Promise<string> | null
  startedAtPage: number
  start: number | null
  punch: PunchRange | null
  stopAfterSeconds: number | null
  firstEmitted: boolean
  overVideo: boolean
  latency: number
  failed: boolean
}

export const useRecordingStore = defineStore('recording', () => {
  const editor = useEditorStore()
  const player = usePlayerStore()
  const panel = useAudioPanelStore()
  const toasts = useToastsStore()

  const settings = reactive<RecordSettings>(loadSettings())
  const dialogOpen = ref(false)
  const dialogTab = ref<'record' | 'clone'>('record')
  const devices = ref<InputDevice[]>([])
  const phase = ref<RecordPhase>('idle')
  const levels = shallowRef<MeterReading[]>([])
  const elapsed = ref(0)
  const error = ref('')
  const notice = ref('')
  const unsent = ref(0)
  const gateOpen = ref(true)
  const countdown = ref(0)
  /** O trecho do punch-in desta gravação, ou nulo numa gravação comum. */
  const punchRange = ref<PunchRange | null>(null)
  const unfinished = ref<RecordingStatus[]>([])
  const calibrating = ref(false)
  const calibrationText = ref('')
  const latencyText = ref('')

  let session: CaptureSession | null = null
  let live: Live | null = null
  let waitTimer: ReturnType<typeof setTimeout> | null = null
  let tickTimer: ReturnType<typeof setInterval> | null = null

  const supported = computed(() => captureEngine().isSupported())
  const busy = computed(() => phase.value === 'recording' || phase.value === 'saving' || phase.value === 'waiting')

  /** A voz que a seleção do painel Áudio marca para regravar, em tempo da linha do tempo; nulo sem seleção de voz gravada. */
  const punchCandidate = computed<PunchRange | null>(() => {
    const target = panel.target
    const selection = panel.selection
    if (!panel.open || !target || !isVoiceTarget(target) || !selection) return null
    const start = toProjectTime(panel.clock, selection.start)
    const end = toProjectTime(panel.clock, selection.end)
    if (start === null || end === null || end - start < 0.05) return null
    return { target, start: roundTime(start), end: roundTime(end) }
  })

  function remember(): void {
    const chosen = Object.fromEntries(REMEMBERED.map((key) => [key, settings[key]]))
    writeStored(SETTINGS_KEY, JSON.stringify(chosen))
  }

  /* ---------- a janela ---------- */

  function openDialog(tab: 'record' | 'clone' = 'record'): void {
    dialogTab.value = tab
    dialogOpen.value = true
    error.value = ''
    settings.punchIn = punchCandidate.value !== null // com um trecho de voz selecionado no painel, o padrão é regravá-lo
    void refreshDevices()
    void loadUnfinished()
  }

  async function closeDialog(): Promise<void> {
    if (busy.value) return // gravando, a janela só fecha depois de parar
    await stopMonitor()
    dialogOpen.value = false
  }

  async function refreshDevices(): Promise<void> {
    try {
      devices.value = await captureEngine().listDevices()
    } catch {
      devices.value = []
    }
    if (settings.deviceId && !devices.value.some((device) => device.deviceId === settings.deviceId)) {
      settings.deviceId = '' // o dispositivo lembrado sumiu: volta ao padrão do sistema
    }
  }

  function describe(failure: unknown): string {
    return failure instanceof CaptureError ? failure.message : errorMessage(failure)
  }

  /* ---------- abrir o microfone (monitorar) ---------- */

  async function openSession(): Promise<CaptureSession | null> {
    if (session) return session
    try {
      session = await captureEngine().open({
        deviceId: settings.deviceId || undefined,
        channels: settings.channels,
        sampleRate: settings.sampleRate,
      })
    } catch (failure) {
      error.value = describe(failure)
      return null
    }
    session.onEnded = (reason) => {
      error.value = reason
      if (phase.value === 'recording') void stop()
      else void stopMonitor()
    }
    session.setMonitor(settings.listen)
    void refreshDevices() // os nomes dos dispositivos só aparecem depois da permissão
    return session
  }

  /** "Monitorar": mostra o nível sem gravar. */
  async function monitor(): Promise<void> {
    if (phase.value !== 'idle') return
    error.value = ''
    const opened = await openSession()
    if (!opened) return
    opened.onBlock = (block) => meter(block)
    phase.value = 'monitoring'
  }

  async function stopMonitor(): Promise<void> {
    if (phase.value === 'monitoring' || (phase.value === 'idle' && session)) {
      await closeSession()
      phase.value = 'idle'
    }
  }

  async function closeSession(): Promise<void> {
    const current = session
    session = null
    levels.value = []
    if (current) {
      current.onBlock = null
      current.onEnded = null
      await current.close()
    }
  }

  function meter(block: CaptureBlock): void {
    levels.value = readLevels(block.channels)
  }

  function setListen(on: boolean): void {
    settings.listen = on
    session?.setMonitor(on)
  }

  /** O dispositivo ou o formato mudou: o microfone aberto é fechado para abrir de novo com a escolha nova. */
  async function settingsChanged(): Promise<void> {
    remember()
    if (phase.value === 'monitoring') {
      await closeSession()
      phase.value = 'idle'
      await monitor()
    }
  }

  /* ---------- gravar ---------- */

  function currentLatency(opened: CaptureSession): number {
    const estimate = webAudioLatency(opened.latency())
    const total = totalLatency(estimate, readCalibration(opened.deviceId))
    latencyText.value = `${Math.round(total * 1000)} ms`
    return total
  }

  /** Pede a gravação: agora, ou na hora marcada (a janela fica esperando, com o microfone já aberto). */
  async function start(): Promise<void> {
    if (busy.value) return
    error.value = ''
    notice.value = ''
    if (!editor.name) {
      error.value = 'Abra um projeto para gravar.'
      return
    }
    const range = settings.punchIn ? punchCandidate.value : null
    if (settings.punchIn && !range) {
      error.value = 'Selecione na onda o trecho da voz gravada que será regravado.'
      return
    }
    let waitMs = 0
    let duration: number | null = null
    if (settings.scheduled) {
      const result = resolveSchedule(
        {
          startAt: parseLocalDateTime(settings.startAt),
          endAt: parseLocalDateTime(settings.endAt),
          durationSeconds: settings.durationMinutes ? settings.durationMinutes * 60 : null,
        },
        new Date(),
      )
      if (!result.ok) {
        error.value = result.message
        return
      }
      waitMs = result.schedule.waitMs
      duration = result.schedule.durationSeconds
    }
    const opened = await openSession()
    if (!opened) return
    punchRange.value = range
    if (waitMs > 500) {
      phase.value = 'waiting'
      opened.onBlock = (block) => meter(block)
      countdown.value = Math.round(waitMs / 1000)
      const fireAt = Date.now() + waitMs
      tickTimer = setInterval(() => (countdown.value = Math.max(0, Math.round((fireAt - Date.now()) / 1000))), 500)
      waitTimer = setTimeout(() => {
        clearTimers()
        void begin(opened, duration)
      }, waitMs)
      return
    }
    await begin(opened, duration)
  }

  function clearTimers(): void {
    if (waitTimer) clearTimeout(waitTimer)
    if (tickTimer) clearInterval(tickTimer)
    waitTimer = null
    tickTimer = null
  }

  async function begin(opened: CaptureSession, durationSeconds: number | null): Promise<void> {
    const project = editor.name
    if (!project) return
    const range = punchRange.value
    const overVideo = settings.overVideo || range !== null
    const blockMs = (BLOCK_FRAMES / opened.rate) * 1000
    live = {
      session: opened,
      uploader: new ChunkUploader(
        async (seq, bytes) => {
          const id = await ensureOpen()
          await recordingsApi.putChunk(project, id, seq, bytes)
        },
        {
          onRetry: () => (notice.value = 'Sem conexão com o servidor: a gravação continua e os pedaços vão ser reenviados.'),
          // o servidor entendeu e recusou (projeto apagado, pedaço inválido): repetir não conserta
          isFatal: (failure) =>
            failure instanceof ApiError && failure.status >= 400 && failure.status < 500 && failure.status !== 408 && failure.status !== 429,
        },
      ),
      clock: new PreviewClock(),
      gate: settings.soundActivated
        ? new SoundGate({
            thresholdDb: settings.thresholdDb,
            waitMs: settings.waitSeconds * 1000,
            prerollMs: DEFAULT_GATE.prerollMs,
            tailMs: DEFAULT_GATE.tailMs,
            blockMs,
          })
        : null,
      blocks: new Map(),
      blockIndex: 0,
      pending: [],
      pendingFrames: 0,
      seq: 0,
      framesWritten: 0,
      capturedFrames: 0,
      recordingId: null,
      startedAtPage: performance.now(),
      start: null,
      punch: range,
      stopAfterSeconds: durationSeconds,
      firstEmitted: false,
      overVideo,
      latency: overVideo ? currentLatency(opened) : 0,
      failed: false,
    }
    elapsed.value = 0
    gateOpen.value = true
    if (overVideo) {
      const from = range ? Math.max(0, range.start - settings.prerollSeconds) : editor.playhead
      player.pause()
      player.seek(from)
    }
    phase.value = 'recording'
    opened.onBlock = onBlock
    if (overVideo) player.play()
    window.addEventListener('beforeunload', warnBeforeLeaving)
  }

  function warnBeforeLeaving(event: BeforeUnloadEvent): void {
    // o que já chegou ao servidor fica salvo; o aviso é por causa do que ainda está a caminho
    if ((live?.uploader.pending ?? 0) > 0 || phase.value === 'recording') event.preventDefault()
  }

  /** Abre a gravação no servidor, uma vez; se falhar, a próxima tentativa do envio abre de novo. */
  function ensureOpen(): Promise<string> {
    const current = live
    if (!current) return Promise.reject(new Error('sem gravação'))
    if (!current.recordingId) {
      const project = editor.name as string
      const started = current.start ?? editor.playhead
      current.recordingId = recordingsApi
        .open(project, {
          rate: current.session.rate,
          channels: current.session.channels,
          start: roundTime(started),
          device: current.session.deviceLabel,
          ...(current.punch ? { punch: current.punch } : {}),
        })
        .then((status) => status.id)
      current.recordingId.catch(() => {
        if (live === current) current.recordingId = null
      })
    }
    return current.recordingId
  }

  function onBlock(block: CaptureBlock): void {
    const current = live
    if (!current || phase.value !== 'recording') return
    meter(block)
    if (current.overVideo) current.clock.add({ nowMs: block.receivedAtMs, position: editor.playhead })
    const index = current.blockIndex
    current.blockIndex += 1
    current.capturedFrames += block.channels[0]?.length ?? 0
    if (current.gate) {
      current.blocks.set(index, block)
      const step = current.gate.push(blockPeakDb(block.channels))
      gateOpen.value = step.open
      for (const key of step.emit) {
        const kept = current.blocks.get(key)
        current.blocks.delete(key)
        if (kept) write(current, kept)
      }
      // o que o gatilho já não pode pedir mais (mais velho que a espera mais o pré-rolo) sai da memória
      const blockMs = (BLOCK_FRAMES / current.session.rate) * 1000
      const horizon = Math.ceil((settings.waitSeconds * 1000 + 2000) / blockMs)
      for (const key of current.blocks.keys()) if (key < index - horizon) current.blocks.delete(key)
    } else {
      write(current, block)
    }
    const seconds = current.capturedFrames / current.session.rate
    elapsed.value = current.gate ? current.framesWritten / current.session.rate : seconds
    unsent.value = current.uploader.pending
    if (current.uploader.failed && !current.failed) {
      current.failed = true // o servidor recusou um pedaço: seguir gravando seria gravar no vazio
      void stop()
      return
    }
    if (current.stopAfterSeconds !== null && seconds >= current.stopAfterSeconds) void stop()
    else if (current.punch && editor.playhead >= current.punch.end + 0.25) void stop() // passou do fim do trecho
    else if (current.overVideo && !player.playing && seconds > 1) void stop() // o vídeo acabou
  }

  /** Acrescenta um bloco ao arquivo: fixa o instante da gravação no primeiro e manda cada segundo completo. */
  function write(current: Live, block: CaptureBlock): void {
    if (!current.firstEmitted) {
      current.firstEmitted = true
      current.start = startOf(current, block)
      void ensureOpen().catch(() => undefined) // abre já: o primeiro pedaço só sai daqui a um segundo
    }
    current.pending.push(interleave(block.channels))
    const frames = block.channels[0]?.length ?? 0
    current.pendingFrames += frames
    current.framesWritten += frames
    const perChunk = Math.round(current.session.rate * CHUNK_SECONDS)
    while (current.pendingFrames >= perChunk) sendChunk(current, perChunk)
  }

  function startOf(current: Live, block: CaptureBlock): number {
    if (!current.overVideo || !current.clock.ready) return editor.playhead
    const arrival = current.session.pageTime(block.contextTime)
    return compensatedStart(current.clock.positionAt(arrival), current.latency)
  }

  /** Tira `frames` quadros do que está acumulado e os manda como o próximo pedaço. */
  function sendChunk(current: Live, frames: number): void {
    const channels = current.session.channels
    const all = concat(current.pending)
    const take = all.slice(0, frames * channels)
    const rest = all.slice(frames * channels)
    current.pending = rest.length > 0 ? [rest] : []
    current.pendingFrames = rest.length / channels
    const bytes = new Uint8Array(take.buffer.slice(take.byteOffset, take.byteOffset + take.byteLength))
    current.uploader.send(current.seq, bytes)
    current.seq += 1
  }

  /** Para de gravar: manda o resto, o servidor junta os pedaços e a gravação entra na linha do tempo. */
  async function stop(): Promise<void> {
    if (phase.value === 'waiting') {
      clearTimers()
      phase.value = 'monitoring'
      return
    }
    const current = live
    if (!current || phase.value !== 'recording') return
    phase.value = 'saving'
    current.session.onBlock = null
    if (current.overVideo) player.pause()
    window.removeEventListener('beforeunload', warnBeforeLeaving)
    try {
      for (const key of current.gate?.finish() ?? []) {
        const kept = current.blocks.get(key)
        if (kept) write(current, kept)
      }
      if (current.pendingFrames > 0) sendChunk(current, current.pendingFrames)
      if (!current.firstEmitted) {
        notice.value = 'Nada foi gravado: o som não passou do limiar.'
        return
      }
      await current.uploader.flush()
      const id = await ensureOpen()
      const project = editor.name as string
      const finished = await recordingsApi.finish(project, id, {
        ...(current.start !== null ? { start: roundTime(current.start) } : {}),
        ...(current.punch ? { punch: current.punch } : {}),
      })
      const ok = await editor.applyOp(finished.op)
      if (!ok) await editor.applyOp(finished.recover_op) // o punch-in não coube (a voz mudou): entra como voz nova
      toasts.push({
        tone: 'success',
        title: current.punch ? 'Punch-in feito' : 'Gravação posta na linha do tempo',
        description: `${finished.duration.toFixed(1).replace('.', ',')} s${finished.gaps.length ? `, com ${finished.gaps.length} pedaço(s) perdido(s) no caminho` : ''}.`,
      })
      if (finished.gaps.length > 0) notice.value = `Faltaram ${finished.gaps.length} pedaço(s) de um segundo; viraram silêncio.`
    } catch (failure) {
      error.value = `${describe(failure)} O que já chegou ao servidor está salvo e pode ser recuperado.`
      void loadUnfinished()
    } finally {
      live = null
      unsent.value = 0
      await closeSession()
      phase.value = 'idle'
      punchRange.value = null
    }
  }

  /** Desiste: o que foi gravado é apagado do servidor e nada entra na linha do tempo. */
  async function cancel(): Promise<void> {
    clearTimers()
    const current = live
    if (!current) {
      if (phase.value === 'waiting') {
        phase.value = 'monitoring'
      }
      return
    }
    current.uploader.abandon()
    current.session.onBlock = null
    window.removeEventListener('beforeunload', warnBeforeLeaving)
    if (current.overVideo) player.pause()
    const pending = current.recordingId
    live = null
    if (pending) {
      const project = editor.name as string
      const id = await pending.catch(() => null)
      if (id) await recordingsApi.discard(project, id).catch(() => undefined)
    }
    await closeSession()
    unsent.value = 0
    phase.value = 'idle'
    punchRange.value = null
  }

  /* ---------- recuperar a gravação que a aba deixou aberta ---------- */

  async function loadUnfinished(): Promise<void> {
    const project = editor.name
    if (!project) {
      unfinished.value = []
      return
    }
    try {
      const found = await recordingsApi.list(project, true)
      unfinished.value = found.recordings
    } catch {
      unfinished.value = []
    }
  }

  /** Finaliza uma gravação aberta com o que chegou e a põe na linha do tempo como voz nova. */
  async function recover(id: string): Promise<boolean> {
    const project = editor.name
    if (!project) return false
    try {
      const finished = await recordingsApi.finish(project, id)
      const ok = await editor.applyOp(finished.recover_op)
      if (ok) {
        toasts.push({
          tone: 'success',
          title: 'Gravação recuperada',
          description: `${finished.duration.toFixed(1).replace('.', ',')} s postos na linha do tempo.`,
        })
      }
      await loadUnfinished()
      return ok
    } catch (failure) {
      toasts.push({ tone: 'error', title: 'Não consegui recuperar a gravação', description: describe(failure) })
      return false
    }
  }

  async function discardUnfinished(id: string): Promise<void> {
    const project = editor.name
    if (!project) return
    try {
      await recordingsApi.discard(project, id)
    } catch (failure) {
      toasts.push({ tone: 'error', title: 'Não consegui descartar a gravação', description: describe(failure) })
    }
    await loadUnfinished()
  }

  /* ---------- calibrar a latência ---------- */

  /** Toca um clique, grava e acha o atraso por correlação, como o teste de latência do Audacity. Precisa do microfone
   *  ouvindo o alto-falante (fone fora). Guarda a correção por dispositivo. */
  async function calibrate(): Promise<void> {
    if (phase.value !== 'idle' && phase.value !== 'monitoring') return
    error.value = ''
    calibrationText.value = ''
    const opened = await openSession()
    if (!opened) return
    const keepMonitoring = phase.value === 'monitoring'
    calibrating.value = true
    const click = makeClick(opened.rate)
    const parts: Float32Array[] = []
    let firstTime: number | null = null
    let playedAt = 0
    opened.onBlock = (block) => {
      meter(block)
      if (firstTime === null) {
        firstTime = block.contextTime
        playedAt = opened.playClick(click, CLICK_AFTER_SECONDS)
      }
      parts.push(block.channels[0] ?? new Float32Array(0))
    }
    await new Promise<void>((resolve) => setTimeout(resolve, CALIBRATION_SECONDS * 1000))
    opened.onBlock = keepMonitoring ? (block) => meter(block) : null
    calibrating.value = false
    if (firstTime === null) {
      error.value = 'O microfone não entregou som durante a calibração.'
    } else {
      const found = findDelay(click, concat(parts), opened.rate, CALIBRATION_SECONDS - 0.2)
      if (!found || found.confidence < MIN_CALIBRATION_CONFIDENCE) {
        error.value =
          'Não ouvi o clique. Aproxime o microfone do alto-falante, tire o fone e aumente o volume do computador.'
      } else {
        // o clique foi tocado em `playedAt` e apareceu na gravação em `found.seconds` depois do primeiro bloco
        const measured = found.seconds - (playedAt - firstTime)
        const correction = calibrationCorrection(measured, webAudioLatency(opened.latency()))
        writeCalibration(opened.deviceId, correction)
        calibrationText.value = `Latência medida: ${Math.round(measured * 1000)} ms (correção de ${Math.round(correction * 1000)} ms guardada para este microfone).`
        latencyText.value = `${Math.round(measured * 1000)} ms`
      }
    }
    if (!keepMonitoring && phase.value === 'idle') await closeSession()
  }

  return {
    settings,
    dialogOpen,
    dialogTab,
    devices,
    phase,
    levels,
    elapsed,
    error,
    notice,
    unsent,
    gateOpen,
    countdown,
    unfinished,
    calibrating,
    calibrationText,
    latencyText,
    supported,
    busy,
    punchCandidate,
    punchRange,
    openDialog,
    closeDialog,
    refreshDevices,
    monitor,
    stopMonitor,
    setListen,
    settingsChanged,
    start,
    stop,
    cancel,
    loadUnfinished,
    recover,
    discardUnfinished,
    calibrate,
  }
})
