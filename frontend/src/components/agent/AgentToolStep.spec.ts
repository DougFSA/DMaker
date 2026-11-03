import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ToolItem } from '@/lib/agent'
import AgentToolStep from './AgentToolStep.vue'

describe('AgentToolStep: estados da transcrição salva', () => {
  const tool = (overrides: Partial<ToolItem>): ToolItem => ({
    kind: 'tool',
    id: 't1',
    name: 'render_project',
    arguments: { name_or_path: 'meu-video' },
    state: 'done',
    detail: '',
    result: '',
    percent: null,
    label: '',
    ...overrides,
  })

  it('a ferramenta que o DMaker interrompeu aparece como "interrompida", com o motivo', () => {
    const wrapper = mount(AgentToolStep, {
      props: { tool: tool({ state: 'interrupted', detail: 'Interrompida porque o DMaker foi fechado.' }) },
    })
    expect(wrapper.text()).toContain('interrompida')
    expect(wrapper.text()).toContain('Interrompida porque o DMaker foi fechado.')
  })

  it('o resultado inteiro só pode ser aberto quando tem mais que a primeira linha', () => {
    const short = mount(AgentToolStep, { props: { tool: tool({ detail: 'ok', result: 'ok' }) } })
    expect(short.find('details').exists()).toBe(false)

    const long = mount(AgentToolStep, { props: { tool: tool({ detail: 'linha um', result: 'linha um\nlinha dois' }) } })
    expect(long.find('details').attributes('open')).toBeUndefined()
    expect(long.find('details pre').text()).toBe('linha um\nlinha dois')
  })
})
