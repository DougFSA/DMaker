import { describe, expect, it, vi } from 'vitest'
import type { LiveChannel, LivePlan } from './playerAudio'
import { AudioChannel, PlayerAudio, syncVideo, type MediaElementLike } from './playerEngine'

/** Um elemento de mídia de mentira que se comporta como o do navegador no que o player usa. */
function fakeElement(extra: Partial<MediaElementLike> = {}): MediaElementLike & { plays: number; pauses: number; dataset: Record<string, string> } {
  const element = {
    currentTime: 0,
    paused: true,
    muted: false,
    volume: 1,
    playbackRate: 1,
    duration: Number.NaN,
    readyState: 0,
    src: '',
    plays: 0,
    pauses: 0,
    dataset: {} as Record<string, string>,
    preload: '',
    play() {
      element.plays += 1
      element.paused = false
      return Promise.resolve()
    },
    pause() {
      element.pauses += 1
      element.paused = true
    },
    removeAttribute(name: string) {
      if (name === 'src') element.src = ''
    },
    load() {},
    remove() {},
    getAttribute: (name: string) => (name === 'src' && element.src ? element.src : null),
    addEventListener() {},
    ...extra,
  }
  return element
}

describe('syncVideo', () => {
  it('é sempre mudo, mesmo se alguém o destravou', () => {
    const video = fakeElement({ muted: false, volume: 1 })
    syncVideo(video, { fileTime: 3, speed: 1, rate: 1 })
    expect(video.muted).toBe(true)
    expect(video.volume).toBe(0)
  })

  it('tocando: busca só quando se afasta da tolerância, ajusta a velocidade e dá o play', () => {
    const video = fakeElement({ currentTime: 3.05 })
    syncVideo(video, { fileTime: 3, speed: 1.5, rate: 2 })
    expect(video.currentTime).toBe(3.05) // 50 ms de diferença: dentro da tolerância
    expect(video.playbackRate).toBe(3)
    expect(video.paused).toBe(false)
    syncVideo(video, { fileTime: 5, speed: 1, rate: 1 })
    expect(video.currentTime).toBe(5)
    expect(video.plays).toBe(1) // já tocava: não chama play de novo
  })

  it('parado ou voltando: pausa e mostra o quadro exato do instante', () => {
    const video = fakeElement({ currentTime: 3, paused: false })
    syncVideo(video, { fileTime: 3.033, speed: 1, rate: 0 })
    expect(video.paused).toBe(true)
    expect(video.currentTime).toBe(3.033) // um quadro à frente, mesmo dentro da tolerância de quem toca
    syncVideo(video, { fileTime: 2, speed: 1, rate: -1 })
    expect(video.paused).toBe(true)
    expect(video.currentTime).toBe(2)
  })

  it('vídeo que não abriu (sem proxy ainda) não é tocado', () => {
    const video = fakeElement()
    syncVideo(video, { fileTime: 3, speed: 1, rate: 1, errored: true })
    expect(video.plays).toBe(0)
  })

  it('nunca busca um tempo negativo', () => {
    const video = fakeElement({ currentTime: 4 })
    syncVideo(video, { fileTime: -2, speed: 1, rate: 0 })
    expect(video.currentTime).toBe(0)
  })
})

describe('AudioChannel', () => {
  const frame = (extra: Partial<Parameters<AudioChannel['sync']>[0]> = {}) => ({
    target: 10,
    mediaRate: 1,
    rate: 1,
    speed: 1,
    muted: false,
    volume: 0.7,
    now: 1000,
    ...extra,
  })

  it('carrega o arquivo uma vez e toca no ponto pedido, com o volume', () => {
    const element = fakeElement()
    const channel = new AudioChannel(element)
    channel.load('/api/file?path=a')
    channel.load('/api/file?path=a')
    expect(element.src).toBe('/api/file?path=a')
    channel.sync(frame())
    expect(element.currentTime).toBe(10)
    expect(element.volume).toBe(0.7)
    expect(element.muted).toBe(false)
    expect(element.paused).toBe(false)
  })

  it('sem alvo (o item não cobre o instante) pausa, em vez de prender em 0', () => {
    const element = fakeElement({ paused: false })
    const channel = new AudioChannel(element)
    channel.load('/x')
    channel.sync(frame({ target: null }))
    expect(element.paused).toBe(true)
    expect(element.currentTime).toBe(0)
  })

  it('logo depois de uma busca não busca de novo a cada quadro', () => {
    const element = fakeElement()
    const channel = new AudioChannel(element)
    channel.load('/x')
    channel.sync(frame({ target: 50, now: 1000 }))
    element.currentTime = 0 // o elemento ainda está carregando
    channel.sync(frame({ target: 50.016, now: 1016 }))
    expect(element.currentTime).toBe(0)
    channel.sync(frame({ target: 50.9, now: 1100 })) // o alvo saltou além do previsto: é outra busca
    expect(element.currentTime).toBe(50.9)
  })

  it('parado ou voltando, o áudio pausa', () => {
    const element = fakeElement()
    const channel = new AudioChannel(element)
    channel.load('/x')
    channel.sync(frame())
    channel.sync(frame({ rate: 0 }))
    expect(element.paused).toBe(true)
    channel.sync(frame({ rate: -1 }))
    expect(element.paused).toBe(true)
  })

  it('avisa quando o navegador bloqueia o som', async () => {
    const element = fakeElement({ play: () => Promise.reject(new Error('NotAllowedError')) })
    const blocked = vi.fn()
    const channel = new AudioChannel(element, blocked)
    channel.load('/x')
    channel.sync(frame())
    await Promise.resolve()
    await Promise.resolve()
    expect(blocked).toHaveBeenCalledOnce()
  })

  it('soltar tira o arquivo do elemento', () => {
    const element = fakeElement()
    const channel = new AudioChannel(element)
    channel.load('/x')
    channel.release()
    expect(channel.url).toBeNull()
    expect(element.src).toBe('')
  })
})

