/* O arrasto na linha do tempo, sem tocar no navegador: onde o fantasma fica a cada movimento do mouse e qual
   operação de edição sai quando o mouse é solto. Há três gestos: mover um trecho da V1 (muda a ordem), aparar uma
   borda e deslocar um bloco (sobreposição ou fala da narração). */
import type { EditOperation, TimelineItem, TimelineTrack } from '@/api'
import { MIN_ITEM_SECONDS, narrationMoveOp, roundSeconds, snapBlock, snapTime } from './timeline'

export type DragMode = 'move-v1' | 'trim' | 'shift'
export type TrimSide = 'in' | 'out'

export interface DragSpan {
  start: number
  end: number
}

/** O gesto em andamento: quem está sendo arrastado e de onde ele partiu. */
export interface DragStart {
  mode: DragMode
  trackId: string
  item: TimelineItem
  side: TrimSide | null
  original: DragSpan
}

/** O que o fantasma mostra: o intervalo em que o bloco ficaria, e na V1 a posição do marcador de inserção. */
export interface DragPreview extends DragSpan {
  /** Só em `move-v1`: a posição (em segundos) do marcador de onde o trecho vai entrar. */
  indicatorAt: number | null
  /** Só em `move-v1`: o índice de destino entre os trechos (antes de descontar o próprio trecho). */
  targetIndex: number | null
}

export interface SnapContext {
  /** Os pontos de encaixe ordenados (ver `snapPoints`). */
  points: readonly number[]
  /** A tolerância do encaixe em segundos (SNAP_PX / zoom); 0 desliga o encaixe. */
  tolerance: number
  total: number
}

function snapped(time: number, snap: SnapContext): number {
  return snap.tolerance > 0 ? snapTime(time, snap.points, snap.tolerance) : time
}

/** Para onde vai a borda aparada: encaixada, e sem deixar o item menor que o mínimo nem sair da linha do tempo. */
function trimmedSpan(original: DragSpan, side: TrimSide, deltaSeconds: number, snap: SnapContext): DragSpan {
  if (side === 'in') {
    const edge = snapped(original.start + deltaSeconds, snap)
    return { start: Math.min(Math.max(edge, 0), original.end - MIN_ITEM_SECONDS), end: original.end }
  }
  const edge = snapped(original.end + deltaSeconds, snap)
  return { start: original.start, end: Math.max(edge, original.start + MIN_ITEM_SECONDS) }
}

/** Desloca o bloco inteiro: encaixa pelo começo ou pelo fim sem mudar a duração, e o mantém dentro de 0..total. */
function shiftedSpan(original: DragSpan, deltaSeconds: number, snap: SnapContext): DragSpan {
  const duration = original.end - original.start
  let block = { start: original.start + deltaSeconds, end: original.end + deltaSeconds }
  if (snap.tolerance > 0) block = snapBlock(block.start, block.end, snap.points, snap.tolerance)
  let { start } = block
  if (start < 0) start = 0
  if (start + duration > snap.total) start = Math.max(0, snap.total - duration)
  return { start, end: start + duration }
}

/** O índice onde o trecho arrastado entraria na V1: antes do primeiro outro trecho que começa depois do alvo. */
export function v1TargetIndex(items: readonly TimelineItem[], draggedId: string, targetTime: number): number {
  const index = items.findIndex((item) => item.id !== draggedId && item.start > targetTime)
  return index === -1 ? items.length : index
}

/** O fantasma do gesto, dado quanto o mouse andou (em segundos) desde que foi apertado. */
export function dragPreview(drag: DragStart, track: TimelineTrack, deltaSeconds: number, snap: SnapContext): DragPreview {
  const duration = drag.original.end - drag.original.start
  if (drag.mode === 'move-v1') {
    const targetTime = snapped(drag.original.start + deltaSeconds, snap)
    const targetIndex = v1TargetIndex(track.items, drag.item.id, targetTime)
    const indicator = track.items[targetIndex]
    return {
      start: Math.max(0, targetTime),
      end: Math.max(0, targetTime) + duration,
      indicatorAt: indicator ? indicator.start : snap.total,
      targetIndex,
    }
  }
  const span =
    drag.mode === 'trim' && drag.side
      ? trimmedSpan(drag.original, drag.side, deltaSeconds, snap)
      : shiftedSpan(drag.original, deltaSeconds, snap)
  return { ...span, indicatorAt: null, targetIndex: null }
}

/**
 * A operação que o gesto solto vira, ou nulo se nada mudou. A V1 usa as operações de trecho (mover, aparar); as
 * sobreposições usam `overlay_span`; a fala da narração só desloca o início. Aparar uma sobreposição NÃO usa
 * `trim`: aquela operação mexe no trecho da V1 de mesmo índice.
 */
export function dragOperation(drag: DragStart, track: TimelineTrack, preview: DragPreview): EditOperation | null {
  const { item, original } = drag
  if (drag.mode === 'move-v1') {
    const ownIndex = track.items.findIndex((candidate) => candidate.id === item.id)
    let to = preview.targetIndex ?? ownIndex
    if (to > ownIndex) to -= 1
    return to !== ownIndex && to >= 0 ? { type: 'move', index: item.index, to } : null
  }
  if (Math.abs(preview.start - original.start) < 0.001 && Math.abs(preview.end - original.end) < 0.001) return null
  if (drag.trackId === 'NAR') return narrationMoveOp(item, preview.start)
  if (drag.mode === 'trim' && drag.side) {
    if (drag.trackId === 'V1') {
      const delta = drag.side === 'in' ? preview.start - original.start : preview.end - original.end
      return { type: 'trim', index: item.index, side: drag.side, delta: roundSeconds(delta) }
    }
  }
  return { type: 'overlay_span', index: item.index, start: roundSeconds(preview.start), end: roundSeconds(preview.end) }
}
