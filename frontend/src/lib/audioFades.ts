/* As contas da alça de fade na linha do tempo, todas puras: as curvas (as mesmas de `domain/fade_curves.py`, para o
   desenho bater com o som), o que o item da vista diz dos fades dele, para onde o arrasto leva a duração e a operação
   que o gesto solto vira. O arrasto grava ao soltar; durante ele só o desenho muda. */
import type { EditOperation, TimelineItem } from '@/api'
import { roundSeconds } from './timeline'

export const FADE_CURVES = ['linear', 'logarithmic', 'exponential', 'sine', 'quadratic'] as const
export type FadeCurve = (typeof FADE_CURVES)[number]
export type FadeSide = 'in' | 'out'

export const FADE_CURVE_LABEL: Record<FadeCurve, string> = {
  linear: 'Linear',
  logarithmic: 'Logarítmica',
  exponential: 'Exponencial',
  sine: 'Seno (S)',
  quadratic: 'Quadrática',
}

/** O fade preso à borda de um item, como a vista o entrega (`extra.fades`): a duração é em segundos do item. */
export interface EdgeFade {
  duration: number
  curve: FadeCurve
}

export type ItemFades = Partial<Record<FadeSide, EdgeFade>>

/** O ganho de um fade de entrada em `u` (0 a 1), igual ao do `afade` com a curva correspondente. */
export function fadeInGain(curve: FadeCurve, u: number): number {
  const x = Math.min(Math.max(u, 0), 1)
  switch (curve) {
    case 'linear':
      return x
    case 'logarithmic':
      return Math.max(1 + 0.2 * Math.log10(Math.max(x, 1e-6)), 0)
    case 'exponential':
      return 0.1 ** (5 * (1 - x))
    case 'sine':
      return (1 - Math.cos(Math.PI * x)) / 2
    case 'quadratic':
      return x * x
  }
}

/** O ganho em `u` (0 no começo do fade, 1 no fim): a entrada sobe, a saída é a entrada de trás para a frente. */
export function fadeGain(side: FadeSide, curve: FadeCurve, u: number): number {
  return side === 'in' ? fadeInGain(curve, u) : fadeInGain(curve, 1 - u)
}

function isCurve(value: unknown): value is FadeCurve {
  return typeof value === 'string' && (FADE_CURVES as readonly string[]).includes(value)
}

/** Os fades da borda que o item da vista traz; item sem som ou sem fade devolve vazio. */
export function itemFades(item: Pick<TimelineItem, 'extra'>): ItemFades {
  const raw = item.extra?.fades
  if (!raw || typeof raw !== 'object') return {}
  const fades: ItemFades = {}
  for (const side of ['in', 'out'] as const) {
    const entry = (raw as Record<string, unknown>)[side]
    if (!entry || typeof entry !== 'object') continue
    const { duration, curve } = entry as { duration?: unknown; curve?: unknown }
    if (typeof duration === 'number' && duration > 0) fades[side] = { duration, curve: isCurve(curve) ? curve : 'linear' }
  }
  return fades
}

/** As trilhas cujos itens têm alça de fade: o som do clipe (A1), a música, a narração e a voz gravada. As faixas externas
 *  (A2...) não têm: o item delas é uma janela de um arquivo longo, e a borda da janela não é a borda do som. */
const FADE_TRACK = /^(A1|MUS|NAR|VO)$/

/** O alvo de `edit_project` da cadeia de um item com alça de fade, ou nulo se o item não tem. */
export function fadeTarget(trackId: string, item: Pick<TimelineItem, 'index' | 'kind'>): string | null {
  if (!FADE_TRACK.test(trackId)) return null
  if (trackId === 'A1') return item.kind === 'clip-audio' ? `timeline.${item.index}` : null
  if (trackId === 'MUS') return 'audio.music'
  if (trackId === 'NAR') return `audio.narration.${item.index}`
  return `audio.voiceover.${item.index}`
}

/** A velocidade com que o item toca (o clipe acelerado): os fades são em segundos do item, o desenho em segundos da tela. */
export function itemSpeed(item: Pick<TimelineItem, 'extra'>): number {
  const speed = item.extra?.speed
  return typeof speed === 'number' && speed > 0 ? speed : 1
}

/** Menos que isto de fade (20 ms) não vale a alça: soltar perto da borda tira o fade. */
export const MIN_FADE_SECONDS = 0.02

/**
 * A duração do fade (segundos do item) para onde o ponteiro foi. `pointerSeconds` é a distância, em segundos da tela,
 * entre a borda do item e o ponteiro (já positiva para dentro do item); `lengthSeconds` é a duração do item na tela.
 * O fade não passa do item, e perto da borda vira zero (sem fade).
 */
export function draggedFadeDuration(pointerSeconds: number, lengthSeconds: number, speed = 1): number {
  const inside = Math.min(Math.max(pointerSeconds, 0), lengthSeconds)
  if (inside < MIN_FADE_SECONDS) return 0
  return roundSeconds(inside * speed)
}

/** A operação que o gesto solto vira: grava o fade da borda com a duração nova (0 tira) e mantém a curva que ele já tinha. */
export function fadeOperation(target: string, side: FadeSide, duration: number, curve?: FadeCurve): EditOperation {
  return { type: 'audio_fade', target, side, duration, ...(curve ? { curve } : {}) }
}

/** Os pontos do polígono da curva, num retângulo de `width` por `height`: a região entre a curva de ganho e o topo, que é
 *  o som que o fade tira, para o desenho sobre a forma de onda escurecer só isso. */
export function fadeShadePoints(side: FadeSide, curve: FadeCurve, width: number, height: number, steps = 24): string {
  const points: string[] = []
  for (let step = 0; step <= steps; step += 1) {
    const u = step / steps
    const x = u * width
    const y = (1 - fadeGain(side, curve, u)) * height
    points.push(`${x.toFixed(2)},${y.toFixed(2)}`)
  }
  // fecha pelo canto de cima, do lado da borda do item: a região entre a curva e o topo é o som que o fade tira
  points.push(side === 'in' ? '0,0' : `${width.toFixed(2)},0`)
  return points.join(' ')
}
