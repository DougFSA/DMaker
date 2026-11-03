/* Apoio dos testes da prévia ao vivo: um AudioContext de mentira que só registra o que foi agendado, com o relógio
   (`currentTime`) na mão do teste. */
import type { LiveAudioContext, LiveBuffer, LiveGain, LiveParam, LiveSource } from '@/lib/livePlayer'

type ParamEvent = ['set' | 'ramp', number, number]

export class FakeParam implements LiveParam {
  value = 1
  events: ParamEvent[] = []

  setValueAtTime(value: number, time: number): this {
    this.events.push(['set', value, time])
    return this
  }

  linearRampToValueAtTime(value: number, time: number): this {
    this.events.push(['ramp', value, time])
    return this
  }

  cancelScheduledValues(): this {
    return this
  }
}

export class FakeGain implements LiveGain {
  readonly gain = new FakeParam()
  disconnected = false

  connect(): void {}

  disconnect(): void {
    this.disconnected = true
  }
}

export class FakeSource implements LiveSource {
  buffer: LiveBuffer | null = null
  onended: (() => void) | null = null
  startedAt: number | null = null
  stoppedAt: number | null = null
  /** Faz `stop` lançar, como o nó que já terminou de tocar. */
  throwOnStop = false

  connect(): void {}

  start(when: number): void {
    this.startedAt = when
  }

  stop(when: number): void {
    if (this.throwOnStop) throw new Error('o nó já terminou')
    this.stoppedAt = when
  }
}

export class FakeAudioContext implements LiveAudioContext {
  static instances: FakeAudioContext[] = []
  currentTime: number
  readonly destination = {}
  readonly gains: FakeGain[] = []
  readonly sources: FakeSource[] = []
  resumed = 0
  /** O que `decodeAudioData` devolve para os bytes recebidos; o padrão é 1 s de áudio. */
  decode: (bytes: ArrayBuffer) => Promise<LiveBuffer> = async () => ({ duration: 1 })

  constructor(startTime = 0) {
    this.currentTime = startTime
    FakeAudioContext.instances.push(this)
  }

  static reset(): void {
    FakeAudioContext.instances = []
  }

  static latest(): FakeAudioContext {
    const context = FakeAudioContext.instances.at(-1)
    if (!context) throw new Error('nenhum AudioContext criado')
    return context
  }

  createGain(): FakeGain {
    const gain = new FakeGain()
    this.gains.push(gain)
    return gain
  }

  createBufferSource(): FakeSource {
    const source = new FakeSource()
    this.sources.push(source)
    return source
  }

  decodeAudioData(bytes: ArrayBuffer): Promise<LiveBuffer> {
    return this.decode(bytes)
  }

  async resume(): Promise<void> {
    this.resumed += 1
  }
}

/** O mesmo contexto falso com a duração de cada fala vinda do texto dos bytes ("1.5" é 1,5 s). */
export function contextWithDurations(startTime = 0): FakeAudioContext {
  const context = new FakeAudioContext(startTime)
  context.decode = async (bytes) => ({ duration: Number(new TextDecoder().decode(bytes)) || 1 })
  return context
}

/** Bytes que `contextWithDurations` lê como a duração da fala. */
export function bytesOf(duration: number): ArrayBuffer {
  const encoded = new TextEncoder().encode(String(duration))
  return encoded.buffer.slice(encoded.byteOffset, encoded.byteOffset + encoded.byteLength) as ArrayBuffer
}
