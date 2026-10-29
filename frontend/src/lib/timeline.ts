/* As contas da linha do tempo, sem tocar no navegador: escala de zoom, passo da régua, encaixe (snap), quais itens
   se arrastam ou se apara, quais botões o cabeçalho de cada trilha mostra e os nomes que a pessoa lê. Funções puras,
   a base do painel da linha do tempo e das ações do teclado. */
import type { TimelineItem, TimelineTrack, TimelineView } from '@/api'

/** Largura do cabeçalho da trilha (rótulo e botões M, H e cadeado), que fica colado à esquerda ao rolar. */
export const TRACK_HEADER_WIDTH = 92
export const TRACK_ROW_HEIGHT = 34
export const RULER_HEIGHT = 26
export const MIN_PX_PER_SEC = 4
export const MAX_PX_PER_SEC = 400
export const DEFAULT_PX_PER_SEC = 60
/** Um ponto de encaixe atrai o que passar a até estes pixels dele (em segundos, depende do zoom). */
export const SNAP_PX = 8
/** Nenhum trecho ou sobreposição fica menor que isto ao ser aparado (segundos). */
export const MIN_ITEM_SECONDS = 0.1
/** Folga depois do fim do vídeo na largura da linha do tempo (pixels), para o cursor poder parar no fim. */
export const TRAILING_PX = 40
/** Fator dos botões + e −. */
export const ZOOM_STEP = 1.3
/** Fator de cada clique da roda com o Ctrl apertado. */
export const WHEEL_ZOOM_STEP = 1.15
/** O tipo MIME que o painel Mídia usa ao arrastar um arquivo para a linha do tempo. */
export const MEDIA_DND_MIME = 'application/x-dmaker-media'

export type TrackToggle = 'muted' | 'hidden' | 'locked'

/** Mantém o zoom dentro da faixa em que a linha do tempo ainda é legível. */
export function clampZoom(pxPerSec: number): number {
  return Math.max(MIN_PX_PER_SEC, Math.min(MAX_PX_PER_SEC, pxPerSec))
}

/** A largura da área das trilhas (sem o cabeçalho) para a duração e o zoom dados. */
export function laneWidth(total: number, pxPerSec: number): number {
  return Math.max(200, total * pxPerSec + TRAILING_PX)
}

/** O zoom que faz o vídeo inteiro caber em `availablePx` (a largura visível da área das trilhas). */
export function fitZoom(total: number, availablePx: number): number {
  const lane = Math.max(1, availablePx - TRAILING_PX)
  return clampZoom(lane / Math.max(1, total))
}

const TICK_STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800]
const MIN_TICK_GAP_PX = 70

/** O passo (em segundos) entre as marcas da régua para que fiquem a pelo menos ~70 px uma da outra no zoom atual. */
export function tickStep(pxPerSec: number): number {
  return TICK_STEPS.find((step) => step * pxPerSec >= MIN_TICK_GAP_PX) ?? (TICK_STEPS[TICK_STEPS.length - 1] as number)
}

/** As marcas da régua: de zero até depois do fim, de `tickStep` em `tickStep`. */
export function rulerTicks(total: number, pxPerSec: number): number[] {
  const step = tickStep(pxPerSec)
  const ticks: number[] = []
  // multiplica em vez de somar para o ponto flutuante não acumular erro nos passos de 0,1 s
  for (let index = 0; index * step <= total + step; index += 1) ticks.push(Math.round(index * step * 1000) / 1000)
  return ticks
}

/** O tempo (em segundos) sob a posição `clientX` da tela, dentro da área rolável. */
export function timeAtX(clientX: number, areaLeft: number, scrollLeft: number, pxPerSec: number, total: number): number {
  const x = clientX - areaLeft + scrollLeft - TRACK_HEADER_WIDTH
  return Math.max(0, Math.min(total, x / pxPerSec))
}

/** Segundos com precisão de milissegundo, para o arrasto não gravar 0.30000000000000004 na spec. */
export function roundSeconds(seconds: number): number {
  return Math.round(seconds * 1000) / 1000
}

/* ---------- encaixe ---------- */

/**
 * Os pontos em que o arrasto encaixa: o começo, o fim, o cursor e as bordas de todos os itens (menos o que se
 * arrasta). Ao arrastar o próprio cursor, `playhead` é nulo: ele não encaixa em si mesmo.
 */
