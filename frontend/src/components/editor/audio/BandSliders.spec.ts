import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { BAND_LABELS } from '@/test/eqFixtures'
import BandSliders from './BandSliders.vue'

const flat = () => new Array<number>(31).fill(0)

function mountSliders(gains = flat()) {
  return mount(BandSliders, { props: { modelValue: gains, labels: BAND_LABELS, minimum: -20, maximum: 20, name: 'EQ gráfico' } })
}

const slider = (wrapper: ReturnType<typeof mountSliders>, band: number) => wrapper.find(`[data-band="${band}"]`)

describe('BandSliders', () => {
  it('mostra um controle por banda, de 20 Hz a 20 kHz, de -20 a +20 dB', () => {
    const wrapper = mountSliders()
    const sliders = wrapper.findAll('input[type="range"]')
    expect(sliders).toHaveLength(31)
    expect(sliders[0]!.attributes('min')).toBe('-20')
    expect(sliders[0]!.attributes('max')).toBe('20')
    expect(sliders[0]!.attributes('aria-label')).toBe('EQ gráfico: banda de 20 Hz')
    expect(sliders[22]!.attributes('aria-label')).toBe('EQ gráfico: banda de 3,15 kHz')
    expect(wrapper.findAll('.bands__label').map((label) => label.text()).slice(0, 3)).toEqual(['20', '25', '31.5'])
  })

  it('mexer num controle muda só aquela banda, em meio dB, e avisa ao soltar', async () => {
    const wrapper = mountSliders()
    const input = slider(wrapper, 22).element as HTMLInputElement
    input.value = '6.2'
    await slider(wrapper, 22).trigger('input')
    const updates = wrapper.emitted('update:modelValue') as number[][][]
    const gains = updates[0]![0]!
    expect(gains[22]).toBe(6)
    expect(gains.filter((gain) => gain !== 0)).toHaveLength(1)
    expect(wrapper.emitted('commit')).toBeUndefined() // o `input` do setValue não é o soltar
    await slider(wrapper, 22).trigger('change')
    expect(wrapper.emitted('commit')).toHaveLength(1)
  })

  it('clique duplo leva a banda a 0 dB e grava; Zerar leva todas', async () => {
    const gains = flat()
    gains[5] = -4
    gains[22] = 6
    const wrapper = mountSliders(gains)
    await slider(wrapper, 5).trigger('dblclick')
    expect((wrapper.emitted('update:modelValue') as number[][][])[0]![0]![5]).toBe(0)
    expect(wrapper.emitted('commit')).toHaveLength(1)
    await wrapper.find('[data-band-reset]').trigger('click')
    expect((wrapper.emitted('update:modelValue') as number[][][]).at(-1)![0]!.every((gain) => gain === 0)).toBe(true)
    expect(wrapper.emitted('commit')).toHaveLength(2)
  })

  it('Zerar fica desligado quando tudo já está em zero, e o texto diz a banda sob o ponteiro', async () => {
    const wrapper = mountSliders()
    expect(wrapper.find('[data-band-reset]').attributes('disabled')).toBeDefined()
    await wrapper.findAll('.bands__band')[22]!.trigger('pointerenter')
    expect(wrapper.find('[data-band-readout]').text()).toBe('Banda de 3,15 kHz: +0,0 dB')
    await wrapper.findAll('.bands__band')[22]!.trigger('pointerleave')
    expect(wrapper.find('[data-band-readout]').text()).toContain('clique duas vezes')
  })
})
