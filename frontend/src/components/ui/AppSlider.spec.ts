import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppSlider from './AppSlider.vue'

describe('AppSlider', () => {
  it('mostra o valor ao lado, com vírgula decimal, e o diz ao leitor de tela', () => {
    const wrapper = mount(AppSlider, { props: { label: 'Velocidade', modelValue: 1.25, min: 0.5, max: 2, step: 0.05 } })
    const range = wrapper.find('input')
    expect(range.attributes('type')).toBe('range')
    expect(range.attributes('min')).toBe('0.5')
    expect(range.attributes('max')).toBe('2')
    expect(range.attributes('step')).toBe('0.05')
    expect(wrapper.find('output').text()).toBe('1,25')
    expect(range.attributes('aria-valuetext')).toBe('1,25')
    expect(wrapper.find('label').attributes('for')).toBe(range.attributes('id'))
  })

  it('usa o formato dado para escrever o valor', () => {
    const wrapper = mount(AppSlider, {
      props: { label: 'Velocidade', modelValue: 1, min: 0.5, max: 2, step: 0.05, format: (value: number) => `${value.toFixed(2)}x` },
    })
    expect(wrapper.find('output').text()).toBe('1.00x')
  })

  it('avisa o número ao arrastar', async () => {
    const wrapper = mount(AppSlider, { props: { label: 'Velocidade', modelValue: 1, min: 0.5, max: 2, step: 0.05 } })
    await wrapper.find('input').setValue('1.5')
    expect(wrapper.emitted('update:modelValue')).toEqual([[1.5]])
  })

  it('descreve a dica', () => {
    const wrapper = mount(AppSlider, { props: { label: 'Volume', modelValue: 50, min: 0, max: 100, hint: 'Em porcentagem.' } })
    expect(wrapper.text()).toContain('Em porcentagem.')
    expect(wrapper.find('input').attributes('aria-describedby')).toBeTruthy()
  })
})
