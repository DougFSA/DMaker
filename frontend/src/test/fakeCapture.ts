/* Apoio dos testes da gravação: um microfone de mentira no lugar do `getUserMedia` + AudioWorklet (o jsdom não tem Web Audio
   e o navegador embutido não tem microfone). O teste empurra blocos de som sintético e vê o que a gravação faz com eles. */
import type { CaptureBlock, CaptureEngine, CaptureSession, CaptureSettings, InputDevice } from '@/lib/recordingCapture'
import type { BrowserLatency } from '@/lib/recordingLatency'
import { BLOCK_FRAMES } from '@/lib/recordingCapture'

export const FAKE_RATE = 48000

export class FakeSession implements CaptureSession {
  rate = FAKE_RATE
  channels: number
  deviceLabel = 'Microfone de teste'
  deviceId: string
  onBlock: ((block: CaptureBlock) => void) | null = null
  onEnded: ((reason: string) => void) | null = null
  closed = false
  monitoring = false
  clicks: Array<{ samples: Float32Array; at: number }> = []
  /** O relógio do contexto: avança com os blocos empurrados. */
  private clock = 0
  /** O relógio da página (ms) quando o contexto marcava zero. */
  pageOrigin = 0
  latencyReading: BrowserLatency = { baseLatency: 0.01, outputLatency: 0.04, inputLatency: 0.02 }

  constructor(settings: CaptureSettings) {
    this.channels = settings.channels
    this.deviceId = settings.deviceId ?? ''
  }

  latency(): BrowserLatency {
    return this.latencyReading
  }

  setMonitor(on: boolean): void {
    this.monitoring = on
  }

  contextNow(): number {
    return this.clock
  }

  pageTime(contextTime: number): number {
    return this.pageOrigin + contextTime * 1000
  }

  playClick(samples: Float32Array, afterSeconds: number): number {
    const at = this.clock + afterSeconds
    this.clicks.push({ samples, at })
    return at
  }

  async close(): Promise<void> {
    this.closed = true
  }

  /** Entrega um bloco de som (um array por canal) como se o worklet o tivesse mandado; `atMs` é o relógio da página. */
  push(channels: Float32Array[], atMs?: number): void {
    const block: CaptureBlock = {
      channels,
      contextTime: this.clock,
      receivedAtMs: atMs ?? this.pageTime(this.clock),
    }
    this.clock += (channels[0]?.length ?? 0) / this.rate
    this.onBlock?.(block)
  }

  /** Um bloco de `BLOCK_FRAMES` quadros com o valor constante `level` (linear) em todos os canais. */
  pushLevel(level: number, atMs?: number): void {
    this.push(
      Array.from({ length: this.channels }, () => new Float32Array(BLOCK_FRAMES).fill(level)),
      atMs,
    )
  }

  /** Empurra `seconds` de som no nível dado, bloco a bloco. */
  pushSeconds(seconds: number, level: number): void {
    const blocks = Math.round((seconds * this.rate) / BLOCK_FRAMES)
    for (let index = 0; index < blocks; index += 1) this.pushLevel(level)
  }
}

export interface FakeEngine extends CaptureEngine {
  sessions: FakeSession[]
  devices: InputDevice[]
  failWith: Error | null
}

export function fakeEngine(): FakeEngine {
  const engine: FakeEngine = {
    sessions: [],
    devices: [
      { deviceId: 'mic-a', label: 'Microfone A' },
      { deviceId: 'mic-b', label: 'Microfone B' },
    ],
    failWith: null,
    isSupported: () => true,
    listDevices: async () => engine.devices,
    open: async (settings) => {
      if (engine.failWith) throw engine.failWith
      const session = new FakeSession(settings)
      engine.sessions.push(session)
      return session
    },
  }
  return engine
}
