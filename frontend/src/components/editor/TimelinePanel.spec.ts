import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineItem, TimelineView } from '@/api'
import { MEDIA_DND_MIME, TRACK_HEADER_WIDTH } from '@/lib/timeline'
import { projectSpec, timelineItem, timelineTrack } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import TimelinePanel from './TimelinePanel.vue'

/** Todas as trilhas: duas V1 em transição, PiP, texto, imagem e barra, áudio de clipe, faixa externa, narração, música e legendas. */
function fullView(): TimelineView {
  const clip = (index: number, start: number, end: number, extra: Partial<TimelineItem> = {}) =>
    timelineItem(index, { id: `V1-${index}`, start, end, label: `clip${index}.mp4`, path: `C:/clip${index}.mp4`, ...extra })
  return {
    total: 12,
    fps: 30,
    width: 1080,
    height: 1920,
    warnings: [],
    sources: {},
    tracks: [
      timelineTrack('V2', [timelineItem(0, { id: 'V2-0', kind: 'video', start: 2, end: 5, label: 'pip.mp4', path: 'C:/pip.mp4' })]),
      timelineTrack('TX', [timelineItem(0, { id: 'TX-0', kind: 'text', start: 1, end: 4, label: 'Título' })], { kind: 'text' }),
      timelineTrack(
        'GR',
        [
          timelineItem(1, { id: 'GR-1', kind: 'image', start: 0, end: 12, label: 'logo' }),
          timelineItem(2, { id: 'GR-2', kind: 'progress-bar', start: 0, end: 12, label: 'barra' }),
        ],
        { kind: 'graphics' },
      ),
      timelineTrack('V1', [
        clip(0, 0, 4),
        clip(1, 3.5, 8, { transition: { type: 'fade', duration: 0.5 } }),
        clip(2, 8, 12, { missing: true }),
      ]),
      timelineTrack('A1', [timelineItem(0, { id: 'A1-0', kind: 'clip-audio', start: 0, end: 4, label: 'clip0.mp4', path: 'C:/clip0.mp4' })], {
        kind: 'audio',
      }),
      timelineTrack('A2', [timelineItem(0, { id: 'A2-0', kind: 'track', start: 0, end: 12, label: 'mesa.wav', path: 'C:/mesa.wav' })], {
        kind: 'audio',
        muted: true,
      }),
      timelineTrack(
        'NAR',
        [timelineItem(0, { id: 'NAR-0', kind: 'narration', start: 2, end: 6, label: 'Olá, mundo', extra: { estimated: true } })],
        { kind: 'audio' },
      ),
      timelineTrack('MUS', [timelineItem(0, { id: 'MUS-0', kind: 'music', start: 0, end: 12, label: 'musica.mp3', path: 'C:/musica.mp3', extra: { loop: true } })], {
        kind: 'audio',
      }),
      timelineTrack('CC', [timelineItem(0, { id: 'CC-0', kind: 'captions', start: 0, end: 12, label: 'legendas' })], { kind: 'captions', locked: true }),
    ],
  }
}

let wrapper: VueWrapper | null = null
let opened: OpenedEditor
let currentView: TimelineView

const WAVEFORM = { duration: 6, peaks_per_second: 10, peaks: [0.2, 0.5, 0.9] }

async function mountTimeline(view: TimelineView = fullView(), routes: Record<string, unknown> = {}) {
  currentView = view
  opened = await openEditor(projectSpec(), {
    'POST /api/projects/demo/timeline': () => currentView,
    'POST /api/projects/demo/edit': () => ({ spec: projectSpec(), timeline: currentView }),
    'GET /api/waveform': WAVEFORM,
    ...routes,
  })
  wrapper = await mountEditorPart(TimelinePanel, opened)
  return wrapper
}

const rows = () => (wrapper as VueWrapper).findAll('.row').map((row) => row.attributes('data-track-id'))
const item = (id: string) => (wrapper as VueWrapper).find(`[data-item-id="${id}"]`)
const header = (trackId: string) => (wrapper as VueWrapper).find(`.row[data-track-id="${trackId}"] .row__header`)
const edits = () => opened.fetch.to('POST /api/projects/demo/edit')
const mouse = (target: Document | Element, type: string, clientX: number) =>
  target.dispatchEvent(new MouseEvent(type, { clientX, bubbles: true, cancelable: true, button: 0 }))

