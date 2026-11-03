import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BoxLayout, TimelineView } from '@/api'
import { boxLayout, overlayBox, projectSpec, timelineItem, timelineTrack } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { usePlayerStore } from '@/stores/player'
import PlayerStage from './PlayerStage.vue'

/* Um quadro 1080x1920 com um texto (0), uma imagem (1), um PiP (2) e um HTML (3). As caixas são as que o servidor
   devolveria: o palco só as desenha, escolhe e destaca. */
const SPEC = {
  ...projectSpec(),
  overlays: [
    { type: 'text', text: 'Gancho', role: 'hook', start: 0, end: 4 },
    { type: 'image', src: 'selo.png', start: 0, opacity: 0.5 },
    { type: 'video', src: 'cam.mp4', start: 0, border: 6, border_color: '#fff' },
    { type: 'html', src: 'card.html', start: 0, x: 0.5, y: 0.5, width: 0.6, height: 0.3 },
  ],
}

function stageView(): TimelineView {
  return {
    total: 12,
    fps: 30,
    width: 1080,
    height: 1920,
    warnings: [],
    sources: {},
    tracks: [
      timelineTrack('V2', [timelineItem(2, { id: 'V2-2', kind: 'video', start: 0, end: 12, path: 'C:/cam.mp4' })]),
      timelineTrack('TX', [timelineItem(0, { id: 'TX-0', kind: 'text', start: 0, end: 4, label: 'Gancho', path: null, extra: { role: 'hook' } })], {
        kind: 'text',
      }),
      timelineTrack(
        'GR',
        [
          timelineItem(1, { id: 'GR-1', kind: 'image', start: 0, end: 12, src: 'selo.png', path: 'C:/selo.png' }),
          timelineItem(3, { id: 'GR-3', kind: 'html', start: 0, end: 12, src: 'card.html', path: null }),
        ],
        { kind: 'graphics' },
      ),
      timelineTrack('V1', [timelineItem(0, { id: 'V1-0', start: 0, end: 12, path: 'C:/cam1.mp4' })]),
    ],
  }
}

function stageBoxes(extra: Partial<Record<number, Parameters<typeof overlayBox>[0]>> = {}): BoxLayout {
  return boxLayout([
    overlayBox({ index: 0, kind: 'text', start: 0, end: 4, left: 0.1, top: 0.2, width: 0.5, height: 0.07, anchor: { x: 0.1, y: 0.235 }, ...extra[0] }),
    overlayBox({ index: 1, kind: 'image', left: 0.7, top: 0.05, width: 0.2, height: 0.1, resize: 'keep_aspect', wrap: null, ...extra[1] }),
    overlayBox({ index: 2, kind: 'video', left: 0.5, top: 0.6, width: 0.4, height: 0.225, resize: 'keep_aspect', wrap: null, ...extra[2] }),
    overlayBox({ index: 3, kind: 'html', left: 0.2, top: 0.35, width: 0.6, height: 0.3, resize: 'free', wrap: null, ...extra[3] }),
  ])
}

let wrapper: VueWrapper | null = null
let opened: OpenedEditor

async function mountStage(layout: BoxLayout | null = stageBoxes(), view: TimelineView = stageView()) {
  opened = await openEditor(SPEC, {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/boxes': () => layout ?? { semCaixas: true },
  })
  wrapper = await mountEditorPart(PlayerStage, opened, {}, true)
  await flushPromises()
  return wrapper
}

const boxButtons = () => wrapper!.findAll('button.box')
const boxOf = (index: number) => wrapper!.find(`button.box[data-overlay="${index}"]`)

beforeEach(() => {
  const playing = new WeakSet<HTMLMediaElement>()
  vi.spyOn(HTMLMediaElement.prototype, 'paused', 'get').mockImplementation(function (this: HTMLMediaElement) {
    return !playing.has(this)
  })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLMediaElement) {
    playing.add(this)
    return Promise.resolve()
  })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (this: HTMLMediaElement) {
    playing.delete(this)
  })
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => undefined)
  window.localStorage.clear()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('o palco: composição nas caixas do servidor', () => {
  it('o texto, a imagem e o PiP ficam dentro das caixas que o servidor calculou', async () => {
    await mountStage()
    const text = wrapper!.find('.text').attributes('style') ?? ''
    expect(text).toContain('top: 20%')
    expect(text).toContain('text-align: left')
    const image = wrapper!.find('.overlay-image').attributes('style') ?? ''
    expect(image).toContain('left: 70%')
    expect(image).toContain('width: 20%')
    expect(image).toContain('height: 10%')
    const pip = wrapper!.find('.pip').attributes('style') ?? ''
    expect(pip).toContain('left: 50%')
    expect(pip).toContain('top: 60%')
    expect(pip).toContain('height: 22.5%')
  })

  it('sem as caixas (servidor antigo, spec incompleta), o palco continua inteiro, na posição aproximada', async () => {
    await mountStage(null)
    expect(boxButtons()).toHaveLength(0)
    expect(wrapper!.find('.text').attributes('style')).toContain('top: 8%')
    expect(wrapper!.find('.pip').exists()).toBe(true)
  })
})

