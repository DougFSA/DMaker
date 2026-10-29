import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppSelect from './AppSelect.vue'

const options = [
  { value: 'pt', label: 'Português' },
  { value: 'en', label: 'Inglês' },
  { value: 'fr', label: 'Francês', disabled: true },
]

describe('AppSelect', () => {
  it('lista as opções com o rótulo ligado ao select', () => {
    const wrapper = mount(AppSelect, { props: { label: 'Idioma', modelValue: 'pt', options } })
    expect(wrapper.find('label').attributes('for')).toBe(wrapper.find('select').attributes('id'))
    expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['Português', 'Inglês', 'Francês'])
    expect(wrapper.findAll('option')[2]?.attributes('disabled')).toBeDefined()
    expect(wrapper.find('select').element.value).toBe('pt')
  })

  it('avisa a opção escolhida', async () => {
    const wrapper = mount(AppSelect, { props: { label: 'Idioma', modelValue: 'pt', options } })
    await wrapper.find('select').setValue('en')
    expect(wrapper.emitted('update:modelValue')).toEqual([['en']])
  })

  it('com texto de espaço reservado, ganha uma primeira opção vazia', async () => {
    const wrapper = mount(AppSelect, {
      props: { label: 'Voz', modelValue: 'ana', options: [{ value: 'ana', label: 'Ana' }], placeholder: 'Voz automática' },
    })
    const first = wrapper.findAll('option')[0]
    expect(first?.text()).toBe('Voz automática')
    expect(first?.element.value).toBe('')
    await wrapper.find('select').setValue('')
    expect(wrapper.emitted('update:modelValue')).toEqual([['']])
  })

  it('sem espaço reservado não cria a opção vazia', () => {
    const wrapper = mount(AppSelect, { props: { label: 'Idioma', modelValue: 'pt', options } })
    expect(wrapper.findAll('option')).toHaveLength(3)
  })

  it('mantém a escolha quando as opções chegam depois (lista de vozes carregada pela rede)', async () => {
    const wrapper = mount(AppSelect, { props: { label: 'Voz', modelValue: 'ana', options: [] } })
    await wrapper.setProps({ options: [{ value: 'bia', label: 'Bia' }, { value: 'ana', label: 'Ana' }] })
    expect(wrapper.find('select').element.value).toBe('ana')
  })

  it('descreve dica e erro e marca o campo inválido', () => {
    const wrapper = mount(AppSelect, {
      props: { label: 'Idioma', modelValue: '', options, hint: 'O da fala.', error: 'Escolha um idioma.' },
    })
    expect(wrapper.find('select').attributes('aria-invalid')).toBe('true')
    expect(wrapper.text()).toContain('Escolha um idioma.')
    expect(wrapper.text()).toContain('O da fala.')
  })
})
