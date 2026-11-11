/* Contas do gráfico do espectro: do dado (frequência × dB) às coordenadas do SVG e de volta, a nota mais próxima e os
   rótulos da grade. Tudo função pura: o componente só desenha. Os limites do eixo seguem os do PNG do servidor
   (analysis/plot.py), para a imagem exportada e o gráfico da tela mostrarem o mesmo recorte. */
import type { SpectrumAxis, SpectrumCurve } from '@/api'

/** Abaixo disso não há som audível, e o logaritmo de 0 Hz (o DC) não existe. */
export const MIN_LOG_HZ = 20
/** Quantos dB o eixo vertical mostra, abaixo do pico arredondado para cima. */
export const DB_SPAN = 100
const LOG_TICKS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
const A4_HZ = 440
const NOTE_NAMES = ['Dó', 'Dó#', 'Ré', 'Ré#', 'Mi', 'Fá', 'Fá#', 'Sol', 'Sol#', 'Lá', 'Lá#', 'Si']

/** A área onde a curva é desenhada, dentro do SVG. */
export interface PlotBox {
  left: number
  right: number
  top: number
  bottom: number
}

export interface SpectrumRange {
  lowHz: number
  highHz: number
  lowDb: number
  highDb: number
}

export function spectrumRange(curve: SpectrumCurve, axis: SpectrumAxis): SpectrumRange {
  const highHz = Math.max(curve.frequencies.at(-1) ?? 20000, MIN_LOG_HZ * 2)
  const peak = curve.levels_db.length > 0 ? Math.max(...curve.levels_db) : 0
  // o + 0 troca o -0 (que o ceil de um pico negativo pequeno dá) por 0
  const highDb = Math.min(Math.ceil(peak / 10) * 10, 20) + 0
  return { lowHz: axis === 'log' ? MIN_LOG_HZ : 0, highHz, lowDb: highDb - DB_SPAN, highDb }
}

export function xOfFrequency(frequency: number, axis: SpectrumAxis, range: SpectrumRange, box: PlotBox): number {
  const width = box.right - box.left
  if (axis === 'log') {
    const low = Math.log10(range.lowHz)
    const position = (Math.log10(Math.max(frequency, range.lowHz)) - low) / (Math.log10(range.highHz) - low)
    return box.left + position * width
  }
  return box.left + ((frequency - range.lowHz) / (range.highHz - range.lowHz)) * width
}

/** A frequência sob uma posição horizontal do SVG, limitada ao que o eixo mostra. */
export function frequencyAtX(x: number, axis: SpectrumAxis, range: SpectrumRange, box: PlotBox): number {
  const position = Math.min(Math.max((x - box.left) / (box.right - box.left), 0), 1)
  if (axis === 'log') {
    const low = Math.log10(range.lowHz)
    return 10 ** (low + position * (Math.log10(range.highHz) - low))
  }
  return range.lowHz + position * (range.highHz - range.lowHz)
}

export function yOfLevel(level: number, range: SpectrumRange, box: PlotBox): number {
  const clamped = Math.min(Math.max(level, range.lowDb), range.highDb)
  return box.bottom - ((clamped - range.lowDb) / (range.highDb - range.lowDb)) * (box.bottom - box.top)
}

/** O traçado da curva (`d` do `<path>`), só com o que cai dentro do eixo de frequência. */
export function curvePath(curve: SpectrumCurve, axis: SpectrumAxis, range: SpectrumRange, box: PlotBox): string {
  const points: string[] = []
  curve.frequencies.forEach((frequency, index) => {
    if (frequency < range.lowHz || frequency > range.highHz) return
    const x = xOfFrequency(frequency, axis, range, box).toFixed(1)
    const y = yOfLevel(curve.levels_db[index] ?? range.lowDb, range, box).toFixed(1)
    points.push(`${points.length === 0 ? 'M' : 'L'}${x} ${y}`)
  })
  return points.join(' ')
}

/** O nível da curva numa frequência, interpolado entre as duas divisões vizinhas (a curva está em ordem crescente). */
export function levelAt(curve: SpectrumCurve, frequency: number): number {
  const { frequencies, levels_db: levels } = curve
  if (frequencies.length === 0) return -Infinity
  if (frequency <= frequencies[0]!) return levels[0]!
  const last = frequencies.length - 1
  if (frequency >= frequencies[last]!) return levels[last]!
  let low = 0
  let high = last
  while (high - low > 1) {
    const middle = (low + high) >> 1
    if (frequencies[middle]! <= frequency) low = middle
    else high = middle
  }
  const span = frequencies[high]! - frequencies[low]!
  const weight = span > 0 ? (frequency - frequencies[low]!) / span : 0
  return levels[low]! + weight * (levels[high]! - levels[low]!)
}

export interface Note {
  /** O nome com a oitava ("Lá4"). */
  name: string
  /** Quanto a frequência dista da nota, em cents (de -50 a +50). */
  cents: number
}

/** A nota mais próxima de uma frequência, com lá 4 em 440 Hz; nulo para o DC e para o que não é frequência. */
export function noteOf(frequency: number, a4 = A4_HZ): Note | null {
  if (!(frequency > 0) || !(a4 > 0)) return null
  const exact = 69 + 12 * Math.log2(frequency / a4)
  const number = Math.round(exact)
  const index = ((number % 12) + 12) % 12
  const octave = Math.floor(number / 12) - 1
  return { name: `${NOTE_NAMES[index]}${octave}`, cents: (exact - number) * 100 }
}

export function formatNote(note: Note): string {
  const cents = Math.round(note.cents)
  return `${note.name} ${cents >= 0 ? '+' : '-'}${Math.abs(cents)} cents`
}

/** "440 Hz", "1,5 kHz": o rótulo curto de uma frequência. */
export function formatHz(frequency: number): string {
  if (frequency >= 1000) return `${(frequency / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} kHz`
  return `${frequency.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} Hz`
}

export function formatDb(level: number): string {
  return `${level.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} dB`
}

/** Os pontos da grade de frequência: a sequência 1-2-5 de 20 Hz a 20 kHz no eixo logarítmico, números redondos no linear. */
export function frequencyTicks(axis: SpectrumAxis, range: SpectrumRange): number[] {
  if (axis === 'log') return LOG_TICKS.filter((tick) => tick >= range.lowHz && tick <= range.highHz)
  const raw = range.highHz / 5
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((factor) => factor * magnitude).find((candidate) => range.highHz / candidate <= 8) ?? raw
  const ticks: number[] = []
  for (let tick = 0; tick <= range.highHz; tick += step) ticks.push(tick)
  return ticks
}

/** Os pontos da grade de nível: de dez em dez dB dentro do eixo. */
export function levelTicks(range: SpectrumRange): number[] {
  const ticks: number[] = []
  for (let tick = Math.ceil(range.lowDb / 10) * 10; tick <= range.highDb; tick += 10) ticks.push(tick)
  return ticks
}

/** O item de que a análise fala, a partir da lista de efeitos que o painel Filtros edita: `timeline.2.effects` vira
 *  `timeline.2`, e o master (`audio.master_effects`) vira `output`, a saída final já renderizada. */
export function analysisTargetOf(listPath: string): string {
  if (listPath === 'audio.master_effects') return 'output'
  return listPath.replace(/\.effects$/, '')
}
