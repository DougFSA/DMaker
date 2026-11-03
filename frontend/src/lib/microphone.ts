/* Gravação pelo microfone (getUserMedia + MediaRecorder) isolada atrás de uma interface pequena. Os controles da
   tela só conhecem `Microphone`; os testes trocam o ambiente por um falso, sem navegador, e o navegador de
   verdade entra por `browserEnvironment()`. */
import { extensionForMime } from './voice'

/** Tampa da gravação: uma referência de voz não precisa de mais que isso, e o servidor só usa 15 s dela. */
export const MAX_RECORDING_MS = 30_000
/** De quanto em quanto tempo o relógio da tela é avisado. */
const TICK_MS = 200

export type MicrophoneFailure = 'unsupported' | 'denied' | 'not-found' | 'busy' | 'failed' | 'empty' | 'cancelled'

const MESSAGES: Record<MicrophoneFailure, string> = {
  unsupported: 'Este navegador não grava pelo microfone. Envie um arquivo de áudio.',
  denied: 'Sem acesso ao microfone. Libere a permissão no navegador ou envie um arquivo.',
  'not-found': 'Nenhum microfone foi encontrado neste computador. Conecte um ou envie um arquivo de áudio.',
  busy: 'O microfone está em uso por outro programa. Feche-o e tente de novo.',
  failed: 'A gravação falhou. Tente de novo ou envie um arquivo de áudio.',
  empty: 'A gravação saiu vazia. Fale perto do microfone e tente de novo.',
  cancelled: 'Gravação descartada.',
}

/** Falha da gravação, com a frase pronta para a tela em `message` e o motivo em `reason`. */
export class MicrophoneError extends Error {
  readonly reason: MicrophoneFailure

  constructor(reason: MicrophoneFailure) {
    super(MESSAGES[reason])
    this.name = 'MicrophoneError'
    this.reason = reason
  }
}

/** O que o `getUserMedia` rejeita: o nome da exceção diz se foi permissão, falta de aparelho ou aparelho ocupado. */
function failureOf(error: unknown): MicrophoneFailure {
  // lê `name` de qualquer objeto: a DOMException de outro contexto (iframe, jsdom) nem sempre é `instanceof Error`
  const name = typeof error === 'object' && error !== null && 'name' in error ? String(error.name) : ''
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') return 'denied'
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || name === 'OverconstrainedError') {
    return 'not-found'
  }
  if (name === 'NotReadableError' || name === 'TrackStartError' || name === 'AbortError') return 'busy'
  return 'failed'
}

/** O arquivo gravado, pronto para ir no multipart da clonagem. */
export interface Recording {
  blob: Blob
  /** `gravacao.webm`, `gravacao.m4a`...: o servidor escolhe o leitor pela extensão. */
  filename: string
  mimeType: string
  durationMs: number
}

export interface RecordingHandle {
  /** Pede para parar; o arquivo chega por `finished`. Chamar de novo, ou depois de parar, não faz nada. */
  stop(): void
  /** Fecha o microfone e descarta o que foi gravado. `finished` rejeita com `cancelled`. */
  cancel(): void
  /** Resolve quando a gravação acaba (a pessoa parou ou a tampa de tempo chegou) e rejeita se ela falhou. */
  finished: Promise<Recording>
}

export interface StartOptions {
  /** Tampa de tempo; o padrão é `MAX_RECORDING_MS`. */
  maxMs?: number
  /** Avisa o tempo gravado, para o relógio da tela. */
  onTick?: (elapsedMs: number) => void
}

export interface Microphone {
  /** O navegador sabe gravar áudio (há `getUserMedia` e `MediaRecorder`)? */
  isSupported(): boolean
  /** Pede o microfone e começa a gravar. Rejeita com `MicrophoneError` se a permissão for negada, por exemplo. */
  start(options?: StartOptions): Promise<RecordingHandle>
}

/** O pedaço do MediaStream que a gravação usa: soltar as faixas apaga o ícone de "gravando" do navegador. */
export interface StreamLike {
  getTracks(): Array<{ stop(): void }>
}

/** O pedaço do MediaRecorder que a gravação usa. */
export interface RecorderLike {
  readonly state: string
  readonly mimeType: string
  ondataavailable: ((event: { data: Blob }) => void) | null
  onstop: (() => void) | null
  onerror: ((event: unknown) => void) | null
  start(): void
  stop(): void
}