beforeEach(() => {
  window.localStorage.clear()
  // o jsdom não tem canvas: um contexto de mentira basta para a forma de onda não reclamar
  const context = { clearRect: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), fill: vi.fn(), fillStyle: '' }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as never)
})

afterEach(() => {
  // um gesto que o teste deixou no meio (mouse apertado) termina aqui, para os ouvintes do documento não vazarem
  document.dispatchEvent(new MouseEvent('mouseup'))
  wrapper?.unmount()
  wrapper = null
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('trilhas e rótulos', () => {
  it('desenha as trilhas na ordem da vista: V2, TX, GR, V1, A1, A2, NAR, MUS e CC', async () => {
    await mountTimeline()
    expect(rows()).toEqual(['V2', 'TX', 'GR', 'V1', 'A1', 'A2', 'NAR', 'MUS', 'CC'])
  })

  it('o cabeçalho tem o rótulo (nota musical nas de áudio) e o balão com o nome por extenso', async () => {
    await mountTimeline()
    expect(header('V1').text()).toContain('V1')
    expect(header('A1').text()).toContain('A1 ♪')
    expect(header('A1').attributes('title')).toBe('Áudio dos clipes (A1)')
    expect(header('NAR').attributes('title')).toBe('Narração (NAR)')
    expect(header('V2').attributes('title')).toBe('Vídeo sobreposto (V2)')
  })

  it('cada item mostra o nome do arquivo e tem o tipo na classe', async () => {
    await mountTimeline()
    expect(item('V1-0').text()).toBe('clip0.mp4')
    expect(item('V1-0').classes()).toContain('item--clip')
    expect(item('MUS-0').classes()).toContain('item--music')
    expect(item('TX-0').text()).toBe('Título')
  })

  it('a fala da narração com duração estimada tem o balão e a borda tracejada', async () => {
    await mountTimeline()
    expect(item('NAR-0').attributes('title')).toBe('Olá, mundo (duração estimada: 4,0 s)')
    expect(item('NAR-0').classes()).toContain('item--estimated')
  })

  it('o item cujo arquivo sumiu abre marcado "fonte não encontrada", sem forma de onda', async () => {
    await mountTimeline()
    expect(item('V1-2').classes()).toContain('item--missing')
    expect(item('V1-2').attributes('title')).toBe('clip2.mp4 (fonte não encontrada)')
  })

  it('a hachura da transição aparece entre os trechos da V1', async () => {
    const panel = await mountTimeline()
    const hatch = panel.find('.transition')
    expect(hatch.exists()).toBe(true)
    expect(hatch.attributes('title')).toBe('Transição: fade')
    // o trecho de entrada começa em 3,5 s e o anterior termina em 4 s: 30 px de hachura
    expect(hatch.attributes('style')).toContain('left: 210px')
    expect(hatch.attributes('style')).toContain('width: 30px')
  })

  it('o cabeçalho mostra só os botões que a trilha tem: M no áudio, H nas camadas, cadeado em todas', async () => {
    await mountTimeline()
    const letters = (id: string) => (wrapper as VueWrapper).findAll(`.row[data-track-id="${id}"] .row__button`).map((button) => button.text())
    expect(letters('V1')).toEqual(['L'])
    expect(letters('V2')).toEqual(['H', 'L'])
    expect(letters('A1')).toEqual(['M', 'L'])
    expect(letters('CC')).toEqual(['H', 'L'])
    expect((wrapper as VueWrapper).find('.row[data-track-id="A2"] [data-track-action="muted"]').classes()).toContain('row__button--on')
  })
})

describe('sem linha do tempo', () => {
  it('diz o motivo em vez de uma área vazia', async () => {
    const panel = await mountTimeline(fullView(), { 'POST /api/projects/demo/timeline': reply(422, { detail: 'fonte não cobre o trecho' }) })
    expect(panel.text()).toContain('A linha do tempo não abriu')
    expect(panel.text()).toContain('fonte não cobre o trecho')
    expect(panel.find('.timeline__scroll').exists()).toBe(false)
  })
})

describe('seleção', () => {
  it('clicar num item o seleciona e tira a seleção dos outros', async () => {
    await mountTimeline()
    await item('V1-0').trigger('mousedown', { button: 0 })
    expect(opened.store.selection).toEqual(['V1-0'])
    await item('V1-1').trigger('mousedown', { button: 0 })
    expect(opened.store.selection).toEqual(['V1-1'])
    expect(item('V1-1').classes()).toContain('item--selected')
    expect(item('V1-0').classes()).not.toContain('item--selected')
    expect(item('V1-1').attributes('aria-pressed')).toBe('true')
  })

  it('Ctrl soma ao que já estava selecionado, e Ctrl de novo no mesmo item o tira', async () => {
    await mountTimeline()
    await item('V1-0').trigger('mousedown', { button: 0 })
    await item('V1-1').trigger('mousedown', { button: 0, ctrlKey: true })
    expect(opened.store.selection).toEqual(['V1-0', 'V1-1'])
    await item('V1-0').trigger('mousedown', { button: 0, ctrlKey: true })
    expect(opened.store.selection).toEqual(['V1-1'])
  })

  it('clicar numa faixa vazia limpa a seleção e leva o cursor até lá', async () => {
    const panel = await mountTimeline()
    await item('V1-0').trigger('mousedown', { button: 0 })
    // A1 ocupa 0 a 4 s: 5 s está vazio; o jsdom não mede a tela, então o início da área é x=0
    const lane = panel.find('.row[data-track-id="A1"] .lane')
    await lane.trigger('mousedown', { button: 0, clientX: TRACK_HEADER_WIDTH + 5 * 60 })
    expect(opened.store.selection).toEqual([])
    expect(opened.store.playhead).toBeCloseTo(5, 6)
    expect(panel.find('.timecode__now').text()).toBe('00:00:05:00')
  })

  it('só o botão principal do mouse seleciona', async () => {
    await mountTimeline()
    await item('V1-0').trigger('mousedown', { button: 2 })
    expect(opened.store.selection).toEqual([])
  })

  it('item de trilha bloqueada não se seleciona e avisa do cadeado', async () => {
    await mountTimeline()
    await item('CC-0').trigger('mousedown', { button: 0 })
    expect(opened.store.selection).toEqual([])
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('A trilha CC está bloqueada (cadeado no cabeçalho).')
  })
})

describe('régua e cursor', () => {
  it('clicar e arrastar na régua leva o cursor, e a régua tem as marcas de 2 em 2 segundos no zoom padrão', async () => {
    const panel = await mountTimeline()
    const labels = panel.findAll('.ruler__tick').map((tick) => tick.text())
    expect(labels.slice(0, 4)).toEqual(['00:00:00', '00:00:02', '00:00:04', '00:00:06'])
    const ruler = panel.find('[data-ruler]')
    await ruler.trigger('mousedown', { button: 0, clientX: TRACK_HEADER_WIDTH + 120 })
    expect(opened.store.playhead).toBeCloseTo(2, 6)
    mouse(document, 'mousemove', TRACK_HEADER_WIDTH + 300)
    expect(opened.store.playhead).toBeCloseTo(5, 6)
    mouse(document, 'mouseup', TRACK_HEADER_WIDTH + 300)
    mouse(document, 'mousemove', TRACK_HEADER_WIDTH + 600)
    // largou o mouse: o cursor não segue mais
    expect(opened.store.playhead).toBeCloseTo(5, 6)
  })

  it('o cursor encaixa nas bordas dos itens perto do clique', async () => {
    const panel = await mountTimeline()
    // 3,95 s está a 3 px da borda do trecho que começa em 4 s (um pouco menos que o encaixe de 8 px)
    await panel.find('[data-ruler]').trigger('mousedown', { button: 0, clientX: TRACK_HEADER_WIDTH + 3.95 * 60 })
    expect(opened.store.playhead).toBe(4)
    mouse(document, 'mouseup', 0)
  })

  it('o cursor fica numa posição que acompanha o tempo e o zoom', async () => {
    const panel = await mountTimeline()
    opened.store.setPlayhead(2)
    await flushPromises()
    expect(panel.find('[data-playhead]').attributes('style')).toContain(`left: ${TRACK_HEADER_WIDTH + 120}px`)
    useTimelineStore().setZoom(120)
    await flushPromises()
    expect(panel.find('[data-playhead]').attributes('style')).toContain(`left: ${TRACK_HEADER_WIDTH + 240}px`)
  })
})

describe('zoom', () => {
  it('Ctrl com a roda faz zoom e impede o zoom da página; sem Ctrl a roda segue para a rolagem', async () => {
    const panel = await mountTimeline()
    const area = panel.find('.timeline__scroll').element
    const withCtrl = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, cancelable: true, bubbles: true })
    area.dispatchEvent(withCtrl)
    expect(withCtrl.defaultPrevented).toBe(true)
    expect(useTimelineStore().pxPerSec).toBeCloseTo(60 * 1.15, 9)
    const plain = new WheelEvent('wheel', { deltaY: -100, cancelable: true, bubbles: true })
    area.dispatchEvent(plain)
    expect(plain.defaultPrevented).toBe(false)
    const out = new WheelEvent('wheel', { deltaY: 100, ctrlKey: true, cancelable: true, bubbles: true })
    area.dispatchEvent(out)
    expect(useTimelineStore().pxPerSec).toBeCloseTo(60, 9)
  })

  it('o ouvinte da roda não é passivo (senão o preventDefault seria ignorado)', async () => {
    const add = vi.spyOn(EventTarget.prototype, 'addEventListener')
    await mountTimeline()
    const wheelOptions = add.mock.calls.filter(([type]) => type === 'wheel').map((call) => call[2])
    expect(wheelOptions).toContainEqual({ passive: false })
  })

  it('o zoom muda a largura das trilhas e a posição dos itens', async () => {
    const panel = await mountTimeline()
    expect(item('V1-1').attributes('style')).toContain('left: 210px')
    useTimelineStore().setZoom(120)
    await flushPromises()
    expect(item('V1-1').attributes('style')).toContain('left: 420px')
    expect(panel.find('.timeline__content').attributes('style')).toContain(`width: ${TRACK_HEADER_WIDTH + 12 * 120 + 40}px`)
  })

  it('"Ajustar" e o pedido de rolagem levam a área rolável ao começo', async () => {
    const panel = await mountTimeline()
    const area = panel.find('.timeline__scroll').element as HTMLElement
    area.scrollLeft = 500
    useTimelineStore().zoomFit()
    await flushPromises()
    expect(area.scrollLeft).toBe(0)
  })

  it('aproximar centraliza o cursor na área rolável', async () => {
    const panel = await mountTimeline()
    const area = panel.find('.timeline__scroll').element as HTMLElement
    Object.defineProperty(area, 'clientWidth', { configurable: true, value: 600 })
    opened.store.setPlayhead(6)
    useTimelineStore().zoomIn()
    await flushPromises()
    // 92 de cabeçalho + 6 s a 78 px/s, menos a metade da largura visível
    expect(area.scrollLeft).toBeCloseTo(TRACK_HEADER_WIDTH + 6 * 78 - 300, 6)
  })
})

