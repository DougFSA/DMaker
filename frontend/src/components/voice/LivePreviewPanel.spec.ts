import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LivePreviewPanel from './LivePreviewPanel.vue'

const mountPanel = (props: { status?: string; finished?: boolean; stopped?: boolean } = {}) =>
  mount(LivePreviewPanel, { props: { status: 'Tocando fala 2 de 5', finished: false, ...props } })

describe('LivePreviewPanel', () => {
  it('mostra a frase de andamento como aviso para leitor de tela', () => {
    const wrapper = mountPanel()
    const status = wrapper.find('[role="status"]')
    expect(status.text()).toBe('Tocando fala 2 de 5')
    expect(status.attributes('aria-live')).toBe('polite')
  })

  it('avisa que a prévia é a fala crua e que o arquivo final vem depois', () => {
    const text = mountPanel().text()
    expect(text).toContain('fala crua, sem o acabamento final')
    expect(text).toContain('O arquivo final')
  })

  it('depois de parada a pedido, não promete mais um arquivo final e diz que as falas ficaram guardadas', () => {
    const text = mountPanel({ finished: true, stopped: true }).text()
    expect(text).toContain('não há arquivo final')
    expect(text).toContain('não sintetiza outra vez as falas que já saíram')
    expect(text).not.toContain('aparece abaixo quando o roteiro terminar')
  })

  it('Silenciar prévia avisa a ação', async () => {
    const wrapper = mountPanel()
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('mute')).toHaveLength(1)
  })

  it('depois de silenciada ou parada, o botão não tem mais o que fazer', () => {
    expect(mountPanel({ finished: true }).find('button').attributes('disabled')).toBeDefined()
    expect(mountPanel().find('button').attributes('disabled')).toBeUndefined()
  })
})
