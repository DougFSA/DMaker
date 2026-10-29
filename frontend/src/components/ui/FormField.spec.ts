import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import FormField from './FormField.vue'

function mountField(props: Record<string, unknown>) {
  return mount(FormField, {
    props: { label: 'Nome', ...props },
    slots: {
      default: (slot: { id: string; describedBy?: string; invalid: boolean }) =>
        h('input', {
          id: slot.id,
          'aria-describedby': slot.describedBy,
          'aria-invalid': slot.invalid ? 'true' : undefined,
        }),
    },
  })
}

describe('FormField', () => {
  it('liga o rótulo ao campo pelo mesmo id', () => {
    const wrapper = mountField({})
    const input = wrapper.find('input')
    expect(wrapper.find('label').attributes('for')).toBe(input.attributes('id'))
    expect(wrapper.find('label').text()).toBe('Nome')
  })

  it('usa o id dado no lugar do gerado', () => {
    const wrapper = mountField({ id: 'meu-campo' })
    expect(wrapper.find('input').attributes('id')).toBe('meu-campo')
    expect(wrapper.find('label').attributes('for')).toBe('meu-campo')
  })

  it('dois campos na mesma página nunca dividem o mesmo id', () => {
    const Page = defineComponent({
      render: () =>
        h('div', [
          h(FormField, { label: 'A' }, { default: (slot: { id: string }) => h('input', { id: slot.id }) }),
          h(FormField, { label: 'B' }, { default: (slot: { id: string }) => h('input', { id: slot.id }) }),
        ]),
    })
    const [first, second] = mount(Page)
      .findAll('input')
      .map((input) => input.attributes('id'))
    expect(first).toBeTruthy()
    expect(first).not.toBe(second)
  })

  it('a dica e o erro são descritos ao leitor de tela, o erro primeiro', () => {
    const wrapper = mountField({ hint: 'Até 20 mil caracteres.', error: 'Escreva o texto.' })
    const described = wrapper.find('input').attributes('aria-describedby') ?? ''
    const [errorId, hintId] = described.split(' ')
    expect(wrapper.find(`#${errorId}`).text()).toBe('Escreva o texto.')
    expect(wrapper.find(`#${errorId}`).attributes('role')).toBe('alert')
    expect(wrapper.find(`#${hintId}`).text()).toBe('Até 20 mil caracteres.')
    expect(wrapper.find('input').attributes('aria-invalid')).toBe('true')
  })

  it('sem dica nem erro não descreve nada', () => {
    const wrapper = mountField({})
    expect(wrapper.find('input').attributes('aria-describedby')).toBeUndefined()
    expect(wrapper.find('.field-hint').exists()).toBe(false)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('marca o obrigatório só na tela, sem mudar o nome lido pelo leitor', () => {
    const wrapper = mountField({ required: true })
    const mark = wrapper.find('.field-required')
    expect(mark.text()).toBe('*')
    expect(mark.attributes('aria-hidden')).toBe('true')
  })

  it('esconde o rótulo na tela mantendo-o para o leitor', () => {
    const wrapper = mountField({ hideLabel: true })
    expect(wrapper.find('label').classes()).toContain('visually-hidden')
  })
})
