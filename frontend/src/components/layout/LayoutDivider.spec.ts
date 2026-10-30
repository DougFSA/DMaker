import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LayoutDivider from './LayoutDivider.vue'

function mountDivider(props: Record<string, unknown> = {}) {
  return mount(LayoutDivider, {
    props: { orientation: 'vertical', label: 'Largura', value: 240, min: 160, max: 560, perPixel: 1, step: 16, ...props },
  })
}

const move = (x: number, y = 0) => window.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: y }))
const release = () => window.dispatchEvent(new MouseEvent('mouseup'))

describe('LayoutDivider', () => {
  it('é um separador com nome, orientação e valor para o leitor de tela', () => {
    const wrapper = mountDivider()
    const divider = wrapper.get('[role="separator"]')
    expect(divider.attributes('aria-orientation')).toBe('vertical')
    expect(divider.attributes('aria-label')).toBe('Largura')
    expect(divider.attributes('aria-valuenow')).toBe('240')
    expect(divider.attributes('aria-valuemin')).toBe('160')
    expect(divider.attributes('aria-valuemax')).toBe('560')
    expect(divider.attributes('tabindex')).toBe('0')
  })

  it('arrastar calcula o valor a partir do ponto onde começou, sem acumular erro', async () => {
    const wrapper = mountDivider()
    await wrapper.get('[role="separator"]').trigger('mousedown', { button: 0, clientX: 100 })
    move(130)
    move(160)
    move(120)
    release()
    expect(wrapper.emitted('resize')).toEqual([[270], [300], [260]])
    expect(wrapper.emitted('commit')).toHaveLength(1)
    expect(wrapper.emitted('drag')).toEqual([[true], [false]])
  })

  it('a barra deitada acompanha o mouse na vertical, na escala dada', async () => {
    const wrapper = mountDivider({ orientation: 'horizontal', value: 0.4, min: 0.1, max: 0.85, perPixel: 0.001, step: 0.02 })
    await wrapper.get('[role="separator"]').trigger('mousedown', { button: 0, clientY: 300 })
    move(0, 400)
    release()
    expect(wrapper.emitted('resize')![0]![0]).toBeCloseTo(0.5, 10)
  })

  it('o divisor da direita cresce quando o mouse vai para a esquerda', async () => {
    const wrapper = mountDivider({ invert: true })
    await wrapper.get('[role="separator"]').trigger('mousedown', { button: 0, clientX: 500 })
    move(450)
    release()
    expect(wrapper.emitted('resize')![0]).toEqual([290])
  })

  it('o valor não passa do mínimo nem do máximo', async () => {
    const wrapper = mountDivider()
    await wrapper.get('[role="separator"]').trigger('mousedown', { button: 0, clientX: 0 })
    move(5000)
    move(-5000)
    release()
    expect(wrapper.emitted('resize')).toEqual([[560], [160]])
  })

  it('só o botão esquerdo arrasta, e depois de soltar o mouse não mexe mais', async () => {
    const wrapper = mountDivider()
    await wrapper.get('[role="separator"]').trigger('mousedown', { button: 2, clientX: 0 })
    move(50)
    expect(wrapper.emitted('resize')).toBeUndefined()
    await wrapper.get('[role="separator"]').trigger('mousedown', { button: 0, clientX: 0 })
    release()
    move(80)
    expect(wrapper.emitted('resize')).toBeUndefined()
  })

  it('marca o divisor enquanto ele está sendo arrastado', async () => {
    const wrapper = mountDivider()
    await wrapper.get('[role="separator"]').trigger('mousedown', { button: 0, clientX: 0 })
    expect(wrapper.classes()).toContain('is-dragging')
    release()
    await wrapper.vm.$nextTick()
    expect(wrapper.classes()).not.toContain('is-dragging')
  })

  it('as setas movem de step em step, e só as do eixo dele', async () => {
    const wrapper = mountDivider()
    const divider = wrapper.get('[role="separator"]')
    await divider.trigger('keydown', { key: 'ArrowRight' })
    await divider.trigger('keydown', { key: 'ArrowLeft' })
    await divider.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.emitted('resize')).toEqual([[256], [224]])
    expect(wrapper.emitted('commit')).toHaveLength(2)
  })

  it('na barra deitada, para baixo aumenta; no divisor da direita, a seta para a esquerda aumenta', async () => {
    const horizontal = mountDivider({ orientation: 'horizontal', value: 0.4, min: 0.1, max: 0.85, step: 0.02 })
    await horizontal.get('[role="separator"]').trigger('keydown', { key: 'ArrowDown' })
    expect(horizontal.emitted('resize')![0]![0]).toBeCloseTo(0.42, 10)

    const right = mountDivider({ invert: true })
    await right.get('[role="separator"]').trigger('keydown', { key: 'ArrowLeft' })
    expect(right.emitted('resize')![0]).toEqual([256])
  })

  it('ao sair da tela no meio do arrasto, solta o mouse e avisa', async () => {
    const wrapper = mountDivider()
    await wrapper.get('[role="separator"]').trigger('mousedown', { button: 0, clientX: 0 })
    wrapper.unmount()
    move(100)
    expect(wrapper.emitted('resize')).toBeUndefined()
  })
})
