import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BoxLayout, TimelineView } from '@/api'
import { FRAME_POLL_MS } from '@/stores/realFrame'
import { useRealFrameStore } from '@/stores/realFrame'
import { usePlayerStore } from '@/stores/player'
import { useToastsStore } from '@/stores/toasts'
import { boxLayout, overlayBox, projectSpec, timelineItem, timelineTrack } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import PlayerStage from './PlayerStage.vue'

/* Os gestos no palco: um quadro 1080x1920 com um texto alinhado à esquerda (0), uma imagem (1), um PiP (2) e uma HTML
   (3). O palco mede 300 x 500 px na tela (o jsdom não mede layout, então o retângulo é injetado): 30 px na horizontal
   e 50 px na vertical valem 0,1 do quadro. As caixas são as que o servidor devolveria. */
const STAGE_PX = { width: 300, height: 500 }

type Overlays = Array<Record<string, unknown>>

const OVERLAYS: Overlays = [
  { type: 'text', text: 'Gancho', role: 'hook', start: 0, end: 4 },
  { type: 'image', src: 'selo.png', start: 0, opacity: 0.5, position: 'top-right' },
  { type: 'video', src: 'cam.mp4', start: 0, position: 'bottom-right', border: 6 },
  { type: 'html', infographic: 'barra', start: 0 },
]

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
          timelineItem(3, { id: 'GR-3', kind: 'html', start: 0, end: 12, src: null, path: null }),
        ],
        { kind: 'graphics' },
      ),
      timelineTrack('V1', [timelineItem(0, { id: 'V1-0', start: 0, end: 12, path: 'C:/cam1.mp4' })]),
    ],
  }
}

type BoxExtras = Partial<Record<number, Parameters<typeof overlayBox>[0]>>

function stageBoxes(extra: BoxExtras = {}): BoxLayout {
  return boxLayout([
    // texto alinhado à esquerda: a âncora é a borda do texto
    overlayBox({ index: 0, kind: 'text', start: 0, end: 4, left: 0.1, top: 0.2, width: 0.5, height: 0.07, anchor: { x: 0.1, y: 0.235 }, wrap: { left: 0.08, width: 0.84 }, ...extra[0] }),
    overlayBox({ index: 1, kind: 'image', left: 0.6, top: 0.3, width: 0.2, height: 0.1, anchor: { x: 0.7, y: 0.35 }, resize: 'keep_aspect', wrap: null, ...extra[1] }),
    overlayBox({ index: 2, kind: 'video', left: 0.5, top: 0.6, width: 0.4, height: 0.225, anchor: { x: 0.7, y: 0.7125 }, resize: 'keep_aspect', wrap: null, ...extra[2] }),
    overlayBox({ index: 3, kind: 'html', left: 0.2, top: 0.35, width: 0.6, height: 0.3, anchor: { x: 0.5, y: 0.5 }, resize: 'free', wrap: null, ...extra[3] }),
  ])
}

let wrapper: VueWrapper | null = null
let opened: OpenedEditor
// o que o servidor devolve de caixas: um teste troca isto depois da gravação para simular a nova conta
let boxesNow: () => BoxLayout

interface Setup {
  overlays?: Overlays
  boxes?: BoxExtras
  routes?: Record<string, unknown>
}

async function mountGesture(setup: Setup = {}) {
  const spec = { ...projectSpec(), overlays: setup.overlays ?? OVERLAYS }
  boxesNow = () => stageBoxes(setup.boxes)
  opened = await openEditor(spec, {
    'POST /api/projects/demo/timeline': () => stageView(),
    'POST /api/projects/demo/boxes': () => boxesNow(),
    'PUT /api/projects/demo': { ok: true, spec_path: 'x', revision: 'rev-2' },
    ...setup.routes,
  })
  wrapper = await mountEditorPart(PlayerStage, opened, {}, true)
  // o jsdom não mede layout: o palco ganha o retângulo de mentira
  vi.spyOn(wrapper.find('.stage').element, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: STAGE_PX.width,
    bottom: STAGE_PX.height,
    ...STAGE_PX,
    toJSON: () => ({}),
  })
  await flushPromises()
  return wrapper
}

