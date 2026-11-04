/* A grade do andamento do projeto (`audio.tempo`), sem tocar no navegador: o instante de cada tempo e de cada compasso, a
   régua em compassos, os pontos de encaixe e a escolha da régua (segundos ou compassos). É o espelho em TypeScript de
   `domain/tempo_grid.py` (os mesmos números, o mesmo arredondamento de microssegundo), e os dois têm o mesmo caso de teste.
   Os números contam a partir de 1: o tempo 1 do compasso 1 cai em `offset`. */
import type { TimelineTempo } from '@/api'
import { timeToX, type AxisView, type ItemClockInfo, type Tick } from './audioWave'
import { SNAP_PX } from './timeline'

export type RulerMode = 'seconds' | 'bars'

/** Onde a escolha da régua fica no navegador (por pessoa, não por projeto). */
export const RULER_MODE_KEY = 'dmaker.timeline.ruler'
/** Dois pontos de encaixe da grade nunca ficam mais perto que isto em pixels: mais perto, a grade engoliria as bordas dos itens. */
export const MIN_GRID_SNAP_PX = 24
/** Dois números da régua nunca ficam mais perto que isto em pixels. */
export const MIN_RULER_LABEL_PX = 48

export type GridLevel = 'beat' | 'bar'

export interface BarTick {
  time: number
  /** O texto da marca: o número do compasso (`9`) no início dele e `9.3` no tempo 3. */
  label: string
  /** Início de compasso: a marca alta. */
  strong: boolean
}

function microseconds(seconds: number): number {
  return Math.round(seconds * 1_000_000) / 1_000_000
}

/** O instante do tempo `number` (1 é o primeiro, em `offset`). */
export function beatTime(tempo: TimelineTempo, number: number): number {
  return microseconds(tempo.offset + (number - 1) * tempo.period)
}

/** O instante em que começa o compasso `number` (1 é o primeiro). */
export function barTime(tempo: TimelineTempo, number: number): number {
  return microseconds(tempo.offset + (number - 1) * tempo.period * tempo.beats_per_bar)
}

/** Em que tempo (fracionário, contado de 1) cai `time`; antes do tempo 1 vale menos que 1. */
export function beatNumberAt(tempo: TimelineTempo, time: number): number {
  return (time - tempo.offset) / tempo.period + 1
}

/** O instante como compasso.tempo (`9.1` é o primeiro tempo do compasso 9). */
export function positionLabel(tempo: TimelineTempo, time: number): string {
  const number = Math.max(Math.floor(beatNumberAt(tempo, time) + 1e-9), 1)
  const bar = Math.floor((number - 1) / tempo.beats_per_bar)
  return `${bar + 1}.${((number - 1) % tempo.beats_per_bar) + 1}`
}

function range(tempo: TimelineTempo, step: number, from: number, to: number): number[] {
  const first = Math.max(Math.ceil((from - tempo.offset) / step - 1e-9), 0)
  const last = Math.floor((to - tempo.offset) / step + 1e-9)
  const points: number[] = []
  for (let n = first; n <= last; n += 1) points.push(microseconds(tempo.offset + n * step))
  return points
}

/** Os instantes de todos os tempos em [from, to], em ordem. */
export function gridBeats(tempo: TimelineTempo, from: number, to: number): number[] {
  return range(tempo, tempo.period, from, to)
}

/** Os instantes de início de compasso em [from, to], em ordem. */
export function gridBars(tempo: TimelineTempo, from: number, to: number): number[] {
  return range(tempo, tempo.period * tempo.beats_per_bar, from, to)
}

/**
 * Os pontos em que o arrasto encaixa na grade, no zoom atual: cada tempo se eles estão a `MIN_GRID_SNAP_PX` uns dos outros,
 * senão cada início de compasso, senão nenhum. Assim a grade atrai com o zoom perto e não engole as bordas dos itens com o
 * zoom longe.
 */
export function gridSnapPoints(tempo: TimelineTempo, total: number, pxPerSec: number): number[] {
  if (tempo.period * pxPerSec >= MIN_GRID_SNAP_PX) return gridBeats(tempo, 0, total)
  if (tempo.period * tempo.beats_per_bar * pxPerSec >= MIN_GRID_SNAP_PX) return gridBars(tempo, 0, total)
  return []
}