describe('o cursor fica à vista', () => {
  async function mountMeasured() {
    const panel = await mountTimeline()
    const area = panel.find('.timeline__scroll').element as HTMLElement
    Object.defineProperty(area, 'clientWidth', { configurable: true, value: 600 })
    useTimelineStore().setScroll(0, 600)
    return area
  }

  it('ao sair pela direita a área rola uma página, e o cursor fica perto da borda esquerda', async () => {
    const area = await mountMeasured()
    // 92 px de cabeçalho mais 12 s a 60 px/s
    opened.store.setPlayhead(12)
    await flushPromises()
    expect(area.scrollLeft).toBe(92 + 12 * 60 - TRACK_HEADER_WIDTH - 40)
    expect(useTimelineStore().scrollLeft).toBe(area.scrollLeft)
  })

  it('ao sair pela esquerda (um salto ao começo, ou tocar para trás) volta a rolar', async () => {
    const area = await mountMeasured()
    opened.store.setPlayhead(12)
    await flushPromises()
    opened.store.setPlayhead(0)
    await flushPromises()
    expect(area.scrollLeft).toBe(0)
  })

  it('dentro da área visível, a rolagem fica quieta (nada de seguir o cursor a cada quadro)', async () => {
    const area = await mountMeasured()
    for (const seconds of [1, 2, 3, 4, 5, 6]) {
      opened.store.setPlayhead(seconds)
      await flushPromises()
    }
    expect(area.scrollLeft).toBe(0)
  })
})

