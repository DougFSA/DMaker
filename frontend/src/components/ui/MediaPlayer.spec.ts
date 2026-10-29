import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MediaPlayer from './MediaPlayer.vue'

// o jsdom não toca mídia: troca os métodos do elemento por espiões
beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

describe('MediaPlayer', () => {
  it('áudio: usa o elemento audio com controles e o título como nome', () => {
    const wrapper = mount(MediaPlayer, { props: { src: '/api/voices/audio?path=a.wav', kind: 'audio', title: 'Voz isolada' } })
    const audio = wrapper.find('audio')
    expect(audio.exists()).toBe(true)
    expect(wrapper.find('video').exists()).toBe(false)
    expect(audio.attributes('src')).toBe('/api/voices/audio?path=a.wav')
    expect(audio.attributes('controls')).toBeDefined()
    expect(audio.attributes('aria-label')).toBe('Voz isolada')
    expect(wrapper.find('.player__title').text()).toBe('Voz isolada')
  })

  it('vídeo: usa o elemento video', () => {
    const wrapper = mount(MediaPlayer, { props: { src: '/api/file?path=a.mp4', kind: 'video' } })
    expect(wrapper.find('video').exists()).toBe(true)
    expect(wrapper.find('audio').exists()).toBe(false)
  })

  it('mostra a linha de dados sob o título', () => {
    const wrapper = mount(MediaPlayer, {
      props: { src: 'a.wav', kind: 'audio', title: 'Narração', meta: ['12,3 s', '', '1,2 MB'] },
    })
    expect(wrapper.find('.player__meta').text()).toBe('12,3 s · 1,2 MB')
  })

  it('sem título nem dados, não desenha a legenda', () => {
    const wrapper = mount(MediaPlayer, { props: { src: 'a.wav', kind: 'audio' } })
    expect(wrapper.find('figcaption').exists()).toBe(false)
  })

  it('o slot de ações aparece ao lado dos dados', () => {
    const wrapper = mount(MediaPlayer, {
      props: { src: 'a.wav', kind: 'audio', title: 'x' },
      slots: { actions: '<button>Baixar</button>' },
    })
    expect(wrapper.find('.player__actions').text()).toBe('Baixar')
  })

  it('refreshKey força o navegador a buscar de novo o arquivo regravado', async () => {
    const wrapper = mount(MediaPlayer, { props: { src: '/api/voices/audio?path=a.wav', kind: 'audio', refreshKey: 1 } })
    expect(wrapper.find('audio').attributes('src')).toBe('/api/voices/audio?path=a.wav&t=1')
    await wrapper.setProps({ refreshKey: 2 })
    expect(wrapper.find('audio').attributes('src')).toBe('/api/voices/audio?path=a.wav&t=2')
  })

  it('repassa os eventos do elemento', async () => {
    const wrapper = mount(MediaPlayer, { props: { src: 'a.wav', kind: 'audio' } })
    const audio = wrapper.find('audio')
    await audio.trigger('play')
    await audio.trigger('pause')
    await audio.trigger('ended')
    audio.element.currentTime = 4.5
    await audio.trigger('timeupdate')
    expect(wrapper.emitted('play')).toHaveLength(1)
    expect(wrapper.emitted('pause')).toHaveLength(1)
    expect(wrapper.emitted('ended')).toHaveLength(1)
    expect(wrapper.emitted('timeupdate')).toEqual([[4.5]])
  })

  it('expõe tocar, pausar e ir para um instante', async () => {
    const wrapper = mount(MediaPlayer, { props: { src: 'a.wav', kind: 'audio' } })
    const player = wrapper.vm as unknown as { play: () => Promise<void>; pause: () => void; seek: (s: number) => void; currentTime: () => number }
    await player.play()
    player.pause()
    player.seek(7.25)
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(1)
    expect(player.currentTime()).toBe(7.25)
    player.seek(-3)
    expect(player.currentTime()).toBe(0)
  })
})
