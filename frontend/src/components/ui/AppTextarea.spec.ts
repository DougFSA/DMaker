import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppTextarea from './AppTextarea.vue'

describe('AppTextarea', () => {
  it('mostra o texto e avisa cada mudança', async () => {
    const wrapper = mount(AppTextarea, { props: { label: 'Roteiro', modelValue: 'Olá' } })
    const area = wrapper.find('textarea')
    expect(area.element.value).toBe('Olá')
    expect(wrapper.find('label').attributes('for')).toBe(area.attributes('id'))
    await area.setValue('Olá, mundo')
    expect(wrapper.emitted('update:modelValue')).toEqual([['Olá, mundo']])
  })

  it('usa as linhas pedidas', () => {
    expect(mount(AppTextarea, { props: { label: 'x', modelValue: '', rows: 9 } }).find('textarea').attributes('rows')).toBe(
      '9',
    )
  })

  it('com limite, conta os caracteres e trava no máximo', () => {
    const wrapper = mount(AppTextarea, { props: { label: 'Roteiro', modelValue: 'abcd', maxlength: 20000 } })
    expect(wrapper.find('textarea').attributes('maxlength')).toBe('20000')
    expect(wrapper.find('.textarea__count').text()).toBe('4 de 20000 caracteres')
  })

  it('sem limite não mostra contagem', () => {
    expect(mount(AppTextarea, { props: { label: 'x', modelValue: 'abc' } }).find('.textarea__count').exists()).toBe(false)
  })

  it('descreve a dica e o erro', () => {
    const wrapper = mount(AppTextarea, {
      props: { label: 'Roteiro', modelValue: '', hint: 'Use [pausa 1.2] para pausar.', error: 'Escreva o texto.' },
    })
    expect(wrapper.find('textarea').attributes('aria-invalid')).toBe('true')
    expect(wrapper.text()).toContain('Use [pausa 1.2] para pausar.')
    expect(wrapper.text()).toContain('Escreva o texto.')
  })
})
