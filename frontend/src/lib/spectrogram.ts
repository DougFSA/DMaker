/* O espectrograma do painel Áudio: os ajustes da vista, as escalas de frequência (as mesmas fórmulas de
   `analysis/scales.py`, para o retângulo da seleção cair no mesmo pixel que a imagem do servidor), a régua de frequência e as
   tabelas de cor. O servidor entrega a imagem em tons de cinza; é aqui que o cinza vira cor, para trocar o esquema sem
   pedir a imagem de novo. Funções puras. */

export type SpectrogramScale = 'linear' | 'log' | 'mel' | 'bark' | 'erb'
export type ColorScheme = 'colors' | 'flame' | 'gray' | 'inverse'

export interface SpectrogramSettings {
  scale: SpectrogramScale
  scheme: ColorScheme
  window: string
  windowSize: number
  gainDb: number
  rangeDb: number
  minHz: number
  maxHz: number
}

/** O padrão do Audacity: ganho de 20 dB e alcance de 80 dB, janela de Hann de 2048 amostras. */
export const DEFAULT_SPECTROGRAM: SpectrogramSettings = {
  scale: 'linear',
  scheme: 'colors',
  window: 'hann',
  windowSize: 2048,
  gainDb: 20,
  rangeDb: 80,
  minHz: 0,
  maxHz: 24000,
}

export const SCALE_OPTIONS: Array<{ value: SpectrogramScale; label: string }> = [
  { value: 'linear', label: 'Linear' },
  { value: 'log', label: 'Logarítmica' },
  { value: 'mel', label: 'Mel' },
  { value: 'bark', label: 'Bark' },
  { value: 'erb', label: 'ERB' },
]

export const SCHEME_OPTIONS: Array<{ value: ColorScheme; label: string }> = [
  { value: 'colors', label: 'Cores' },
  { value: 'flame', label: 'Chama' },
  { value: 'gray', label: 'Cinza' },
  { value: 'inverse', label: 'Cinza invertido' },
]

/** As janelas do Audacity, com os nomes da spec. */
export const WINDOW_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'rectangular', label: 'Retangular' },
  { value: 'bartlett', label: 'Bartlett' },
  { value: 'hamming', label: 'Hamming' },
  { value: 'hann', label: 'Hann' },
  { value: 'blackman', label: 'Blackman' },
  { value: 'blackman_harris', label: 'Blackman-Harris' },
  { value: 'welch', label: 'Welch' },
  { value: 'gaussian_2_5', label: 'Gaussiana a 2,5' },
  { value: 'gaussian_3_5', label: 'Gaussiana a 3,5' },
  { value: 'gaussian_4_5', label: 'Gaussiana a 4,5' },
]

/** Os tamanhos de janela que valem a pena num espectrograma (a rota aceita de 128 a 65536). */
export const WINDOW_SIZES = [256, 512, 1024, 2048, 4096, 8192, 16384] as const

/* ---------- escalas ---------- */

const LOG_FLOOR_HZ = 1

export function scalePosition(scale: SpectrogramScale, hz: number): number {
  switch (scale) {
    case 'log':
      return Math.log10(Math.max(hz, LOG_FLOOR_HZ))
    case 'mel':
      return 2595 * Math.log10(1 + hz / 700)
    case 'bark':
      return (26.81 * hz) / (1960 + hz) - 0.53
    case 'erb':
      return 21.4 * Math.log10(1 + 0.00437 * hz)
    default:
      return hz
  }
}

export function scaleFrequency(scale: SpectrogramScale, position: number): number {
  switch (scale) {
    case 'log':
      return 10 ** position
    case 'mel':
      return 700 * (10 ** (position / 2595) - 1)
    case 'bark':
      return (1960 * (position + 0.53)) / (26.81 - (position + 0.53))
    case 'erb':
      return (10 ** (position / 21.4) - 1) / 0.00437
    default:
      return position
  }
}

/** A faixa mostrada com o piso que a escala aceita (a logarítmica não tem o zero) e o teto no Nyquist. */
export function effectiveBand(settings: SpectrogramSettings, rate: number): { min: number; max: number } {
  const nyquist = rate / 2
  const max = Math.min(Math.max(settings.maxHz, 2), nyquist)
  const floor = settings.scale === 'log' ? 20 : 0
  const min = Math.min(Math.max(settings.minHz, floor), max - 1)
  return { min, max }
}

/** Onde a frequência cai na altura da imagem: 0 embaixo (a menor frequência) e 1 em cima. */
export function frequencyFraction(scale: SpectrogramScale, hz: number, band: { min: number; max: number }): number {
  const low = scalePosition(scale, band.min)
  const high = scalePosition(scale, band.max)
  return (scalePosition(scale, hz) - low) / (high - low)
}

/** O caminho de volta: a frequência (Hz) de uma fração da altura (0 embaixo, 1 em cima). */
export function fractionFrequency(scale: SpectrogramScale, fraction: number, band: { min: number; max: number }): number {
  const low = scalePosition(scale, band.min)
  const high = scalePosition(scale, band.max)
  return scaleFrequency(scale, low + fraction * (high - low))
}

/** A frequência central de uma faixa: a média geométrica, como a do servidor (a que o EQ espectral usa). */
export function centerFrequency(low: number, high: number): number {
  return Math.sqrt(Math.max(low, LOG_FLOOR_HZ) * high)
}

