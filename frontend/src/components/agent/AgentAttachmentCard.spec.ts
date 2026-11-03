import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { cardOfAttachment, failedCard, uploadingCard } from '@/lib/agentAttachments'
import { imageAttachment, mediaAttachment, textAttachment } from '@/test/agentServer'
import AgentAttachmentCard from './AgentAttachmentCard.vue'

function mountCard(card: ReturnType<typeof cardOfAttachment>, props: Record<string, unknown> = {}) {
  return mount(AgentAttachmentCard, { props: { card, conversationId: 'c1', ...props } })
}

describe('AgentAttachmentCard', () => {
  it('mostra o nome, o tipo e o tamanho do documento', () => {
    const wrapper = mountCard(cardOfAttachment(textAttachment({ size: 20480 })))

    expect(wrapper.find('.file__name').text()).toBe('roteiro.docx')
    expect(wrapper.find('.file__meta').text()).toBe('Documento · 20 KB')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.file__note').exists()).toBe(false)
  })

  it('o texto cortado diz quantos caracteres vão ao modelo', () => {
    const wrapper = mountCard(cardOfAttachment(textAttachment({ chars: 12400, total_chars: 38000, truncated: true })))

    expect(wrapper.find('.file__note').text()).toBe('cortado: 12.400 de 38.000 caracteres')
  })

  it('a imagem mostra a miniatura da conversa, e não do /api/file', () => {
    const wrapper = mountCard(cardOfAttachment(imageAttachment()))
    const thumb = wrapper.find('img.file__thumb')

    expect(thumb.attributes('src')).toBe('/api/agent/conversations/c1/attachments/a2')
    expect(thumb.attributes('src')).not.toContain('/api/file')
    expect(thumb.attributes('alt')).toBe('Miniatura de foto.png')
  })

  it('a miniatura que não carrega volta ao ícone', async () => {
    const wrapper = mountCard(cardOfAttachment(imageAttachment()))
    await wrapper.find('img').trigger('error')

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.file__icon').exists()).toBe(true)
  })

  it('sem a conversa não há miniatura', () => {
    expect(mountCard(cardOfAttachment(imageAttachment()), { conversationId: null }).find('img').exists()).toBe(false)
  })

  it('vídeo e planilha mostram o ícone do tipo', () => {
    const video = mountCard(cardOfAttachment(mediaAttachment()))
    expect(video.find('.file__meta').text()).toBe('Vídeo · 4 MB')
    expect(video.attributes('data-kind')).toBe('media')
    expect(mountCard(cardOfAttachment({ id: 'a5', kind: 'sheet', name: 'semana.csv', size: 10 })).find('.file__meta').text()).toBe('Planilha · 10 B')
  })

  it('enquanto sobe, diz "Enviando..." e não deixa tirar', () => {
    const wrapper = mountCard(uploadingCard('k1', { name: 'aula.mp4', size: 2048 }), { removable: true })

    expect(wrapper.find('.file__meta').text()).toBe('Enviando...')
    expect(wrapper.attributes('data-state')).toBe('uploading')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('o arquivo que o servidor recusou mostra o motivo e deixa tirar a ficha', async () => {
    const wrapper = mountCard(failedCard(uploadingCard('k1', { name: 'programa.exe', size: 5 }), 'Formato desconhecido: aceito imagem, vídeo e texto.'), { removable: true })

    expect(wrapper.find('[role="alert"]').text()).toBe('Formato desconhecido: aceito imagem, vídeo e texto.')
    await wrapper.find('button[aria-label="Remover programa.exe"]').trigger('click')
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })

  it('só tem o botão de tirar quando a ficha é removível (a da mensagem enviada não é)', () => {
    expect(mountCard(cardOfAttachment(textAttachment()), { removable: true }).find('button').exists()).toBe(true)
    expect(mountCard(cardOfAttachment(textAttachment())).find('button').exists()).toBe(false)
  })
})