describe('só o que está à vista existe no documento', () => {
  it('uma linha do tempo longa desenha só os itens perto da janela visível', async () => {
    const clips = Array.from({ length: 200 }, (_, index) =>
      timelineItem(index, { id: `V1-${index}`, start: index * 2, end: index * 2 + 2, label: `c${index}.mp4`, path: `C:/c${index}.mp4` }),
    )
    const view: TimelineView = { ...fullView(), total: 400, tracks: [timelineTrack('V1', clips)] }
    await mountTimeline(view)
    const drawn = (wrapper as VueWrapper).findAll('[data-item-id]').length
    expect(drawn).toBeGreaterThan(5)
    expect(drawn).toBeLessThan(40)
    expect(item('V1-0').exists()).toBe(true)
    expect(item('V1-150').exists()).toBe(false)
    // rolar para longe troca os itens desenhados
    const timeline = useTimelineStore()
    timeline.setScroll(150 * 2 * 60, 1200)
    await flushPromises()
    expect(item('V1-150').exists()).toBe(true)
    expect(item('V1-0').exists()).toBe(false)
  })

  it('a barra de rolagem tem a largura do vídeo inteiro mesmo com poucos itens desenhados', async () => {
    const clips = Array.from({ length: 200 }, (_, index) => timelineItem(index, { id: `V1-${index}`, start: index * 2, end: index * 2 + 2 }))
    const view: TimelineView = { ...fullView(), total: 400, tracks: [timelineTrack('V1', clips)] }
    const panel = await mountTimeline(view)
    expect(panel.find('.timeline__content').attributes('style')).toContain(`width: ${TRACK_HEADER_WIDTH + 400 * 60 + 40}px`)
  })
})

