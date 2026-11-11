import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { spectrumAnalysis } from '@/test/spectrumFixtures'
import SpectrumPlot from './SpectrumPlot.vue'

afterEach(() => vi.restoreAllMocks())

const readout = (wrapper: ReturnType<typeof mount>) => wrapper.find('[data-spectrum-readout]').text()

/** O jsdom não tem layout: o SVG ganha uma caixa de 640 px de largura para o ponteiro virar frequência. */
function sizedSvg(wrapper: ReturnType<typeof mount>): HTMLElement {
  const svg = wrapper.find('[data-spectrum-plot]').element as unknown as SVGSVGElement
  vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 640, height: 300 } as DOMRect)
  return svg as unknown as HTMLElement
}

describe('SpectrumPlot', () => {
  it('começa com o cursor no pico e mostra a frequência, a nota e o nível', () => {
    const wrapper = mount(SpectrumPlot, { props: { analysis: spectrumAnalysis() } })
    expect(readout(wrapper)).toBe('1 kHz · Si5 +21 cents · -6,0 dB')
    expect(wrapper.find('[data-spectrum-curve]').attributes('d')).toMatch(/^M[\d. ]+L/)
    expect(wrapper.find('[data-spectrum-plot]').attributes('aria-label')).toContain('Pico do espectro')
  })

  it('o ponteiro move o cursor e a leitura segue a frequência sob ele', async () => {
    const wrapper = mount(SpectrumPlot, { props: { analysis: spectrumAnalysis() } })
    const svg = sizedSvg(wrapper)
    // 48 e 628 são as pontas da área (esquerda e direita); no eixo logarítmico o meio é a média geométrica: ~694 Hz
    svg.dispatchEvent(Object.assign(new Event('pointermove'), { clientX: (48 + 628) / 2 }))
    await wrapper.vm.$nextTick()
    const text = readout(wrapper)
    const hz = Number(text.split(' ')[0]?.replace(',', '.'))
    expect(hz).toBeGreaterThan(600)
    expect(hz).toBeLessThan(800)
    expect(text).toContain('Fá')
  })

  it('as setas andam o cursor, Home e End vão às pontas e P volta ao pico', async () => {
    const wrapper = mount(SpectrumPlot, { props: { analysis: spectrumAnalysis() } })
    const svg = wrapper.find('[data-spectrum-plot]')
    await svg.trigger('keydown', { key: 'ArrowRight' })
    const right = readout(wrapper)
    expect(right).not.toBe('1 kHz · Si5 +21 cents · -6,0 dB')
    await svg.trigger('keydown', { key: 'ArrowLeft' })
    await svg.trigger('keydown', { key: 'ArrowLeft' })
    expect(readout(wrapper)).not.toBe(right)
    await svg.trigger('keydown', { key: 'Home' })
    expect(readout(wrapper)).toContain('20 Hz')
    await svg.trigger('keydown', { key: 'End' })
    expect(readout(wrapper)).toContain('24 kHz')
    await svg.trigger('keydown', { key: 'p' })
    expect(readout(wrapper)).toBe('1 kHz · Si5 +21 cents · -6,0 dB')
  })

  it('uma análise nova leva o cursor de volta ao pico dela', async () => {
    const wrapper = mount(SpectrumPlot, { props: { analysis: spectrumAnalysis() } })
    await wrapper.find('[data-spectrum-plot]').trigger('keydown', { key: 'Home' })
    await wrapper.setProps({ analysis: spectrumAnalysis({ peak_hz: 500, peak_note: 'Si4' }) })
    expect(readout(wrapper)).toContain('500 Hz')
  })

  it('o eixo linear redesenha a grade em números redondos', async () => {
    const wrapper = mount(SpectrumPlot, { props: { analysis: spectrumAnalysis({ axis: 'linear' }) } })
    const labels = wrapper.findAll('.plot__grid text').map((node) => node.text())
    expect(labels).toContain('0')
    expect(labels).toContain('5k')
  })
})
