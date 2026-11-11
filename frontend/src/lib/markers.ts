/* As contas da trilha de marcadores (MK), sem tocar no navegador: reconhecer a trilha e o item, a cor, o balão, o
   próximo e o anterior a partir de um instante e a operação que cada gesto vira. Os marcadores moram em `spec.markers`
   no tempo do vídeo final; o servidor os desloca junto quando um corte tira ou põe tempo. */
import type { EditOperation, TimelineItem, TimelineTrack, TimelineView } from '@/api'
import { isInstantMarker, roundSeconds } from './timeline'

/** A cor do marcador, se a spec deu uma; sem ela a trilha usa a do tema. */
export function markerColor(item: Pick<TimelineItem, 'extra'>): string | null {
  const color = item.extra?.color
  return typeof color === 'string' && /^#[0-9a-fA-F]{6}$/.test(color) ? color : null
}

/** O grupo do marcador (vazio = trilha padrão). */
export function markerGroup(item: Pick<TimelineItem, 'extra'>): string {
  return typeof item.extra?.group === 'string' ? item.extra.group : ''
}

function seconds(value: number): string {
  return roundSeconds(value).toString().replace('.', ',')
}

/** O balão do marcador: o texto e onde ele está. */
export function markerTitle(item: Pick<TimelineItem, 'label' | 'start' | 'end' | 'extra'>): string {
  const name = item.label || 'Marcador sem texto'
  const where = isInstantMarker(item) ? `${seconds(item.start)} s` : `${seconds(item.start)} a ${seconds(item.end)} s`
  return `${name} (${where})`
}

/** Os marcadores da vista, de todas as trilhas, por ordem de início. */
export function markerItems(view: TimelineView): TimelineItem[] {
  return view.tracks
    .filter((track) => track.kind === 'markers')
    .flatMap((track) => track.items)
    .sort((a, b) => a.start - b.start)
}

/** Distância mínima (segundos) para um marcador valer como "outro" ao pular de um para o seguinte. */
const JUMP_EPSILON = 0.005

/** O marcador anterior (direção -1) ou o seguinte (1) ao instante dado, ou nulo se não há. */
export function nextMarker(view: TimelineView, time: number, direction: -1 | 1): TimelineItem | null {
  const items = markerItems(view)
  if (direction > 0) return items.find((item) => item.start > time + JUMP_EPSILON) ?? null
  return [...items].reverse().find((item) => item.start < time - JUMP_EPSILON) ?? null
}

/**
 * A operação de soltar um marcador arrastado: o instante inteiro se desloca; a região, quando o corpo é puxado, anda
 * junto, e quando uma borda é puxada muda só aquela ponta (o `preview` já vem encaixado e dentro dos limites).
 */
export function markerMoveOperation(item: TimelineItem, preview: { start: number; end: number }): EditOperation {
  if (isInstantMarker(item)) return { type: 'marker_set', index: item.index, at: roundSeconds(preview.start) }
  return { type: 'marker_set', index: item.index, start: roundSeconds(preview.start), end: roundSeconds(preview.end) }
}

/** A trilha de um grupo na vista, se ela já existe. */
export function markerTrackOf(view: TimelineView, group: string): TimelineTrack | undefined {
  const id = group ? `MK:${group}` : 'MK'
  return view.tracks.find((track) => track.id === id)
}

/** O texto novo de um marcador renomeado, sem espaço sobrando nas pontas. */
export function renameOperation(item: Pick<TimelineItem, 'index' | 'label'>, text: string): EditOperation | null {
  const next = text.trim()
  return next === item.label ? null : { type: 'marker_set', index: item.index, text: next }
}