describe('arrastar e aparar', () => {
  it('arrastar um trecho da V1 para depois do seguinte manda mover, e a seleção segue o trecho', async () => {
    await mountTimeline()
    await item('V1-0').trigger('mousedown', { button: 0, clientX: 100 })
    // 1 s a 60 px/s: o trecho passa a começar em 1 s...
    mouse(document, 'mousemove', 100 + 5 * 60)
    await flushPromises()
    expect((wrapper as VueWrapper).find('[data-ghost]').exists()).toBe(true)
    expect((wrapper as VueWrapper).find('[data-drop-indicator]').exists()).toBe(true)
    mouse(document, 'mouseup', 100 + 5 * 60)
    await flushPromises()
    expect(edits()).toHaveLength(1)
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'move', index: 0, to: 1 } })
    expect((wrapper as VueWrapper).find('[data-ghost]').exists()).toBe(false)
    expect(opened.store.selection).toEqual(['V1-1'])
  })

  it('um clique com o mouse parado não vira arrasto nem operação', async () => {
    await mountTimeline()
    await item('V1-1').trigger('mousedown', { button: 0, clientX: 100 })
    mouse(document, 'mousemove', 101)
    mouse(document, 'mouseup', 101)
    await flushPromises()
    expect(edits()).toHaveLength(0)
    expect(opened.store.selection).toEqual(['V1-1'])
  })

  it('puxar a alça da saída de um trecho da V1 manda aparar com o quanto a borda andou', async () => {
    await mountTimeline()
    const handle = item('V1-0').find('[data-handle="out"]')
    await handle.trigger('mousedown', { button: 0, clientX: 300 })
    mouse(document, 'mousemove', 300 - 30)
    mouse(document, 'mouseup', 300 - 30)
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'trim', index: 0, side: 'out', delta: -0.5 } })
    // puxar a alça não muda a seleção
    expect(opened.store.selection).toEqual([])
  })

  it('puxar a alça de uma sobreposição manda o novo intervalo, não um aparar da V1', async () => {
    await mountTimeline()
    const handle = item('TX-0').find('[data-handle="in"]')
    await handle.trigger('mousedown', { button: 0, clientX: 300 })
    mouse(document, 'mousemove', 300 + 60)
    mouse(document, 'mouseup', 300 + 60)
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'overlay_span', index: 0, start: 2, end: 4 } })
  })

  it('arrastar uma sobreposição a desloca inteira, sem mudar a duração', async () => {
    await mountTimeline()
    await item('V2-0').trigger('mousedown', { button: 0, clientX: 300 })
    mouse(document, 'mousemove', 300 + 120)
    mouse(document, 'mouseup', 300 + 120)
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'overlay_span', index: 0, start: 4, end: 7 } })
  })

  it('arrastar uma fala da narração só muda o início dela', async () => {
    await mountTimeline()
    await item('NAR-0').trigger('mousedown', { button: 0, clientX: 300 })
    mouse(document, 'mousemove', 300 + 60)
    mouse(document, 'mouseup', 300 + 60)
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'set_field', path: 'audio.narration.0.start', value: 3 } })
  })

  it('a narração não tem alças de aparar, e a música e o áudio não se arrastam', async () => {
    await mountTimeline()
    expect(item('NAR-0').find('[data-handle]').exists()).toBe(false)
    expect(item('V1-0').findAll('[data-handle]')).toHaveLength(2)
    await item('MUS-0').trigger('mousedown', { button: 0, clientX: 300 })
    mouse(document, 'mousemove', 400)
    mouse(document, 'mouseup', 400)
    await flushPromises()
    expect(edits()).toHaveLength(0)
    // mas clicar seleciona
    expect(opened.store.selection).toEqual(['MUS-0'])
  })

  it('o encaixe desligado deixa o item cair exatamente onde o mouse o soltou', async () => {
    await mountTimeline()
    useTimelineStore().toggleSnap()
    // 3,95 s: com o encaixe ligado iria para 4 s (a borda do trecho)
    await item('V2-0').trigger('mousedown', { button: 0, clientX: 300 })
    mouse(document, 'mousemove', 300 + 1.95 * 60)
    mouse(document, 'mouseup', 300 + 1.95 * 60)
    await flushPromises()
    const op = edits()[0]?.body as { op: { start: number; end: number } }
    expect(op.op.start).toBeCloseTo(3.95, 6)
    expect(op.op.end).toBeCloseTo(6.95, 6)
  })

  it('soltar o mouse fora do painel termina o gesto e remove os ouvintes do documento', async () => {
    const remove = vi.spyOn(document, 'removeEventListener')
    await mountTimeline()
    await item('V1-0').trigger('mousedown', { button: 0, clientX: 100 })
    mouse(document, 'mouseup', 100)
    const removed = remove.mock.calls.map(([type]) => type)
    expect(removed).toContain('mousemove')
    expect(removed).toContain('mouseup')
  })
})

