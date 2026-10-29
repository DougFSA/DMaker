import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AbCompare from './AbCompare.vue'

const first = { label: 'Original', src: '/api/file?path=o.wav' }
const second = { label: 'Corrigido', src: '/api/voices/audio?path=c.wav', downloadUrl: '/api/voices/audio?path=c.wav&download=true', downloadName: 'c.wav' }

let playSpy: ReturnType<typeof vi.spyOn>
let pauseSpy: ReturnType<typeof vi.spyOn>
let wrapper: VueWrapper

beforeEach(() => {
  setActivePinia(createPinia()) // o botão de baixar usa a fila de avisos
  playSpy = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  pauseSpy = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

function mountAb(props: Record<string, unknown> = {}): VueWrapper {
  wrapper = mount(AbCompare, { props: { first, second, kind: 'audio', ...props } })
  return wrapper
}

const players = () => wrapper.findAll('audio').map((node) => node.element as HTMLAudioElement)
const listenButton = (label: string) => wrapper.findAll('button').find((node) => node.text() === label)!

describe('AbCompare', () => {
  it('mostra os dois players com o nome de cada lado e o botão de baixar só de quem tem endereço', () => {
    mountAb()
    expect(wrapper.findAll('.player__title').map((node) => node.text())).toEqual(['Original', 'Corrigido'])
    expect(players().map((audio) => audio.getAttribute('src'))).toEqual([first.src, second.src])
    expect(wrapper.findAll('.player__actions')).toHaveLength(1)
    expect(wrapper.find('.player__actions').text()).toContain('Baixar')
  })

  it('o grupo tem nome para o leitor de tela', () => {
    mountAb({ label: 'Antes e depois da correção' })
    expect(wrapper.find('[role="group"]').attributes('aria-label')).toBe('Antes e depois da correção')
  })

  it('tocar um lado pausa o outro', async () => {
    mountAb()
    const [a, b] = wrapper.findAll('audio')
    await a!.trigger('play')
    expect(pauseSpy.mock.contexts).toContain(players()[1])
    expect(wrapper.findAll('.ab__side')[0]?.classes()).toContain('is-playing')

    pauseSpy.mockClear()
    await b!.trigger('play')
    expect(pauseSpy.mock.contexts).toContain(players()[0])
    expect(wrapper.findAll('.ab__side')[1]?.classes()).toContain('is-playing')
    expect(wrapper.findAll('.ab__side')[0]?.classes()).not.toContain('is-playing')
  })

  it('"Ouvir" parte do ponto em que o outro lado estava', async () => {
    mountAb()
    players()[0]!.currentTime = 12.5
    await listenButton('Ouvir corrigido').trigger('click')
    expect(players()[1]!.currentTime).toBe(12.5)
    expect(playSpy.mock.contexts).toEqual([players()[1]])
    expect(pauseSpy.mock.contexts).toContain(players()[0])
  })

  it('"Ouvir" pode partir sempre do começo', async () => {
    mountAb({ startAt: 'beginning' })
    players()[0]!.currentTime = 12.5
    players()[1]!.currentTime = 9
    await listenButton('Ouvir corrigido').trigger('click')
    expect(players()[1]!.currentTime).toBe(0)
  })

  it('com região, "Ouvir" toca a janela de 1,5 s em volta e para no fim dela', async () => {
    mountAb({ region: [21.4, 23.4] })
    await listenButton('Ouvir original').trigger('click')
    const original = players()[0]!
    expect(original.currentTime).toBeCloseTo(19.9)
    expect(playSpy).toHaveBeenCalledTimes(1)

    pauseSpy.mockClear()
    original.currentTime = 24
    await wrapper.findAll('audio')[0]!.trigger('timeupdate')
    expect(pauseSpy).not.toHaveBeenCalled() // ainda dentro da janela (termina em 24,9)

    original.currentTime = 24.95
    await wrapper.findAll('audio')[0]!.trigger('timeupdate')
    expect(pauseSpy.mock.contexts).toContain(original)
  })

  it('depois de pausar à mão, a janela deixa de valer', async () => {
    mountAb({ region: [10, 12] })
    await listenButton('Ouvir original').trigger('click')
    await wrapper.findAll('audio')[0]!.trigger('pause')
    pauseSpy.mockClear()
    players()[0]!.currentTime = 99
    await wrapper.findAll('audio')[0]!.trigger('timeupdate')
    expect(pauseSpy).not.toHaveBeenCalled()
  })

  it('explica a folga quando há região', () => {
    mountAb({ region: [10, 12] })
    expect(wrapper.find('.ab__hint').text()).toContain('1,5 s')
    mountAb()
    expect(wrapper.find('.ab__hint').exists()).toBe(false)
  })

  it('quando o navegador bloqueia a reprodução, avisa em vez de falhar calado', async () => {
    mountAb()
    playSpy.mockRejectedValueOnce(new DOMException('bloqueado', 'NotAllowedError'))
    await listenButton('Ouvir original').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[role="status"]').text()).toContain('Use o player'))
  })

  it('vídeo usa dois elementos video', () => {
    mountAb({ kind: 'video' })
    expect(wrapper.findAll('video')).toHaveLength(2)
  })
})
