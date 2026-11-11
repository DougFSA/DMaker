import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import type { CurvePoint } from '@/api'
import EqResponseChart from './EqResponseChart.vue'

const CURVE = { hz: [20, 200, 2000, 20000], db: [-12, -6, 0, 0] }
const POINTS: CurvePoint[] = [
  { hz: 20, db: 0 },
  { hz: 1000, db: 0 },
  { hz: 20000, db: 0 },
]
const RANGE = { min: -48, max: 24 }

/** O desenho de 480 x 200 ocupando exatamente a tela de teste: 1 unidade do desenho é 1 pixel. */
function mountChart(props: Record<string, unknown> = {}) {
  const wrapper = mount(EqResponseChart, { props: { curve: CURVE, label: 'Resposta de teste', ...props }, attachTo: document.body })
  const svg = wrapper.find('svg').element as SVGSVGElement
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 480, height: 200, right: 480, bottom: 200, x: 0, y: 0, toJSON: () => ({}) })
  return wrapper
}

/** Dispara o evento com a posição do mouse (o `trigger` do VTU não consegue pôr clientX num MouseEvent). */
async function fire(target: Element, type: string, x = 0, y = 0, extra: MouseEventInit = {}): Promise<void> {
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, ...extra }))
  await nextTick()
}

const hzAtX = (x: number) => 20 * 2 ** ((x / 480) * Math.log2(1000))

describe('EqResponseChart', () => {
  it('desenha a curva do servidor, a grade e os rótulos', () => {
    const wrapper = mountChart()
    expect(wrapper.find('[data-eq-curve]').attributes('d')).toMatch(/^M0\.0 /)
    expect(wrapper.find('svg').attributes('aria-label')).toBe('Resposta de teste')
    expect(wrapper.text()).toContain('1k')
    expect(wrapper.text()).toContain('20k')
    expect(wrapper.findAll('[data-eq-point]')).toHaveLength(0) // sem pontos, só leitura
  })

  it('sem curva ainda não desenha traço', () => {
    expect(mountChart({ curve: null }).find('[data-eq-curve]').exists()).toBe(false)
  })

  it('mostra o ganho sob o cursor', async () => {
    const wrapper = mountChart()
    await fire(wrapper.find('svg').element, 'pointermove', 480 * 0.6, 80)
    expect(wrapper.find('[data-eq-readout]').text()).toMatch(/kHz, \+0,0 dB$/)
  })

  it('arrasta um ponto: avisa a cada passo e grava ao soltar', async () => {
    const wrapper = mountChart({ points: POINTS, range: RANGE })
    const handle = wrapper.find('[data-eq-point="1"]')
    await handle.trigger('pointerdown', { pointerId: 1 })
    // ganho: a faixa de -48 a 24 em 200 de altura -> y = 100 vale -12 dB
    await fire(wrapper.find('svg').element, 'pointermove', 240, 100)
    const updates = wrapper.emitted('update:points') as CurvePoint[][][]
    expect(updates).toHaveLength(1)
    const moved = updates[0]![0]![1]!
    expect(moved.hz).toBeCloseTo(hzAtX(240), -1)
    expect(moved.db).toBeCloseTo(-12, 1)
    expect(wrapper.emitted('commit')).toBeUndefined()
    await wrapper.find('svg').trigger('pointerup')
    expect(wrapper.emitted('commit')).toHaveLength(1)
    await wrapper.find('svg').trigger('pointerup')
    expect(wrapper.emitted('commit')).toHaveLength(1) // soltar sem estar arrastando não grava de novo
  })

  it('clique duplo no fundo acrescenta um ponto no ganho da curva; num ponto, tira', async () => {
    const wrapper = mountChart({ points: POINTS, range: RANGE })
    await fire(wrapper.find('svg').element, 'dblclick', 200, 100)
    const added = (wrapper.emitted('update:points') as CurvePoint[][][])[0]![0]!
    expect(added).toHaveLength(4)
    expect(added.map((point) => point.hz)).toEqual([...added.map((point) => point.hz)].sort((a, b) => a - b))
    expect(wrapper.emitted('commit')).toHaveLength(1)
    await wrapper.find('[data-eq-point="1"]').trigger('dblclick')
    const removed = (wrapper.emitted('update:points') as CurvePoint[][][])[1]![0]!
    expect(removed.map((point) => point.hz)).toEqual([20, 20000])
    expect(wrapper.emitted('commit')).toHaveLength(2)
  })

  it('só leitura: o clique duplo no fundo não faz nada', async () => {
    const wrapper = mountChart()
    await fire(wrapper.find('svg').element, 'dblclick', 200, 100)
    expect(wrapper.emitted('update:points')).toBeUndefined()
  })

  it('as setas movem o ponto em foco: ganho de 1 dB (6 com Shift) e frequência de 1/12 de oitava', async () => {
    const wrapper = mountChart({ points: POINTS, range: RANGE })
    const handle = wrapper.find('[data-eq-point="1"]')
    await handle.trigger('keydown', { key: 'ArrowUp' })
    await handle.trigger('keydown', { key: 'ArrowDown', shiftKey: true })
    await handle.trigger('keydown', { key: 'ArrowRight' })
    const updates = wrapper.emitted('update:points') as CurvePoint[][][]
    expect(updates[0]![0]![1]!.db).toBe(1)
    expect(updates[1]![0]![1]!.db).toBe(-6)
    expect(updates[2]![0]![1]!.hz).toBe(1060) // 1000 * 2^(1/12) = 1059,5, arredondado para 10 em 10
    await handle.trigger('keyup', { key: 'ArrowUp' })
    expect(wrapper.emitted('commit')).toHaveLength(1)
    await handle.trigger('keydown', { key: 'Delete' })
    expect((updates.at(-1) ?? updates[updates.length - 1])!).toBeDefined()
    expect(wrapper.emitted('commit')).toHaveLength(2)
  })

  it('cada ponto diz a frequência e o ganho para o leitor de tela', () => {
    const wrapper = mountChart({ points: [{ hz: 3150, db: 6 }, { hz: 8000, db: -3 }], range: RANGE })
    const first = wrapper.find('[data-eq-point="0"]')
    expect(first.attributes('aria-valuetext')).toBe('3,15 kHz, +6,0 dB')
    expect(first.attributes('role')).toBe('slider')
  })
})
