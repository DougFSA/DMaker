import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  BLOCK_SECONDS,
  cutPreviewSegments,
  levelDb,
  measureBlock,
  meterFraction,
  METER_FLOOR_DB,
  PanelEngine,
  planSlices,
  type WavAnalyser,
  type WavAudioContext,
  type WavBuffer,
  type WavGain,
  type WavNode,
  type WavParam,
  type WavSource,
} from './audioPlayback'

class FakeParam implements WavParam {
  value = 1
  setValueAtTime(): this {
    return this
  }
  linearRampToValueAtTime(): this {
    return this
  }
  cancelScheduledValues(): this {
    return this
  }
}

class FakeNode implements WavNode {
  connect(): void {}
  disconnect(): void {}
}

class FakeGain extends FakeNode implements WavGain {
  readonly gain = new FakeParam()
}

class FakeAnalyser extends FakeNode implements WavAnalyser {
  fftSize = 1024
  fill = 0
  getFloatTimeDomainData(target: Float32Array): void {
    target.fill(this.fill)
  }
}

class FakeSource extends FakeNode implements WavSource {
  buffer: WavBuffer | null = null
  readonly playbackRate = new FakeParam()
  onended: (() => void) | null = null
  started: Array<{ when?: number; offset?: number; duration?: number }> = []
  stopped = 0
  start(when?: number, offset?: number, duration?: number): void {
    this.started.push({ when, offset, duration })
  }
  stop(): void {
    this.stopped += 1
  }
}

class FakeContext implements WavAudioContext {
  currentTime = 0
  readonly destination = {}
  readonly sources: FakeSource[] = []
  readonly analysers: FakeAnalyser[] = []
  resumed = 0
  createGain = () => new FakeGain()
  createBufferSource(): FakeSource {
    const source = new FakeSource()
    this.sources.push(source)
    return source
  }
  createAnalyser(): FakeAnalyser {
    const analyser = new FakeAnalyser()
    this.analysers.push(analyser)
    return analyser
  }
  createChannelSplitter = () => new FakeNode()
  async decodeAudioData(bytes: ArrayBuffer): Promise<WavBuffer> {
    return { duration: Number(new TextDecoder().decode(bytes)) }
  }
  async resume(): Promise<void> {
    this.resumed += 1
  }
}

const bytes = (seconds: number): ArrayBuffer => {
  const encoded = new TextEncoder().encode(String(seconds))
  return encoded.buffer.slice(encoded.byteOffset, encoded.byteOffset + encoded.byteLength) as ArrayBuffer
}

describe('o plano de pedaços', () => {
  it('corta cada trecho nas fronteiras de bloco', () => {
    expect(planSlices([[6, 20]], 100, 8)).toEqual([
      { block: 0, from: 6, to: 8 },
      { block: 1, from: 8, to: 16 },
      { block: 2, from: 16, to: 20 },
    ])
  })

  it('limita ao áudio e descarta trecho vazio', () => {
    expect(planSlices([[95, 120]], 100, 8)).toEqual([
      { block: 11, from: 95, to: 96 },
      { block: 12, from: 96, to: 100 },
    ])
    expect(planSlices([[10, 10], [-5, -1]], 100, 8)).toEqual([])
  })

  it('a prévia do corte toca 2 s antes e 2 s depois, pulando a seleção', () => {
    expect(cutPreviewSegments({ start: 10, end: 14 }, 60)).toEqual([
      [8, 10],
      [14, 16],
    ])
    expect(cutPreviewSegments({ start: 1, end: 59 }, 60)).toEqual([
      [0, 1],
      [59, 60],
    ])
    expect(cutPreviewSegments({ start: 0, end: 5 }, 60)).toEqual([[5, 7]])
    expect(cutPreviewSegments({ start: 55, end: 60 }, 60)).toEqual([[53, 55]])
  })
})

