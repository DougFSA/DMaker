/* As contas do gráfico de resposta de frequência dos efeitos de equalização, todas puras: do Hz e do dB para a posição no
   desenho e de volta, o caminho da curva, a faixa de dB que cabe na vista e as mudanças nos pontos do EQ por Curva
   (mover sem cruzar o vizinho, acrescentar, remover). A curva em si vem do servidor (POST /api/audio-effects/response):
   aqui só se desenha o que ele devolveu. */
import type { CurvePoint, EffectResponse } from '@/api'

/** O eixo de frequência do gráfico: de 20 Hz a 20 kHz, em oitavas (a mesma grade da resposta do servidor). */
export const CHART_MIN_HZ = 20
export const CHART_MAX_HZ = 20000

/** As frequências que ganham uma linha de grade e um rótulo. */
export const FREQUENCY_TICKS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]

/** O ganho mais baixo e o mais alto que um ponto do EQ por Curva pode ter (os limites do servidor). */
export const POINT_MIN_DB = -40
export const POINT_MAX_DB = 40

/** Quantos pontos a curva aceita (o `firequalizer` do ffmpeg limita as entradas; o servidor recusa mais que isto). */
export const MAX_CURVE_POINTS = 40

/** O menor espaço, em oitavas, entre dois pontos vizinhos: abaixo disso eles se encavalam. */
const MIN_GAP_OCTAVES = 1 / 48

export interface ChartBox {
  width: number
  height: number
}

export interface DbRange {
  min: number
  max: number
}

const LOG_SPAN = Math.log2(CHART_MAX_HZ / CHART_MIN_HZ)

/** A posição horizontal (de 0 a `width`) de uma frequência no eixo em oitavas. */
export function hzToX(hz: number, width: number): number {
  const clamped = Math.min(Math.max(hz, CHART_MIN_HZ), CHART_MAX_HZ)
  return (Math.log2(clamped / CHART_MIN_HZ) / LOG_SPAN) * width
}

/** A frequência de uma posição horizontal, limitada ao eixo. */
export function xToHz(x: number, width: number): number {
  const fraction = Math.min(Math.max(x / width, 0), 1)
  return CHART_MIN_HZ * 2 ** (fraction * LOG_SPAN)
}

/** A posição vertical de um ganho: o máximo da faixa no topo, o mínimo embaixo. */
export function dbToY(db: number, range: DbRange, height: number): number {
  const fraction = (db - range.min) / (range.max - range.min)
  return (1 - Math.min(Math.max(fraction, 0), 1)) * height
}

/** O ganho de uma posição vertical, limitado à faixa. */
export function yToDb(y: number, range: DbRange, height: number): number {
  const fraction = 1 - Math.min(Math.max(y / height, 0), 1)
  return range.min + fraction * (range.max - range.min)
}

/** Os degraus da grade de dB: a cada 6 dB nas faixas curtas, a cada 12 e a cada 24 nas longas. */
export function dbTicks(range: DbRange): number[] {
  const span = range.max - range.min
  const step = span <= 36 ? 6 : span <= 72 ? 12 : 24
  const ticks: number[] = []
  for (let value = Math.ceil(range.min / step) * step; value <= range.max; value += step) ticks.push(value)
  return ticks
}

/** A faixa de dB da vista: arredonda de 6 em 6 para fora do que a curva (e os pontos) alcançam, sempre mostrando o 0 dB, e não
 *  desce abaixo de -72 dB (mais fundo é só o chão numérico de um filtro). `fixed` trava a faixa (o gráfico dos pontos
 *  arrastáveis, para o desenho não se mexer enquanto a pessoa arrasta). */
export function chartRange(curve: EffectResponse | null, points: readonly CurvePoint[] = [], fixed?: DbRange): DbRange {
  if (fixed) return fixed
  const values = [0, ...(curve?.db ?? []), ...points.map((point) => point.db)].filter(Number.isFinite)
  const top = Math.min(Math.max(Math.ceil(Math.max(...values) / 6) * 6, 6), POINT_MAX_DB)
  const bottom = Math.max(Math.min(Math.floor(Math.min(...values) / 6) * 6, -12), -72)
  return { min: bottom, max: top }
}