export function snapPoints(view: TimelineView, playhead: number | null, excludeId: string | null): number[] {
  const points = new Set<number>([0, view.total])
  if (playhead !== null) points.add(playhead)
  for (const track of view.tracks) {
    for (const item of track.items) {
      if (item.id === excludeId) continue
      points.add(item.start)
      points.add(item.end)
    }
  }
  return [...points].sort((a, b) => a - b)
}

/** O ponto de `sorted` mais perto de `time` dentro da tolerância; sem nenhum perto, o próprio `time`. */
export function snapTime(time: number, sorted: readonly number[], toleranceSeconds: number): number {
  let low = 0
  let high = sorted.length
  while (low < high) {
    const middle = (low + high) >> 1
    if ((sorted[middle] as number) < time) low = middle + 1
    else high = middle
  }
  let best = time
  let bestDistance = toleranceSeconds
  for (const candidate of [sorted[low - 1], sorted[low]]) {
    if (candidate === undefined) continue
    const distance = Math.abs(candidate - time)
    if (distance < bestDistance) {
      bestDistance = distance
      best = candidate
    }
  }
  return best
}

/**
 * Encaixa um bloco inteiro pelo começo e, se o começo não encaixou, pelo fim. Encaixar as duas pontas cada uma
 * para o seu lado mudaria a duração do bloco; assim ele só desliza.
 */
export function snapBlock(start: number, end: number, sorted: readonly number[], toleranceSeconds: number): { start: number; end: number } {
  const duration = end - start
  const snappedStart = snapTime(start, sorted, toleranceSeconds)
  if (snappedStart !== start) return { start: snappedStart, end: snappedStart + duration }
  const snappedEnd = snapTime(end, sorted, toleranceSeconds)
  return { start: snappedEnd - duration, end: snappedEnd }
}

/* ---------- o que cada item permite ---------- */

/** A sobreposição vive em `overlays` (texto, imagem da camada GR e vídeo sobreposto das trilhas V2 em diante). */
export function isOverlayTrack(trackId: string, item: Pick<TimelineItem, 'kind'>): boolean {
  if (trackId === 'TX') return true
  if (trackId === 'GR') return item.kind === 'image'
  return /^V\d+$/.test(trackId) && trackId !== 'V1'
}

/** O item se arrasta: trecho da V1, sobreposição, ou fala da narração (que só se desloca). */
export function isDraggable(trackId: string, item: Pick<TimelineItem, 'kind'>): boolean {
  return trackId === 'V1' || trackId === 'NAR' || isOverlayTrack(trackId, item)
}

/** As alças de aparar só existem onde aparar faz sentido: a fala da narração tem a duração que a voz levou. */
export function hasTrimHandles(trackId: string, item: Pick<TimelineItem, 'kind'>): boolean {
  return isDraggable(trackId, item) && trackId !== 'NAR'
}

/** Os botões do cabeçalho da trilha: M (mudo) nas de áudio; H (ocultar) nas de vídeo além da V1, nas de texto,
 *  gráficos e legendas; cadeado em todas. A V1 não se oculta: sem ela não haveria o que renderizar. */
export function headerButtons(track: Pick<TimelineTrack, 'id' | 'kind'>): TrackToggle[] {
  const buttons: TrackToggle[] = []
  if (track.kind === 'audio') buttons.push('muted')
  if (track.id !== 'V1' && (track.kind === 'video' || ['TX', 'GR', 'CC'].includes(track.id))) buttons.push('hidden')
  buttons.push('locked')
  return buttons
}

export const TOGGLE_LABEL: Record<TrackToggle, { letter: string; title: string; verb: string }> = {
  muted: { letter: 'M', title: 'Mudo', verb: 'Silenciar' },
  hidden: { letter: 'H', title: 'Ocultar', verb: 'Ocultar' },
  locked: { letter: 'L', title: 'Bloquear edição', verb: 'Bloquear' },
}

const TRACK_NAMES: Record<string, string> = {
  V1: 'Vídeo principal',
  TX: 'Textos',
  GR: 'Gráficos: imagens e barra de progresso',
  A1: 'Áudio dos clipes',
  NAR: 'Narração',
  MUS: 'Música',
  CC: 'Legendas automáticas',
}

