import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { useToastsStore } from '@/stores/toasts'
import SegmentsSection from './SegmentsSection.vue'

afterEach(() => vi.unstubAllGlobals())

const cards = (wrapper: Awaited<ReturnType<typeof mountEditorPart>>) => wrapper.findAll('article')
const button = (wrapper: Awaited<ReturnType<typeof mountEditorPart>>, label: string) =>
  wrapper.findAll('button').find((candidate) => candidate.attributes('aria-label') === label || candidate.text() === label)

function manySegments(count: number): Record<string, unknown> {
  return {
    ...projectSpec(),
    timeline: Array.from({ length: count }, (_, i) => ({ type: 'card', title: `cartão ${i}`, duration: 2 })),
  }
}

describe('SegmentsSection', () => {
  it('mostra um cartão por trecho, com o número e um resumo', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    expect(wrapper.find('h3').text()).toBe('Trechos')
    expect(cards(wrapper)).toHaveLength(2)
    expect(cards(wrapper)[0]?.text()).toContain('clip0.mp4')
    expect(cards(wrapper)[1]?.text()).toContain('Fim')
  })

  it('com poucos trechos os cartões começam abertos, com os campos do tipo', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    const clip = cards(wrapper)[0]
    expect(clip?.text()).toContain('Velocidade')
    expect(clip?.text()).toContain('Transição de entrada')
    expect(clip?.text()).toContain('Enquadramento')
    expect(cards(wrapper)[1]?.text()).toContain('Mostrar logo')
  })

  it('com muitos trechos os cartões começam recolhidos e abrem ao clicar', async () => {
    const opened = await openEditor(manySegments(9))
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    expect(cards(wrapper)).toHaveLength(9)
    expect(wrapper.findAll('input')).toHaveLength(0)
    expect(wrapper.text()).toContain('começam recolhidos')
    await cards(wrapper)[2]?.find('.card__toggle').trigger('click')
    expect(cards(wrapper)[2]?.findAll('input').length).toBeGreaterThan(0)
    expect(cards(wrapper)[3]?.findAll('input')).toHaveLength(0)
  })

  it('adiciona um trecho de cada tipo e já o deixa aberto', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    await button(wrapper, 'Adicionar imagem')?.trigger('click')
    const timeline = opened.store.get('timeline') as Array<Record<string, unknown>>
    expect(timeline).toHaveLength(3)
    expect(timeline[2]).toMatchObject({ type: 'image', duration: 3 })
    expect(cards(wrapper)).toHaveLength(3)
    expect(cards(wrapper)[2]?.text()).toContain('Intensidade do movimento')
    expect(opened.store.dirty).toBe(true)
  })

  it('trocar o tipo refaz os campos e leva a transição junto', async () => {
    const spec = projectSpec()
    ;(spec.timeline as Array<Record<string, unknown>>)[0] = {
      type: 'clip',
      src: 'a.mp4',
      label: 'abertura',
      transition: { type: 'fade', duration: 1 },
    }
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    await cards(wrapper)[0]?.find('select').setValue('card')
    expect(opened.store.get('timeline.0')).toMatchObject({
      type: 'card',
      label: 'abertura',
      transition: { type: 'fade', duration: 1 },
    })
    expect(opened.store.get('timeline.0')).not.toHaveProperty('src')
  })

  it('sobe, desce e duplica; o primeiro não sobe e o último não desce', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    expect(button(wrapper, 'Subir o trecho 1')?.attributes('disabled')).toBeDefined()
    expect(button(wrapper, 'Descer o trecho 2')?.attributes('disabled')).toBeDefined()
    await button(wrapper, 'Descer o trecho 1')?.trigger('click')
    expect((opened.store.get('timeline') as Array<Record<string, unknown>>).map((s) => s.type)).toEqual(['card', 'clip'])
    await button(wrapper, 'Duplicar o trecho 1')?.trigger('click')
    expect((opened.store.get('timeline') as unknown[]).length).toBe(3)
    expect(opened.store.get('timeline.0')).toEqual(opened.store.get('timeline.1'))
  })

  it('o cartão que mudou de lugar leva o estado aberto junto', async () => {
    const opened = await openEditor(manySegments(8))
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    await cards(wrapper)[0]?.find('.card__toggle').trigger('click')
    await button(wrapper, 'Descer o trecho 1')?.trigger('click')
    await flushPromises()
    expect(cards(wrapper)[0]?.findAll('input')).toHaveLength(0)
    expect(cards(wrapper)[1]?.findAll('input').length).toBeGreaterThan(0)
  })

  it('remove um trecho, mas nunca o último', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    await button(wrapper, 'Remover o trecho 1')?.trigger('click')
    expect(opened.store.get('timeline') as unknown[]).toHaveLength(1)
    await button(wrapper, 'Remover o trecho 1')?.trigger('click')
    expect(opened.store.get('timeline') as unknown[]).toHaveLength(1)
    expect(useToastsStore(opened.pinia).items.at(-1)?.title).toContain('ao menos um trecho')
  })

  it('o enquadramento "cortar" mostra o foco X e Y, e o par fica completo', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    expect(wrapper.text()).not.toContain('Foco X')
    const mode = cards(wrapper)[0]?.findAll('select').find((select) => select.findAll('option').some((o) => o.text() === 'Cortar'))
    await mode?.setValue('crop')
    expect(wrapper.text()).toContain('Foco X (0 a 1)')
    const focusX = cards(wrapper)[0]?.findAll('input[type="number"]').find((input) => input.attributes('step') === '0.05')
    await focusX?.setValue('0.2')
    expect(opened.store.get('timeline.0.reframe.focus')).toEqual([0.2, 0.5])
  })

  it('um tipo de trecho que o formulário não conhece mostra o aviso e continua removível', async () => {
    const spec = projectSpec()
    ;(spec.timeline as unknown[]).push({ type: 'misterio', x: 1 })
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    expect(cards(wrapper)[2]?.text()).toContain('não tem formulário')
    await button(wrapper, 'Remover o trecho 3')?.trigger('click')
    expect(opened.store.get('timeline') as unknown[]).toHaveLength(2)
  })

  it('a lista de transições vem do catálogo, com o corte seco primeiro', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SegmentsSection, opened)
    const select = cards(wrapper)[0]?.findAll('select').find((s) => s.findAll('option').some((o) => o.text() === 'Corte seco'))
    expect(select?.findAll('option').map((o) => o.text())).toEqual(['Corte seco', 'Fade', 'Dissolve', 'Wipe esquerda'])
  })
})