/** O tempo (ou início de compasso) mais perto de `time`; antes do tempo 1 vale o próprio tempo 1. */
export function nearestGridPoint(tempo: TimelineTempo, time: number, level: GridLevel = 'beat'): number {
  const step = level === 'bar' ? tempo.period * tempo.beats_per_bar : tempo.period
  return microseconds(tempo.offset + Math.max(Math.round((time - tempo.offset) / step), 0) * step)
}

/**
 * As marcas da régua em compassos entre `from` e `to`: o número de cada compasso (alto) e, com zoom para caber, cada tempo
 * (`9.2`, `9.3`...). A cada tantos compassos quanto precisar para os números não se atropelarem.
 */
export function barRulerTicks(tempo: TimelineTempo, from: number, to: number, pxPerSec: number): BarTick[] {
  const barSeconds = tempo.period * tempo.beats_per_bar
  const everyBars = Math.max(1, Math.ceil(MIN_RULER_LABEL_PX / (barSeconds * pxPerSec)))
  const showBeats = tempo.period * pxPerSec >= MIN_RULER_LABEL_PX
  const ticks: BarTick[] = []
  for (const time of showBeats ? gridBeats(tempo, from, to) : gridBars(tempo, from, to)) {
    const label = positionLabel(tempo, time)
    const [bar, beat] = label.split('.')
    const strong = beat === '1'
    if (strong && (Number(bar) - 1) % everyBars !== 0) continue
    ticks.push({ time, label: strong ? (bar as string) : label, strong })
  }
  return ticks
}

/** Lê a régua escolhida; sem armazenamento (janela privada) ou com valor quebrado, vale a de segundos. */
export function loadRulerMode(): RulerMode {
  try {
    return window.localStorage.getItem(RULER_MODE_KEY) === 'bars' ? 'bars' : 'seconds'
  } catch {
    return 'seconds'
  }
}

export function saveRulerMode(mode: RulerMode): void {
  try {
    window.localStorage.setItem(RULER_MODE_KEY, mode)
  } catch {
    // sem armazenamento: a escolha vale só nesta sessão
  }
}

/* ---------- o painel Áudio: o eixo é o do item, não o do projeto ---------- */

/** O instante do eixo do item como instante do projeto, e o caminho de volta (o relógio do item). */
const toProject = (clock: ItemClockInfo, axisTime: number): number => clock.start + (axisTime - clock.origin) / clock.speed
const toAxis = (clock: ItemClockInfo, projectTime: number): number => clock.origin + (projectTime - clock.start) * clock.speed

/**
 * Os marcos da régua em compassos para a janela do painel Áudio: a grade é do projeto, então a janela vai ao tempo do
 * projeto pelo relógio do item, as marcas são as da linha do tempo e voltam ao eixo (com a posição em pixels).
 */
export function barAxisTicks(view: AxisView, width: number, tempo: TimelineTempo, clock: ItemClockInfo): Tick[] {
  if (!(view.end > view.start) || width <= 0 || !(clock.speed > 0)) return []
  const from = toProject(clock, view.start)
  const to = toProject(clock, view.end)
  const projectPxPerSec = width / (to - from)
  return barRulerTicks(tempo, Math.max(from, 0), to, projectPxPerSec).map((tick) => {
    const axis = toAxis(clock, tick.time)
    return { time: axis, x: timeToX(axis, view, width), label: tick.label, major: tick.strong }
  })
}

/**
 * Encaixa um instante do eixo do item no tempo mais perto quando ele está a `SNAP_PX` pixels ou menos, e só se os tempos
 * estão a `MIN_GRID_SNAP_PX` ou mais uns dos outros na tela (senão a grade engoliria a seleção). `secondsPerPixel` é o do eixo.
 */
export function snapAxisToGrid(axisTime: number, clock: ItemClockInfo, tempo: TimelineTempo, secondsPerPixel: number): number {
  if (!(secondsPerPixel > 0) || !(clock.speed > 0)) return axisTime
  if ((tempo.period * clock.speed) / secondsPerPixel < MIN_GRID_SNAP_PX) return axisTime
  const point = toAxis(clock, nearestGridPoint(tempo, toProject(clock, axisTime)))
  return Math.abs(point - axisTime) <= SNAP_PX * secondsPerPixel ? point : axisTime
}