export function formatHz(hz: number): string {
  if (hz >= 10000) return `${(hz / 1000).toFixed(0)} kHz`
  if (hz >= 1000) return `${(hz / 1000).toFixed(2).replace(/\.?0+$/, '').replace('.', ',')} kHz`
  return `${Math.round(hz)} Hz`
}

export interface FrequencyTick {
  hz: number
  label: string
  /** 0 embaixo, 1 em cima. */
  fraction: number
}

/** Os passos "redondos" da régua linear, em Hz: a régua usa o menor que deixa as marcas a `minPixels` uma da outra. */
const LINEAR_STEPS = [100, 200, 250, 500, 1000, 2000, 2500, 4000, 5000, 10000]
const LOG_TICKS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]

/** As marcas da régua de frequência: valores redondos, no máximo uma a cada `minPixels` de altura. */
export function frequencyTicks(
  scale: SpectrogramScale,
  band: { min: number; max: number },
  height: number,
  minPixels = 26,
): FrequencyTick[] {
  const candidates = scale === 'linear' ? linearCandidates(band, height, minPixels) : LOG_TICKS
  const ticks: FrequencyTick[] = []
  let lastY = Number.NEGATIVE_INFINITY
  for (const hz of [...candidates].sort((a, b) => b - a)) {
    if (hz <= band.min || hz >= band.max) continue
    const y = (1 - frequencyFraction(scale, hz, band)) * height
    if (y - lastY < minPixels) continue
    if (y < 9 || y > height - 4) continue
    ticks.push({ hz, label: formatHz(hz), fraction: frequencyFraction(scale, hz, band) })
    lastY = y
  }
  return ticks
}

function linearCandidates(band: { min: number; max: number }, height: number, minPixels: number): number[] {
  const pixelsPerHz = height / (band.max - band.min)
  const step = LINEAR_STEPS.find((candidate) => candidate * pixelsPerHz >= minPixels) ?? (LINEAR_STEPS[LINEAR_STEPS.length - 1] as number)
  const values: number[] = []
  for (let hz = Math.ceil(band.min / step) * step; hz < band.max; hz += step) values.push(hz)
  return values
}

/* ---------- cores ---------- */

type Stop = [number, number, number, number]

const STOPS: Record<ColorScheme, Stop[]> = {
  colors: [
    [0, 0, 0, 24],
    [0.25, 40, 20, 140],
    [0.5, 160, 30, 150],
    [0.75, 240, 110, 40],
    [1, 255, 250, 200],
  ],
  flame: [
    [0, 0, 0, 0],
    [0.4, 150, 20, 10],
    [0.75, 250, 150, 20],
    [1, 255, 255, 230],
  ],
  gray: [
    [0, 0, 0, 0],
    [1, 255, 255, 255],
  ],
  inverse: [
    [0, 255, 255, 255],
    [1, 0, 0, 0],
  ],
}

/** A tabela de 256 cores (R, G, B em sequência) de um esquema: o cinza 0 a 255 do servidor indexa nela. */
export function palette(scheme: ColorScheme): Uint8ClampedArray {
  const stops = STOPS[scheme]
  const table = new Uint8ClampedArray(256 * 3)
  for (let level = 0; level < 256; level += 1) {
    const at = level / 255
    let index = 0
    while (index < stops.length - 2 && at > (stops[index + 1] as Stop)[0]) index += 1
    const from = stops[index] as Stop
    const to = stops[index + 1] as Stop
    const mix = Math.min(Math.max((at - from[0]) / (to[0] - from[0]), 0), 1)
    for (let channel = 0; channel < 3; channel += 1) {
      table[level * 3 + channel] = Math.round((from[channel + 1] as number) + ((to[channel + 1] as number) - (from[channel + 1] as number)) * mix)
    }
  }
  return table
}

/** Pinta `pixels` (RGBA, com o cinza no canal vermelho, como o PNG decodificado) com a tabela de cores, no lugar. */
export function colorize(pixels: Uint8ClampedArray, table: Uint8ClampedArray): void {
  for (let at = 0; at < pixels.length; at += 4) {
    const base = (pixels[at] as number) * 3
    pixels[at] = table[base] as number
    pixels[at + 1] = table[base + 1] as number
    pixels[at + 2] = table[base + 2] as number
    pixels[at + 3] = 255
  }
}

/* ---------- o retângulo da seleção ---------- */

export interface SpectralBox {
  left: number
  right: number
  top: number
  bottom: number
}

/** O retângulo da seleção em pixels: de `start` a `end` (s) e de `low` a `high` (Hz) numa área de `width` por `height`. */
export function selectionBox(
  selection: { start: number; end: number; low_hz?: number; high_hz?: number },
  toX: (time: number) => number,
  settings: SpectrogramSettings,
  band: { min: number; max: number },
  height: number,
): SpectralBox | null {
  if (selection.low_hz === undefined || selection.high_hz === undefined) return null
  const top = (1 - frequencyFraction(settings.scale, selection.high_hz, band)) * height
  const bottom = (1 - frequencyFraction(settings.scale, selection.low_hz, band)) * height
  return { left: toX(selection.start), right: toX(selection.end), top, bottom }
}
