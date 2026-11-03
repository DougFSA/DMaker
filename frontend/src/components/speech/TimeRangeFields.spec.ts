import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TimeRangeFields from './TimeRangeFields.vue'

const inputs = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('input')

describe('TimeRangeFields', () => {
  it('mostra os dois campos com os rótulos padrão e a dica do arquivo inteiro', () => {
    const wrapper = mount(TimeRangeFields)
    expect(wrapper.findAll('label').map((label) => label.text())).toEqual(['Início (s, opcional)', 'Fim (s, opcional)'])
    expect(inputs(wrapper).map((input) => input.attributes('placeholder'))).toEqual(['Começo do arquivo', 'Fim do arquivo'])
  })

  it('aceita outros rótulos e passo', () => {
    const wrapper = mount(TimeRangeFields, { props: { startLabel: 'Transcrever de (s, opcional)', endLabel: 'até (s, opcional)', step: 1 } })
    expect(wrapper.findAll('label').map((label) => label.text())).toEqual(['Transcrever de (s, opcional)', 'até (s, opcional)'])
    expect(inputs(wrapper).map((input) => input.attributes('step'))).toEqual(['1', '1'])
  })

  it('digitar atualiza início e fim; apagar volta para vazio (arquivo inteiro)', async () => {
    const wrapper = mount(TimeRangeFields, { props: { start: null, end: null } })
    await inputs(wrapper)[0]!.setValue('2.5')
    await inputs(wrapper)[1]!.setValue('8')
    expect(wrapper.emitted('update:start')?.at(-1)).toEqual([2.5])
    expect(wrapper.emitted('update:end')?.at(-1)).toEqual([8])
    await inputs(wrapper)[0]!.setValue('')
    expect(wrapper.emitted('update:start')?.at(-1)).toEqual([null])
  })

  it('fim que não vem depois do início aparece como erro no campo do fim', () => {
    const wrapper = mount(TimeRangeFields, { props: { start: 8, end: 3 } })
    expect(wrapper.find('[role="alert"]').text()).toBe('O fim precisa ser maior que o início.')
    expect(inputs(wrapper)[1]!.attributes('aria-invalid')).toBe('true')
  })

  it('intervalo certo ou vazio não mostra erro', () => {
    expect(mount(TimeRangeFields, { props: { start: 1, end: 5 } }).find('[role="alert"]').exists()).toBe(false)
    expect(mount(TimeRangeFields).find('[role="alert"]').exists()).toBe(false)
  })

  it('desligado trava os dois campos', () => {
    const wrapper = mount(TimeRangeFields, { props: { disabled: true } })
    expect(inputs(wrapper).every((input) => input.attributes('disabled') !== undefined)).toBe(true)
  })
})