const boxOf = (index: number) => wrapper!.find(`button.box[data-overlay="${index}"]`)
const handlesOf = () => wrapper!.findAll('.handle').map((handle) => handle.attributes('data-handle'))
const saves = () => opened.fetch.to('PUT /api/projects/demo')
const boxRequests = () => opened.fetch.to('POST /api/projects/demo/boxes')
const frameRequests = () => opened.fetch.to('POST /api/projects/demo/frame')
const savedOverlay = (index: number, call = 0) => (saves()[call]?.body as { overlays: Array<Record<string, unknown>> }).overlays[index]

function mouse(type: 'mousemove' | 'mouseup', x: number, y: number, extra: MouseEventInit = {}) {
  document.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, bubbles: true, cancelable: true, button: 0, ...extra }))
}

/** Aperta o mouse na caixa (ou na alça) em (0, 0), anda até (x, y) e solta, e espera o resto do que o soltar dispara. */
async function drag(target: { trigger: (type: string, init?: object) => Promise<void> }, x: number, y: number, extra: MouseEventInit = {}) {
  await target.trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
  mouse('mousemove', x, y, extra)
  mouse('mouseup', x, y, extra)
  await flushPromises()
}

const noAlt = { altKey: true }

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
  // um gesto que o teste deixou no meio (mouse apertado) termina aqui, para os ouvintes do documento não vazarem
  document.dispatchEvent(new MouseEvent('mouseup'))
  wrapper?.unmount()
  wrapper = null
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('clique e arrasto', () => {
  it('um clique sem movimento é só seleção: não grava, não cria passo no desfazer e não pede nada', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 1, 1)
    mouse('mouseup', 1, 1)
    await boxOf(1).trigger('click')
    await flushPromises()
    expect(opened.store.selectedOverlay).toBe(1)
    expect(saves()).toHaveLength(0)
    expect(opened.store.canUndo).toBe(false)
    expect(opened.store.gesturing).toBe(false)
    expect(frameRequests()).toHaveLength(0)
  })

  it('o clique que o navegador manda ao fim de um arrasto não abre o inspetor, mas um clique de verdade abre', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 30, 50, noAlt)
    mouse('mouseup', 30, 50, noAlt)
    // o navegador manda o click logo depois do mouseup, antes de qualquer espera
    await boxOf(1).trigger('click')
    await flushPromises()
    expect(opened.store.selectedOverlay).toBe(1)
    expect(opened.store.overlayReveal).toBe(0)
    await boxOf(1).trigger('click')
    expect(opened.store.overlayReveal).toBe(1)
  })

  it('só depois de alguns pixels começa o gesto', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 2, 0, noAlt)
    expect(opened.store.gesturing).toBe(false)
    mouse('mousemove', 4, 0, noAlt)
    expect(opened.store.gesturing).toBe(true)
  })

  it('durante o gesto a caixa anda no cliente, sem chamar o servidor, e o disco não é consultado', async () => {
    await mountGesture()
    const requestsBefore = boxRequests().length
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 30, 50, noAlt)
    await flushPromises()
    expect(boxOf(1).attributes('style')).toContain('left: 70%')
    expect(boxOf(1).attributes('style')).toContain('top: 40%')
    expect(boxOf(1).classes()).toContain('box--dragging')
    // a imagem do palco segue a caixa
    expect(wrapper!.find('.overlay-image').attributes('style')).toContain('left: 70%')
    expect(opened.store.gesturing).toBe(true)
    expect(opened.store.selectedOverlay).toBe(1)
    expect(saves()).toHaveLength(0)
    expect(boxRequests()).toHaveLength(requestsBefore)
    await opened.store.checkDisk()
    expect(opened.fetch.to('GET /api/projects/demo/revision')).toHaveLength(0)
    mouse('mouseup', 30, 50, noAlt)
    await flushPromises()
  })

  it('o gesto pausa o player: a caixa vale para o instante do cursor', async () => {
    await mountGesture()
    const player = usePlayerStore()
    player.setRate(1)
    expect(player.playing).toBe(true)
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 30, 0, noAlt)
    expect(player.playing).toBe(false)
    mouse('mouseup', 30, 0, noAlt)
    await flushPromises()
  })

  it('Esc larga o gesto sem gravar nada', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 30, 50, noAlt)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    mouse('mouseup', 30, 50, noAlt)
    await flushPromises()
    expect(opened.store.gesturing).toBe(false)
    expect(saves()).toHaveLength(0)
    expect(opened.store.canUndo).toBe(false)
    expect(boxOf(1).attributes('style')).toContain('left: 60%')
  })

  it('só o botão principal do mouse começa o gesto', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 2, clientX: 0, clientY: 0 })
    mouse('mousemove', 30, 50, noAlt)
    expect(opened.store.gesturing).toBe(false)
  })

  it('sem a medida do palco (nada desenhado ainda) não há como traduzir pixel em fração, e o gesto não começa', async () => {
    await mountGesture()
    vi.spyOn(wrapper!.find('.stage').element, 'getBoundingClientRect').mockReturnValue({ width: 0, height: 0 } as DOMRect)
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 30, 50, noAlt)
    expect(opened.store.gesturing).toBe(false)
  })
})

