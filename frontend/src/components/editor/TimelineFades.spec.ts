import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineView } from '@/api'
import { projectSpec, timelineItem, timelineTrack } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import TimelinePanel from './TimelinePanel.vue'

/** O áudio do clipe e a música, cada um com um fade na borda, e uma faixa externa (que não tem alça). */
function view(): TimelineView {
  return {
    total: 10,
    fps: 30,
    width: 1080,
    height: 1920,
    warnings: [],
    sources: {},
    tracks: [
      timelineTrack('V1', [timelineItem(0, { id: 'V1-0', start: 0, end: 4 })]),
      timelineTrack(
        'A1',
        [
          timelineItem(0, {
            id: 'A1-0',
            kind: 'clip-audio',
            start: 0,
            end: 4,
            path: 'C:/clip0.mp4',
            extra: { fades: { in: { duration: 1, curve: 'sine' } } },
          }),
        ],
        { kind: 'audio' },
      ),
      timelineTrack('A2', [timelineItem(0, { id: 'A2-0', kind: 'track', start: 0, end: 10, path: 'C:/mesa.wav' })], { kind: 'audio' }),
      timelineTrack(
        'MUS',
        [timelineItem(0, { id: 'MUS-0', kind: 'music', start: 0, end: 10, path: 'C:/musica.mp3', extra: {} })],
        { kind: 'audio' },
      ),
    ],
  }
}

let wrapper: VueWrapper | null = null
let opened: OpenedEditor
let current: TimelineView

async function mountTimeline(locked = false) {
  current = view()
  const audioTrack = current.tracks[1]
  if (locked && audioTrack) audioTrack.locked = true
  opened = await openEditor(projectSpec(), {
    'POST /api/projects/demo/timeline': () => current,
    'POST /api/projects/demo/edit': () => ({ spec: projectSpec(), timeline: current }),
    'GET /api/waveform': { duration: 6, peaks_per_second: 10, peaks: [0.2, 0.5, 0.9] },
  })
  wrapper = await mountEditorPart(TimelinePanel, opened)
}

const item = (id: string) => (wrapper as VueWrapper).find(`[data-item-id="${id}"]`)
const edits = () => opened.fetch.to('POST /api/projects/demo/edit')
const mouse = (target: Document | Element, type: string, clientX: number) =>
  target.dispatchEvent(new MouseEvent(type, { clientX, bubbles: true, cancelable: true, button: 0 }))

beforeEach(() => {
  window.localStorage.clear()
  const context = { clearRect: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), fill: vi.fn(), fillStyle: '' }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as never)
  // o jsdom não mede nada: o item do clipe ocupa 4 s a 60 px/s, de x = 200 a x = 440
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const left = 200
    return { left, right: left + 240, top: 0, bottom: 30, width: 240, height: 30, x: left, y: 0, toJSON: () => ({}) }
  })
})

afterEach(() => {
  document.dispatchEvent(new MouseEvent('mouseup'))
  wrapper?.unmount()
  wrapper = null
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('a alça de fade na linha do tempo', () => {
  it('os itens com som próprio têm uma alça em cada ponta; a faixa externa e a imagem não têm', async () => {
    await mountTimeline()
    expect(item('A1-0').findAll('[data-fade]').map((handle) => handle.attributes('data-fade'))).toEqual(['in', 'out'])
    expect(item('MUS-0').findAll('[data-fade]')).toHaveLength(2)
    expect(item('A2-0').findAll('[data-fade]')).toHaveLength(0)
    expect(item('V1-0').findAll('[data-fade]')).toHaveLength(0)
  })

  it('mostra a curva do fade que o item tem, na largura dele, e só nessa ponta', async () => {
    await mountTimeline()
    const shade = item('A1-0').find('svg.fade--in')
    expect(shade.exists()).toBe(true)
    expect(shade.attributes('style')).toContain('width: 60px') // 1 s a 60 px/s
    expect(item('A1-0').find('svg.fade--out').exists()).toBe(false)
    expect(item('A1-0').find('[data-fade="in"]').attributes('style')).toContain('left: 60px')
    expect(item('A1-0').find('[data-fade="in"]').attributes('title')).toContain('1.00 s')
  })

  it('arrastar a alça da saída grava o Fade Out ao soltar, com a duração até o ponteiro', async () => {
    await mountTimeline()
    await item('A1-0').find('[data-fade="out"]').trigger('mousedown', { button: 0, clientX: 440 })
    mouse(document, 'mousemove', 440 - 90)
    await flushPromises()
    // durante o gesto só o desenho muda: nada foi gravado
    expect(useTimelineStore().fadePreview).toEqual({ itemId: 'A1-0', side: 'out', duration: 1.5 })
    expect(item('A1-0').find('svg.fade--out').attributes('style')).toContain('width: 90px')
    expect(edits()).toHaveLength(0)
    mouse(document, 'mouseup', 440 - 90)
    await flushPromises()
    expect(edits()).toHaveLength(1)
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'audio_fade', target: 'timeline.0', side: 'out', duration: 1.5 } })
    expect(useTimelineStore().fadePreview).toBeNull()
  })

  it('arrastar a alça da entrada de volta à borda tira o fade (duração 0)', async () => {
    await mountTimeline()
    await item('A1-0').find('[data-fade="in"]').trigger('mousedown', { button: 0, clientX: 260 })
    mouse(document, 'mousemove', 201)
    mouse(document, 'mouseup', 201)
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'audio_fade', target: 'timeline.0', side: 'in', duration: 0 } })
  })

  it('na música o alvo é a música; o fade não passa da duração do item', async () => {
    await mountTimeline()
    await item('MUS-0').find('[data-fade="in"]').trigger('mousedown', { button: 0, clientX: 200 })
    mouse(document, 'mousemove', 200 + 800)
    mouse(document, 'mouseup', 200 + 800)
    await flushPromises()
    // o rect mockado tem 240 px (4 s) de largura: a alça vai até o ponteiro, que o item limita ao comprimento dele (10 s)
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'audio_fade', target: 'audio.music', side: 'in' } })
    expect((edits()[0]?.body as { op: { duration: number } }).op.duration).toBeLessThanOrEqual(10)
  })

  it('um clique na alça sem mover não grava nada nem muda a seleção', async () => {
    await mountTimeline()
    await item('A1-0').find('[data-fade="out"]').trigger('mousedown', { button: 0, clientX: 440 })
    mouse(document, 'mousemove', 441)
    mouse(document, 'mouseup', 441)
    await flushPromises()
    expect(edits()).toHaveLength(0)
    expect(opened.store.selection).toEqual([])
  })

  it('duplo clique na alça troca a curva pela seguinte e mantém a duração', async () => {
    await mountTimeline()
    await item('A1-0').find('[data-fade="in"]').trigger('dblclick')
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({
      op: { type: 'audio_fade', target: 'timeline.0', side: 'in', duration: 1, curve: 'quadratic' }, // depois de sine vem quadratic
    })
  })

  it('numa trilha bloqueada a alça não age', async () => {
    await mountTimeline(true)
    await item('A1-0').find('[data-fade="out"]').trigger('mousedown', { button: 0, clientX: 440 })
    mouse(document, 'mousemove', 380)
    mouse(document, 'mouseup', 380)
    await flushPromises()
    expect(edits()).toHaveLength(0)
    expect(useToastsStore().items.length).toBeGreaterThan(0)
  })
})
