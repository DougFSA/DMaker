import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ChatItem } from '@/lib/agent'
import { cardOfAttachment } from '@/lib/agentAttachments'
import { imageAttachment, textAttachment } from '@/test/agentServer'
import AgentTranscript from './AgentTranscript.vue'

describe('AgentTranscript', () => {
  const kits = [{ name: 'editing', title: 'Edição e render', description: '', tools: 18 }]

  it('desenha cada tipo de item com o componente dele, igual para o turno ao vivo e o salvo', () => {
    const items: ChatItem[] = [
      { kind: 'user', id: '1', text: 'Valida o projeto' },
      { kind: 'kits', id: '2', kits: ['editing'], method: 'keywords' },
      { kind: 'thinking', id: '3', text: 'Preciso validar.', streaming: false },
      { kind: 'tool', id: '4', name: 'validate_project', arguments: {}, state: 'done', detail: 'ok', result: 'ok', percent: null, label: '' },
      { kind: 'notice', id: '5', level: 'info', code: 'history_trimmed', text: 'Tirei 1 turno antigo.' },
      { kind: 'answer', id: '6', text: 'Está válido.', interrupted: false, streaming: false },
      { kind: 'error', id: '7', text: 'TimeoutError: o modelo não respondeu' },
    ]
    const wrapper = mount(AgentTranscript, { props: { items, kits } })

    expect(wrapper.find('.bubble--user').text()).toBe('Valida o projeto')
    expect(wrapper.find('.kits').text()).toBe('Kit: Edição e render')
    expect(wrapper.find('details.think').exists()).toBe(true)
    expect(wrapper.find('.step').text()).toContain('validate_project')
    expect(wrapper.find('.notice').text()).toContain('Tirei 1 turno antigo.')
    expect(wrapper.find('.bubble--agent').text()).toBe('Está válido.')
    expect(wrapper.find('.bubble--error').text()).toBe('TimeoutError: o modelo não respondeu')
  })

  it('a mensagem enviada com anexos mostra as fichas acima do texto, com a miniatura da imagem', () => {
    const items: ChatItem[] = [
      {
        kind: 'user',
        id: '1',
        text: 'Veja os anexos.',
        attachments: [cardOfAttachment(textAttachment({ chars: 800, total_chars: 5000, truncated: true })), cardOfAttachment(imageAttachment())],
      },
    ]
    const wrapper = mount(AgentTranscript, { props: { items, kits, conversationId: 'c1' } })

    expect(wrapper.find('.bubble--user').text()).toBe('Veja os anexos.')
    expect(wrapper.findAll('.sent__files .file')).toHaveLength(2)
    expect(wrapper.find('.file__note').text()).toBe('cortado: 800 de 5.000 caracteres')
    expect(wrapper.find('.file__thumb').attributes('src')).toBe('/api/agent/conversations/c1/attachments/a2')
    expect(wrapper.find('.sent__files button').exists()).toBe(false)
  })

  it('a mensagem sem anexo continua só com o balão', () => {
    const wrapper = mount(AgentTranscript, { props: { items: [{ kind: 'user', id: '1', text: 'oi' }], kits } })

    expect(wrapper.find('.sent__files').exists()).toBe(false)
    expect(wrapper.find('.bubble--user').text()).toBe('oi')
  })

  it('a resposta parada leva a marca "interrompida"; a que está chegando leva o cursor', () => {
    const items: ChatItem[] = [
      { kind: 'answer', id: '1', text: 'O cinema,', interrupted: true, streaming: false },
      { kind: 'answer', id: '2', text: 'Escrevendo', interrupted: false, streaming: true },
    ]
    const wrapper = mount(AgentTranscript, { props: { items, kits } })
    const [stopped, live] = wrapper.findAll('.bubble--agent')

    expect(stopped!.text()).toContain('interrompida')
    expect(stopped!.attributes('data-streaming')).toBe('false')
    expect(live!.text()).not.toContain('interrompida')
    expect(live!.attributes('data-streaming')).toBe('true')
  })

  it('repassa o clique da confirmação', async () => {
    const items: ChatItem[] = [
      { kind: 'confirmation', id: '1', confirmationId: 'cf1', tool: 'render_project', question: 'Posso?', type: 'action', state: 'pending' },
    ]
    const wrapper = mount(AgentTranscript, { props: { items, kits } })
    await wrapper.findAll('.ask button')[1]!.trigger('click')

    expect(wrapper.emitted('answer')).toEqual([['cf1', false]])
  })
})
