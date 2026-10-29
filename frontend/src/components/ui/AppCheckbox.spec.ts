import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppCheckbox from './AppCheckbox.vue'

describe('AppCheckbox', () => {
  it('reflete o valor e avisa quando a pessoa marca', async () => {
    const wrapper = mount(AppCheckbox, { props: { label: 'Rascunho', modelValue: false } })
    const box = wrapper.find('input')
    expect(box.element.checked).toBe(false)
    await box.setValue(true)
    expect(wrapper.emitted('update:modelValue')).toEqual([[true]])
  })

  it('o texto do rótulo marca e desmarca (rótulo ligado ao campo)', () => {
    const wrapper = mount(AppCheckbox, { props: { label: 'Rascunho', modelValue: true } })
    expect(wrapper.find('label').attributes('for')).toBe(wrapper.find('input').attributes('id'))
    expect(wrapper.find('label').text()).toBe('Rascunho')
    expect(wrapper.find('input').element.checked).toBe(true)
  })

  it('descreve a dica ao leitor de tela', () => {
    const wrapper = mount(AppCheckbox, { props: { label: 'Tenho permissão', modelValue: false, hint: 'Obrigatório para clonar.' } })
    const describedBy = wrapper.find('input').attributes('aria-describedby')
    expect(wrapper.find(`#${describedBy}`).text()).toBe('Obrigatório para clonar.')
  })

  it('desabilitada não muda', () => {
    const wrapper = mount(AppCheckbox, { props: { label: 'x', modelValue: false, disabled: true } })
    expect(wrapper.find('input').attributes('disabled')).toBeDefined()
  })
})