describe('ao soltar: uma mudança, uma gravação', () => {
  it('a imagem grava o centro novo, tira a posição nomeada e vale UM passo do desfazer', async () => {
    await mountGesture()
    const before = JSON.stringify(opened.store.spec)
    await drag(boxOf(1), 30, 50, noAlt)
    expect(saves()).toHaveLength(1)
    const saved = savedOverlay(1)
    expect(saved).toMatchObject({ type: 'image', src: 'selo.png', x: 0.8, y: 0.45 })
    expect(saved).not.toHaveProperty('position')
    expect(saves()[0]?.headers['If-Match']).toBe('rev-1')
    expect(opened.store.dirty).toBe(false)
    expect(opened.store.gesturing).toBe(false)
    // um passo só: desfazer volta tudo, e não sobra nada para desfazer
    opened.store.undo()
    expect(JSON.stringify(opened.store.spec)).toBe(before)
    expect(opened.store.canUndo).toBe(false)
  })

  it('a ordem é: gravar, pedir as caixas novas e só então o quadro real', async () => {
    await mountGesture({ routes: { 'POST /api/projects/demo/frame': () => ({ key: '0123456789abcdef', status: 'ready', t: 0, notes: [], url: '/api/file?path=q.png' }) } })
    const requestsBefore = opened.fetch.calls.length
    await drag(boxOf(1), 30, 50, noAlt)
    const order = opened.fetch.calls
      .slice(requestsBefore)
      .map((call) => `${call.method} ${call.path}`)
      .filter((route) => !route.startsWith('GET /api/state') && !route.startsWith('GET /api/templates') && !route.endsWith('/timeline'))
    expect(order.slice(0, 3)).toEqual(['PUT /api/projects/demo', 'POST /api/projects/demo/boxes', 'POST /api/projects/demo/frame'])
  })

  it('o texto alinhado à esquerda move a BORDA (a âncora) e escreve x e y juntos', async () => {
    await mountGesture()
    await drag(boxOf(0), 30, 0, noAlt)
    expect(savedOverlay(0)).toMatchObject({ type: 'text', x: 0.2, y: 0.235 })
  })

  it('o PiP com slide guarda a posição: é dela que vem a direção da entrada', async () => {
    await mountGesture({ overlays: [OVERLAYS[0]!, OVERLAYS[1]!, { ...OVERLAYS[2]!, animation: 'slide' }, OVERLAYS[3]!] })
    await drag(boxOf(2), -30, 0, noAlt)
    expect(savedOverlay(2)).toMatchObject({ x: 0.6, y: 0.7125, position: 'bottom-right', animation: 'slide' })
  })

  it('o PiP sem slide perde a posição nomeada, que o x e o y substituem', async () => {
    await mountGesture()
    await drag(boxOf(2), -30, 0, noAlt)
    expect(savedOverlay(2)).toMatchObject({ x: 0.6, y: 0.7125 })
    expect(savedOverlay(2)).not.toHaveProperty('position')
  })

  it('a HTML grava x, y, width e height juntos, ou só x e y a devolveriam ao quadro todo', async () => {
    await mountGesture()
    await drag(boxOf(3), 30, 0, noAlt)
    expect(savedOverlay(3)).toMatchObject({ type: 'html', x: 0.6, y: 0.5, width: 0.6, height: 0.3 })
  })

  it('x e y ficam entre 0 e 1 mesmo arrastando para fora do quadro', async () => {
    await mountGesture()
    await drag(boxOf(1), 900, 2000, noAlt)
    expect(savedOverlay(1)).toMatchObject({ x: 1, y: 1 })
    await drag(boxOf(1), -9000, -9000, noAlt)
    expect(savedOverlay(1, 1)).toMatchObject({ x: 0, y: 0 })
  })

  it('sai da região: grava os campos explícitos, tira a região e diz isso na tela', async () => {
    await mountGesture({
      overlays: [{ type: 'text', text: 'Gancho', role: 'hook', start: 0, end: 4, region: 'topo' }, OVERLAYS[1]!, OVERLAYS[2]!, OVERLAYS[3]!],
      boxes: { 0: { placement: 'region', region: 'topo', left: 0.3, width: 0.4, anchor: { x: 0.5, y: 0.2 }, wrap: { left: 0.1, width: 0.8 } } },
    })
    await drag(boxOf(0), 30, 0, noAlt)
    const saved = savedOverlay(0)
    expect(saved).not.toHaveProperty('region')
    expect(saved).toMatchObject({ x: 0.6, y: 0.2, style: { align: 'center', max_width: 0.8 } })
    expect(wrapper!.find('[data-status="notice"]').text()).toContain('Texto 1 deixou de seguir a região “topo”')
  })

  it('não mostra travessão em nenhum aviso do palco', async () => {
    await mountGesture({
      overlays: [{ type: 'text', text: 'Gancho', role: 'hook', start: 0, end: 4, region: 'topo' }, OVERLAYS[1]!, OVERLAYS[2]!, OVERLAYS[3]!],
      boxes: { 0: { placement: 'region', region: 'topo' } },
    })
    await drag(boxOf(0), 30, 0, noAlt)
    expect(wrapper!.find('.stage-status').text()).not.toMatch(/[—–]/)
  })

  it('um gesto que volta ao ponto de partida não grava nada nem cria passo no desfazer', async () => {
    await mountGesture({ overlays: [OVERLAYS[0]!, { type: 'image', src: 'selo.png', start: 0, x: 0.7, y: 0.35 }, OVERLAYS[2]!, OVERLAYS[3]!] })
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 20, 0, noAlt)
    mouse('mousemove', 0, 0, noAlt)
    mouse('mouseup', 0, 0, noAlt)
    await flushPromises()
    expect(saves()).toHaveLength(0)
    expect(opened.store.canUndo).toBe(false)
    expect(opened.store.gesturing).toBe(false)
  })

  it('as outras mudanças ainda não salvas vão junto, e o indicador de "não salvo" some', async () => {
    await mountGesture()
    opened.store.setField('overlays.0.text', 'Outro gancho')
    expect(opened.store.dirty).toBe(true)
    await drag(boxOf(1), 30, 0, noAlt)
    expect(saves()).toHaveLength(1)
    expect((saves()[0]?.body as { overlays: Array<{ text?: string }> }).overlays[0]?.text).toBe('Outro gancho')
    expect(opened.store.dirty).toBe(false)
  })

  it('com 409 a faixa de escolha abre, o gesto fica como "não salvo" e nenhum erro aparece por cima', async () => {
    await mountGesture({ routes: { 'PUT /api/projects/demo': () => reply(409, { detail: 'O projeto mudou no disco.', revision: 'rev-9' }) } })
    await drag(boxOf(1), 30, 0, noAlt)
    expect(opened.store.conflict).toEqual({ revision: 'rev-9' })
    expect(opened.store.dirty).toBe(true)
    expect(useToastsStore().items).toEqual([])
    expect(opened.store.gesturing).toBe(false)
    // as caixas seguem a edição da tela
    expect(boxRequests().length).toBeGreaterThan(1)
  })

  it('as caixas novas do servidor tomam o lugar da caixa do gesto', async () => {
    await mountGesture()
    boxesNow = () => stageBoxes({ 1: { left: 0.55, top: 0.45, anchor: { x: 0.65, y: 0.5 } } })
    await drag(boxOf(1), 30, 50, noAlt)
    expect(boxOf(1).attributes('style')).toContain('left: 55%')
    expect(boxOf(1).classes()).not.toContain('box--dragging')
  })
})

