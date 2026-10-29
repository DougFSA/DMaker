import { describe, expect, it } from 'vitest'
import type { TimelineItem, TimelineTrack } from '@/api'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import { dragOperation, dragPreview, v1TargetIndex, type DragStart, type SnapContext } from './timelineDrag'

const NO_SNAP: SnapContext = { points: [], tolerance: 0, total: 30 }

function v1(): TimelineTrack {
  // quatro trechos de 3 s: 0-3, 3-6, 6-9, 9-12
  return timelineTrack('V1', [0, 1, 2, 3].map((index) => timelineItem(index)))
}

function startOf(mode: DragStart['mode'], trackId: string, item: TimelineItem, side: DragStart['side'] = null): DragStart {
  return { mode, trackId, item, side, original: { start: item.start, end: item.end } }
}

describe('mover um trecho da V1', () => {
  it('o alvo é o primeiro outro trecho que começa depois do ponto onde o trecho foi solto', () => {
    const track = v1()
    expect(v1TargetIndex(track.items, 'V1:0', 7)).toBe(3)
    expect(v1TargetIndex(track.items, 'V1:0', 20)).toBe(4)
    expect(v1TargetIndex(track.items, 'V1:3', 0.5)).toBe(1)
  })

  it('o fantasma segue o mouse e o marcador mostra onde o trecho entra', () => {
    const track = v1()
    const drag = startOf('move-v1', 'V1', track.items[0] as TimelineItem)
    const preview = dragPreview(drag, track, 7, NO_SNAP)
    expect(preview.start).toBe(7)
    expect(preview.end).toBe(10)
    expect(preview.targetIndex).toBe(3)
    expect(preview.indicatorAt).toBe(9)
  })

  it('soltar depois do último trecho põe o marcador no fim do vídeo', () => {
    const track = v1()
    const drag = startOf('move-v1', 'V1', track.items[0] as TimelineItem)
    expect(dragPreview(drag, track, 40, NO_SNAP).indicatorAt).toBe(30)
  })

  it('o ponto onde o trecho cai encaixa nas bordas', () => {
    const track = v1()
    const drag = startOf('move-v1', 'V1', track.items[0] as TimelineItem)
    const snap: SnapContext = { points: [6, 9], tolerance: 0.2, total: 30 }
    expect(dragPreview(drag, track, 5.9, snap).start).toBe(6)
  })

  it('a operação é um mover para o índice de destino, descontando o próprio trecho', () => {
    const track = v1()
    const drag = startOf('move-v1', 'V1', track.items[0] as TimelineItem)
    const preview = dragPreview(drag, track, 7, NO_SNAP)
    expect(dragOperation(drag, track, preview)).toEqual({ type: 'move', index: 0, to: 2 })
  })

  it('soltar onde já estava, ou logo depois de si mesmo, não faz nada', () => {
    const track = v1()
    const drag = startOf('move-v1', 'V1', track.items[1] as TimelineItem)
    expect(dragOperation(drag, track, dragPreview(drag, track, 0.1, NO_SNAP))).toBeNull()
    expect(dragOperation(drag, track, dragPreview(drag, track, 2.5, NO_SNAP))).toBeNull()
  })

  it('arrastar para a esquerda leva o trecho para antes dos que começam depois do alvo', () => {
    const track = v1()
    const drag = startOf('move-v1', 'V1', track.items[3] as TimelineItem)
    expect(dragOperation(drag, track, dragPreview(drag, track, -10, NO_SNAP))).toEqual({ type: 'move', index: 3, to: 0 })
    expect(dragOperation(drag, track, dragPreview(drag, track, -8, NO_SNAP))).toEqual({ type: 'move', index: 3, to: 1 })
  })
})