/** As duas peças do navegador de que a gravação depende; `null` quando o navegador não as tem. */
export interface MicrophoneEnvironment {
  getUserMedia: ((constraints: { audio: boolean }) => Promise<StreamLike>) | null
  createRecorder: ((stream: StreamLike) => RecorderLike) | null
}

/** Lê o navegador na hora de usar (e não ao carregar o módulo), para os testes poderem trocar `MediaRecorder`. */
export function browserEnvironment(): MicrophoneEnvironment {
  const devices = typeof navigator === 'undefined' ? undefined : navigator.mediaDevices
  return {
    getUserMedia: devices?.getUserMedia ? (constraints) => devices.getUserMedia(constraints) : null,
    // o cast é só de tipo: o MediaRecorder real tem tudo o que `RecorderLike` usa, com eventos mais completos
    createRecorder:
      typeof MediaRecorder === 'undefined'
        ? null
        : (stream) => new MediaRecorder(stream as MediaStream) as unknown as RecorderLike,
  }
}

export function createMicrophone(environment: () => MicrophoneEnvironment = browserEnvironment): Microphone {
  return {
    isSupported() {
      const { getUserMedia, createRecorder } = environment()
      return !!getUserMedia && !!createRecorder
    },

    async start(options = {}) {
      const { getUserMedia, createRecorder } = environment()
      if (!getUserMedia || !createRecorder) throw new MicrophoneError('unsupported')

      let stream: StreamLike
      try {
        stream = await getUserMedia({ audio: true })
      } catch (error) {
        throw new MicrophoneError(failureOf(error))
      }

      let recorder: RecorderLike
      try {
        recorder = createRecorder(stream)
      } catch {
        stream.getTracks().forEach((track) => track.stop())
        throw new MicrophoneError('failed')
      }
      return record(stream, recorder, options)
    },
  }
}

function record(stream: StreamLike, recorder: RecorderLike, options: StartOptions): RecordingHandle {
  const maxMs = options.maxMs ?? MAX_RECORDING_MS
  const chunks: Blob[] = []
  const startedAt = Date.now()
  let settled = false
  let resolveFinished: (recording: Recording) => void
  let rejectFinished: (error: MicrophoneError) => void

  const finished = new Promise<Recording>((resolve, reject) => {
    resolveFinished = resolve
    rejectFinished = reject
  })
  // quem só chama stop() não precisa esperar `finished`: sem isto, descartar a gravação geraria um aviso de promessa rejeitada
  finished.catch(() => undefined)

  /** Solta o microfone e os relógios; é o que fecha a gravação, qualquer que seja o motivo. */
  function release(): void {
    clearInterval(tick)
    clearTimeout(cap)
    stream.getTracks().forEach((track) => track.stop())
  }

  function settle(failure: MicrophoneFailure | null): void {
    if (settled) return
    settled = true
    release()
    if (failure) {
      rejectFinished(new MicrophoneError(failure))
      return
    }
    const mimeType = recorder.mimeType || 'audio/webm'
    const blob = new Blob(chunks, { type: mimeType })
    if (blob.size === 0) {
      rejectFinished(new MicrophoneError('empty'))
      return
    }
    resolveFinished({
      blob,
      filename: `gravacao.${extensionForMime(mimeType)}`,
      mimeType,
      durationMs: Math.min(Date.now() - startedAt, maxMs),
    })
  }

  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) chunks.push(event.data)
  }
  recorder.onstop = () => settle(null)
  recorder.onerror = () => settle('failed')

  function stop(): void {
    if (settled || recorder.state === 'inactive') return
    // para o relógio já: o fim de verdade chega no `onstop`, que pode demorar alguns milissegundos
    clearInterval(tick)
    clearTimeout(cap)
    options.onTick?.(Math.min(Date.now() - startedAt, maxMs))
    recorder.stop()
  }

  function cancel(): void {
    if (settled) return
    recorder.ondataavailable = null
    recorder.onstop = null
    recorder.onerror = null
    if (recorder.state !== 'inactive') recorder.stop()
    settle('cancelled')
  }

  try {
    recorder.start()
  } catch {
    // não chegou a gravar: o microfone que o navegador abriu precisa ser solto mesmo assim
    stream.getTracks().forEach((track) => track.stop())
    throw new MicrophoneError('failed')
  }
  options.onTick?.(0)
  // os relógios nascem depois das funções que os desligam; elas só rodam depois deste ponto
  const tick = setInterval(() => options.onTick?.(Math.min(Date.now() - startedAt, maxMs)), TICK_MS)
  const cap = setTimeout(stop, maxMs)

  return { stop, cancel, finished }
}