describe('as alças', () => {
  it('só a caixa escolhida tem alças: o texto à esquerda puxa a borda direita, a imagem tem os quatro cantos, a HTML tem oito', async () => {
    await mountGesture()
    expect(handlesOf()).toEqual([])
    opened.store.selectOverlay(0)
    await flushPromises()
    expect(handlesOf()).toEqual(['e'])
    opened.store.selectOverlay(1)
    await flushPromises()
    expect(handlesOf()).toEqual(['nw', 'ne', 'sw', 'se'])
    opened.store.selectOverlay(2)
    await flushPromises()
    expect(handlesOf()).toHaveLength(4)
    opened.store.selectOverlay(3)
    await flushPromises()
    expect(handlesOf()).toHaveLength(8)
  })

  it('o texto centralizado tem as duas bordas, o alinhado à direita só a esquerda', async () => {
    await mountGesture({ boxes: { 0: { left: 0.3, width: 0.4, anchor: { x: 0.5, y: 0.235 } } } })
    opened.store.selectOverlay(0)
    await flushPromises()
    expect(handlesOf()).toEqual(['w', 'e'])
    boxesNow = () => stageBoxes({ 0: { left: 0.4, width: 0.5, anchor: { x: 0.9, y: 0.235 } } })
    await opened.store.refreshBoxes()
    await flushPromises()
    expect(handlesOf()).toEqual(['w'])
  })

  it('as alças do texto ficam na área da quebra, que é mais larga que o bloco escrito', async () => {
    await mountGesture()
    opened.store.selectOverlay(0)
    await flushPromises()
    const frame = wrapper!.find('.frame--wrap')
    expect(frame.attributes('style')).toContain('left: 8%')
    expect(frame.attributes('style')).toContain('width: 84%')
  })

  it('a caixa que não se move mostra o motivo e não tem alça nem gesto', async () => {
    await mountGesture({ boxes: { 3: { movable: false, locked_reason: 'Presa à palavra "oi" da legenda.', resize: 'none' } } })
    opened.store.selectOverlay(3)
    await flushPromises()
    expect(handlesOf()).toEqual([])
    expect(boxOf(3).attributes('title')).toBe('Presa à palavra "oi" da legenda.')
    await drag(boxOf(3), 30, 50, noAlt)
    expect(saves()).toHaveLength(0)
    expect(opened.store.gesturing).toBe(false)
  })

  it('redimensionar o texto muda a largura da quebra (style.max_width) e mais nada', async () => {
    await mountGesture()
    opened.store.selectOverlay(0)
    await flushPromises()
    await drag(wrapper!.find('[data-handle="e"]'), 30, 0, noAlt)
    const saved = savedOverlay(0)
    expect(saved).toMatchObject({ type: 'text', text: 'Gancho', style: { max_width: 0.94 } })
    expect(saved).not.toHaveProperty('x')
    expect(saved).not.toHaveProperty('y')
  })

  it('durante o redimensionamento a quebra anda no cliente', async () => {
    await mountGesture()
    opened.store.selectOverlay(0)
    await flushPromises()
    await wrapper!.find('[data-handle="e"]').trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', -60, 0, noAlt)
    await flushPromises()
    expect(wrapper!.find('.frame--wrap').attributes('style')).toContain('width: 64%')
    mouse('mouseup', -60, 0, noAlt)
    await flushPromises()
  })

  it('a imagem muda pelo canto, com o canto oposto parado e o aspecto mantido', async () => {
    await mountGesture()
    opened.store.selectOverlay(1)
    await flushPromises()
    await drag(wrapper!.find('[data-handle="se"]'), 30, 50, noAlt)
    const saved = savedOverlay(1) as { x: number; y: number; width: number }
    // o canto de cima à esquerda (0,6 ; 0,3) fica onde estava: a altura é metade da largura, em fração, e o aspecto se mantém
    expect(saved.x - saved.width / 2).toBeCloseTo(0.6, 3)
    expect(saved.y - saved.width / 4).toBeCloseTo(0.3, 3)
    expect(saved.width).toBeGreaterThan(0.2)
    expect(saved).not.toHaveProperty('position')
  })

  it('a HTML muda por borda: só a largura anda, com o lado oposto parado', async () => {
    await mountGesture()
    opened.store.selectOverlay(3)
    await flushPromises()
    await drag(wrapper!.find('[data-handle="e"]'), 30, 0, noAlt)
    const saved = savedOverlay(3) as { x: number; y: number; width: number; height: number }
    expect(saved.width).toBeCloseTo(0.7, 4)
    expect(saved.x).toBeCloseTo(0.55, 4)
    expect(saved.height).toBeCloseTo(0.3, 4)
    expect(saved.y).toBeCloseTo(0.5, 4)
  })

  it('o texto em região sai da região ao ser redimensionado, mantendo a âncora e o alinhamento', async () => {
    await mountGesture({
      overlays: [{ type: 'text', text: 'Gancho', role: 'hook', start: 0, end: 4, region: 'topo' }, OVERLAYS[1]!, OVERLAYS[2]!, OVERLAYS[3]!],
      boxes: { 0: { placement: 'region', region: 'topo', left: 0.3, width: 0.4, anchor: { x: 0.5, y: 0.2 }, wrap: { left: 0.1, width: 0.8 } } },
    })
    opened.store.selectOverlay(0)
    await flushPromises()
    await drag(wrapper!.find('[data-handle="e"]'), 30, 0, noAlt)
    const saved = savedOverlay(0)
    expect(saved).not.toHaveProperty('region')
    expect(saved).toMatchObject({ x: 0.5, y: 0.2, style: { align: 'center', max_width: 1 } })
  })
})

