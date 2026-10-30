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

  it('com anexo, a mensagem pode seguir sem texto', () => {
    const wrapper = mount(AgentComposer, {
      props: { placeholder: 'Escreva', busy: false, stopping: false, ready: true, modelValue: '', hasAttachments: true },
    })

    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('sem texto e sem anexo, não envia', () => {
    expect(mountComposer({ modelValue: '' }).find('button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('colar uma imagem anexa o arquivo e não cola o nome dele como texto', async () => {
    const wrapper = mountComposer()
    const print = new File(['x'], 'image.png', { type: 'image/png' })
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { files: [print] } })
    wrapper.find('textarea').element.dispatchEvent(event)

    expect(wrapper.emitted('attach')).toEqual([[[print]]])
    expect(event.defaultPrevented).toBe(true)
  })

  it('colar só texto segue como texto', async () => {
    const wrapper = mountComposer()
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { files: [], getData: () => 'um texto' } })
    wrapper.find('textarea').element.dispatchEvent(event)

    expect(wrapper.emitted('attach')).toBeUndefined()
    expect(event.defaultPrevented).toBe(false)
  })

  it('soltar arquivos na caixa os anexa, e arrastar sobre ela a destaca até sair', async () => {
    const wrapper = mountComposer()
    const form = wrapper.find('form')
    const dropped = new File(['x'], 'aula.mp4', { type: 'video/mp4' })

    await form.trigger('dragover', { dataTransfer: { types: ['Files'] } })
    expect(form.classes()).toContain('composer--dropping')
    await form.trigger('dragleave', { relatedTarget: null })
    expect(form.classes()).not.toContain('composer--dropping')

    await form.trigger('dragover', { dataTransfer: { types: ['Files'] } })
    await form.trigger('drop', { dataTransfer: { files: [dropped], types: ['Files'] } })
    expect(wrapper.emitted('attach')).toEqual([[[dropped]]])
    expect(form.classes()).not.toContain('composer--dropping')
  })

  it('arrastar texto (não arquivo) sobre a caixa não a destaca', async () => {
    const wrapper = mountComposer()
    await wrapper.find('form').trigger('dragover', { dataTransfer: { types: ['text/plain'] } })

    expect(wrapper.find('form').classes()).not.toContain('composer--dropping')
  })

  it('soltar arquivos já tratados por quem está dentro da caixa (o botão Anexar) não anexa duas vezes', async () => {
    const wrapper = mountComposer({}, { actions: '<span class="inner" />' })
    const dropped = new File(['x'], 'a.png')
    const inner = wrapper.find('.inner').element
    inner.addEventListener('drop', (event) => event.preventDefault())
    await wrapper.find('.inner').trigger('drop', { dataTransfer: { files: [dropped], types: ['Files'] } })

    expect(wrapper.emitted('attach')).toBeUndefined()
  })

  it('os slots recebem as fichas e os botões que a entrega dos anexos vai pôr', () => {
    const wrapper = mountComposer({}, { above: '<span class="chip">video.mp4</span>', actions: '<button type="button" class="attach">Anexar</button>' })

    expect(wrapper.find('.composer__above .chip').exists()).toBe(true)
    expect(wrapper.find('.composer__actions .attach').exists()).toBe(true)
    expect(mountComposer().find('.composer__above').exists()).toBe(false)
  })
})