describe('o medidor', () => {
  it('mede pico e valor eficaz e passa para dB com piso', () => {
    const block = new Float32Array([0.5, -0.5, 0.5, -0.5])
    expect(measureBlock(block)).toEqual({ peak: 0.5, rms: 0.5 })
    expect(levelDb(0.5)).toBeCloseTo(-6.02, 1)
    expect(levelDb(0)).toBe(METER_FLOOR_DB)
    expect(levelDb(1e-9)).toBe(METER_FLOOR_DB)
    expect(measureBlock(new Float32Array())).toEqual({ peak: 0, rms: 0 })
  })

  it('põe o nível na barra entre o piso e 0 dBFS', () => {
    expect(meterFraction(0)).toBe(1)
    expect(meterFraction(-30)).toBe(0.5)
    expect(meterFraction(-90)).toBe(0)
    expect(meterFraction(6)).toBe(1)
  })
})

describe('o motor de reprodução', () => {
  let context: FakeContext
  let fetched: Array<[number, number]>
  let ended: number

  /** Adianta o relógio do contexto e deixa o laço de reposição rodar uma vez, como o tempo passando. */
  async function advance(clock: number): Promise<void> {
    context.currentTime = clock
    await vi.advanceTimersByTimeAsync(100)
  }

  function engine(duration = 100): PanelEngine {
    return new PanelEngine({
      createContext: () => context,
      fetchBlock: async (start, end) => {
        fetched.push([start, end])
        return bytes(end - start)
      },
      duration: () => duration,
      onEnded: () => {
        ended += 1
      },
    })
  }

  beforeEach(() => {
    vi.useFakeTimers()
    context = new FakeContext()
    fetched = []
    ended = 0
  })
  afterEach(() => vi.useRealTimers())

  it('toca exatamente o trecho pedido: um bloco, o ponto de entrada e a duração', async () => {
    const player = engine()
    await player.play([[10, 13]], { loop: false, rate: 1 })
    const source = context.sources[0] as FakeSource
    expect(fetched).toEqual([[8, 16]])
    expect(source.started).toHaveLength(1)
    const call = source.started[0] as { when: number; offset: number; duration: number }
    expect(call.offset).toBe(2) // 10 s dentro do bloco que começa em 8 s
    expect(call.duration).toBe(3)
    expect(call.when).toBeGreaterThan(0)
    player.dispose()
  })

  it('emenda os blocos sem lacuna no relógio do contexto', async () => {
    const player = engine()
    await player.play([[6, 20]], { loop: false, rate: 1 })
    await advance(1) // falta menos de 1,5 s para o primeiro pedaço acabar: o motor agenda o segundo
    await advance(9) // e, perto do fim do segundo, o terceiro
    const starts = context.sources.map((source) => source.started[0] as { when: number; duration: number })
    expect(starts).toHaveLength(3)
    expect(starts[1]?.when).toBeCloseTo((starts[0]?.when ?? 0) + (starts[0]?.duration ?? 0))
    expect(starts[2]?.when).toBeCloseTo((starts[1]?.when ?? 0) + (starts[1]?.duration ?? 0))
    player.dispose()
  })

  it('em loop volta ao começo da seleção na mesma amostra em que o fim chega', async () => {
    const player = engine()
    await player.play([[10, 11]], { loop: true, rate: 1 })
    await advance(0.2)
    const first = context.sources[0]?.started[0] as { when: number; offset: number; duration: number }
    const second = context.sources[1]?.started[0] as { when: number; offset: number; duration: number }
    expect(second.offset).toBe(first.offset)
    expect(second.when).toBeCloseTo(first.when + first.duration)
    // com 1,5 s de folga à frente, a seleção de 1 s se repete mais de uma vez
    expect(context.sources.length).toBeGreaterThanOrEqual(2)
    player.dispose()
  })

  it('a velocidade encurta ou alonga o trecho no relógio sem mudar o que é lido', async () => {
    const player = engine()
    await player.play([[10, 12]], { loop: false, rate: 2 })
    const source = context.sources[0] as FakeSource
    expect(source.playbackRate.value).toBe(2)
    const call = source.started[0] as { duration: number }
    expect(call.duration).toBe(2) // o trecho lido continua sendo de 2 s do arquivo
    expect(player.position()).toBeCloseTo(10)
    context.currentTime = (source.started[0]?.when ?? 0) + 0.5 // meio segundo de relógio a 2x = 1 s do eixo
    expect(player.position()).toBeCloseTo(11, 1)
    player.dispose()
  })

  it('toca a prévia do corte como dois trechos seguidos', async () => {
    const player = engine()
    await player.play(cutPreviewSegments({ start: 10, end: 14 }, 100), { loop: false, rate: 1 })
    await advance(1)
    const calls = context.sources.map((source) => source.started[0] as { when: number; offset: number; duration: number })
    expect(calls).toHaveLength(2)
    expect(calls[0]).toMatchObject({ offset: 0, duration: 2 }) // 8 a 10 s, do bloco que começa em 8
    expect(calls[1]).toMatchObject({ offset: 6, duration: 2 }) // 14 a 16 s, do mesmo bloco
    expect(calls[1]?.when).toBeCloseTo((calls[0]?.when ?? 0) + 2)
    player.dispose()
  })

  it('termina sozinho depois do último trecho e avisa uma vez', async () => {
    const player = engine()
    await player.play([[0, 1]], { loop: false, rate: 1 })
    await advance(0.5)
    expect(ended).toBe(0)
    await advance(5)
    expect(ended).toBe(1)
    expect(player.playing).toBe(false)
    expect(player.position()).toBeCloseTo(1, 1)
  })

  it('parar guarda onde parou e solta os nós', async () => {
    const player = engine()
    await player.play([[0, 4]], { loop: false, rate: 1 })
    const source = context.sources[0] as FakeSource
    context.currentTime = (source.started[0]?.when ?? 0) + 1.5
    player.stop()
    expect(source.stopped).toBe(1)
    expect(player.playing).toBe(false)
    expect(player.position()).toBeCloseTo(1.5, 1)
  })

  it('reaproveita os blocos já baixados e os esquece quando o som muda', async () => {
    const player = engine()
    await player.play([[1, 2]], { loop: false, rate: 1 })
    player.stop()
    await player.play([[3, 4]], { loop: false, rate: 1 })
    expect(fetched).toHaveLength(1)
    player.invalidate()
    player.stop()
    await player.play([[3, 4]], { loop: false, rate: 1 })
    expect(fetched).toHaveLength(2)
    player.dispose()
  })

  it('o scrub toca um pedaço curto no instante pedido e descarta o anterior que ainda não chegou', async () => {
    const player = engine()
    await player.scrub(20.5)
    const source = context.sources[0] as FakeSource
    const call = source.started[0] as { offset: number; duration: number }
    expect(call.offset).toBeCloseTo(4.5) // bloco que começa em 16 s
    expect(call.duration).toBeCloseTo(0.12)
    expect(fetched).toEqual([[16, 24]])
    await player.scrub(21)
    expect(source.stopped).toBe(1) // o pedaço anterior foi calado
    player.endScrub()
    player.dispose()
  })

  it('lê o nível de cada canal e marca o clipping', async () => {
    const player = engine()
    await player.play([[0, 1]], { loop: false, rate: 1 })
    expect(context.analysers).toHaveLength(2)
    ;(context.analysers[0] as FakeAnalyser).fill = 1
    ;(context.analysers[1] as FakeAnalyser).fill = 0.1
    const [left, right] = player.levels()
    expect(left?.clipped).toBe(true)
    expect(right?.clipped).toBe(false)
    expect(right?.peakDb).toBeCloseTo(-20)
    player.dispose()
  })

  it('o bloco tem o tamanho documentado', () => {
    expect(BLOCK_SECONDS).toBe(8)
  })
})
