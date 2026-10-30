import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ConfirmationItem } from '@/lib/agent'
import AgentConfirmation from './AgentConfirmation.vue'

describe('AgentConfirmation: estados da transcrição salva', () => {
  const confirmation = (state: ConfirmationItem['state']): ConfirmationItem => ({
    kind: 'confirmation',
    id: 'c1',
    confirmationId: 'cf1',
    tool: 'render_project',
    question: 'Posso gerar o vídeo final?',
    type: 'action',
    state,
  })

  it('a pergunta que ficou sem resposta mostra "Não confirmada" e nenhum botão', () => {
    const wrapper = mount(AgentConfirmation, { props: { confirmation: confirmation('unconfirmed') } })

    expect(wrapper.text()).toContain('Posso gerar o vídeo final?')
    expect(wrapper.text()).toContain('Não confirmada')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('pendente mostra os botões; respondida mostra o que a pessoa fez', async () => {
    const pending = mount(AgentConfirmation, { props: { confirmation: confirmation('pending') } })
    await pending.findAll('button')[0]!.trigger('click')
    expect(pending.emitted('answer')).toEqual([['cf1', true]])

    expect(mount(AgentConfirmation, { props: { confirmation: confirmation('approved') } }).text()).toContain('Você confirmou')
    expect(mount(AgentConfirmation, { props: { confirmation: confirmation('refused') } }).text()).toContain('Você não confirmou')
  })
})
