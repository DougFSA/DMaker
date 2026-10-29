import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppInput from './AppInput.vue'
import AppNumberInput from './AppNumberInput.vue'

describe('AppInput', () => {
  it('mostra o valor e avisa cada digitação', async () => {
    const wrapper = mount(AppInput, { props: { label: 'Nome da voz', modelValue: 'Ana' } })
    const input = wrapper.find('input')
    expect(input.element.value).toBe('Ana')
    expect(wrapper.find('label').text()).toBe('Nome da voz')
    await input.setValue('Ana Maria')
    expect(wrapper.emitted('update:modelValue')).toEqual([['Ana Maria']])
  })

  it('passa dica, erro, placeholder e limite ao campo', () => {
    const wrapper = mount(AppInput, {
      props: {
        label: 'Nome',
        modelValue: '',
        hint: 'Aparece na lista.',
        error: 'Informe um nome.',
        placeholder: 'Ex.: Ana',
        maxlength: 40,
        required: true,
        type: 'search',
      },
    })
    const input = wrapper.find('input')
    expect(input.attributes('placeholder')).toBe('Ex.: Ana')
    expect(input.attributes('maxlength')).toBe('40')
    expect(input.attributes('type')).toBe('search')
    expect(input.attributes('required')).toBeDefined()
    expect(input.attributes('aria-invalid')).toBe('true')
    expect(wrapper.text()).toContain('Informe um nome.')
    expect(wrapper.text()).toContain('Aparece na lista.')
  })

  it('desabilitado não aceita digitação', () => {
    const wrapper = mount(AppInput, { props: { label: 'Nome', modelValue: 'x', disabled: true } })
    expect(wrapper.find('input').attributes('disabled')).toBeDefined()
  })
})

describe('AppNumberInput', () => {
  it('entrega um número, e null quando o campo fica vazio', async () => {
    const wrapper = mount(AppNumberInput, { props: { label: 'Início', modelValue: null } })
    const input = wrapper.find('input')
    expect(input.attributes('type')).toBe('number')
    await input.setValue('3.5')
    await input.setValue('')
    expect(wrapper.emitted('update:modelValue')).toEqual([[3.5], [null]])
  })

  it('mostra o valor atual e vazio quando é null', () => {
    expect(mount(AppNumberInput, { props: { label: 'Início', modelValue: 12 } }).find('input').element.value).toBe('12')
    expect(mount(AppNumberInput, { props: { label: 'Início', modelValue: null } }).find('input').element.value).toBe('')
  })

  it('passa limites, passo e unidade', () => {
    const wrapper = mount(AppNumberInput, {
      props: { label: 'Volume', modelValue: -18, min: -60, max: 0, step: 1, unit: 'dB', hint: 'Zero ou negativo.' },
    })
    const input = wrapper.find('input')
    expect(input.attributes('min')).toBe('-60')
    expect(input.attributes('max')).toBe('0')
    expect(input.attributes('step')).toBe('1')
    expect(wrapper.find('.number__unit').text()).toBe('dB')
    expect(wrapper.text()).toContain('Zero ou negativo.')
  })
})
