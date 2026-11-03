import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { stubVoiceServer } from '@/test/voiceServer'
import { useNarrationStore, type NarrationItem } from '@/stores/narration'
import { useToastsStore } from '@/stores/toasts'
import { useWorkspaceStore } from '@/stores/workspace'
import NarrationResult from './NarrationResult.vue'

let wrapper: VueWrapper | null = null

const ITEM: NarrationItem = {
  id: 7,
  text: 'Olá, mundo.',
  voiceId: 'dora',
  voiceName: 'Dora (feminina)',
  speed: 1.25,
  language: null,
  seed: null,
  duration: 12.4,
  audioUrl: '/api/voices/audio?path=n7',
  output: 'X:/saida/n7.wav',
  at: new Date(2026, 9, 29, 14, 5, 9),
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  stubVoiceServer()
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function mountResult() {
  wrapper = mount(NarrationResult, { props: { item: ITEM }, global: { stubs: { RouterLink: RouterLinkStub } } })
  return wrapper
}

describe('NarrationResult', () => {
  it('mostra o player com a voz, a duração e a velocidade', () => {
    const view = mountResult()
    expect(view.find('audio').attributes('src')).toContain('/api/voices/audio?path=n7')
    expect(view.find('audio').attributes('aria-label')).toBe('Narração')
    expect(view.text()).toContain('Dora (feminina) · 12 s · velocidade 1,25x')
  })

  it('o player busca o arquivo de novo a cada narração (a chave é o id)', () => {
    expect(mountResult().find('audio').attributes('src')).toContain('t=7')
  })

  it('Baixar áudio pede o arquivo como anexo', async () => {
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute('href') ?? '')
    })
    const view = mountResult()
    await view.findAll('button').find((node) => node.text() === 'Baixar áudio')!.trigger('click')
    expect(clicked).toEqual(['/api/voices/audio?path=n7&download=true'])
  })

  it('sem projeto aberto, o Inserir fica desligado e a tela manda abrir um em Projetos', () => {
    const view = mountResult()
    const insert = view.findAll('button').find((node) => node.text() === 'Inserir no projeto aberto')!
    expect(insert.attributes('disabled')).toBeDefined()
    expect(view.text()).toContain('Nenhum projeto aberto.')
    expect(view.findComponent(RouterLinkStub).props('to')).toBe('/projetos')
  })

  it('com projeto aberto, o campo mostra a posição padrão e escrever nele muda a posição usada', async () => {
    useWorkspaceStore().openProject('demo')
    const narration = useNarrationStore()
    narration.defaultStart = 9.5
    const view = mountResult()
    const input = view.find('input[type="number"]')

    expect(input.attributes('placeholder')).toBe('9,5')
    expect(view.text()).toContain('Projeto aberto: demo.')
    await input.setValue('3')
    expect(narration.insertStart).toBe(3)
    expect(narration.startAt).toBe(3)
    await input.setValue('')
    expect(narration.insertStart).toBeNull()
    expect(narration.startAt).toBe(9.5)
  })

  it('Inserir no projeto aberto insere esta narração', async () => {
    useWorkspaceStore().openProject('demo')
    const narration = useNarrationStore()
    const insert = vi.spyOn(narration, 'insertIntoProject').mockResolvedValue(true)
    const view = mountResult()
    await view.findAll('button').find((node) => node.text() === 'Inserir no projeto aberto')!.trigger('click')
    expect(insert).toHaveBeenCalledWith(ITEM)
  })

  it('mostra o que a inserção respondeu', async () => {
    useWorkspaceStore().openProject('demo')
    const narration = useNarrationStore()
    const view = mountResult()
    narration.insertNote = 'Narração inserida em 9,50 s do projeto demo.'
    await flushPromises()
    expect(view.find('[role="status"]').text()).toBe('Narração inserida em 9,50 s do projeto demo.')
  })

  it('Ouvir no histórico faz o player tocar', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    mountResult()
    useNarrationStore().playStamp += 1
    await flushPromises()
    expect(play).toHaveBeenCalledTimes(1)
  })

  it('se o navegador recusa tocar sozinho, avisa para usar o player', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(new DOMException('autoplay', 'NotAllowedError'))
    mountResult()
    useNarrationStore().playStamp += 1
    await flushPromises()
    expect(useToastsStore().items.at(-1)).toMatchObject({ title: 'Narração pronta', description: 'Use o player para ouvir.' })
  })
})
