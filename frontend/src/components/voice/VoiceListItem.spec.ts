import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { VoiceProfile } from '@/api'
import VoiceListItem from './VoiceListItem.vue'

const LANGUAGES = [{ value: 'pt', label: 'Português' }]

function voice(overrides: Partial<VoiceProfile> = {}): VoiceProfile {
  return {
    id: 'ana',
    name: 'Ana',
    kind: 'clone',
    engine: 'omnivoice',
    preset: null,
    language: 'pt',
    brand: 'medlycare',
    instruct: null,
    reference: null,
    reference_text: null,
    created: '2026-10-29',
    ...overrides,
  }
}

function mountItem(props: Partial<InstanceType<typeof VoiceListItem>['$props']> = {}) {
  return mount(VoiceListItem, {
    props: {
      voice: voice(),
      languages: LANGUAGES,
      selected: false,
      status: '',
      failed: false,
      previewing: false,
      ...props,
    },
  })
}

const buttons = (wrapper: ReturnType<typeof mountItem>) => wrapper.findAll('button').map((node) => node.text())

describe('VoiceListItem', () => {
  it('mostra o nome, o tipo e os detalhes da voz', () => {
    const wrapper = mountItem()
    expect(wrapper.find('strong').text()).toBe('Ana')
    expect(wrapper.text()).toContain('clonada')
    expect(wrapper.text()).toContain('Português · medlycare · omnivoice')
  })

  it('a voz clonada tem Ouvir, Usar e Remover', () => {
    expect(buttons(mountItem())).toEqual(['Ouvir', 'Usar', 'Remover'])
  })

  it('a voz pronta do motor não tem Remover', () => {
    const wrapper = mountItem({ voice: voice({ kind: 'preset', brand: null }) })
    expect(buttons(wrapper)).toEqual(['Ouvir', 'Usar'])
    expect(wrapper.text()).toContain('pronta')
  })

  it('cada botão avisa a sua ação', async () => {
    const wrapper = mountItem()
    const [listen, use, remove] = wrapper.findAll('button')
    await listen!.trigger('click')
    await use!.trigger('click')
    await remove!.trigger('click')
    expect(wrapper.emitted('preview')).toHaveLength(1)
    expect(wrapper.emitted('use')).toHaveLength(1)
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })

  it('os botões dizem de qual voz são, para o leitor de tela', () => {
    const labels = mountItem()
      .findAll('button')
      .map((node) => node.attributes('aria-label'))
    expect(labels).toEqual(['Ouvir uma amostra da voz Ana', 'Usar a voz Ana no roteiro', 'Remover a voz Ana'])
  })

  it('a voz do roteiro ganha o selo', () => {
    expect(mountItem().text()).not.toContain('Voz do roteiro')
    expect(mountItem({ selected: true }).text()).toContain('Voz do roteiro')
  })

  it('enquanto a amostra é gerada o Ouvir fica desligado e o andamento aparece', () => {
    const wrapper = mountItem({ previewing: true, status: 'Gerando amostra... 0:07' })
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    const status = wrapper.find('.voice__status')
    expect(status.text()).toBe('Gerando amostra... 0:07')
    expect(status.attributes('role')).toBe('status')
  })

  it('se a amostra falhou, o erro é um alerta e o Ouvir volta a funcionar', () => {
    const wrapper = mountItem({ status: 'Não consegui gerar a amostra: sem modelo', failed: true })
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.voice__status').attributes('role')).toBe('alert')
    expect(wrapper.find('.voice__status').classes()).toContain('is-error')
  })

  it('sem andamento a linha de estado não aparece', () => {
    expect(mountItem().find('.voice__status').exists()).toBe(false)
  })
})
