import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { cardOfAttachment, type AttachmentWarning } from '@/lib/agentAttachments'
import { imageAttachment, textAttachment } from '@/test/agentServer'
import AgentAttachmentTray from './AgentAttachmentTray.vue'

const WARNING: AttachmentWarning = {
  code: 'image_without_vision',
  text: 'O modelo gpt-oss:20b não lê imagem. Escolha um modelo com o selo Imagem: gemma3:4b.',
  models: ['gemma3:4b'],
}

function mountTray(props: Partial<{ cards: ReturnType<typeof cardOfAttachment>[]; warnings: AttachmentWarning[]; notice: string }> = {}) {
  return mount(AgentAttachmentTray, {
    props: { cards: [], warnings: [], notice: '', conversationId: 'c1', ...props },
  })
}

describe('AgentAttachmentTray', () => {
  it('lista uma ficha por arquivo e tira a que a pessoa escolher', async () => {
    const cards = [cardOfAttachment(textAttachment()), cardOfAttachment(imageAttachment())]
    const wrapper = mountTray({ cards })

    expect(wrapper.findAll('.file')).toHaveLength(2)
    await wrapper.find('button[aria-label="Remover foto.png"]').trigger('click')
    expect(wrapper.emitted('remove')).toEqual([[cards[1]]])
  })

  it('o aviso de imagem aparece com os modelos que resolvem, e o clique escolhe o modelo', async () => {
    const wrapper = mountTray({ cards: [cardOfAttachment(imageAttachment())], warnings: [WARNING] })

    expect(wrapper.find('[data-code="image_without_vision"]').text()).toContain('não lê imagem')
    const use = wrapper.find('[data-code="image_without_vision"] button')
    expect(use.text()).toBe('Usar gemma3:4b')
    await use.trigger('click')
    expect(wrapper.emitted('use-model')).toEqual([['gemma3:4b']])
  })

  it('o aviso sem modelo que resolva não tem botão', () => {
    const wrapper = mountTray({ warnings: [{ ...WARNING, models: [] }] })

    expect(wrapper.find('[data-code="image_without_vision"] button').exists()).toBe(false)
  })

  it('mostra o que a tela recusou ao escolher os arquivos', () => {
    const wrapper = mountTray({ notice: 'Uma mensagem leva no máximo 8 anexos. Não anexei: f9.txt.' })

    expect(wrapper.find('[data-code="notice"]').text()).toContain('Não anexei: f9.txt')
    expect(wrapper.find('.tray__files').exists()).toBe(false)
  })
})