describe('o ímã', () => {
  it('puxa o centro da caixa para o centro do quadro e mostra a linha-guia', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    // o centro da imagem está em 0,7: 0,19 para a esquerda (57 px) o leva a 0,51, a 0,01 da linha do centro (dentro dos 8 px)
    mouse('mousemove', -57, 0)
    await flushPromises()
    expect(wrapper!.find('[data-guide="x"]').exists()).toBe(true)
    expect(wrapper!.find('[data-guide="x"]').attributes('style')).toContain('left: 50%')
    expect(wrapper!.find('[data-guide="y"]').exists()).toBe(false)
    expect(boxOf(1).attributes('style')).toContain('left: 40%')
    mouse('mouseup', -57, 0)
    await flushPromises()
    expect(wrapper!.find('[data-guide="x"]').exists()).toBe(false)
    expect(savedOverlay(1)).toMatchObject({ x: 0.5, y: 0.35 })
  })

  it('segura a borda da caixa na margem da zona segura', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    // a borda de cima (0,3) sobe 0,18 (90 px) e vai a 0,12, a 0,005 da margem de cima (0,115)
    mouse('mousemove', 0, -90)
    await flushPromises()
    expect(wrapper!.find('[data-guide="y"]').attributes('style')).toContain('top: 11.5%')
    expect(boxOf(1).attributes('style')).toContain('top: 11.5%')
    mouse('mouseup', 0, -90)
    await flushPromises()
  })

  it('o Alt desliga o ímã durante o gesto', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 0, -90, noAlt)
    await flushPromises()
    expect(wrapper!.find('[data-guide="y"]').exists()).toBe(false)
    expect(boxOf(1).attributes('style')).toContain('top: 12%')
    // soltar o Alt no meio do gesto traz o ímã de volta
    mouse('mousemove', 0, -90)
    await flushPromises()
    expect(boxOf(1).attributes('style')).toContain('top: 11.5%')
    mouse('mouseup', 0, -90)
    await flushPromises()
  })

  it('o canto puxado ao redimensionar também é segurado por uma linha', async () => {
    await mountGesture()
    opened.store.selectOverlay(1)
    await flushPromises()
    await wrapper!.find('[data-handle="se"]').trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    // o canto de baixo à direita está em x = 0,8: 9 px (0,03) a mais ainda deixa a margem da direita (0,861) longe
    mouse('mousemove', 9, 0)
    await flushPromises()
    expect(wrapper!.find('[data-guide="x"]').exists()).toBe(false)
    // com 25 px (0,083) o canto passa a menos de 8 px da margem da direita, e a linha o segura
    mouse('mousemove', 25, 0)
    await flushPromises()
    expect(wrapper!.find('[data-guide="x"]').exists()).toBe(true)
    mouse('mouseup', 25, 0)
    await flushPromises()
  })
})

