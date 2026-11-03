import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppTabs from './AppTabs.vue'

const items = [
  { value: 'arquivo', label: 'Por arquivo' },
  { value: 'microfone', label: 'Por microfone' },
  { value: 'bloqueada', label: 'Bloqueada', disabled: true },
]

function mountTabs(modelValue = 'arquivo') {
  return mount(AppTabs, {
    props: { items, modelValue, label: 'Como clonar' },
    slots: {
      arquivo: '<p>Painel do arquivo</p>',
      microfone: '<p>Painel do microfone</p>',
      bloqueada: '<p>Nunca aparece</p>',
    },
  })
}

describe('AppTabs', () => {
  it('é uma lista de abas com nome e a aba escolhida marcada', () => {
    const wrapper = mountTabs()
    expect(wrapper.find('[role="tablist"]').attributes('aria-label')).toBe('Como clonar')
    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs.map((tab) => tab.text())).toEqual(['Por arquivo', 'Por microfone', 'Bloqueada'])
    expect(tabs[0]?.attributes('aria-selected')).toBe('true')
    expect(tabs[1]?.attributes('aria-selected')).toBe('false')
  })

  it('mostra só o painel da aba escolhida', () => {
    const wrapper = mountTabs()
    expect(wrapper.text()).toContain('Painel do arquivo')
    expect(wrapper.text()).not.toContain('Painel do microfone')
  })

  it('clicar noutra aba avisa a escolha', async () => {
    const wrapper = mountTabs()
    await wrapper.findAll('[role="tab"]')[1]?.trigger('mousedown', { button: 0 })
    expect(wrapper.emitted('update:modelValue')).toEqual([['microfone']])
  })

  it('a aba desabilitada não é escolhida', async () => {
    const wrapper = mountTabs()
    const blocked = wrapper.findAll('[role="tab"]')[2]
    expect(blocked?.attributes('disabled')).toBeDefined()
    await blocked?.trigger('mousedown', { button: 0 })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('o painel mostrado acompanha o valor', async () => {
    const wrapper = mountTabs()
    await wrapper.setProps({ modelValue: 'microfone' })
    await flushPromises()
    expect(wrapper.text()).toContain('Painel do microfone')
    expect(wrapper.text()).not.toContain('Painel do arquivo')
  })
})
