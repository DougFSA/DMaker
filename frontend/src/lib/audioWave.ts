/* As contas da onda do painel Áudio, todas puras: a janela de tempo que a tela mostra (zoom e rolagem), a conversão
   entre segundo e pixel, a régua em tempo e em amostras, a seleção e a altura de cada coluna. O tempo do painel é o
   do eixo do item (segundos do som em que os efeitos falam); quem o liga à linha do tempo do projeto é o relógio
   (`clock`) que o servidor entrega. Nada aqui toca o navegador. */

/** O pedaço do eixo que está na tela. */
export interface AxisView {
  start: number
  end: number
}

export interface AxisSelection {
  start: number
  end: number
}

/** O relógio do item: o instante `t` do eixo é o instante `start + (t - origin) / speed` da linha do tempo. */
export interface ItemClockInfo {
  start: number
  speed: number
  /** O instante do eixo em que o item começa a soar (a música com `start_at` começa no meio do arquivo). */
  origin: number
}

/** Quantas amostras a janela mais aproximada mostra: com 24, cada amostra ocupa umas 60 telas de pixel em 1.500 px. */
export const MIN_VIEW_SAMPLES = 24
/** A fração da janela que uma rolagem de roda anda. */
export const PAN_FRACTION = 0.2
/** O passo dos botões de aproximar e afastar. */
export const ZOOM_STEP = 2

export const clamp = (value: number, low: number, high: number): number => Math.min(high, Math.max(low, value))

/** A menor janela possível: `MIN_VIEW_SAMPLES` amostras (ou o áudio todo, se ele for ainda menor). */
export function minViewSeconds(rate: number, duration: number): number {
  return Math.min(duration, rate > 0 ? MIN_VIEW_SAMPLES / rate : duration)
}

/** A janela mantida dentro do áudio e da largura permitida; se passa do fim, ela encosta nele sem encolher. */
export function clampView(view: AxisView, duration: number, rate: number): AxisView {
  const smallest = minViewSeconds(rate, duration)
  const width = clamp(view.end - view.start, smallest, duration)
  const start = clamp(view.start, 0, Math.max(duration - width, 0))
  return { start, end: start + width }
}

/** O áudio inteiro. */
export function fitProject(duration: number): AxisView {
  return { start: 0, end: Math.max(duration, 0) }
}

/** A seleção com uma folga de 5% de cada lado (sem seleção, o áudio inteiro). */
export function fitSelection(selection: AxisSelection | null, duration: number, rate: number): AxisView {
  if (!selection) return fitProject(duration)
  const margin = (selection.end - selection.start) * 0.05
  return clampView({ start: selection.start - margin, end: selection.end + margin }, duration, rate)
}

/**
 * Aproxima (`factor` > 1) ou afasta (`factor` < 1) mantendo no mesmo lugar da tela o instante `anchor`: a roda do
 * mouse usa o instante sob o ponteiro, os botões usam o cursor ou o meio.
 */
export function zoomAround(view: AxisView, factor: number, anchor: number, duration: number, rate: number): AxisView {
  const width = (view.end - view.start) / factor
  const fraction = view.end > view.start ? (anchor - view.start) / (view.end - view.start) : 0.5
  const start = anchor - fraction * width
  return clampView({ start, end: start + width }, duration, rate)
}

/** Anda a janela `seconds` segundos sem mudar a largura. */
export function panView(view: AxisView, seconds: number, duration: number, rate: number): AxisView {
  return clampView({ start: view.start + seconds, end: view.end + seconds }, duration, rate)
}

/** A janela com o instante `time` à vista: nada muda se já está, senão ela anda o mínimo (o cursor segue a reprodução). */
export function revealTime(view: AxisView, time: number, duration: number, rate: number): AxisView {
  if (time >= view.start && time <= view.end) return view
  const width = view.end - view.start
  return clampView(time < view.start ? { start: time, end: time + width } : { start: time - width, end: time }, duration, rate)
}

export const timeToX = (time: number, view: AxisView, width: number): number =>
  view.end > view.start ? ((time - view.start) / (view.end - view.start)) * width : 0

export const xToTime = (x: number, view: AxisView, width: number): number =>
  width > 0 ? view.start + (x / width) * (view.end - view.start) : view.start

/** Quantas amostras cabem em um pixel de tela. Abaixo de 1 cada amostra ocupa mais de um pixel (a Draw Tool vale). */
export function samplesPerPixel(view: AxisView, width: number, rate: number): number {
  return width > 0 ? ((view.end - view.start) * rate) / width : 0
}

/** O zoom máximo: cada amostra tem pelo menos 4 pixels, o que dá para desenhar (a Draw Tool). */
export const DRAW_MIN_PIXELS_PER_SAMPLE = 4

export function canDraw(view: AxisView, width: number, rate: number): boolean {
  const perPixel = samplesPerPixel(view, width, rate)
  return perPixel > 0 && 1 / perPixel >= DRAW_MIN_PIXELS_PER_SAMPLE
}

/* ---------- seleção ---------- */

/** A seleção com as pontas na ordem certa e dentro do áudio; menor que meia amostra não é seleção. */
export function normalizeSelection(a: number, b: number, duration: number, rate: number): AxisSelection | null {
  const start = clamp(Math.min(a, b), 0, duration)
  const end = clamp(Math.max(a, b), 0, duration)
  return end - start >= 0.5 / Math.max(rate, 1) ? { start, end } : null
}