describe('as caixas por cima do palco', () => {
  it('uma caixa por sobreposição ativa, com o rótulo curto e o lugar do servidor', async () => {
    await mountStage()
    expect(boxButtons().map((box) => box.find('.box__label').text())).toEqual(['Texto 1', 'Imagem 2', 'PiP 3', 'HTML 4'])
    expect(boxOf(1).attributes('style')).toContain('left: 70%')
    expect(boxOf(1).attributes('style')).toContain('top: 5%')
    expect(boxOf(1).attributes('style')).toContain('width: 20%')
    expect(boxOf(1).attributes('style')).toContain('height: 10%')
    expect(boxOf(3).classes()).toContain('box--html')
  })

  it('só as que estão na tela no instante do cursor', async () => {
    await mountStage()
    opened.store.setPlayhead(5)
    await flushPromises()
    // o texto 1 termina aos 4 s
    expect(boxButtons().map((box) => box.find('.box__label').text())).toEqual(['Imagem 2', 'PiP 3', 'HTML 4'])
  })

  it('trilha oculta não ganha caixa, e a sobreposição sem área calculada também não', async () => {
    const view = stageView()
    view.tracks = view.tracks.map((track) => (track.id === 'TX' ? { ...track, hidden: true } : track))
    await mountStage(stageBoxes({ 3: { left: null, top: null, width: null, height: null, movable: false } }), view)
    expect(boxButtons().map((box) => box.find('.box__label').text())).toEqual(['Imagem 2', 'PiP 3'])
  })

  it('clicar numa caixa escolhe a sobreposição e pede ao inspetor para mostrá-la', async () => {
    await mountStage()
    await boxOf(2).trigger('click')
    expect(opened.store.selectedOverlay).toBe(2)
    expect(opened.store.overlayReveal).toBe(1)
    expect(boxOf(2).classes()).toContain('box--selected')
    expect(boxOf(2).attributes('aria-pressed')).toBe('true')
    expect(boxOf(1).attributes('aria-pressed')).toBe('false')
  })

  it('a escolha feita no inspetor destaca a caixa, e trocar a escolha tira o destaque da outra', async () => {
    await mountStage()
    opened.store.selectOverlay(1)
    await flushPromises()
    expect(boxOf(1).classes()).toContain('box--selected')
    opened.store.selectOverlay(2)
    await flushPromises()
    expect(boxOf(1).classes()).not.toContain('box--selected')
    expect(boxOf(2).classes()).toContain('box--selected')
    // a escolha vinda do inspetor não força a abertura do inspetor
    expect(opened.store.overlayReveal).toBe(0)
  })

  it('a caixa fora da zona segura fica com a cor de aviso e diz de que lado saiu', async () => {
    await mountStage(stageBoxes({ 0: { outside_safe_zone: ['bottom', 'left'] } }))
    expect(boxOf(0).classes()).toContain('box--warn')
    expect(boxOf(0).attributes('aria-label')).toBe('Texto 1, fora da zona segura embaixo e à esquerda')
    expect(boxOf(1).classes()).not.toContain('box--warn')
  })

  it('a caixa que não se move mostra o motivo e fica marcada como fixa', async () => {
    await mountStage(stageBoxes({ 3: { movable: false, locked_reason: 'Presa a uma palavra da legenda.' } }))
    expect(boxOf(3).classes()).toContain('box--locked')
    expect(boxOf(3).attributes('title')).toBe('Presa a uma palavra da legenda.')
    expect(boxOf(3).attributes('aria-label')).toContain('Presa a uma palavra da legenda.')
    expect(boxOf(0).classes()).not.toContain('box--locked')
  })

  it('o palco é um grupo de elementos clicáveis, e não uma imagem', async () => {
    await mountStage()
    expect(wrapper!.find('.stage').attributes('role')).toBe('group')
  })
})

describe('a zona segura', () => {
  it('fica escondida até o botão do player ligá-la, e então mostra as quatro margens do formato', async () => {
    await mountStage()
    expect(wrapper!.find('[data-layer="safe-zone"]').exists()).toBe(false)
    usePlayerStore().setSafeZoneShown(true)
    await flushPromises()
    const layer = wrapper!.find('[data-layer="safe-zone"]')
    expect(layer.exists()).toBe(true)
    const bands = layer.findAll('.safe--band').map((band) => band.attributes('style') ?? '')
    expect(bands).toHaveLength(4)
    expect(bands[0]).toContain('height: 11.5%') // em cima
    expect(bands[1]).toContain('height: 21.9%') // embaixo
    expect(bands[2]).toContain('width: 5.6%') // à esquerda
    expect(bands[3]).toContain('width: 13.9%') // à direita
    expect(layer.find('.safe--edge').attributes('style')).toContain('top: 11.5%')
    // a zona não rouba o clique das caixas
    expect(layer.classes()).toContain('layer--safe')
  })

  it('sem as caixas do servidor não há margens para desenhar', async () => {
    await mountStage(null)
    usePlayerStore().setSafeZoneShown(true)
    await flushPromises()
    expect(wrapper!.find('[data-layer="safe-zone"]').exists()).toBe(false)
  })
})
