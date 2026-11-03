import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MediaEntry } from '@/lib/media'
import type { DubOutcome } from '@/stores/dubbing'
import { renderResult } from '@/test/dubServer'
import DubResultCard from './DubResultCard.vue'

beforeEach(() => setActivePinia(createPinia()))

const ENTRY: MediaEntry = { id: 'file:D:/m/a.mp4', kind: 'clip', label: 'a.mp4', path: 'D:/m/a.mp4', src: 'D:/m/a.mp4' }

function mountCard(over: Record<string, unknown> = {}, props: Record<string, unknown> = {}) {
  const outcome = { ...renderResult(over), stamp: 1 } as unknown as DubOutcome
  return mount(DubResultCard, { props: { outcome, project: 'demo', entry: ENTRY, ...props } })
}

describe('DubResultCard', () => {
  it('compara o original e o dublado em vídeo e resume o que foi feito', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('Dublagem pronta')
    expect(wrapper.text()).toContain('2 fala(s) sintetizada(s) agora e 1 reaproveitada(s) do cache')
    expect(wrapper.findAll('video')).toHaveLength(2)
    expect(wrapper.text()).toContain('Ouvir original')
    expect(wrapper.text()).toContain('Ouvir dublado')
    expect(wrapper.find('ul').exists()).toBe(false)
  })

  it('o vídeo dublado muda de endereço a cada geração, para o navegador não mostrar o antigo', () => {
    const first = mountCard({}, {}).findAll('video')[1]!.attributes('src')
    const outcome = { ...renderResult(), stamp: 2 } as unknown as DubOutcome
    const second = mount(DubResultCard, { props: { outcome, project: 'demo', entry: ENTRY } }).findAll('video')[1]!.attributes('src')
    expect(first).not.toBe(second)
  })

  it('oferece os downloads com o nome certo para vídeo e para áudio', () => {
    expect(mountCard().text()).toContain('Baixar o vídeo dublado')
    const audio = mountCard({ output: 'X:/saida/dublagem/podcast.en.mp3' })
    expect(audio.text()).toContain('Baixar o áudio dublado')
    expect(audio.text()).toContain('Baixar a legenda (.srt)')
    expect(audio.findAll('audio')).toHaveLength(2)
  })

  it('"Usar no projeto" avisa quando o resultado entrou no projeto', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
        const answer = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body)))
        if (url === '/api/projects/demo') return answer({ name: 'demo', spec_path: 'p', spec: { timeline: [{ type: 'clip', src: 'D:/m/a.mp4' }] }, captions_exists: false, outputs: [], cuts: null })
        if (url === '/api/projects/demo/edit') return answer({ spec: { timeline: [{ type: 'clip', src: 'X:/saida/dublagem/entrevista.en.mp4' }] }, timeline: {} })
        if (init.method === 'PUT') return answer({ ok: true })
        return answer({})
      }),
    )
    const wrapper = mountCard()
    const use = wrapper.findAll('button').find((button) => button.text().includes('Usar no projeto'))!
    await use.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('used')?.[0]).toEqual([1])
    expect(wrapper.text()).toContain('Projeto demo atualizado: vídeo dublado em 1 ponto(s).')
    vi.unstubAllGlobals()
  })

  it('sem projeto de origem, "Usar no projeto" fica desligado e diz por quê', () => {
    const wrapper = mountCard({}, { project: null, entry: null })
    const use = wrapper.findAll('button').find((button) => button.text().includes('Usar no projeto'))!
    expect(use.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Para usar no projeto, escolha um arquivo do projeto aberto.')
  })

  it('lista os avisos, um por linha', () => {
    const wrapper = mountCard({ warnings: ['Fala s1: não coube.', 'Fala s3: ficou apertada.'] })
    expect(wrapper.findAll('ul[aria-label="Avisos da geração"] li').map((item) => item.text())).toEqual([
      'Fala s1: não coube.',
      'Fala s3: ficou apertada.',
    ])
  })
})
