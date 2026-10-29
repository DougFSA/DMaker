/* A forma de onda dos itens com som na linha do tempo, sem tocar no navegador: quais itens têm onda, qual trecho de
   qual arquivo cada canvas desenha e a altura de cada coluna. Os picos vêm do servidor (`GET /api/waveform`); o
   desenho em si (o canvas) fica no componente. */
import type { TimelineItem, TimelineTrack, TimelineView, Waveform } from '@/api'

/** Largura máxima de um canvas (pixels de tela): ele cobre só a janela visível do item, não o item inteiro. */
export const WAVEFORM_MAX_PX = 6000

/**
 * A altura do canvas (pixels de tela): a linha de 34 px menos a borda dela (1), as margens do item (3 + 3), a borda do
 * item (1 + 1) e as margens do canvas (3 + 3). É fixa para o componente não ler a altura do documento a cada desenho,
 * o que forçaria o navegador a refazer o layout da página inteira para cada onda a cada passo do zoom.
 */
export const WAVEFORM_HEIGHT_PX = 19

/** Têm forma de onda o áudio de clipe (A1), as faixas externas (A2...), a música (MUS) e o vídeo sobreposto (V2...):
 *  os únicos tipos com som na linha do tempo. */
export function waveformEligible(track: Pick<TimelineTrack, 'id' | 'kind'>, item: Pick<TimelineItem, 'kind'>): boolean {
  if (track.id === 'A1') return item.kind === 'clip-audio'
  if (track.id === 'MUS') return item.kind === 'music'
  if (track.kind === 'audio') return item.kind === 'track'
  if (track.kind === 'video' && track.id !== 'V1') return item.kind === 'video'
  return false
}

export interface ItemPiece {
  start: number
  end: number
  in_point: number
  path: string
}

/** Os pedaços de um clipe de fonte em várias partes (`extra.pieces`): um por arquivo, já com o ponto de cada um. */
export function itemPieces(item: Pick<TimelineItem, 'extra'>): ItemPiece[] {
  const pieces = item.extra?.pieces
  return Array.isArray(pieces) ? (pieces as ItemPiece[]) : []
}

/** A velocidade do clipe (A1 e as faixas fatiadas guardam `speed` em `extra`); os outros itens tocam a 1x. */
export function itemAudioRate(item: Pick<TimelineItem, 'extra'>): number {
  const speed = item.extra?.speed
  return typeof speed === 'number' && speed > 0 ? speed : 1
}

/** O deslocamento da fonte no relógio da sessão: o `extra.offset` explícito (zero nas faixas fatiadas, cujo
 *  `in_point` já é tempo no arquivo) ou o da fonte nomeada; zero para arquivos avulsos. */
export function itemAudioOffset(view: Pick<TimelineView, 'sources'>, item: Pick<TimelineItem, 'extra' | 'source'>): number {
  const explicit = item.extra?.offset
  if (typeof explicit === 'number') return explicit
  if (item.source) return view.sources?.[item.source]?.offset ?? 0
  return 0
}

/** O arquivo de áudio de um item: o caminho que o servidor já resolveu ou, na falta dele, o `src` ou a fonte nomeada. */
export function itemSourcePath(view: Pick<TimelineView, 'sources'>, item: Pick<TimelineItem, 'path' | 'src' | 'source'>): string | null {
  if (item.path) return item.path
  if (item.src) return item.src
  if (item.source) {
    const source = view.sources?.[item.source]
    return source ? source.path || source.src : null
  }
  return null
}

/** O que um canvas de onda desenha: o intervalo da linha do tempo que cobre, o arquivo e o tempo nele em cada instante. */
export interface WaveformWindow {
  path: string | null
  start: number
  end: number
  /** O tempo no arquivo que toca no instante `t` da linha do tempo. */
  fileTimeAt: (t: number) => number
}

/**
 * A janela de um item. Com `pieceIndex`, o pedaço do clipe que cai naquele arquivo (fonte em várias partes); sem
 * ele, o item inteiro. Mesma conta do player: ponto de entrada mais o avanço desde o início na velocidade do item,
 * menos o deslocamento da fonte.
 */
export function waveformWindow(
  view: Pick<TimelineView, 'sources'>,
  item: TimelineItem,
  pieceIndex: number | null,
): WaveformWindow {
  const rate = itemAudioRate(item)
  const piece = pieceIndex === null ? undefined : itemPieces(item)[pieceIndex]
  if (piece) {
    return {
      path: piece.path,
      start: piece.start,
      end: piece.end,
      fileTimeAt: (t) => piece.in_point + (t - piece.start) * rate,
    }
  }
  const offset = itemAudioOffset(view, item)
  return {
    path: itemSourcePath(view, item),
    start: item.start,
    end: item.end,
    fileTimeAt: (t) => item.in_point + (t - item.start) * rate - offset,
  }
}

/** Em loop (a música repete o arquivo até o fim do item). */
export function itemLoops(item: Pick<TimelineItem, 'extra'>): boolean {
  return !!item.extra?.loop
}

/** O índice do pico mais perto de um tempo do arquivo, ou -1 se ele cai fora do trecho gravado. */
export function peakIndexAt(peaksLength: number, peaksPerSecond: number, duration: number, fileTime: number, loop: boolean): number {
  let time = fileTime
  if (loop && duration > 0) {
    time = ((time % duration) + duration) % duration
  } else if (time < 0 || time >= duration) {
    return -1
  }
  const index = Math.floor(time * peaksPerSecond)
  return index >= 0 && index < peaksLength ? index : -1
}

/**
 * A altura (0 a 1) de cada coluna do canvas: `columns` colunas cobrindo o trecho do arquivo entre `fileStart` e
 * `fileEnd`. Coluna fora do trecho gravado (antes do início, ou depois do fim sem loop) fica em 0.
 */
export function waveformColumns(
  columns: number,
  waveform: Waveform,
  fileStart: number,
  fileEnd: number,
  loop: boolean,
): Float32Array {
  const heights = new Float32Array(Math.max(0, columns))
  const peaks = waveform.peaks
  if (peaks.length === 0 || columns <= 0) return heights
  const span = fileEnd - fileStart
  for (let column = 0; column < columns; column += 1) {
    const time = span === 0 ? fileStart : fileStart + (column / columns) * span
    const index = peakIndexAt(peaks.length, waveform.peaks_per_second, waveform.duration, time, loop)
    if (index >= 0) heights[column] = Math.max(0, Math.min(1, peaks[index] as number))
  }
  return heights
}

/** Guarda os picos de cada arquivo: um pedido só por arquivo, mesmo que vários itens o usem ao mesmo tempo. */
export class WaveformCache {
  private readonly entries = new Map<string, Promise<Waveform | null>>()

  constructor(private readonly fetchPeaks: (path: string, stream: number) => Promise<Waveform>) {}

  /** Os picos do arquivo, ou nulo se o servidor não conseguiu gerá-los (arquivo sem áudio, por exemplo). */
  peaks(path: string | null, stream = 0): Promise<Waveform | null> {
    if (!path) return Promise.resolve(null)
    const key = `${path}::${stream}`
    let entry = this.entries.get(key)
    if (!entry) {
      entry = this.fetchPeaks(path, stream).catch(() => null)
      this.entries.set(key, entry)
    }
    return entry
  }

  clear(): void {
    this.entries.clear()
  }
}
