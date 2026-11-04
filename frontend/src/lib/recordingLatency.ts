/* A conta de latência da gravação sobre o vídeo, toda pura: de onde sai o número, como a gravação cai no lugar certo da linha
   do tempo e como a calibração (um clique tocado, gravado e achado por correlação) o corrige. Sem DOM nem Web Audio: o
   navegador entrega os números e os testes entregam sinais sintéticos.

   O caminho do som, para quem lê a conta: a prévia toca o instante `p` e o alto-falante o solta `saída` depois; a pessoa fala
   junto do que ouve; o microfone capta e o navegador entrega o bloco `entrada` depois. Então o primeiro quadro da gravação,
   que chega à página quando a prévia marca `t0`, foi captado a `entrada + saída` antes do instante que a pessoa estava
   vendo, e o item entra em `t0 - (entrada + saída)`. */
import { readStored, writeStored } from './storage'

/** Os números de latência que o navegador conhece (segundos). Cada um pode faltar: o Safari não tem `outputLatency`. */
export interface BrowserLatency {
  /** `AudioContext.baseLatency`: do grafo até o destino. */
  baseLatency?: number | null
  /** `AudioContext.outputLatency`: do destino até o alto-falante. */
  outputLatency?: number | null
  /** `MediaStreamTrack.getSettings().latency`: do microfone até a página. */
  inputLatency?: number | null
}

const finite = (value: number | null | undefined): number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0

/** A latência que a Web Audio informa, em segundos: entrada + processamento + saída. */
export function webAudioLatency(reading: BrowserLatency): number {
  return finite(reading.inputLatency) + finite(reading.baseLatency) + finite(reading.outputLatency)
}

/** A latência usada: a da Web Audio mais a correção que a calibração mediu (pode ser negativa), nunca abaixo de zero. */
export function totalLatency(estimate: number, calibration = 0): number {
  return Math.max(estimate + calibration, 0)
}

/** O instante da linha do tempo em que a gravação começa: o da prévia quando o primeiro quadro chegou, menos a latência.
 *  Pode sair negativo (gravar no começo do vídeo); a spec apara esse pedaço do arquivo. */
export function compensatedStart(previewPosition: number, latency: number): number {
  return previewPosition - latency
}

/** Arredonda ao microssegundo, o que a spec guarda. */
export const roundTime = (seconds: number): number => Math.round(seconds * 1e6) / 1e6

/* ---------- o relógio da prévia ---------- */

/** Uma leitura da prévia: o relógio da página (ms) e a posição do cursor naquele momento (s). */
export interface ClockSample {
  nowMs: number
  position: number
}

/**
 * Relaciona o relógio da página com a posição da prévia. O cursor só anda a cada quadro de animação, então toda leitura
 * está atrasada entre 0 e um quadro em relação ao tempo real; `posição - tempo decorrido` é, portanto, sempre um pouco
 * menor que o valor certo, e o MAIOR deles, entre muitas leituras, é o da leitura que pegou o cursor recém-atualizado.
 * Com a prévia tocando a 1x, o erro cai de até um quadro (uns 16 ms) para menos de 1 ms em um segundo de leituras.
 */
export class PreviewClock {
  private offset = Number.NEGATIVE_INFINITY

  constructor(private readonly speed = 1) {}

  /** Anota uma leitura (cada bloco de áudio que chega é uma). */
  add(sample: ClockSample): void {
    const candidate = sample.position - (sample.nowMs / 1000) * this.speed
    if (candidate > this.offset) this.offset = candidate
  }

  get ready(): boolean {
    return Number.isFinite(this.offset)
  }

  /** A posição da prévia no instante `nowMs` do relógio da página. */
  positionAt(nowMs: number): number {
    if (!this.ready) throw new Error('o relógio da prévia ainda não tem leituras')
    return this.offset + (nowMs / 1000) * this.speed
  }
}

/* ---------- a calibração: tocar um clique, gravar e achar o atraso ---------- */

