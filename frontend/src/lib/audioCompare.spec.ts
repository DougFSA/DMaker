import { describe, expect, it } from 'vitest'
import { ComparePlayer } from './audioCompare'
import type { WavAnalyser, WavAudioContext, WavBuffer, WavGain, WavNode, WavParam, WavSource } from './audioPlayback'

class Param implements WavParam {
  value = 1
  history: Array<[number, number]> = []
  setValueAtTime(value: number, time: number): this {
    this.value = value
    this.history.push([value, time])
    return this
  }
  linearRampToValueAtTime(): this {
    return this
  }
  cancelScheduledValues(): this {
    return this
  }
}

class Node implements WavNode {
  connect(): void {}
  disconnect(): void {}
}

class Gain extends Node implements WavGain {
  readonly gain = new Param()
}

class Source extends Node implements WavSource {
  buffer: WavBuffer | null = null
  loop = false
  readonly playbackRate = new Param()
  onended: (() => void) | null = null
  starts: Array<number | undefined> = []
  stopped = 0
  start(when?: number): void {
    this.starts.push(when)
  }
  stop(): void {
    this.stopped += 1
  }
}

class Context implements WavAudioContext {
  currentTime = 0
  readonly destination = {}
  readonly gains: Gain[] = []
  readonly sources: Source[] = []
  createGain(): Gain {
    const gain = new Gain()
    this.gains.push(gain)
    return gain
  }
  createBufferSource(): Source {
    const source = new Source()
    this.sources.push(source)
    return source
  }
  createAnalyser(): WavAnalyser {
    throw new Error('não usado')
  }
  createChannelSplitter(): WavNode {
    return new Node()
  }
  async decodeAudioData(bytes: ArrayBuffer): Promise<WavBuffer> {
    return { duration: bytes.byteLength / 10 }
  }
  async resume(): Promise<void> {}
}

const bytes = (seconds: number): ArrayBuffer => new ArrayBuffer(seconds * 10)

describe('o antes e depois', () => {
  it('toca os dois lados ao mesmo tempo, em loop, e só um deles soa', async () => {
    const context = new Context()
    const player = new ComparePlayer(() => context)
    await player.load(bytes(3), bytes(3))
    await player.play('after')
    expect(context.sources).toHaveLength(2)
    expect(context.sources.every((source) => source.loop && source.starts[0] === 0)).toBe(true)
    expect(context.gains.map((gain) => gain.gain.value)).toEqual([0, 1]) // antes calado, depois soando
    expect(player.playing).toBe(true)
  })

  it('trocar de lado não reinicia o som: só muda os ganhos', async () => {
    const context = new Context()
    const player = new ComparePlayer(() => context)
    await player.load(bytes(3), bytes(3))
    await player.play('before')
    context.currentTime = 1.25
    player.switchTo('after')
    expect(context.sources.map((source) => source.stopped)).toEqual([0, 0])
    expect(context.gains.map((gain) => gain.gain.value)).toEqual([0, 1])
    expect(player.side).toBe('after')
    expect(player.position()).toBeCloseTo(1.25)
    context.currentTime = 3.5
    expect(player.position()).toBeCloseTo(0.5) // a volta do loop
  })

  it('parar solta os nós, e carregar de novo para o que estava tocando', async () => {
    const context = new Context()
    const player = new ComparePlayer(() => context)
    await player.load(bytes(2), bytes(2))
    await player.play('before')
    await player.load(bytes(2), bytes(4))
    expect(context.sources.map((source) => source.stopped)).toEqual([1, 1])
    expect(player.playing).toBe(false)
    expect(player.loaded).toBe(true)
  })
})
