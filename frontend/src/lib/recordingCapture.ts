/* A captura do microfone pelo navegador: `getUserMedia` com o cancelamento de eco, a supressão de ruído e o ganho
   automático DESLIGADOS (eles estragam a voz de referência para clonar e mexem no nível da narração) e um AudioWorklet que
   entrega o som cru, em float32, na taxa escolhida, sem MediaRecorder e sem compressão.

   Tudo que depende do navegador mora atrás de `CaptureEngine`: a tela, o armazenamento e o envio só conhecem esta
   interface, e os testes entregam uma captura falsa (`test/fakeCapture.ts`). */
import type { BrowserLatency } from './recordingLatency'

/** Um microfone ou interface de áudio que o navegador listou. */
export interface InputDevice {
  deviceId: string
  label: string
}

export interface CaptureSettings {
  /** O dispositivo escolhido; vazio usa o padrão do sistema. */
  deviceId?: string
  /** Mono (1) ou estéreo (2). */
  channels: 1 | 2
  /** A taxa de amostragem pedida (Hz); o navegador pode usar outra, e `CaptureSession.rate` diz qual valeu. */
  sampleRate: number
}

/** Um bloco de som captado: um `Float32Array` por canal. */
export interface CaptureBlock {
  channels: Float32Array[]
  /** O instante do contexto de áudio em que o primeiro quadro do bloco chegou. */
  contextTime: number
  /** O relógio da página (ms) quando o bloco chegou à aba. */
  receivedAtMs: number
}

export interface CaptureSession {
  /** A taxa real do contexto de áudio. */
  readonly rate: number
  readonly channels: number
  /** O nome do dispositivo que o navegador abriu. */
  readonly deviceLabel: string
  /** O `deviceId` que o navegador abriu (a calibração é guardada por ele). */
  readonly deviceId: string
  /** Chamado a cada bloco, na ordem; o primeiro bloco depois de `open` é o primeiro quadro da gravação. */
  onBlock: ((block: CaptureBlock) => void) | null
  /** Chamado se o dispositivo some ou o navegador encerra a captura (microfone desligado, aba suspensa). */
  onEnded: ((reason: string) => void) | null
  /** Os números de latência que o navegador informa neste momento. */
  latency(): BrowserLatency
  /** Liga ou desliga a escuta pelo fone (o som do microfone sai pelo alto-falante do computador). */
  setMonitor(on: boolean): void
  /** O relógio do contexto de áudio, em segundos. */
  contextNow(): number
  /** Converte um instante do contexto de áudio para o relógio da página (ms). */
  pageTime(contextTime: number): number
  /** Toca `samples` pelo alto-falante daqui a `afterSeconds`; devolve o instante do contexto em que o som começa. */
  playClick(samples: Float32Array, afterSeconds: number): number
  /** Solta o microfone e fecha o contexto. */
  close(): Promise<void>
}

export type CaptureFailure = 'unsupported' | 'denied' | 'not-found' | 'busy' | 'failed'

const MESSAGES: Record<CaptureFailure, string> = {
  unsupported: 'Este navegador não captura o som cru do microfone (faltam getUserMedia e AudioWorklet).',
  denied: 'Sem acesso ao microfone. Libere a permissão no navegador e tente de novo.',
  'not-found': 'Nenhum microfone foi encontrado neste computador, ou o escolhido foi desconectado.',
  busy: 'O microfone está em uso por outro programa. Feche-o e tente de novo.',
  failed: 'Não consegui abrir o microfone. Tente de novo ou escolha outro dispositivo.',
}

export class CaptureError extends Error {
  readonly reason: CaptureFailure

  constructor(reason: CaptureFailure) {
    super(MESSAGES[reason])
    this.name = 'CaptureError'
    this.reason = reason
  }
}

export interface CaptureEngine {
  isSupported(): boolean
  /** Lista as entradas. Os nomes só aparecem depois da primeira permissão. */
  listDevices(): Promise<InputDevice[]>
  open(settings: CaptureSettings): Promise<CaptureSession>
}

/** Frames por bloco do worklet: 2048 a 48 kHz são 43 ms, o bastante para o medidor andar suave sem sobrecarregar a página. */
export const BLOCK_FRAMES = 2048

/** O código do worklet, carregado por um endereço `blob:` para a captura não depender de um arquivo a mais no servidor. */
const WORKLET_SOURCE = `
class DmakerRecorder extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const config = options.processorOptions
    this.channels = config.channels
    this.size = config.block
    this.reset()
  }
  reset() {
    this.buffers = Array.from({ length: this.channels }, () => new Float32Array(this.size))
    this.filled = 0
    this.startedAt = 0
  }
  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) return true
    const frames = input[0].length
    if (this.filled === 0) this.startedAt = currentTime
    for (let channel = 0; channel < this.channels; channel += 1) {
      // um microfone mono alimenta os dois canais de uma gravação estéreo
      this.buffers[channel].set(input[Math.min(channel, input.length - 1)], this.filled)
    }
    this.filled += frames
    if (this.filled + frames > this.size) {
      const channels = this.buffers.map((buffer) => buffer.slice(0, this.filled))
      this.port.postMessage({ channels, contextTime: this.startedAt }, channels.map((buffer) => buffer.buffer))
      this.reset()
    }
    return true
  }
}
registerProcessor('dmaker-recorder', DmakerRecorder)
`

