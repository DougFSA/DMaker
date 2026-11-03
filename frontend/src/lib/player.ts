/* O que o player decide a cada instante da linha do tempo, sem tocar no navegador: que item cobre o instante,
   que arquivo e que ponto dele tocar, quanto vale o volume e quando vale a pena buscar de novo. Funções puras,
   a base do palco, do som ao vivo e do transporte. */
import type { TimelineItem, TimelineTrack } from '@/api'

/** O elemento de mídia pode se afastar do relógio até isto (segundos) antes de ser buscado de novo. */
export const SYNC_TOLERANCE_S = 0.15
/** Depois de uma busca, o tempo (ms) que o elemento tem para carregar antes de ser buscado outra vez. */
export const SEEK_GRACE_MS = 800
/** Dentro da carência, só busca de novo se o alvo andou além do que a busca anterior prevê (segundos). */
export const RESEEK_WINDOW_S = 0.5

export const MIN_PLAYBACK_RATE = 0.0625
export const MAX_PLAYBACK_RATE = 16
/** O J, o L e o botão de velocidade dobram a velocidade até este teto. */
export const MAX_SPEED_LEVEL = 8

/** Dá o deslocamento de uma fonte nomeada no relógio da sessão (a fonte principal tem zero). */
export type SourceOffsetOf = (sourceName: string) => number

/** O item da trilha que cobre o instante (início incluído, fim excluído), ou nulo: onde nenhum item soa, a trilha
 * fica muda, porque a vista só manda um item por trecho que a faixa realmente cobre. */
export function itemAt(items: readonly TimelineItem[] | undefined, t: number): TimelineItem | null {
  return (items ?? []).find((item) => t >= item.start && t < item.end) ?? null
}

/** O deslocamento que o `in_point` do item ainda precisa descontar para virar tempo no arquivo: o `extra.offset`
 * do item (zero nos itens fatiados por corte, cujo `in_point` já é tempo no arquivo) ou o da fonte nomeada. */
export function fileOffset(item: TimelineItem, sourceOffsetOf: SourceOffsetOf): number {
  const explicit = item.extra?.offset
  if (typeof explicit === 'number') return explicit
  return item.source ? sourceOffsetOf(item.source) : 0
}

/** O tempo no arquivo de origem para o instante `t` da linha do tempo: a mesma conta de clipes, PiP, faixas
 * externas e música (ver `timeline_view.py`). `itemRate` é a velocidade do trecho. */
export function fileTime(item: TimelineItem, t: number, itemRate: number, sourceOffsetOf: SourceOffsetOf): number {
  return item.in_point + (t - item.start) * itemRate - fileOffset(item, sourceOffsetOf)
}

/** Onde buscar no arquivo para tocar `time`, ou nulo para pausar: nunca um tempo negativo (a faixa ainda não
 * tinha começado) nem além do fim (que dispararia busca a cada quadro e estalos). Com `loop`, passar do fim dá a
 * volta, como a música em loop do render. Sem a duração (os metadados ainda não chegaram), vale o tempo pedido. */
export function playableTime(time: number, duration: number, loop: boolean): number | null {
  if (!(time >= 0)) return null
  if (!Number.isFinite(duration) || duration <= 0) return time
  if (time < duration) return time
  return loop ? time % duration : null
}

export interface ClipPlayback {
  path: string | null
  fileTime: number
}

interface ClipPiece {
  start: number
  end: number
  in_point: number
  path: string
}

function piecesOf(item: TimelineItem): ClipPiece[] {
  const pieces = item.extra?.pieces
  return Array.isArray(pieces) ? (pieces as ClipPiece[]) : []
}

/** O arquivo e o tempo nele que um clipe da V1 toca em `t`. Um clipe de fonte em várias partes traz
 * `extra.pieces`, um pedaço por arquivo (já com o ponto de cada um), e toca o que grava o instante. */
export function clipPlayback(
  item: TimelineItem,
  t: number,
  itemRate: number,
  sourceOffsetOf: SourceOffsetOf,
  fallbackPath: string | null,
): ClipPlayback {
  const pieces = piecesOf(item)
  const first = pieces[0]
  const last = pieces[pieces.length - 1]
  if (first && last) {
    const piece = pieces.find((candidate) => t >= candidate.start && t < candidate.end) ?? (t < first.start ? first : last)
    return { path: piece.path, fileTime: piece.in_point + (t - piece.start) * itemRate }
  }
  return { path: fallbackPath, fileTime: fileTime(item, t, itemRate, sourceOffsetOf) }
}

