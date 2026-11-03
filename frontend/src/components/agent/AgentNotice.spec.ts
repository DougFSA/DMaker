import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { NoticeItem } from '@/lib/agent'
import AgentNotice from './AgentNotice.vue'

describe('AgentNotice', () => {
  it('mostra o título curto do aviso e o texto do servidor', () => {
    const notice: NoticeItem = { kind: 'notice', id: 'n1', level: 'warning', code: 'unfinished', text: 'Esta resposta não terminou porque o DMaker foi fechado no meio dela.' }
    const wrapper = mount(AgentNotice, { props: { notice } })

    expect(wrapper.attributes('data-level')).toBe('warning')
    expect(wrapper.text()).toContain('Resposta incompleta.')
    expect(wrapper.text()).toContain('o DMaker foi fechado no meio dela')
  })
})
