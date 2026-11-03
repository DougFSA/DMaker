import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { bytesOf, contextWithDurations, FakeAudioContext } from '@/test/audioContext'
import { browserLiveAudio, createLivePlayer, fetchChunkBytes } from './livePlayer'

const wait = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds))
const rounded = (value: number | null) => Number((value ?? 0).toFixed(6))

beforeEach(() => FakeAudioContext.reset())
afterEach(() => vi.unstubAllGlobals())

describe('createLivePlayer', () => {
  it('agenda na ordem de chegada, com fade nas duas pontas de cada fala', async () => {
    const context = contextWithDurations(10)
    // a primeira demora mais para carregar: a ordem de chegada tem que ser mantida mesmo assim
    const load = async (url: string) => {
      if (url === 'a') await wait(30)
      return bytesOf(url === 'a' ? 1 : 2)
    }
    const player = createLivePlayer(context, load)
    void player.enqueue({ index: 1, url: 'a', pauseAfter: 0.35 })
    await player.enqueue({ index: 2, url: 'b', pauseAfter: 0 })

    expect(player.plans.map((plan) => plan.index)).toEqual([1, 2])
    expect(context.sources.map((source) => rounded(source.startedAt))).toEqual([10.06, 11.41])
    // gains[0] é o volume geral; gains[1] é o da primeira fala
    const events = context.gains[1]!.gain.events.map(([kind, value, time]) => [kind, value, rounded(time)])
    expect(events).toEqual([
      ['set', 0, 10.06],
      ['ramp', 1, 10.065],
      ['set', 1, 11.055],
      ['ramp', 0, 11.06],
    ])
    expect(player.ready()).toBe(2)
  })

  it('diz qual fala toca pelo relógio do áudio', async () => {
    const context = contextWithDurations(0)
    const player = createLivePlayer(context, async () => bytesOf(1))
    await player.enqueue({ index: 1, url: 'a', pauseAfter: 0 })
    await player.enqueue({ index: 2, url: 'b', pauseAfter: 0 })

    expect(player.playingIndex()).toBe(1)
    context.currentTime = 1.5
    expect(player.playingIndex()).toBe(2)
    context.currentTime = 5
    expect(player.playingIndex()).toBeNull()
  })

  it('parar baixa o volume em rampa e ignora as falas que chegam depois', async () => {
    const context = contextWithDurations(5)
    const player = createLivePlayer(context, async () => bytesOf(1))
    await player.enqueue({ index: 1, url: 'a', pauseAfter: 0 })
    player.stop()
    await player.enqueue({ index: 2, url: 'b', pauseAfter: 0 })

    expect(context.sources).toHaveLength(1)
    expect(context.sources[0]!.stoppedAt).toBeCloseTo(5.025, 6)
    const master = context.gains[0]!.gain.events
    expect(master.some(([kind, value, time]) => kind === 'ramp' && value === 0 && Math.abs(time - 5.02) < 1e-9)).toBe(true)
  })

  it('parar não quebra quando um nó já terminou de tocar', async () => {
    const context = contextWithDurations(0)
    const player = createLivePlayer(context, async () => bytesOf(1))
    await player.enqueue({ index: 1, url: 'a', pauseAfter: 0 })
    context.sources[0]!.throwOnStop = true
    expect(() => player.stop()).not.toThrow()
  })

  it('avisa o erro de carregar uma fala e segue com as próximas', async () => {
    const context = contextWithDurations(0)
    const errors: string[] = []
    const load = async (url: string) => {
      if (url === 'ruim') throw new Error('falhou')
      return bytesOf(1)
    }
    const player = createLivePlayer(context, load, (error) => errors.push((error as Error).message))
    void player.enqueue({ index: 1, url: 'ruim', pauseAfter: 0 })
    await player.enqueue({ index: 2, url: 'boa', pauseAfter: 0 })

    expect(errors).toEqual(['falhou'])
    expect(player.plans.map((plan) => plan.index)).toEqual([2])
  })

  it('solta o nó de volume da fala quando ela termina', async () => {
    const context = contextWithDurations(0)
    const player = createLivePlayer(context, async () => bytesOf(1))
    await player.enqueue({ index: 1, url: 'a', pauseAfter: 0 })
    context.sources[0]!.onended?.()
    expect(context.gains[1]!.disconnected).toBe(true)
  })
})

describe('browserLiveAudio', () => {
  it('sem Web Audio no navegador devolve nada', () => {
    vi.stubGlobal('AudioContext', undefined)
    vi.stubGlobal('webkitAudioContext', undefined)
    expect(browserLiveAudio()).toBeNull()
  })

  it('cria um contexto só e o reaproveita enquanto o navegador é o mesmo', () => {
    vi.stubGlobal('AudioContext', FakeAudioContext)
    const first = browserLiveAudio()
    expect(first).toBeInstanceOf(FakeAudioContext)
    expect(browserLiveAudio()).toBe(first)
    expect(FakeAudioContext.instances).toHaveLength(1)
  })

  it('usa o prefixo antigo do Safari quando é o que existe', () => {
    vi.stubGlobal('AudioContext', undefined)
    vi.stubGlobal('webkitAudioContext', FakeAudioContext)
    expect(browserLiveAudio()).toBeInstanceOf(FakeAudioContext)
  })
})

describe('fetchChunkBytes', () => {
  it('devolve os bytes da fala', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(bytesOf(2))))
    const bytes = await fetchChunkBytes('/api/voices/audio?path=x')
    expect(new TextDecoder().decode(bytes)).toBe('2')
  })

  it('uma resposta de erro vira a mensagem da prévia ao vivo', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('nada', { status: 404 })))
    await expect(fetchChunkBytes('/x')).rejects.toThrow('Não consegui carregar uma fala da prévia ao vivo.')
  })
})