/** Shift: estende a seleção para o instante `time`, movendo a ponta que está mais perto dele. */
export function extendSelection(
  selection: AxisSelection | null,
  anchor: number,
  time: number,
  duration: number,
  rate: number,
): AxisSelection | null {
  if (!selection) return normalizeSelection(anchor, time, duration, rate)
  const nearStart = Math.abs(time - selection.start) <= Math.abs(time - selection.end)
  return nearStart
    ? normalizeSelection(time, selection.end, duration, rate)
    : normalizeSelection(selection.start, time, duration, rate)
}

/** O instante arredondado para a amostra mais perto (a seleção e o cursor caem sempre numa amostra). */
export function snapToSample(time: number, rate: number): number {
  return rate > 0 ? Math.round(time * rate) / rate : time
}

/** Do cursor até o instante do marcador seguinte (ou anterior, se estiver antes), como "selecionar até o marcador". */
export function selectionToMarker(cursor: number, markerTime: number, duration: number, rate: number): AxisSelection | null {
  return normalizeSelection(cursor, markerTime, duration, rate)
}

/* ---------- régua ---------- */

export interface Tick {
  time: number
  x: number
  label: string
  major: boolean
}

const STEPS = [1, 2, 5]

/** O passo "redondo" (1, 2 ou 5 vezes uma potência de dez) que deixa pelo menos `minPixels` entre dois marcos. */
export function niceStep(secondsPerPixel: number, minPixels: number): number {
  const raw = secondsPerPixel * minPixels
  if (!(raw > 0)) return 1
  const power = Math.floor(Math.log10(raw))
  for (const exponent of [power, power + 1]) {
    for (const base of STEPS) {
      const step = base * 10 ** exponent
      if (step >= raw) return step
    }
  }
  return 10 ** (power + 1)
}

/** O tempo como a régua o escreve: "1:05" quando o passo é de segundos, "1:05,250" quando é menor que um segundo. */
export function formatAxisTime(seconds: number, step: number): string {
  const sign = seconds < 0 ? '-' : ''
  const total = Math.abs(seconds)
  const minutes = Math.floor(total / 60)
  const rest = total - minutes * 60
  if (step >= 1) return `${sign}${minutes}:${String(Math.floor(rest + 1e-9)).padStart(2, '0')}`
  const decimals = step >= 0.1 ? 1 : step >= 0.01 ? 2 : step >= 0.001 ? 3 : 4
  const [whole, fraction] = rest.toFixed(decimals).split('.')
  return `${sign}${minutes}:${(whole ?? '0').padStart(2, '0')},${fraction ?? ''}`
}

/** Os marcos da régua de tempo dentro da janela, com a posição em pixels. */
export function timeTicks(view: AxisView, width: number, minPixels = 90): Tick[] {
  if (!(view.end > view.start) || width <= 0) return []
  const step = niceStep((view.end - view.start) / width, minPixels)
  const first = Math.ceil(view.start / step - 1e-9)
  const ticks: Tick[] = []
  for (let index = first; index * step <= view.end + 1e-9 && ticks.length < 400; index += 1) {
    const time = index * step
    ticks.push({ time, x: timeToX(time, view, width), label: formatAxisTime(time, step), major: true })
  }
  return ticks
}

/** Os marcos da régua em amostras: só quando a janela é pequena o bastante para a amostra ser a unidade natural. */
export function sampleTicks(view: AxisView, width: number, rate: number, minPixels = 70): Tick[] {
  if (!(view.end > view.start) || width <= 0 || rate <= 0) return []
  const step = Math.max(1, Math.round(niceStep(((view.end - view.start) * rate) / width, minPixels)))
  const first = Math.ceil((view.start * rate) / step - 1e-9)
  const ticks: Tick[] = []
  for (let index = first; index * step <= view.end * rate + 1e-9 && ticks.length < 400; index += 1) {
    const sample = index * step
    ticks.push({ time: sample / rate, x: timeToX(sample / rate, view, width), label: String(sample), major: true })
  }
  return ticks
}

/** A régua de amostras só aparece quando há poucas amostras por marco (a janela cabe em alguns segundos). */
export function showsSampleRuler(view: AxisView, width: number, rate: number): boolean {
  return samplesPerPixel(view, width, rate) <= 256
}

/* ---------- desenho ---------- */

/** O que se lê do servidor, por coluna: o mínimo e o máximo em inteiros de -127 a 127. */
export const PEAK_SCALE = 127

/** Os pixels de cima e de baixo da barra de uma coluna, num canal de altura `height` (0 em cima, o zero da onda no meio).
 *  Uma coluna sem som ainda ocupa um pixel, para a linha do zero não ter buracos. */
export function columnExtent(min: number, max: number, height: number): { top: number; bottom: number } {
  const half = height / 2
  const top = half - (clamp(max, -PEAK_SCALE, PEAK_SCALE) / PEAK_SCALE) * half
  const bottom = half - (clamp(min, -PEAK_SCALE, PEAK_SCALE) / PEAK_SCALE) * half
  return { top: Math.min(top, half - 0.5), bottom: Math.max(bottom, half + 0.5) }
}

/** O instante da amostra de índice `index` (a posição de uma amostra no eixo). */
export const sampleTime = (index: number, rate: number): number => index / rate

/** A posição em amostras de um instante, arredondada. */
export const timeSample = (time: number, rate: number): number => Math.round(time * rate)

/** O texto de uma duração curta para os campos da seleção: "1:05,250 s" ou "0,120 s". */
export function formatSpan(seconds: number): string {
  if (seconds >= 60) return formatAxisTime(seconds, 0.001)
  return `${seconds.toFixed(seconds >= 10 ? 2 : 3).replace('.', ',')} s`
}