/** O nome por extenso da trilha, para o balão do cabeçalho. */
export function trackTitle(track: Pick<TimelineTrack, 'id' | 'label'>): string {
  const known = TRACK_NAMES[track.id]
  if (known) return `${known} (${track.id})`
  if (/^V\d+$/.test(track.id)) return `Vídeo sobreposto (${track.id})`
  if (/^A\d+$/.test(track.id)) return `Faixa de áudio externa (${track.id})`
  return track.label
}

/** O rótulo do cabeçalho: o da trilha, com uma nota musical nas de áudio. */
export function trackLabel(track: Pick<TimelineTrack, 'label' | 'kind'>): string {
  return track.kind === 'audio' ? `${track.label} ♪` : track.label
}

/** Nome de arquivo, sem a pasta, para rótulos que vêm de um caminho; texto de cartão e de sobreposição fica como veio. */
export function displayLabel(label: string | null | undefined): string {
  if (!label) return ''
  return /[\\/]/.test(label) ? (label.split(/[\\/]/).pop() ?? '') : label
}

/** O balão de um item. Na narração diz a fala inteira e se a duração é a real (já sintetizada) ou estimada. */
export function itemTitle(item: Pick<TimelineItem, 'kind' | 'label' | 'start' | 'end' | 'extra' | 'missing'>): string {
  const label = item.label || item.kind
  if (item.missing) return `${label} (fonte não encontrada)`
  if (item.kind !== 'narration') return label
  const seconds = roundSeconds(item.end - item.start).toFixed(1).replace('.', ',')
  return `${label} (${item.extra?.estimated ? 'duração estimada' : 'duração real'}: ${seconds} s)`
}

/** O nome de classe do tipo do item (a cor do bloco). */
export function kindClass(kind: string | null | undefined): string {
  return String(kind || 'other').replace(/[^a-z0-9-]/gi, '-')
}

/** A operação de arrastar uma fala da narração: o novo início de `audio.narration[i]`, nunca antes de zero. */
export function narrationMoveOp(item: Pick<TimelineItem, 'index'>, start: number) {
  return { type: 'set_field' as const, path: `audio.narration.${item.index}.start`, value: roundSeconds(Math.max(0, start)) }
}

/* ---------- a V1 ---------- */

/** Em que posição da V1 entra uma mídia solta ou inserida no instante `time`: antes do primeiro trecho que começa
 *  depois dele, ou no fim se não houver nenhum. */
export function v1InsertIndexAt(view: TimelineView, time: number): number {
  const v1 = view.tracks.find((track) => track.id === 'V1')
  if (!v1 || v1.items.length === 0) return 0
  const index = v1.items.findIndex((item) => item.start > time + 0.001)
  return index === -1 ? v1.items.length : index
}

/** Os instantes de corte da V1 (começo, fim e as emendas), sem repetição e em ordem: o "edição anterior/próxima". */
export function edgeTimes(view: TimelineView): number[] {
  const v1 = view.tracks.find((track) => track.id === 'V1')
  const times = new Set<number>([0, view.total])
  for (const item of v1?.items ?? []) {
    times.add(item.start)
    times.add(item.end)
  }
  return [...times].sort((a, b) => a - b)
}

/** A emenda para onde ir a partir de `time` na direção dada (1 adiante, -1 para trás), ou nulo se não há. */
export function nextEdge(edges: readonly number[], time: number, direction: -1 | 1): number | null {
  const epsilon = 0.005
  if (direction > 0) return edges.find((edge) => edge > time + epsilon) ?? null
  return [...edges].reverse().find((edge) => edge < time - epsilon) ?? null
}

/** O item da trilha que cobre o instante (início incluído, fim excluído). */
export function itemCovering(track: TimelineTrack | undefined, time: number): TimelineItem | null {
  return track?.items.find((item) => time >= item.start && time < item.end) ?? null
}

/** A hachura da transição entre dois trechos da V1: do começo do trecho de entrada até onde o anterior termina. */
export function transitionSpans(items: readonly TimelineItem[]): Array<{ id: string; start: number; end: number; type: string }> {
  const spans: Array<{ id: string; start: number; end: number; type: string }> = []
  for (let index = 1; index < items.length; index += 1) {
    const previous = items[index - 1] as TimelineItem
    const current = items[index] as TimelineItem
    if (current.transition && current.start < previous.end) {
      spans.push({
        id: current.id,
        start: current.start,
        end: Math.min(previous.end, current.end),
        type: String(current.transition.type ?? ''),
      })
    }
  }
  return spans
}
