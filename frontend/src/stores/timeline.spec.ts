import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { RULER_MODE_KEY } from '@/lib/tempoGrid'
import { projectSpec, timelineView } from '@/test/editorFixtures'
import { openEditor } from '@/test/editorMount'
import { MAX_PX_PER_SEC, MIN_PX_PER_SEC, TRACK_HEADER_WIDTH } from '@/lib/timeline'
import { useTimelineStore, WINDOW_CHUNK_PX } from './timeline'

beforeEach(() => {
  window.localStorage.clear()
})

async function openTimeline() {
  const opened = await openEditor() // a vista de 6 s
  return { ...opened, timeline: useTimelineStore() }
}

describe('zoom', () => {
  it('começa em 60 px por segundo e os botões aproximam e afastam em passos de 1,3', async () => {
    const { timeline } = await openTimeline()
    expect(timeline.pxPerSec).toBe(60)
    timeline.zoomIn()
    expect(timeline.pxPerSec).toBeCloseTo(78, 9)
    timeline.zoomOut()
    timeline.zoomOut()
    expect(timeline.pxPerSec).toBeCloseTo(60 / 1.3, 9)
  })

  it('nunca passa dos limites', async () => {
    const { timeline } = await openTimeline()
    timeline.setZoom(100_000)
    expect(timeline.pxPerSec).toBe(MAX_PX_PER_SEC)
    timeline.setZoom(0.001)
    expect(timeline.pxPerSec).toBe(MIN_PX_PER_SEC)
  })

  it('aproximar pede ao painel para centralizar o cursor', async () => {
    const { timeline, store } = await openTimeline()
    store.setPlayhead(2)
    timeline.zoomIn()
    expect(timeline.scrollRequest).toMatchObject({ kind: 'center', seconds: 2 })
  })

  it('a roda com Ctrl mantém o instante sob o ponteiro no mesmo lugar da tela', async () => {
    const { timeline } = await openTimeline()
    timeline.zoomWheel(1, 3.5, 200)
    expect(timeline.pxPerSec).toBeCloseTo(60 * 1.15, 9)
    expect(timeline.scrollRequest).toMatchObject({ kind: 'anchor', seconds: 3.5, offsetPx: 200 })
    timeline.zoomWheel(-1, 3.5, 200)
    expect(timeline.pxPerSec).toBeCloseTo(60, 9)
  })

  it('no limite do zoom, nada muda e nenhum pedido de rolagem sai', async () => {
    const { timeline } = await openTimeline()
    timeline.setZoom(MAX_PX_PER_SEC)
    const before = timeline.scrollRequest
    timeline.zoomWheel(1, 1, 10)
    expect(timeline.scrollRequest).toBe(before)
  })

  it('"Ajustar" faz os 6 s do vídeo caberem na largura medida e volta ao começo', async () => {
    const { timeline } = await openTimeline()
    timeline.setScroll(0, 540 + TRACK_HEADER_WIDTH)
    timeline.zoomFit()
    // (540 - 40 de folga) / 6 s
    expect(timeline.pxPerSec).toBeCloseTo(500 / 6, 9)
    expect(timeline.scrollRequest).toMatchObject({ kind: 'start' })
  })
})

describe('encaixe e rótulo de ripple', () => {
  it('o encaixe liga e desliga; a tolerância é 8 px em segundos, ou zero desligado', async () => {
    const { timeline } = await openTimeline()
    expect(timeline.snapEnabled).toBe(true)
    expect(timeline.snapTolerance).toBeCloseTo(8 / 60, 9)
    expect(timeline.toggleSnap()).toBe(false)
    expect(timeline.snapTolerance).toBe(0)
  })

  it('o botão de ripple só troca o rótulo', async () => {
    const { timeline } = await openTimeline()
    expect(timeline.rippleAlways).toBe(false)
    expect(timeline.toggleRipple()).toBe(true)
    expect(timeline.toggleRipple()).toBe(false)
  })
})

const TEMPO = { bpm: 120, time_signature: '4/4', beats_per_bar: 4, offset: 0, period: 0.5 }

async function openWithTempo() {
  const view = { ...timelineView(), tempo: TEMPO }
  const opened = await openEditor(projectSpec(), { 'POST /api/projects/demo/timeline': () => view })
  return { ...opened, timeline: useTimelineStore() }
}

