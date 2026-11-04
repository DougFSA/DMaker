/* A reprodução do painel Áudio pela Web Audio do navegador: tocar uma seleção (em loop ou não), o trecho em volta de um
   corte, o scrub e a velocidade, sem baixar o áudio inteiro. O som vem do servidor em blocos curtos (WAV de poucos
   segundos, "como soa", com os efeitos), que viram `AudioBuffer`; o motor agenda os pedaços um depois do outro no relógio
   do contexto, então a emenda de um bloco com o seguinte, e a volta do loop, caem na mesma amostra. O motor não conhece
   Vue nem o servidor: o contexto de áudio e a busca de blocos entram por injeção (e os testes põem um contexto falso). */

/** O pedaço do contexto de áudio que o motor usa (o `AudioContext` do navegador serve; os testes põem um falso). */
export interface WavParam {
  value: number
  setValueAtTime(value: number, time: number): unknown
  linearRampToValueAtTime(value: number, time: number): unknown
  cancelScheduledValues(time: number): unknown
}

export interface WavBuffer {
  readonly duration: number
}

export interface WavNode {
  connect(destination: unknown, output?: number, input?: number): unknown
  disconnect(): void
}

export interface WavSource extends WavNode {
  buffer: WavBuffer | null
  loop?: boolean
  readonly playbackRate: WavParam
  onended: ((event: Event) => unknown) | null
  start(when?: number, offset?: number, duration?: number): void
  stop(when?: number): void
}

export interface WavGain extends WavNode {
  readonly gain: WavParam
}

export interface WavAnalyser extends WavNode {
  fftSize: number
  getFloatTimeDomainData(target: Float32Array<ArrayBuffer>): void
}

export interface WavAudioContext {
  readonly currentTime: number
  readonly destination: unknown
  createGain(): WavGain
  createBufferSource(): WavSource
  createAnalyser(): WavAnalyser
  createChannelSplitter(outputs: number): WavNode
  decodeAudioData(bytes: ArrayBuffer): Promise<WavBuffer>
  resume(): Promise<void>
  close?(): Promise<void>
}

/** Um trecho do eixo a tocar, de `start` a `end` (segundos). */
export type Segment = readonly [number, number]

/** Os segundos de cada bloco pedido ao servidor: curto para o scrub e o primeiro som chegarem logo, longo o bastante
 *  para uma hora de áudio não virar centenas de pedidos. */
export const BLOCK_SECONDS = 8
/** Quanto som já agendado o motor quer à frente do relógio; o laço de reposição roda a cada `PUMP_MS`. */
const SCHEDULE_AHEAD = 1.5
const PUMP_MS = 100
/** A folga entre o clique e o primeiro som, para o primeiro pedaço entrar inteiro no relógio. */
const START_LEAD = 0.04
/** A duração e a rampa de um pedaço de scrub: curto para acompanhar o mouse, com rampa para não estalar. */
export const SCRUB_SECONDS = 0.12
const SCRUB_RAMP = 0.008
/** Quantos blocos decodificados o motor guarda (cada um tem uns 1,5 MB por segundo de estéreo a 48 kHz em float). */
const KEEP_BLOCKS = 12
export const PREVIEW_CONTEXT_SECONDS = 2

export interface Slice {
  block: number
  from: number
  to: number
}

/** Os pedaços de cada trecho cortados nas fronteiras de bloco: cada um sai de um bloco só. */
export function planSlices(segments: readonly Segment[], duration: number, blockSeconds = BLOCK_SECONDS): Slice[] {
  const slices: Slice[] = []
  for (const [rawStart, rawEnd] of segments) {
    const start = Math.max(rawStart, 0)
    const end = Math.min(rawEnd, duration)
    if (end <= start) continue
    for (let block = Math.floor(start / blockSeconds); block * blockSeconds < end; block += 1) {
      const from = Math.max(start, block * blockSeconds)
      const to = Math.min(end, (block + 1) * blockSeconds)
      if (to - from > 1e-6) slices.push({ block, from, to })
    }
  }
  return slices
}

/** Os trechos da "prévia do corte" (Play cut preview): `context` segundos antes da seleção e depois dela, pulando a seleção. */
export function cutPreviewSegments(selection: { start: number; end: number }, duration: number, context = PREVIEW_CONTEXT_SECONDS): Segment[] {
  const segments: Segment[] = []
  if (selection.start > 0) segments.push([Math.max(selection.start - context, 0), selection.start])
  if (selection.end < duration) segments.push([selection.end, Math.min(selection.end + context, duration)])
  return segments
}

/* ---------- medidor ---------- */

export const METER_FLOOR_DB = -60

/** O nível linear em dB, com o piso do medidor para o silêncio. */
export function levelDb(linear: number): number {
  return linear > 0 ? Math.max(METER_FLOOR_DB, 20 * Math.log10(linear)) : METER_FLOOR_DB
}