/** O clique da calibração: um pulso curto e forte, de energia concentrada, fácil de achar por correlação. */
export function makeClick(rate: number, durationMs = 4): Float32Array {
  const length = Math.max(2, Math.round((rate * durationMs) / 1000))
  const click = new Float32Array(length)
  for (let index = 0; index < length; index += 1) {
    // meia janela de Hann com sinal alternado: tem banda larga e começa e termina em zero, sem estalo do próprio clique
    const envelope = Math.sin((Math.PI * (index + 0.5)) / length) ** 2
    click[index] = (index % 2 === 0 ? 1 : -1) * 0.9 * envelope
  }
  return click
}

export interface DelayEstimate {
  /** O atraso, em segundos, do início do clique tocado ao início dele na gravação. */
  seconds: number
  /** Quão nítido foi o pico (0 a 1): abaixo de 0,3 o clique não se distinguiu do ruído e a medida não vale. */
  confidence: number
}

/**
 * O atraso do `template` (o clique tocado) dentro de `recorded` por correlação cruzada normalizada, de 0 até
 * `maxDelaySeconds`. A normalização pela energia de cada janela deixa o pico independente do volume com que o microfone
 * ouviu o clique. Devolve `null` se a gravação não tem energia.
 */
export function findDelay(
  template: Float32Array,
  recorded: Float32Array,
  rate: number,
  maxDelaySeconds = 1,
): DelayEstimate | null {
  const size = template.length
  const lastLag = Math.min(Math.floor(maxDelaySeconds * rate), recorded.length - size)
  if (size === 0 || lastLag < 0) return null
  let templateEnergy = 0
  for (const value of template) templateEnergy += value * value
  if (templateEnergy === 0) return null

  // energia acumulada para a norma de cada janela sair em O(1)
  const cumulative = new Float64Array(recorded.length + 1)
  for (let index = 0; index < recorded.length; index += 1) {
    const value = recorded[index] ?? 0
    cumulative[index + 1] = (cumulative[index] ?? 0) + value * value
  }

  let best = -1
  let bestLag = 0
  let second = -1
  const scores = new Float64Array(lastLag + 1)
  for (let lag = 0; lag <= lastLag; lag += 1) {
    const energy = (cumulative[lag + size] ?? 0) - (cumulative[lag] ?? 0)
    if (energy <= 1e-12) continue
    let dot = 0
    for (let index = 0; index < size; index += 1) dot += (template[index] ?? 0) * (recorded[lag + index] ?? 0)
    const score = Math.abs(dot) / Math.sqrt(templateEnergy * energy)
    scores[lag] = score
    if (score > best) {
      best = score
      bestLag = lag
    }
  }
  if (best <= 0) return null
  // o segundo melhor pico, fora da vizinhança do primeiro, mede quanto o primeiro se destaca
  const guard = Math.max(size, 8)
  for (let lag = 0; lag <= lastLag; lag += 1) {
    if (Math.abs(lag - bestLag) > guard && (scores[lag] ?? 0) > second) second = scores[lag] ?? 0
  }
  const confidence = Math.max(0, Math.min(1, best - Math.max(second, 0) * 0.5))
  return { seconds: bestLag / rate, confidence }
}

/** A confiança mínima para aceitar uma calibração. */
export const MIN_CALIBRATION_CONFIDENCE = 0.3

/**
 * O que a calibração mediu, como correção da estimativa da Web Audio. O atraso medido é o do caminho todo (do clique
 * tocado ao clique gravado, em tempo do contexto de áudio); a correção é o que falta a estimativa para chegar a ele.
 */
export function calibrationCorrection(measuredDelay: number, estimate: number): number {
  return measuredDelay - estimate
}

/* ---------- a calibração guardada, por dispositivo ---------- */

const CALIBRATION_PREFIX = 'dmaker.recording.latency.'

/** A correção de latência guardada para o dispositivo de entrada (0 se nunca calibrou ou se não há armazenamento). */
export function readCalibration(deviceId: string): number {
  const stored = Number(readStored(CALIBRATION_PREFIX + (deviceId || 'default')))
  return Number.isFinite(stored) ? stored : 0
}

export function writeCalibration(deviceId: string, correction: number): void {
  writeStored(CALIBRATION_PREFIX + (deviceId || 'default'), String(roundTime(correction)))
}