describe('régua em compassos e encaixe nos tempos', () => {
  it('sem andamento no projeto a régua é de segundos, o botão não alterna e a grade não atrai', async () => {
    const { timeline } = await openTimeline()
    expect(timeline.tempo).toBeNull()
    expect(timeline.toggleRuler()).toBe('seconds')
    expect(timeline.rulerMode).toBe('seconds')
    expect(timeline.gridPoints).toEqual([])
    expect(window.localStorage.getItem(RULER_MODE_KEY)).toBeNull()
  })

  it('com andamento a régua alterna entre segundos e compassos e a escolha fica no navegador', async () => {
    const { timeline } = await openWithTempo()
    expect(timeline.tempo).toEqual(TEMPO)
    expect(timeline.rulerMode).toBe('seconds')
    expect(timeline.toggleRuler()).toBe('bars')
    expect(timeline.rulerMode).toBe('bars')
    expect(window.localStorage.getItem(RULER_MODE_KEY)).toBe('bars')
    expect(timeline.toggleRuler()).toBe('seconds')
    expect(window.localStorage.getItem(RULER_MODE_KEY)).toBe('seconds')
  })

  it('lembra a régua escolhida ao abrir de novo, mas sem andamento volta a segundos', async () => {
    window.localStorage.setItem(RULER_MODE_KEY, 'bars')
    const { timeline } = await openWithTempo()
    expect(timeline.rulerMode).toBe('bars')
    const plain = await openTimeline()
    expect(plain.timeline.rulerMode).toBe('seconds')
  })

  it('os tempos entram como alvos do encaixe enquanto o Snap está ligado', async () => {
    const { timeline } = await openWithTempo()
    expect(timeline.gridPoints.slice(0, 4)).toEqual([0, 0.5, 1, 1.5]) // 30 px por tempo no zoom padrão
    expect(timeline.gridPoints.at(-1)).toBe(6)
    timeline.toggleSnap()
    expect(timeline.gridPoints).toEqual([])
    timeline.toggleSnap()
    timeline.setZoom(10) // 5 px por tempo: só os compassos, a 20 px, ainda não cabem
    expect(timeline.gridPoints).toEqual([])
    timeline.setZoom(15) // 7,5 px por tempo, 30 px por compasso
    expect(timeline.gridPoints).toEqual([0, 2, 4, 6])
  })
})

describe('janela visível', () => {
  it('anda em blocos, com um bloco de folga de cada lado, e a rolagem dentro do bloco não a muda', async () => {
    const { timeline } = await openTimeline()
    timeline.setScroll(0, 1000)
    const right = timeline.windowRightPx
    expect(timeline.windowLeftPx).toBe(0)
    expect(right).toBe(Math.ceil(1000 / WINDOW_CHUNK_PX) * WINDOW_CHUNK_PX + WINDOW_CHUNK_PX)
    timeline.setScroll(30, 1000)
    expect(timeline.windowRightPx).toBe(right)
    timeline.setScroll(3000, 1000)
    expect(timeline.windowLeftPx).toBeGreaterThan(2000)
    expect(timeline.windowRightPx).toBeGreaterThan(right)
  })

  it('antes de medir o painel (largura zero), assume uma largura para não esconder tudo', async () => {
    const { timeline } = await openTimeline()
    expect(timeline.viewportWidth).toBe(0)
    expect(timeline.windowRightPx).toBeGreaterThan(1000)
  })
})

describe('soltar mídia', () => {
  it('o painel Mídia registra o tratador e pode desregistrar; um tratador antigo não derruba o novo', async () => {
    const { timeline } = await openTimeline()
    const first = () => undefined
    const second = () => undefined
    const stopFirst = timeline.onMediaDrop(first)
    expect(timeline.mediaDropHandler).toBe(first)
    timeline.onMediaDrop(second)
    stopFirst()
    expect(timeline.mediaDropHandler).toBe(second)
  })
})

describe('trocar de projeto', () => {
  it('o zoom, a rolagem e a trilha sob o mouse voltam ao padrão', async () => {
    const { timeline, store } = await openTimeline()
    timeline.setZoom(200)
    timeline.setScroll(500, 900)
    timeline.hoverTrackId = 'V1'
    await store.open('outro', { force: true })
    await nextTick()
    expect(timeline.pxPerSec).toBe(60)
    expect(timeline.scrollLeft).toBe(0)
    expect(timeline.hoverTrackId).toBeNull()
  })
})

describe('sem projeto aberto', () => {
  it('o store existe e usa o padrão', () => {
    setActivePinia(createPinia())
    const timeline = useTimelineStore()
    expect(timeline.pxPerSec).toBe(60)
    expect(timeline.snapEnabled).toBe(true)
  })
})