/** Pico e valor eficaz (lineares) de um bloco de amostras. */
export function measureBlock(samples: Float32Array): { peak: number; rms: number } {
  let peak = 0
  let sum = 0
  for (const value of samples) {
    const magnitude = Math.abs(value)
    if (magnitude > peak) peak = magnitude
    sum += value * value
  }
  return { peak, rms: samples.length > 0 ? Math.sqrt(sum / samples.length) : 0 }
}

/** Onde o nível cai na barra do medidor (0 no piso, 1 em 0 dBFS). */
export function meterFraction(db: number): number {
  return Math.min(1, Math.max(0, (db - METER_FLOOR_DB) / -METER_FLOOR_DB))
}

export interface MeterReading {
  peakDb: number
  rmsDb: number
  /** O pico chegou a 0 dBFS ou passou: o som clipa. */
  clipped: boolean
}

/* ---------- o motor ---------- */

interface Scheduled {
  when: number
  /** Quanto dura no relógio do contexto (a duração do trecho dividida pela velocidade). */
  length: number
  from: number
  rate: number
}

export interface EngineOptions {
  createContext: () => WavAudioContext
  /** O som do trecho [start, end) do eixo, em WAV. */
  fetchBlock: (start: number, end: number) => Promise<ArrayBuffer>
  /** A duração do eixo, em segundos. */
  duration: () => number
  blockSeconds?: number
  onEnded?: () => void
}

export interface PlayOptions {
  loop: boolean
  /** A velocidade (1 é a normal). Como numa fita, mudá-la muda também o tom. */
  rate: number
}

export class PanelEngine {
  private context: WavAudioContext | null = null
  private master: WavGain | null = null
  private analysers: WavAnalyser[] = []
  private readonly blocks = new Map<number, Promise<WavBuffer>>()
  private sources: WavSource[] = []
  private schedule: Scheduled[] = []
  private token = 0
  private scrubToken = 0
  private timer: ReturnType<typeof setInterval> | null = null
  private scrubSource: { source: WavSource; gain: WavGain } | null = null
  private lastPosition: number | null = null
  private buffers: Float32Array<ArrayBuffer>[] = []

  constructor(private readonly options: EngineOptions) {}

  private get blockSeconds(): number {
    return this.options.blockSeconds ?? BLOCK_SECONDS
  }

  get playing(): boolean {
    return this.timer !== null
  }

  private ensureContext(): WavAudioContext {
    return this.graph().context
  }

  /** O contexto e o ganho geral, criados na primeira vez que alguém precisa (o navegador só deixa tocar depois de um gesto). */
  private graph(): { context: WavAudioContext; master: WavGain } {
    if (this.context && this.master) return { context: this.context, master: this.master }
    const context = this.options.createContext()
    const master = context.createGain()
    master.connect(context.destination)
    const splitter = context.createChannelSplitter(2)
    master.connect(splitter)
    this.analysers = [0, 1].map((channel) => {
      const analyser = context.createAnalyser()
      analyser.fftSize = 1024
      splitter.connect(analyser, channel)
      return analyser
    })
    this.buffers = this.analysers.map(() => new Float32Array(new ArrayBuffer(1024 * 4)))
    this.context = context
    this.master = master
    return { context, master }
  }

  /** O som foi mudado (um efeito, um corte): os blocos guardados valem para o som de antes. */
  invalidate(): void {
    this.blocks.clear()
  }

  private block(index: number): Promise<WavBuffer> {
    const cached = this.blocks.get(index)
    if (cached) {
      // o mais recente vai para o fim, e os mais antigos saem primeiro
      this.blocks.delete(index)
      this.blocks.set(index, cached)
      return cached
    }
    const start = index * this.blockSeconds
    const end = Math.min(start + this.blockSeconds, this.options.duration())
    const context = this.ensureContext()
    const pending = this.options
      .fetchBlock(start, end)
      .then((bytes) => context.decodeAudioData(bytes))
      .catch((error: unknown) => {
        this.blocks.delete(index)
        throw error
      })
    this.blocks.set(index, pending)
    while (this.blocks.size > KEEP_BLOCKS) {
      const oldest = this.blocks.keys().next().value
      if (oldest === undefined) break
      this.blocks.delete(oldest)
    }
    return pending
  }

  /** Começa a buscar o bloco de um instante (o scrub e o Espaço ficam mais ágeis com ele já a caminho). */
  prefetch(time: number): void {
    void this.block(Math.floor(Math.max(time, 0) / this.blockSeconds)).catch(() => undefined)
  }

