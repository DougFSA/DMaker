import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineItem } from '@/api'
import { projectSpec, timelineItem, timelineView } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import { useTimelineStore } from '@/stores/timeline'
import TimelineWaveform from './TimelineWaveform.vue'

/** Um contexto de canvas de mentira que guarda o que foi desenhado. */
function fakeContext() {
  return { clearRect: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), fill: vi.fn(), fillStyle: '' }
}

let context = fakeContext()
let wrapper: VueWrapper | null = null
const peaksFor = (peaks: number[], duration = 10) => ({ duration, peaks_per_second: 1, peaks })

beforeEach(() => {
  window.localStorage.clear()
  context = fakeContext()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => context as never)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 1 })
})

async function mountWave(item: TimelineItem, options: { piece?: number | null; selected?: boolean; routes?: Record<string, unknown> } = {}) {
  const opened = await openEditor(projectSpec(), {
    'POST /api/projects/demo/timeline': () => ({ ...timelineView(), total: 20 }),
    'GET /api/waveform': peaksFor(new Array(10).fill(0.5)),
    ...options.routes,
  })
  wrapper = await mountEditorPart(TimelineWaveform, opened, {
    item,
    pieceIndex: options.piece ?? null,
    selected: options.selected ?? false,
  })
  await flushPromises()
  return { opened, panel: wrapper }
}

const music = (extra: Partial<TimelineItem> = {}) =>
  timelineItem(0, { id: 'MUS-0', kind: 'music', start: 0, end: 5, path: 'C:/musica.mp3', extra: {}, ...extra })

describe('forma de onda de um item', () => {
  it('pede os picos do arquivo e desenha uma barra por coluna do trecho visível', async () => {
    const { opened, panel } = await mountWave(music())
    expect(opened.fetch.to('GET /api/waveform')).toHaveLength(1)
    expect(opened.fetch.to('GET /api/waveform')[0]?.url).toContain('path=C%3A%2Fmusica.mp3')
    const canvas = panel.find('canvas').element as HTMLCanvasElement
    // 5 s a 60 px/s
    expect(canvas.width).toBe(300)
    expect(context.rect).toHaveBeenCalledTimes(300)
    expect(context.fill).toHaveBeenCalledTimes(1)
  })

  it('a altura da barra segue o pico: pico 0,5 numa altura fixa de 19 px, centrada no meio', async () => {
    await mountWave(music())
    expect(context.rect.mock.calls[0]).toEqual([0, 4.75, 1, 9.5])
  })

  it('o canvas tem o tamanho da tela vezes a densidade de pixels', async () => {
    Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 2 })
    const { panel } = await mountWave(music())
    const canvas = panel.find('canvas').element as HTMLCanvasElement
    expect(canvas.width).toBe(600)
    expect(canvas.height).toBe(38)
  })

  it('a música em loop repete o arquivo até o fim do item; sem loop, o trecho depois do fim fica em branco', async () => {
    // arquivo de 2 s num item de 5 s
    const routes = { 'GET /api/waveform': peaksFor([0.5, 0.5], 2) }
    await mountWave(music({ extra: { loop: true } }), { routes })
    expect(context.rect).toHaveBeenCalledTimes(300)
    context = fakeContext()
    wrapper?.unmount()
    await mountWave(music(), { routes })
    // 2 s de 5 s = 120 colunas
    expect(context.rect).toHaveBeenCalledTimes(120)
  })

  it('item selecionado desenha mais claro, e mudo, mais apagado', async () => {
    await mountWave(music(), { selected: true })
    expect(context.fillStyle).toBe('rgba(255, 255, 255, 0.88)')
    wrapper?.unmount()
    context = fakeContext()
    await mountWave(music({ muted: true }))
    expect(context.fillStyle).toBe('rgba(255, 255, 255, 0.2)')
    wrapper?.unmount()
    context = fakeContext()
    await mountWave(music())
    expect(context.fillStyle).toBe('rgba(255, 255, 255, 0.5)')
  })

  it('o arquivo é pedido uma vez só mesmo com vários itens dele', async () => {
    const { opened } = await mountWave(music())
    const second = await mountEditorPart(TimelineWaveform, opened, { item: music({ id: 'MUS-1', start: 5, end: 8 }), pieceIndex: null, selected: false })
    await flushPromises()
    expect(opened.fetch.to('GET /api/waveform')).toHaveLength(1)
    second.unmount()
  })

  it('item fora da janela visível fica escondido e não desenha', async () => {
    const { panel, opened } = await mountWave(music({ start: 1000, end: 1005 }))
    expect(panel.find('canvas').attributes('style')).toContain('display: none')
    expect(context.rect).not.toHaveBeenCalled()
    // rolar até ele mostra e desenha
    useTimelineStore().setScroll(1000 * 60, 1200)
    await flushPromises()
    expect(panel.find('canvas').attributes('style') ?? '').not.toContain('display: none')
    expect(context.rect).toHaveBeenCalled()
    expect(opened.fetch.to('GET /api/waveform')).toHaveLength(1)
  })

  it('o canvas cobre só a janela, não o item inteiro, e nunca passa do limite de largura', async () => {
    const { panel } = await mountWave(music({ start: 0, end: 3600 }), { routes: { 'GET /api/waveform': peaksFor(new Array(10).fill(0.4), 3600) } })
    const canvas = panel.find('canvas').element as HTMLCanvasElement
    // a janela vai até 1600 px (1200 de largura assumida mais as folgas), muito menos que as 216000 px do item
    expect(canvas.width).toBeLessThan(2000)
    expect(canvas.width).toBeGreaterThan(1000)
  })

  it('um pedaço de uma fonte em várias partes desenha o arquivo dele, no intervalo dele', async () => {
    const pieces = [
      { start: 0, end: 3, in_point: 0, path: 'C:/p1.mp4' },
      { start: 3, end: 6, in_point: 0, path: 'C:/p2.mp4' },
    ]
    const item = timelineItem(0, { id: 'A1-0', kind: 'clip-audio', start: 0, end: 6, path: 'C:/p1.mp4', extra: { pieces, speed: 1 } })
    const { opened, panel } = await mountWave(item, { piece: 1 })
    expect(opened.fetch.to('GET /api/waveform')[0]?.url).toContain('p2.mp4')
    // o segundo pedaço começa em 3 s: 180 px para dentro do item
    expect(panel.find('canvas').attributes('style')).toContain('left: 180px')
    expect(panel.find('canvas').attributes('style')).toContain('width: 180px')
  })

  it('item com arquivo ausente não pede picos', async () => {
    const { opened } = await mountWave(music({ missing: true }))
    expect(opened.fetch.to('GET /api/waveform')).toHaveLength(0)
    expect(context.rect).not.toHaveBeenCalled()
  })

  it('o servidor sem picos (arquivo sem áudio) deixa o canvas limpo, sem erro', async () => {
    await mountWave(music(), { routes: { 'GET /api/waveform': reply(404, { detail: 'sem áudio' }) } })
    expect(context.rect).not.toHaveBeenCalled()
  })
})