describe('a zona segura durante e depois do gesto', () => {
  it('durante o gesto a cor de aviso é recalculada no cliente, sem esperar o servidor', async () => {
    await mountGesture()
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    // a imagem desce 0,4: a borda de baixo (0,8) passa da margem de baixo (0,781)
    mouse('mousemove', 0, 200, noAlt)
    await flushPromises()
    expect(boxOf(1).classes()).toContain('box--warn')
    expect(boxOf(1).attributes('aria-label')).toContain('fora da zona segura embaixo')
    // trazendo de volta, a cor de aviso sai
    mouse('mousemove', 0, 50, noAlt)
    await flushPromises()
    expect(boxOf(1).classes()).not.toContain('box--warn')
    mouse('mouseup', 0, 50, noAlt)
    await flushPromises()
  })

  it('ao soltar fora da zona, o aviso diz a rede, o formato e o lado; trazendo de volta, o aviso sai', async () => {
    await mountGesture()
    boxesNow = () => stageBoxes({ 1: { top: 0.7, anchor: { x: 0.7, y: 0.75 }, outside_safe_zone: ['bottom'] } })
    await drag(boxOf(1), 0, 200, noAlt)
    const notice = wrapper!.find('[data-status="notice"]')
    expect(notice.text()).toBe('Imagem 2 saiu da zona segura do Instagram Reels, embaixo.')
    expect(notice.text()).not.toMatch(/[—–]/)
    expect(boxOf(1).classes()).toContain('box--warn')
    boxesNow = () => stageBoxes()
    await drag(boxOf(1), 0, -250, noAlt)
    expect(wrapper!.find('[data-status="notice"]').exists()).toBe(false)
    expect(boxOf(1).classes()).not.toContain('box--warn')
  })

  it('o aviso sai quando a escolha muda ou a spec muda por outro caminho', async () => {
    await mountGesture()
    boxesNow = () => stageBoxes({ 1: { top: 0.7, outside_safe_zone: ['bottom', 'left'] } })
    await drag(boxOf(1), 0, 200, noAlt)
    expect(wrapper!.find('[data-status="notice"]').text()).toContain('embaixo e à esquerda')
    opened.store.undo()
    await flushPromises()
    expect(wrapper!.find('[data-status="notice"]').exists()).toBe(false)
  })
})