/** O traço da curva (comandos do SVG, `M` e `L`), com o ganho preso à faixa para um filtro fundo não sair do desenho. */
export function curvePath(curve: EffectResponse | null, range: DbRange, box: ChartBox): string {
  if (!curve || curve.hz.length === 0) return ''
  return curve.hz
    .map((hz, index) => {
      const command = index === 0 ? 'M' : 'L'
      return `${command}${hzToX(hz, box.width).toFixed(1)} ${dbToY(curve.db[index] ?? 0, range, box.height).toFixed(1)}`
    })
    .join(' ')
}

/** O ganho da curva desenhada na frequência mais perto (para mostrar o valor sob o cursor). */
export function responseAt(curve: EffectResponse | null, hz: number): number | null {
  if (!curve || curve.hz.length === 0) return null
  const distance = (index: number) => Math.abs(Math.log((curve.hz[index] ?? 1) / hz))
  let best = 0
  for (let index = 1; index < curve.hz.length; index += 1) {
    if (distance(index) < distance(best)) best = index
  }
  return curve.db[best] ?? null
}

/* ---------- os pontos do EQ por Curva ---------- */

const clampDb = (db: number) => Math.min(Math.max(db, POINT_MIN_DB), POINT_MAX_DB)

/** Arredonda para o que a pessoa lê: o Hz com uma casa até 100, inteiro até 1000 e de 10 em 10 acima (ainda menor que o
 *  espaço mínimo entre dois pontos, então o arredondamento não junta vizinhos), e o dB com uma casa. */
function tidy(point: CurvePoint): CurvePoint {
  const hz = point.hz >= 1000 ? Math.round(point.hz / 10) * 10 : point.hz >= 100 ? Math.round(point.hz) : Math.round(point.hz * 10) / 10
  return { hz: Math.min(Math.max(hz, CHART_MIN_HZ), CHART_MAX_HZ), db: Math.round(clampDb(point.db) * 10) / 10 }
}

/** Move o ponto `index` para `hz` e `db`, sem passar do vizinho (a lista continua em ordem crescente de frequência). Devolve a
 *  lista nova; os outros pontos não mudam. */
export function movePoint(points: readonly CurvePoint[], index: number, hz: number, db: number): CurvePoint[] {
  const previous = points[index - 1]
  const next = points[index + 1]
  const low = previous ? previous.hz * 2 ** MIN_GAP_OCTAVES : CHART_MIN_HZ
  const high = next ? next.hz / 2 ** MIN_GAP_OCTAVES : CHART_MAX_HZ
  const moved = tidy({ hz: Math.min(Math.max(hz, low), Math.max(low, high)), db })
  return points.map((point, position) => (position === index ? moved : { ...point }))
}

/** Acrescenta um ponto em `hz` e `db`, no lugar certo da ordem. Recusa (devolve a lista como está) quando já há o teto de
 *  pontos ou quando já existe um ponto praticamente na mesma frequência. */
export function addPoint(points: readonly CurvePoint[], hz: number, db: number): CurvePoint[] {
  const added = tidy({ hz, db })
  const crowded = points.some((point) => Math.abs(Math.log2(point.hz / added.hz)) < MIN_GAP_OCTAVES)
  if (points.length >= MAX_CURVE_POINTS || crowded) return points.map((point) => ({ ...point }))
  return [...points.map((point) => ({ ...point })), added].sort((a, b) => a.hz - b.hz)
}

/** Tira o ponto `index`. A curva guarda ao menos dois pontos: com menos, devolve a lista como está. */
export function removePoint(points: readonly CurvePoint[], index: number): CurvePoint[] {
  if (points.length <= 2 || index < 0 || index >= points.length) return points.map((point) => ({ ...point }))
  return points.filter((_, position) => position !== index).map((point) => ({ ...point }))
}

/** O texto de uma frequência: "63 Hz", "3,15 kHz". */
export function formatFrequency(hz: number): string {
  if (hz >= 1000) return `${(hz / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} kHz`
  return `${hz.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} Hz`
}

/** O texto de um ganho, sempre com sinal: "+6,0 dB", "-3,5 dB". */
export function formatGain(db: number): string {
  const text = Math.abs(db).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  return `${db < 0 ? '-' : '+'}${text} dB`
}
