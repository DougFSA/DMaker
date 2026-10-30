import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AgentComposer from './AgentComposer.vue'

describe('AgentComposer', () => {
  const mountComposer = (props: Partial<{ busy: boolean; stopping: boolean; ready: boolean; modelValue: string }> = {}, slots = {}) =>
    mount(AgentComposer, {
      props: { placeholder: 'Escreva', busy: false, stopping: false, ready: true, modelValue: 'oi', ...props },
      slots,
    })

  it('Enter envia e Shift+Enter quebra a linha', async () => {
    const wrapper = mountComposer()
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(wrapper.emitted('submit')).toBeUndefined()

    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('submit')).toHaveLength(1)
  })

  it('o botão Enviar só vale com texto e com o modelo pronto', async () => {
    expect(mountComposer().find('button[type="submit"]').attributes('disabled')).toBeUndefined()
    expect(mountComposer({ modelValue: '   ' }).find('button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(mountComposer({ ready: false }).find('button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('respondendo, o botão vira Parar e o clique pede a parada', async () => {
    const wrapper = mountComposer({ busy: true })

    expect(wrapper.find('button[type="submit"]').exists()).toBe(false)
    const stop = wrapper.find('button')
    expect(stop.text()).toBe('Parar')
    await stop.trigger('click')
    expect(wrapper.emitted('stop')).toHaveLength(1)
  })

  it('depois do clique, o botão mostra "Parando..." e não deixa clicar de novo', () => {
    const wrapper = mountComposer({ busy: true, stopping: true })
    const stop = wrapper.find('button')

    expect(stop.text()).toBe('Parando...')
    expect(stop.attributes('disabled')).toBeDefined()
  })

  it('os slots recebem as fichas e os botões que a entrega dos anexos vai pôr', () => {
    const wrapper = mountComposer({}, { above: '<span class="chip">video.mp4</span>', actions: '<button type="button" class="attach">Anexar</button>' })

    expect(wrapper.find('.composer__above .chip').exists()).toBe(true)
    expect(wrapper.find('.composer__actions .attach').exists()).toBe(true)
    expect(mountComposer().find('.composer__above').exists()).toBe(false)
  })
})
