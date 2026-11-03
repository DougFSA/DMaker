import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { NarrationItem } from '@/stores/narration'
import NarrationHistory from './NarrationHistory.vue'

// o botão de baixar avisa os erros por um Toast, que mora numa store
beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

function item(id: number, overrides: Partial<NarrationItem> = {}): NarrationItem {
  return {
    id,
    text: `Roteiro ${id}`,
    voiceId: null,
    voiceName: 'Voz automática',
    speed: 1,
    language: null,
    seed: null,
    duration: 65,
    audioUrl: `/api/voices/audio?path=n${id}`,
    output: `X:/saida/n${id}.wav`,
    at: new Date(2026, 9, 29, 14, 5, 9),
    ...overrides,
  }
}

function mountHistory(props: Partial<InstanceType<typeof NarrationHistory>['$props']> = {}) {
  return mount(NarrationHistory, {
    props: { items: [item(2), item(1)], currentId: 2, canInsert: true, inserting: false, ...props },
  })
}

describe('NarrationHistory', () => {
  it('sem narrações, avisa que elas aparecem aqui', () => {
    const wrapper = mountHistory({ items: [], currentId: null })
    expect(wrapper.text()).toContain('As narrações geradas nesta sessão aparecem aqui.')
    expect(wrapper.find('li').exists()).toBe(false)
  })

  it('mostra o início do roteiro, a voz, a duração e a hora, na ordem recebida', () => {
    const entries = mountHistory().findAll('li')
    expect(entries.map((node) => node.find('.entry__text').text())).toEqual(['Roteiro 2', 'Roteiro 1'])
    expect(entries[0]!.text()).toContain('Voz automática · 1 min 05 s · 14:05:09')
  })

  it('corta o roteiro longo com reticências', () => {
    const wrapper = mountHistory({ items: [item(1, { text: 'a'.repeat(80) })] })
    expect(wrapper.find('.entry__text').text()).toBe(`${'a'.repeat(70)}...`)
  })

  it('marca a narração que está no player', () => {
    const entries = mountHistory().findAll('li')
    expect(entries[0]!.classes()).toContain('is-current')
    expect(entries[1]!.classes()).not.toContain('is-current')
  })

  it('cada ação avisa de qual narração é', async () => {
    const wrapper = mountHistory()
    const second = wrapper.findAll('li')[1]!
    const click = (label: string) => second.findAll('button').find((node) => node.text() === label)!.trigger('click')
    await click('Ouvir')
    await click('Reusar texto')
    await click('Inserir no projeto')
    expect(wrapper.emitted('play')?.[0]?.[0]).toMatchObject({ id: 1 })
    expect(wrapper.emitted('reuse')?.[0]?.[0]).toMatchObject({ id: 1 })
    expect(wrapper.emitted('insert')?.[0]?.[0]).toMatchObject({ id: 1 })
  })

  it('Baixar pede o arquivo da narração como anexo', async () => {
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute('href') ?? '')
    })
    const wrapper = mountHistory()
    await wrapper.findAll('li')[1]!.findAll('button').find((node) => node.text() === 'Baixar')!.trigger('click')
    expect(clicked).toEqual(['/api/voices/audio?path=n1&download=true'])
  })

  it('sem projeto aberto, Inserir fica desligado', () => {
    const wrapper = mountHistory({ canInsert: false })
    const insert = wrapper.findAll('button').find((node) => node.text() === 'Inserir no projeto')!
    expect(insert.attributes('disabled')).toBeDefined()
  })
})
