import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { AgentConversationSummary } from '@/api'
import AgentConversationList from './AgentConversationList.vue'

describe('AgentConversationList', () => {
  const summary = (overrides: Partial<AgentConversationSummary> = {}): AgentConversationSummary => ({
    id: 'c1',
    title: 'Roteiro do reel',
    created_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
    updated_at: new Date(Date.now() - 3600_000).toISOString(),
    mode: 'operate',
    model: 'gpt-oss:20b',
    effort: null,
    messages: 2,
    running: false,
    ...overrides,
  })

  it('lista as conversas com o modelo e quando foi a última mensagem, e marca a aberta', () => {
    const wrapper = mount(AgentConversationList, {
      props: { conversations: [summary(), summary({ id: 'c2', title: 'Outra', mode: 'free', running: true })], activeId: 'c1' },
    })
    const rows = wrapper.findAll('.row')

    expect(rows).toHaveLength(2)
    expect(rows[0]!.classes()).toContain('row--active')
    expect(rows[0]!.text()).toContain('Roteiro do reel')
    expect(rows[0]!.text()).toContain('há 1 h')
    expect(rows[0]!.text()).toContain('gpt-oss:20b')
    expect(rows[1]!.text()).toContain('respondendo')
    expect(rows[1]!.text()).toContain('Conversa livre')
  })

  it('sem conversas, explica quando a primeira aparece', () => {
    const wrapper = mount(AgentConversationList, { props: { conversations: [], activeId: null } })
    expect(wrapper.text()).toContain('Nenhuma conversa salva ainda')
  })

  it('clicar numa conversa a abre', async () => {
    const wrapper = mount(AgentConversationList, { props: { conversations: [summary()], activeId: null } })
    await wrapper.find('.row__open').trigger('click')

    expect(wrapper.emitted('select')).toEqual([['c1']])
  })

  it('renomeia no próprio lugar: Enter confirma e Esc desiste', async () => {
    const wrapper = mount(AgentConversationList, { props: { conversations: [summary()], activeId: 'c1' }, attachTo: document.body })
    await wrapper.find('button[aria-label="Renomear a conversa Roteiro do reel"]').trigger('click')
    const input = wrapper.find('input')
    expect((input.element as HTMLInputElement).value).toBe('Roteiro do reel')
    expect(document.activeElement).toBe(input.element)

    await input.setValue('  Gancho do reel  ')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('rename')).toEqual([['c1', 'Gancho do reel']])
    expect(wrapper.find('input').exists()).toBe(false)

    await wrapper.find('button[aria-label="Renomear a conversa Roteiro do reel"]').trigger('click')
    await wrapper.find('input').setValue('Outro nome')
    await wrapper.find('input').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('rename')).toHaveLength(1)
    expect(wrapper.find('input').exists()).toBe(false)
    wrapper.unmount()
  })

  it('manter o nome igual não chama o servidor', async () => {
    const wrapper = mount(AgentConversationList, { props: { conversations: [summary()], activeId: 'c1' } })
    await wrapper.find('button[aria-label="Renomear a conversa Roteiro do reel"]').trigger('click')
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('rename')).toBeUndefined()
  })

  it('apagar só avisa a tela, que pergunta antes', async () => {
    const wrapper = mount(AgentConversationList, { props: { conversations: [summary()], activeId: 'c1' } })
    await wrapper.find('button[aria-label="Apagar a conversa Roteiro do reel"]').trigger('click')

    expect(wrapper.emitted('remove')).toEqual([['c1']])
  })
})