function failureOf(error: unknown): CaptureFailure {
  const name = typeof error === 'object' && error !== null && 'name' in error ? String(error.name) : ''
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') return 'denied'
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || name === 'OverconstrainedError') return 'not-found'
  if (name === 'NotReadableError' || name === 'TrackStartError' || name === 'AbortError') return 'busy'
  return 'failed'
}

export function createBrowserCapture(): CaptureEngine {
  const devices = () => (typeof navigator === 'undefined' ? undefined : navigator.mediaDevices)
  return {
    isSupported() {
      return (
        !!devices()?.getUserMedia &&
        typeof AudioContext !== 'undefined' &&
        typeof AudioWorkletNode !== 'undefined'
      )
    },

    async listDevices() {
      const media = devices()
      if (!media?.enumerateDevices) return []
      const all = await media.enumerateDevices()
      return all
        .filter((device) => device.kind === 'audioinput')
        .map((device, index) => ({ deviceId: device.deviceId, label: device.label || `Microfone ${index + 1}` }))
    },

    async open(settings) {
      const media = devices()
      if (!media?.getUserMedia || typeof AudioContext === 'undefined' || typeof AudioWorkletNode === 'undefined') {
        throw new CaptureError('unsupported')
      }
      let stream: MediaStream
      try {
        stream = await media.getUserMedia({
          audio: {
            ...(settings.deviceId ? { deviceId: { exact: settings.deviceId } } : {}),
            channelCount: settings.channels,
            sampleRate: settings.sampleRate,
            // o navegador "melhora" a voz por padrão; para gravar de verdade (e para clonar) tudo isso fica desligado
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          },
        })
      } catch (error) {
        throw new CaptureError(failureOf(error))
      }
      const context = new AudioContext({ sampleRate: settings.sampleRate, latencyHint: 'interactive' })
      const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'application/javascript' }))
      try {
        await context.audioWorklet.addModule(url)
        await context.resume()
      } catch {
        stream.getTracks().forEach((track) => track.stop())
        await context.close()
        throw new CaptureError('failed')
      } finally {
        URL.revokeObjectURL(url)
      }

      const source = context.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(context, 'dmaker-recorder', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { channels: settings.channels, block: BLOCK_FRAMES },
      })
      // o nó só é puxado pelo navegador se chega ao destino; o ganho zero mantém a saída muda
      const silence = context.createGain()
      silence.gain.value = 0
      source.connect(node)
      node.connect(silence).connect(context.destination)
      const monitor = context.createGain()
      monitor.gain.value = 0
      source.connect(monitor).connect(context.destination)

      const track = stream.getAudioTracks()[0]
      const session: CaptureSession = {
        rate: context.sampleRate,
        channels: settings.channels,
        deviceLabel: track?.label ?? '',
        deviceId: String(track?.getSettings().deviceId ?? settings.deviceId ?? ''),
        onBlock: null,
        onEnded: null,
        latency() {
          const reading = track?.getSettings() as (MediaTrackSettings & { latency?: number }) | undefined
          return {
            baseLatency: context.baseLatency,
            outputLatency: (context as AudioContext & { outputLatency?: number }).outputLatency,
            inputLatency: reading?.latency,
          }
        },
        setMonitor(on) {
          monitor.gain.value = on ? 1 : 0
        },
        contextNow: () => context.currentTime,
        pageTime(contextTime) {
          const stamp = context.getOutputTimestamp?.()
          if (stamp && stamp.performanceTime && stamp.contextTime !== undefined) {
            return stamp.performanceTime + (contextTime - stamp.contextTime) * 1000
          }
          return performance.now() - (context.currentTime - contextTime) * 1000
        },
        playClick(samples, afterSeconds) {
          const buffer = context.createBuffer(1, samples.length, context.sampleRate)
          buffer.copyToChannel(samples as Float32Array<ArrayBuffer>, 0)
          const player = context.createBufferSource()
          player.buffer = buffer
          player.connect(context.destination)
          const when = context.currentTime + afterSeconds
          player.start(when)
          return when
        },
        async close() {
          node.port.onmessage = null
          track?.removeEventListener('ended', ended)
          stream.getTracks().forEach((each) => each.stop())
          await context.close().catch(() => undefined)
        },
      }
      const ended = () => session.onEnded?.('O microfone foi desligado ou desconectado.')
      track?.addEventListener('ended', ended)
      node.port.onmessage = (event: MessageEvent<{ channels: Float32Array[]; contextTime: number }>) => {
        session.onBlock?.({
          channels: event.data.channels,
          contextTime: event.data.contextTime,
          receivedAtMs: performance.now(),
        })
      }
      return session
    },
  }
}

let engineFactory: () => CaptureEngine = createBrowserCapture

/** Troca a captura (os testes entregam uma falsa); sem argumento volta à do navegador. */
export function useCaptureEngine(next?: () => CaptureEngine): void {
  engineFactory = next ?? createBrowserCapture
}

export function captureEngine(): CaptureEngine {
  return engineFactory()
}

export { MESSAGES as CAPTURE_MESSAGES }