  /** Toca os `segments` em sequência; com `loop`, volta ao primeiro quando o último acaba, sem emenda. */
  async play(segments: readonly Segment[], options: PlayOptions): Promise<void> {
    this.stop()
    const slices = planSlices(segments, this.options.duration(), this.blockSeconds)
    if (slices.length === 0) return
    const token = ++this.token
    const { context, master } = this.graph()
    await context.resume()
    if (token !== this.token) return
    const rate = Math.min(4, Math.max(0.25, options.rate))
    let when = context.currentTime + START_LEAD
    let next = 0
    let pumping = false
    let finishedAt: number | null = null
    this.lastPosition = slices[0]?.from ?? null

    const pump = async (): Promise<void> => {
      if (pumping || token !== this.token) return
      pumping = true
      try {
        while (token === this.token && finishedAt === null && when - context.currentTime < SCHEDULE_AHEAD) {
          if (!options.loop && next >= slices.length) {
            finishedAt = when
            break
          }
          const slice = slices[next % slices.length] as Slice
          const buffer = await this.block(slice.block)
          if (token !== this.token) return
          const source = context.createBufferSource()
          source.buffer = buffer
          source.playbackRate.value = rate
          source.connect(master)
          const length = (slice.to - slice.from) / rate
          source.start(when, slice.from - slice.block * this.blockSeconds, slice.to - slice.from)
          source.onended = () => {
            this.sources = this.sources.filter((candidate) => candidate !== source)
            source.disconnect()
          }
          this.sources.push(source)
          this.schedule.push({ when, length, from: slice.from, rate })
          // só os dois últimos trechos agendados dizem onde a reprodução está; os antigos de um loop longo saem
          if (this.schedule.length > 4) this.schedule.splice(0, this.schedule.length - 4)
          when += length
          next += 1
        }
      } catch {
        if (token === this.token) this.finish(token)
      } finally {
        pumping = false
      }
      if (finishedAt !== null && context.currentTime >= finishedAt) this.finish(token)
    }

    this.timer = setInterval(() => void pump(), PUMP_MS)
    await pump()
  }

  private finish(token: number): void {
    if (token !== this.token) return
    this.stop()
    this.options.onEnded?.()
  }

  /** Para tudo; a posição de quando parou fica em `position()` até o próximo `play`. */
  stop(): void {
    const stopped = this.position()
    if (stopped !== null) this.lastPosition = stopped
    this.token += 1
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    for (const source of this.sources) {
      source.onended = null
      try {
        source.stop()
      } catch {
        // o nó já terminou de tocar
      }
      source.disconnect()
    }
    this.sources = []
    this.schedule = []
  }

  /** O instante do eixo que está tocando agora, ou, parado, onde parou. Nulo antes de qualquer reprodução. */
  position(): number | null {
    const context = this.context
    if (!context || this.schedule.length === 0) return this.lastPosition
    const now = context.currentTime
    for (let index = this.schedule.length - 1; index >= 0; index -= 1) {
      const slice = this.schedule[index] as Scheduled
      if (now >= slice.when) return slice.from + Math.min(now - slice.when, slice.length) * slice.rate
    }
    return this.lastPosition
  }

  /** Toca um pedaço curto no instante `time` (o scrub). Pedir outro antes de o bloco chegar descarta o anterior. */
  async scrub(time: number, rate = 1): Promise<void> {
    const duration = this.options.duration()
    if (duration <= 0) return
    const instant = Math.min(Math.max(time, 0), duration)
    const token = ++this.scrubToken
    const buffer = await this.block(Math.floor(instant / this.blockSeconds))
    if (token !== this.scrubToken || this.playing) return
    const { context, master } = this.graph()
    await context.resume()
    if (token !== this.scrubToken) return
    this.silenceScrub()
    const gain = context.createGain()
    const source = context.createBufferSource()
    const now = context.currentTime
    const offset = instant - Math.floor(instant / this.blockSeconds) * this.blockSeconds
    const length = Math.min(SCRUB_SECONDS, Math.max(buffer.duration - offset, 0))
    if (length <= 0) return
    source.buffer = buffer
    source.playbackRate.value = rate
    gain.gain.setValueAtTime(0, now)
    gain.gain.linearRampToValueAtTime(1, now + SCRUB_RAMP)
    gain.gain.setValueAtTime(1, now + Math.max(length / rate - SCRUB_RAMP, SCRUB_RAMP))
    gain.gain.linearRampToValueAtTime(0, now + length / rate)
    source.connect(gain)
    gain.connect(master)
    source.start(now, offset, length)
    this.scrubSource = { source, gain }
    this.lastPosition = instant
  }

  private silenceScrub(): void {
    const previous = this.scrubSource
    this.scrubSource = null
    if (!previous) return
    try {
      previous.source.stop()
    } catch {
      // já tinha acabado
    }
    previous.source.disconnect()
    previous.gain.disconnect()
  }

  /** Larga o scrub em andamento (o botão do mouse foi solto). */
  endScrub(): void {
    this.scrubToken += 1
    this.silenceScrub()
  }

  /** O nível do que está soando agora, por canal (esquerdo e direito); vazio se nada tocou ainda. */
  levels(): MeterReading[] {
    return this.analysers.map((analyser, channel) => {
      const buffer = this.buffers[channel]
      if (!buffer) return { peakDb: METER_FLOOR_DB, rmsDb: METER_FLOOR_DB, clipped: false }
      analyser.getFloatTimeDomainData(buffer)
      const { peak, rms } = measureBlock(buffer)
      return { peakDb: levelDb(peak), rmsDb: levelDb(rms), clipped: peak >= 0.999 }
    })
  }

  dispose(): void {
    this.stop()
    this.endScrub()
    this.blocks.clear()
    void this.context?.close?.()
    this.context = null
    this.master = null
    this.analysers = []
  }
}