describe('mudo, ocultar e bloqueio', () => {
  it('o botão M do cabeçalho manda mudar o campo da trilha', async () => {
    await mountTimeline()
    await (wrapper as VueWrapper).find('.row[data-track-id="A1"] [data-track-action="muted"]').trigger('click')
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'set_field', path: 'tracks.A1.muted', value: true } })
  })

  it('o botão do cabeçalho não seleciona nem move o cursor', async () => {
    await mountTimeline()
    await (wrapper as VueWrapper).find('.row[data-track-id="V2"] [data-track-action="hidden"]').trigger('mousedown', { button: 0 })
    expect(opened.store.selection).toEqual([])
    expect(opened.store.playhead).toBe(0)
  })

  it('o cadeado de uma trilha bloqueada a desbloqueia (o botão do cabeçalho nunca fica bloqueado)', async () => {
    await mountTimeline()
    await (wrapper as VueWrapper).find('.row[data-track-id="CC"] [data-track-action="locked"]').trigger('click')
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'set_field', path: 'tracks.CC.locked', value: false } })
  })

  it('trilha muda ou oculta fica esmaecida, e a bloqueada, marcada', async () => {
    const panel = await mountTimeline()
    expect(panel.find('.row[data-track-id="A2"]').classes()).toContain('row--muted')
    expect(panel.find('.row[data-track-id="CC"]').classes()).toContain('row--locked')
  })
})

