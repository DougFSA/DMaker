/* As contas da Draw Tool do painel Áudio, puras: por que o desenho não vale agora, de que canal é o ponto sob o mouse, o
   valor de uma amostra a partir da altura do pixel e como um traço (uma lista de pontos do mouse) vira uma lista contínua
   de amostras. Quem escuta o mouse é `useDrawTool`; quem grava o efeito `draw` é o store do painel. */
import { canDraw, clamp, timeToX, type AxisView } from './audioWave'
import { channelBand } from './audioWaveDraw'

/** A taxa em que os efeitos trabalham (a da mixagem): as amostras do efeito `draw` contam nela. */
export const EFFECT_SAMPLE_RATE = 48000
/** O limite de amostras de um efeito `draw`: um trecho curto, como o Reparar (o servidor recusa mais que isto). */
export const MAX_DRAW_SAMPLES = 512

/** Os canais em que se pode desenhar: um dos dois ou os dois. */
export type DrawChannel = 'both' | 'left' | 'right'

/** Um ponto do traço: a amostra (índice) e o valor de -1 a 1. */
export interface DrawPoint {
  sample: number
  value: number
}

/**
 * Por que a Draw Tool não vale agora, em linguagem de quem usa, ou null quando vale. Só desenha onde cada amostra tem
 * pixels suficientes (zoom máximo) e na taxa dos efeitos, porque o efeito `draw` põe valores nas amostras dessa taxa.
 */
export function drawBlocker(view: AxisView, width: number, rate: number): string | null {
  if (rate !== EFFECT_SAMPLE_RATE) {
    return `A Draw Tool trabalha a ${EFFECT_SAMPLE_RATE / 1000} kHz, a taxa dos efeitos, e este áudio é de ${String(rate / 1000).replace('.', ',')} kHz. Aplique qualquer efeito ao item (ele passa a ${EFFECT_SAMPLE_RATE / 1000} kHz) e desenhe depois.`
  }
  if (!canDraw(view, width, rate)) {
    return 'Aproxime mais o zoom (até as amostras aparecerem como pontos) para desenhar.'
  }
  return null
}

/** O canal em que o traço vale: o que está sob a altura `y` (esquerdo em cima, direito embaixo) ou, com `both`, os dois. */
export function channelAt(y: number, height: number, channels: number, both: boolean): DrawChannel {
  if (both || channels < 2) return 'both'
  return bandAt(y, height, channels) === 0 ? 'left' : 'right'
}

/** O canal (0, 1...) em que a altura `y` cai, de cima para baixo. */
export function bandAt(y: number, height: number, channels: number): number {
  const count = Math.max(channels, 1)
  for (let channel = 0; channel < count; channel += 1) {
    const band = channelBand(channel, count, height)
    if (y <= band.top + band.height + 1) return channel
  }
  return count - 1
}

/** O valor (de -1 a 1) que a altura `y` tem dentro do canal `channel`: o meio do canal é zero, o topo é 1. */
export function valueAt(y: number, height: number, channels: number, channel: number): number {
  const band = channelBand(channel, Math.max(channels, 1), height)
  return clamp(1 - (2 * (y - band.top)) / band.height, -1, 1)
}

/** A altura do pixel de um valor dentro de um canal (o inverso de `valueAt`), para desenhar o traço em andamento. */
export function yOfValue(value: number, channel: number, height: number, channels: number): number {
  const band = channelBand(channel, Math.max(channels, 1), height)
  return band.top + ((1 - clamp(value, -1, 1)) * band.height) / 2
}

/**
 * Do traço do mouse à lista contínua de amostras: entre dois pontos seguidos as amostras do meio recebem o valor da reta
 * que os liga (o mouse anda mais depressa que as amostras), e o que o traço refaz passa por cima do que já tinha. Devolve
 * o índice da primeira amostra e os valores, ou null se o traço ficou vazio. O traço que passa do limite é cortado nele.
 */
export function strokeSamples(points: readonly DrawPoint[], limit = MAX_DRAW_SAMPLES): { first: number; values: number[] } | null {
  if (points.length === 0) return null
  const drawn = new Map<number, number>()
  let previous: DrawPoint | null = null
  for (const point of points) {
    if (previous && point.sample !== previous.sample) {
      const step = Math.sign(point.sample - previous.sample)
      const span = Math.abs(point.sample - previous.sample)
      for (let offset = 1; offset < span; offset += 1) {
        drawn.set(previous.sample + step * offset, previous.value + ((point.value - previous.value) * offset) / span)
      }
    }
    drawn.set(point.sample, point.value)
    previous = point
  }
  const indexes = [...drawn.keys()].sort((a, b) => a - b)
  const first = indexes[0] as number
  const last = Math.min(indexes[indexes.length - 1] as number, first + limit - 1)
  const values: number[] = []
  let held = drawn.get(first) as number
  for (let sample = first; sample <= last; sample += 1) {
    held = drawn.get(sample) ?? held
    values.push(Math.round(held * 100000) / 100000)
  }
  return { first, values }
}

/** Os pontos do traço em pixels (uma linha por canal desenhado), para a onda mostrar a prévia por cima. */
export function strokePixels(
  stroke: { first: number; values: number[] },
  channel: DrawChannel,
  view: AxisView,
  width: number,
  height: number,
  channels: number,
  rate: number,
): string[] {
  const rows = channel === 'both' ? [0, Math.max(channels, 1) - 1] : [channel === 'left' ? 0 : 1]
  return [...new Set(rows)].map((row) =>
    stroke.values
      .map((value, offset) => `${timeToX((stroke.first + offset) / rate, view, width).toFixed(1)},${yOfValue(value, row, height, channels).toFixed(1)}`)
      .join(' '),
  )
}