export interface AudioGain {
  muted: boolean
  /** De 0 a 1: o volume do item vezes o geral. */
  volume: number
}

/** Mudo e volume de um item de áudio. O mudo vem do item, da trilha ou de qualquer um dos dois volumes zerado. */
export function audioGain(item: TimelineItem, trackMuted: boolean, master: number, itemVolume?: number): AudioGain {
  const own = itemVolume ?? (typeof item.extra?.volume === 'number' ? item.extra.volume : 1)
  const muted = !!(item.muted || trackMuted || own <= 0 || master <= 0)
  return { muted, volume: muted ? 0 : Math.min(1, own * master) }
}

/** Trilha de áudio que o som ao vivo toca por elemento: a música e as faixas externas (A2 em diante). */
export function isExternalAudioTrack(track: Pick<TimelineTrack, 'id'>): boolean {
  if (track.id === 'MUS') return true
  const number = /^A(\d+)$/.exec(track.id)?.[1]
  return number !== undefined && Number(number) >= 2
}

export interface SeekMemory {
  target: number
  at: number
}

/** Se vale buscar o elemento para `target`: ele se afastou além da tolerância. Logo depois de uma busca o
 * elemento fica parado carregando dados enquanto `target` segue andando; sem a carência, esse atraso estoura a
 * tolerância e dispara outra busca, e outra (visto numa faixa de câmera a 2x). `mediaRate` é quantos segundos
 * de arquivo passam por segundo de relógio. */
export function shouldSeek(
  current: number,
  target: number,
  now: number,
  last: SeekMemory | null,
  mediaRate: number,
): boolean {
  if (Math.abs(current - target) <= SYNC_TOLERANCE_S) return false
  if (last && now - last.at < SEEK_GRACE_MS) {
    const continued = last.target + ((now - last.at) / 1000) * mediaRate
    if (Math.abs(continued - target) < RESEEK_WINDOW_S) return false
  }
  return true
}

export function clampPlaybackRate(rate: number): number {
  return Math.min(MAX_PLAYBACK_RATE, Math.max(MIN_PLAYBACK_RATE, rate))
}

/** Timecode HH:MM:SS:QQ, com os quadros contados no fps arredondado da vista. */
export function formatTimecode(seconds: number, fps: number): string {
  const total = Math.max(0, seconds || 0)
  const rate = fps && fps > 0 ? fps : 30
  let frames = Math.round(total * rate)
  const perSecond = Math.round(rate)
  const hours = Math.floor(frames / (perSecond * 3600))
  frames -= hours * perSecond * 3600
  const minutes = Math.floor(frames / (perSecond * 60))
  frames -= minutes * perSecond * 60
  const secs = Math.floor(frames / perSecond)
  frames -= secs * perSecond
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(hours)}:${pad(minutes)}:${pad(secs)}:${pad(frames)}`
}

/** A velocidade que o J (-1) ou o L (+1) pedem: o primeiro toque anda a 1x; repetir na mesma direção dobra até 8x;
 * trocar de direção volta a 1x. `current` é a velocidade de agora (0 = parado). */
export function bumpedRate(direction: -1 | 1, current: number): number {
  if (current !== 0 && Math.sign(current) === direction) {
    return direction * Math.min(MAX_SPEED_LEVEL, Math.abs(current) * 2)
  }
  return direction
}

/** O texto da velocidade: "Pausado", "1x", "-2x". */
export function rateLabel(rate: number): string {
  if (rate === 0) return 'Pausado'
  return `${rate < 0 ? '-' : ''}${Math.abs(rate)}x`
}

/** O endereço de um arquivo da máquina servido pela API. */
export function fileUrl(path: string): string {
  return `/api/file?path=${encodeURIComponent(path)}`
}

/** O endereço para mostrar um arquivo: o proxy leve dele, se já existe, ou o próprio arquivo. */
export function mediaUrl(path: string | null | undefined, proxyUrls: Readonly<Record<string, string>>): string | null {
  if (!path) return null
  return proxyUrls[path] ?? fileUrl(path)
}
