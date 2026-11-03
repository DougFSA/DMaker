import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ThinkingItem } from '@/lib/agent'
import AgentThinking from './AgentThinking.vue'

describe('AgentThinking', () => {
  const item = (overrides: Partial<ThinkingItem> = {}): ThinkingItem => ({
    kind: 'thinking',
    id: 't1',
    text: 'O usuário quer um resumo.',
    streaming: false,
    ...overrides,
  })

  it('fica recolhido e a pessoa abre para ler', () => {
    const wrapper = mount(AgentThinking, { props: { item: item() } })
    const details = wrapper.find('details')

    expect(details.attributes('open')).toBeUndefined()
    expect(details.find('summary').text()).toBe('Raciocínio')
    expect(details.text()).toContain('O usuário quer um resumo.')
  })

  it('enquanto chega, o título diz que está pensando', () => {
    const wrapper = mount(AgentThinking, { props: { item: item({ streaming: true }) } })
    expect(wrapper.find('summary').text()).toBe('Pensando...')
  })
})
