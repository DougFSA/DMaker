import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { projectSpec, timelineItem, timelineTrack, timelineView } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import MarkersSection from './MarkersSection.vue'

afterEach(() => vi.unstubAllGlobals())

type Mounted = Awaited<ReturnType<typeof mountEditorPart>>
const rows = (wrapper: Mounted) => wrapper.findAll('.marker__summary')
const button = (wrapper: Mounted, label: string) =>
  wrapper.findAll('button').find((candidate) => candidate.attributes('aria-label') === label || candidate.text() === label)

const MARKERS = [
  { at: 12.5, text: 'refrão', color: '#e0a020' },
  { start: 20, end: 30.25, text: '', group: 'meus' },
]

function withMarkers(markers: unknown[]): Record<string, unknown> {
  return { ...projectSpec(), markers }
}

describe('MarkersSection', () => {
  it('mostra um bloco por marcador: o texto, o tempo (com vírgula) e o grupo, e "sem texto" quando falta', async () => {
    const opened = await openEditor(withMarkers(MARKERS))
    const wrapper = await mountEditorPart(MarkersSection, opened)
    expect(rows(wrapper)).toHaveLength(2)
    expect(rows(wrapper)[0]?.text()).toContain('refrão')
    expect(rows(wrapper)[0]?.text()).toContain('12,5 s')
    expect(rows(wrapper)[1]?.text()).toContain('sem texto')
    expect(rows(wrapper)[1]?.text()).toContain('20 a 30,25 s')
    expect(rows(wrapper)[1]?.text()).toContain('meus')
    expect(wrapper.text()).toContain('Marcadores')
  })

  it('sem marcadores, diz como criar um e que eles acompanham os cortes', async () => {
    const opened = await openEditor(withMarkers([]))
    const wrapper = await mountEditorPart(MarkersSection, opened)
    expect(rows(wrapper)).toHaveLength(0)
    expect(wrapper.text()).toContain('Aperte M')
    expect(wrapper.text()).toContain('acompanham os cortes')
  })

  it('o instante tem um campo de tempo, e a região tem início e fim', async () => {
    const opened = await openEditor(withMarkers(MARKERS))
    const wrapper = await mountEditorPart(MarkersSection, opened)
    const bodies = wrapper.findAll('.marker__body')
    expect(bodies[0]?.text()).toContain('Instante (s)')
    expect(bodies[0]?.text()).not.toContain('Início (s)')
    expect(bodies[1]?.text()).toContain('Início (s)')
    expect(bodies[1]?.text()).toContain('Fim (s)')
  })

  it('editar o texto vai para o marcador certo da spec, em um passo do desfazer', async () => {
    const opened = await openEditor(withMarkers(MARKERS))
    const wrapper = await mountEditorPart(MarkersSection, opened)
    const text = wrapper.findAll('.marker__body')[1]?.findAll('input')[0]
    await text?.setValue('verso')
    await flushPromises()
    expect(opened.store.get('markers.1.text')).toBe('verso')
    expect(opened.store.canUndo).toBe(true)
    opened.store.undo()
    expect(opened.store.get('markers.1.text')).toBe('')
  })

  it('a cor escolhida grava #RRGGBB no marcador', async () => {
    const opened = await openEditor(withMarkers(MARKERS))
    const wrapper = await mountEditorPart(MarkersSection, opened)
    const picker = wrapper.find('input[type="color"]')
    expect((picker.element as HTMLInputElement).value).toBe('#e0a020')
    await picker.setValue('#112233')
    expect(opened.store.get('markers.0.color')).toBe('#112233')
  })

  it('Remover manda marker_remove com a posição do marcador', async () => {
    const view = timelineView()
    view.tracks.push(timelineTrack('MK', [timelineItem(0, { id: 'MK-0', kind: 'marker' })], { kind: 'markers' }))
    const afterRemoval = { ...withMarkers([MARKERS[1]]) }
    const opened = await openEditor(withMarkers(MARKERS), {
      'POST /api/projects/demo/edit': () => ({ spec: afterRemoval, timeline: view }),
    })
    const wrapper = await mountEditorPart(MarkersSection, opened)
    await button(wrapper, 'Remover o marcador 1')?.trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/edit')[0]?.body).toMatchObject({ op: { type: 'marker_remove', index: 0 } })
    expect(opened.store.get('markers')).toEqual([MARKERS[1]])
  })

  it('"Marcador no cursor" cria um marcador na posição do cursor', async () => {
    const opened = await openEditor(withMarkers([]), {
      'POST /api/projects/demo/edit': () => ({ spec: withMarkers([{ at: 4, text: '' }]), timeline: timelineView() }),
    })
    opened.store.setPlayhead(4)
    const wrapper = await mountEditorPart(MarkersSection, opened)
    await button(wrapper, 'Marcador no cursor')?.trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/edit')[0]?.body).toMatchObject({ op: { type: 'marker_add', at: 4 } })
  })
})