describe('a trilha sob o mouse (para o Ctrl+M, Ctrl+H e Ctrl+L)', () => {
  it('passar o mouse numa trilha a guarda; sair da área a esquece', async () => {
    const panel = await mountTimeline()
    await panel.find('.row[data-track-id="A1"] .lane').trigger('mouseover')
    expect(useTimelineStore().hoverTrackId).toBe('A1')
    await item('V1-0').trigger('mouseover')
    expect(useTimelineStore().hoverTrackId).toBe('V1')
    await panel.find('.timeline__scroll').trigger('mouseleave')
    expect(useTimelineStore().hoverTrackId).toBeNull()
  })
})

describe('soltar mídia do painel Mídia', () => {
  function dropEvent(payload: string | null, clientX: number) {
    const event = new Event('drop', { bubbles: true, cancelable: true }) as Event & { dataTransfer: unknown; clientX: number }
    event.dataTransfer = { types: payload ? [MEDIA_DND_MIME] : [], getData: (type: string) => (type === MEDIA_DND_MIME ? (payload ?? '') : '') }
    event.clientX = clientX
    return event
  }

  it('entrega ao tratador registrado o que foi solto, a trilha e o instante', async () => {
    const panel = await mountTimeline()
    const handler = vi.fn()
    useTimelineStore().onMediaDrop(handler)
    const event = dropEvent('{"kind":"video","src":"a.mp4"}', TRACK_HEADER_WIDTH + 5 * 60)
    panel.find('.row[data-track-id="V1"] .lane').element.dispatchEvent(event)
    expect(handler).toHaveBeenCalledWith('{"kind":"video","src":"a.mp4"}', { trackId: 'V1', time: 5 })
    expect(event.defaultPrevented).toBe(true)
  })

  it('sem tratador registrado, soltar não faz nada', async () => {
    const panel = await mountTimeline()
    const event = dropEvent('{"kind":"video"}', 300)
    panel.find('.row[data-track-id="V1"] .lane').element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
  })

  it('arrastar por cima só é aceito se é mídia do DMaker', async () => {
    const panel = await mountTimeline()
    useTimelineStore().onMediaDrop(vi.fn())
    const lane = panel.find('.row[data-track-id="V1"] .lane').element
    const media = new Event('dragover', { bubbles: true, cancelable: true }) as Event & { dataTransfer: unknown }
    media.dataTransfer = { types: [MEDIA_DND_MIME] }
    lane.dispatchEvent(media)
    expect(media.defaultPrevented).toBe(true)
    const file = new Event('dragover', { bubbles: true, cancelable: true }) as Event & { dataTransfer: unknown }
    file.dataTransfer = { types: ['Files'] }
    lane.dispatchEvent(file)
    expect(file.defaultPrevented).toBe(false)
  })
})

describe('a barra de ferramentas e o timecode', () => {
  it('aparecem junto das trilhas, com o timecode da posição e da duração', async () => {
    const panel = await mountTimeline()
    expect(panel.find('[role="toolbar"]').exists()).toBe(true)
    expect(panel.find('.timecode__now').text()).toBe('00:00:00:00')
    expect(panel.find('.timecode__total').text()).toBe('/ 00:00:12:00')
  })
})