describe('PlayerAudio', () => {
  function build() {
    const elements: Array<ReturnType<typeof fakeElement>> = []
    const audio = new PlayerAudio(
      () => {
        const element = fakeElement()
        elements.push(element)
        return element as unknown as HTMLAudioElement
      },
      () => undefined,
      () => undefined,
    )
    return { audio, elements }
  }

  const channel = (trackId: string, extra: Partial<LiveChannel> = {}): LiveChannel => ({
    trackId,
    path: `C:/${trackId}.wav`,
    url: `/api/file?path=${trackId}`,
    fileTime: 12,
    speed: 1,
    loop: false,
    muted: false,
    volume: 0.5,
    ...extra,
  })

  const frame = (plan: LivePlan, extra: Partial<Parameters<PlayerAudio['update']>[0]> = {}) => ({
    time: 14,
    rate: 1,
    volume: 1,
    mixCurrent: false,
    plan,
    now: 1000,
    ...extra,
  })

  it('com a mixagem pronta toca só ela, num elemento só, e nenhum som ao vivo', () => {
    const { audio, elements } = build()
    audio.setMix('/api/file?path=mix.m4a')
    audio.update(frame({ channels: [channel('A2')], dropped: [] }, { mixCurrent: true }))
    expect(elements).toHaveLength(1) // só o da mixagem; a faixa ao vivo nem foi criada
    const mix = elements[0]!
    expect(mix.dataset.player).toBe('mix')
    expect(mix.paused).toBe(false)
    expect(mix.muted).toBe(false)
    expect(mix.currentTime).toBe(14)
    expect(audio.liveTracks).toEqual([])
  })

  it('a mixagem anda com o relógio: volume geral e velocidade', () => {
    const { audio, elements } = build()
    audio.setMix('/mix')
    audio.update(frame({ channels: [], dropped: [] }, { mixCurrent: true, volume: 0.4, rate: 2 }))
    expect(elements[0]!.volume).toBe(0.4)
    expect(elements[0]!.playbackRate).toBe(2)
  })

  it('enquanto a mixagem não está pronta, o som sai ao vivo, um elemento por trilha', () => {
    const { audio, elements } = build()
    audio.setMix(null)
    audio.update(frame({ channels: [channel('A2'), channel('MUS', { loop: true, fileTime: 130 })], dropped: [] }))
    expect(audio.liveTracks).toEqual(['A2', 'MUS'])
    const live = elements.filter((element) => element.dataset.player?.startsWith('live:'))
    expect(live.map((element) => element.currentTime)).toEqual([12, 130])
    expect(live.every((element) => !element.paused)).toBe(true)
    expect(elements[0]!.paused).toBe(true) // o elemento da mixagem não toca ao mesmo tempo
  })

  it('a música em loop dá a volta quando passa do fim do arquivo', () => {
    const { audio, elements } = build()
    audio.update(frame({ channels: [channel('MUS', { loop: true, fileTime: 130 })], dropped: [] }))
    const music = elements.find((element) => element.dataset.player === 'live:MUS')!
    music.duration = 100
    audio.update(frame({ channels: [channel('MUS', { loop: true, fileTime: 130 })], dropped: [] }, { now: 2000 }))
    expect(music.currentTime).toBe(30)
  })

  it('a faixa que sai do plano é solta; a mixagem pronta solta todas', () => {
    const { audio } = build()
    audio.update(frame({ channels: [channel('A2'), channel('MUS')], dropped: [] }))
    audio.update(frame({ channels: [channel('MUS')], dropped: [] }, { now: 1100 }))
    expect(audio.liveTracks).toEqual(['MUS'])
    audio.setMix('/mix')
    audio.update(frame({ channels: [channel('MUS')], dropped: [] }, { mixCurrent: true, now: 1200 }))
    expect(audio.liveTracks).toEqual([])
  })

  it('o ponto negativo ou fora do arquivo pausa a trilha ao vivo', () => {
    const { audio, elements } = build()
    audio.update(frame({ channels: [channel('A2', { fileTime: -0.5 })], dropped: [] }))
    const track = elements.find((element) => element.dataset.player === 'live:A2')!
    expect(track.paused).toBe(true)
    expect(track.currentTime).toBe(0)
  })

  it('pausar e descartar calam tudo', () => {
    const { audio, elements } = build()
    audio.update(frame({ channels: [channel('A2')], dropped: [] }))
    audio.pause()
    expect(elements.every((element) => element.paused)).toBe(true)
    audio.dispose()
    expect(audio.liveTracks).toEqual([])
  })
})