describe('desfazer e refazer cobrem os gestos', () => {
  it('Ctrl+Z desfaz o gesto e Ctrl+Y refaz', async () => {
    await mountGesture()
    const before = JSON.stringify(opened.store.spec)
    await drag(boxOf(1), 30, 50, noAlt)
    const after = JSON.stringify(opened.store.spec)
    expect(after).toContain('"x":0.8')
    expect(opened.store.undo()).toBe(true)
    expect(JSON.stringify(opened.store.spec)).toBe(before)
    expect(opened.store.redo()).toBe(true)
    expect(JSON.stringify(opened.store.spec)).toBe(after)
  })
})

describe('o quadro real', () => {
  const KEY = '0123456789abcdef'
  const readyFrame = (extra: Record<string, unknown> = {}) => ({ key: KEY, status: 'ready', t: 1, notes: [], url: '/api/file?path=q.png', ...extra })

  it('depois de soltar, pede o quadro do cursor com a edição da tela e o mostra sobre o palco, com o instante e as notas', async () => {
    await mountGesture({ routes: { 'POST /api/projects/demo/frame': () => readyFrame({ t: 1.0333, notes: ['A legenda automática não entrou.'] }) } })
    opened.store.setPlayhead(1.03)
    await drag(boxOf(1), 30, 50, noAlt)
    expect(frameRequests()).toHaveLength(1)
    const body = frameRequests()[0]?.body as { t: number; spec: { overlays: Array<Record<string, unknown>> } }
    expect(body.t).toBe(1.03)
    // a edição que está na tela (já com o gesto), e não a do disco
    expect(body.spec.overlays[1]).toMatchObject({ x: 0.8, y: 0.45 })
    expect(wrapper!.find('[data-layer="real-frame"]').attributes('src')).toBe('/api/file?path=q.png')
    // o instante é o que o servidor devolveu (00:00:01:01), e não o pedido
    expect(wrapper!.find('[data-status="real-frame"]').text()).toContain('Quadro real em 00:00:01:01')
    expect(wrapper!.find('[data-status="real-frame-note"]').text()).toBe('A legenda automática não entrou.')
  })

  it('enquanto o quadro não chega mostra a composição aproximada e o andamento, e consulta até ficar pronto', async () => {
    let answers = 0
    await mountGesture({
      routes: {
        'POST /api/projects/demo/frame': () => ({ key: KEY, status: 'pending', t: 0, notes: [], label: 'Montando o trecho', percent: 30 }),
        [`GET /api/projects/demo/frame/${KEY}`]: () => (++answers < 2 ? { key: KEY, status: 'pending', t: 0, notes: [], label: 'Montando o trecho', percent: 70 } : readyFrame({ t: 0 })),
      },
    })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await drag(boxOf(1), 30, 50, noAlt)
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(false)
    expect(wrapper!.find('[data-status="real-frame"]').text()).toBe('Gerando o quadro real: Montando o trecho (30%)')
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS)
    await flushPromises()
    expect(wrapper!.find('[data-status="real-frame"]').text()).toContain('(70%)')
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS)
    await flushPromises()
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(true)
  })

  it('superado: a tela volta ao aproximado e a chave deixa de ser consultada', async () => {
    await mountGesture({
      routes: {
        'POST /api/projects/demo/frame': () => ({ key: KEY, status: 'pending', t: 0, notes: [], label: 'Montando', percent: 0 }),
        [`GET /api/projects/demo/frame/${KEY}`]: () => ({ key: KEY, status: 'superseded', t: 0, notes: [] }),
      },
    })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await drag(boxOf(1), 30, 50, noAlt)
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS)
    await flushPromises()
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(false)
    expect(wrapper!.find('[data-status="real-frame"]').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS * 4)
    expect(opened.fetch.to(`GET /api/projects/demo/frame/${KEY}`)).toHaveLength(1)
  })

  it('um erro do servidor aparece em português, sem derrubar o palco', async () => {
    await mountGesture({ routes: { 'POST /api/projects/demo/frame': () => ({ key: KEY, status: 'error', t: null, notes: [], error: 'O vídeo do trecho sumiu.' }) } })
    await drag(boxOf(1), 30, 50, noAlt)
    expect(wrapper!.find('[data-status="real-frame"]').text()).toBe('Não foi possível gerar o quadro real: O vídeo do trecho sumiu.')
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(false)
    expect(boxOf(1).exists()).toBe(true)
  })

  it('qualquer mudança na spec ou no cursor volta à composição aproximada', async () => {
    await mountGesture({ routes: { 'POST /api/projects/demo/frame': () => readyFrame() } })
    await drag(boxOf(1), 30, 50, noAlt)
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(true)
    opened.store.setPlayhead(2)
    await flushPromises()
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(false)
    opened.fetch.set('POST /api/projects/demo/frame', () => readyFrame())
    await useRealFrameStore().request()
    await flushPromises()
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(true)
    opened.store.setField('overlays.0.text', 'Mudou')
    await flushPromises()
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(false)
  })

  it('o primeiro movimento de um gesto novo já esconde o quadro real', async () => {
    await mountGesture({ routes: { 'POST /api/projects/demo/frame': () => readyFrame() } })
    await drag(boxOf(1), 30, 50, noAlt)
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(true)
    await boxOf(1).trigger('mousedown', { button: 0, clientX: 0, clientY: 0 })
    mouse('mousemove', 10, 0, noAlt)
    await flushPromises()
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(false)
    mouse('mouseup', 10, 0, noAlt)
    await flushPromises()
  })

  it('o botão do aviso volta à prévia aproximada', async () => {
    await mountGesture({ routes: { 'POST /api/projects/demo/frame': () => readyFrame() } })
    await drag(boxOf(1), 30, 50, noAlt)
    await wrapper!.find('.stage-status__close').trigger('click')
    expect(wrapper!.find('[data-layer="real-frame"]').exists()).toBe(false)
    expect(useRealFrameStore().state).toBe('idle')
  })

  it('ao desmontar o palco as consultas pendentes param', async () => {
    await mountGesture({
      routes: {
        'POST /api/projects/demo/frame': () => ({ key: KEY, status: 'pending', t: 0, notes: [], label: 'Montando', percent: 0 }),
        [`GET /api/projects/demo/frame/${KEY}`]: () => ({ key: KEY, status: 'pending', t: 0, notes: [], label: 'Montando', percent: 10 }),
      },
    })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await drag(boxOf(1), 30, 50, noAlt)
    wrapper!.unmount()
    wrapper = null
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS * 4)
    expect(opened.fetch.to(`GET /api/projects/demo/frame/${KEY}`)).toHaveLength(0)
  })

  it('o 409 não impede o quadro real: ele se faz sobre a edição da tela', async () => {
    await mountGesture({
      routes: {
        'PUT /api/projects/demo': () => reply(409, { detail: 'mudou', revision: 'rev-9' }),
        'POST /api/projects/demo/frame': () => readyFrame(),
      },
    })
    await drag(boxOf(1), 30, 50, noAlt)
    expect(frameRequests()).toHaveLength(1)
  })
})