describe('aparar', () => {
  it('a alça de entrada move só o começo e a de saída só o fim', () => {
    const track = v1()
    const item = track.items[1] as TimelineItem
    expect(dragPreview(startOf('trim', 'V1', item, 'in'), track, 1, NO_SNAP)).toMatchObject({ start: 4, end: 6 })
    expect(dragPreview(startOf('trim', 'V1', item, 'out'), track, 1, NO_SNAP)).toMatchObject({ start: 3, end: 7 })
  })

  it('nunca deixa o item menor que o mínimo nem começar antes de zero', () => {
    const track = v1()
    const item = track.items[1] as TimelineItem
    expect(dragPreview(startOf('trim', 'V1', item, 'in'), track, 10, NO_SNAP).start).toBeCloseTo(5.9, 9)
    expect(dragPreview(startOf('trim', 'V1', item, 'out'), track, -10, NO_SNAP).end).toBeCloseTo(3.1, 9)
    expect(dragPreview(startOf('trim', 'V1', item, 'in'), track, -10, NO_SNAP).start).toBe(0)
  })

  it('a borda aparada encaixa nos pontos vizinhos', () => {
    const track = v1()
    const item = track.items[1] as TimelineItem
    const snap: SnapContext = { points: [7], tolerance: 0.2, total: 30 }
    expect(dragPreview(startOf('trim', 'V1', item, 'out'), track, 0.9, snap).end).toBe(7)
  })

  it('na V1 a operação é aparar com o quanto a borda andou', () => {
    const track = v1()
    const item = track.items[1] as TimelineItem
    const inDrag = startOf('trim', 'V1', item, 'in')
    expect(dragOperation(inDrag, track, dragPreview(inDrag, track, 1, NO_SNAP))).toEqual({ type: 'trim', index: 1, side: 'in', delta: 1 })
    const outDrag = startOf('trim', 'V1', item, 'out')
    expect(dragOperation(outDrag, track, dragPreview(outDrag, track, -0.5, NO_SNAP))).toEqual({ type: 'trim', index: 1, side: 'out', delta: -0.5 })
  })

  it('numa sobreposição a operação é o novo intervalo, nunca um aparar da V1 (que mexeria noutro trecho)', () => {
    const text = timelineItem(2, { id: 'TX:2', kind: 'text', start: 4, end: 8 })
    const track = timelineTrack('TX', [text], { kind: 'text' })
    const drag = startOf('trim', 'TX', text, 'out')
    expect(dragOperation(drag, track, dragPreview(drag, track, 1, NO_SNAP))).toEqual({ type: 'overlay_span', index: 2, start: 4, end: 9 })
    const inDrag = startOf('trim', 'TX', text, 'in')
    expect(dragOperation(inDrag, track, dragPreview(inDrag, track, 1, NO_SNAP))).toEqual({ type: 'overlay_span', index: 2, start: 5, end: 8 })
  })

  it('sem mover nada, não há operação', () => {
    const track = v1()
    const item = track.items[1] as TimelineItem
    const drag = startOf('trim', 'V1', item, 'out')
    expect(dragOperation(drag, track, dragPreview(drag, track, 0, NO_SNAP))).toBeNull()
  })
})

describe('deslocar um bloco', () => {
  const text = timelineItem(0, { id: 'TX:0', kind: 'text', start: 4, end: 8 })
  const track = timelineTrack('TX', [text], { kind: 'text' })

  it('anda inteiro, sem mudar a duração, e fica dentro de 0 e do fim do vídeo', () => {
    const drag = startOf('shift', 'TX', text)
    expect(dragPreview(drag, track, 2, NO_SNAP)).toMatchObject({ start: 6, end: 10 })
    expect(dragPreview(drag, track, -9, NO_SNAP)).toMatchObject({ start: 0, end: 4 })
    expect(dragPreview(drag, track, 99, NO_SNAP)).toMatchObject({ start: 26, end: 30 })
  })

  it('encaixa pelo começo ou pelo fim sem esticar nem encolher o bloco', () => {
    const drag = startOf('shift', 'TX', text)
    const byStart = dragPreview(drag, track, 1.95, { points: [6], tolerance: 0.1, total: 30 })
    expect(byStart.start).toBe(6)
    expect(byStart.end).toBeCloseTo(10, 9)
    const byEnd = dragPreview(drag, track, 1.95, { points: [10], tolerance: 0.1, total: 30 })
    expect(byEnd.end).toBe(10)
    expect(byEnd.start).toBeCloseTo(6, 9)
  })

  it('a operação é o novo intervalo da sobreposição', () => {
    const drag = startOf('shift', 'TX', text)
    expect(dragOperation(drag, track, dragPreview(drag, track, 2, NO_SNAP))).toEqual({ type: 'overlay_span', index: 0, start: 6, end: 10 })
  })

  it('a fala da narração só muda o início, pelo mesmo set_field das outras edições de campo', () => {
    const speech = timelineItem(1, { id: 'NAR:1', kind: 'narration', start: 4, end: 7 })
    const narration = timelineTrack('NAR', [speech], { kind: 'audio' })
    const drag = startOf('shift', 'NAR', speech)
    expect(dragOperation(drag, narration, dragPreview(drag, narration, 1.5, NO_SNAP))).toEqual({
      type: 'set_field',
      path: 'audio.narration.1.start',
      value: 5.5,
    })
  })

  it('arrastar menos que um milissegundo não faz nada', () => {
    const drag = startOf('shift', 'TX', text)
    expect(dragOperation(drag, track, dragPreview(drag, track, 0.0004, NO_SNAP))).toBeNull()
  })
})
