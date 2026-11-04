import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { CarrierValue } from '@/api'
import CarrierControl from './CarrierControl.vue'

const sawtooth: CarrierValue = { generator: 'tone', params: { waveform: 'sawtooth', frequency_hz: 110, amplitude_db: -6 } }

function mountControl(modelValue: CarrierValue = sawtooth) {
  return mount(CarrierControl, { props: { modelValue, label: 'Portadora' } })
}

describe('CarrierControl', () => {
  it('mostra a onda e a frequência do Tom, com o que a spec guarda', () => {
    const wrapper = mountControl()
    expect((wrapper.find('[data-carrier="waveform"] select').element as HTMLSelectElement).value).toBe('sawtooth')
    expect((wrapper.find('[data-carrier="frequency"] input').element as HTMLInputElement).value).toBe('110')
  })

  it('trocar a onda grava a portadora inteira, sem perder os outros parâmetros do gerador', async () => {
    const wrapper = mountControl()
    await wrapper.find('[data-carrier="waveform"] select').setValue('square')
    expect(wrapper.emitted('commit')).toEqual([[{ generator: 'tone', params: { waveform: 'square', frequency_hz: 110, amplitude_db: -6 } }]])
  })

  it('a frequência só grava ao sair do campo, limitada à faixa do gerador', async () => {
    const wrapper = mountControl()
    const input = wrapper.find('[data-carrier="frequency"] input')
    await input.setValue('140')
    expect(wrapper.emitted('commit')).toBeUndefined()
    await input.trigger('focusout')
    expect(wrapper.emitted('commit')).toEqual([[{ generator: 'tone', params: { waveform: 'sawtooth', frequency_hz: 140, amplitude_db: -6 } }]])
    await input.setValue('99999')
    await input.trigger('focusout')
    expect((wrapper.emitted('commit') as CarrierValue[][]).at(-1)![0]!.params.frequency_hz).toBe(20000)
  })

  it('outro gerador aparece só como texto: a tela não o edita', () => {
    const wrapper = mountControl({ generator: 'noise', params: { noise_type: 'pink' } })
    expect(wrapper.find('[data-carrier="other"]').text()).toContain('noise')
    expect(wrapper.find('select').exists()).toBe(false)
  })
})
