import { describe, expect, it } from 'vitest'
import {
  centerFrequency,
  colorize,
  DEFAULT_SPECTROGRAM,
  effectiveBand,
  formatHz,
  fractionFrequency,
  frequencyFraction,
  frequencyTicks,
  palette,
  scaleFrequency,
  scalePosition,
  selectionBox,
  type SpectrogramScale,
} from './spectrogram'

const SCALES: SpectrogramScale[] = ['linear', 'log', 'mel', 'bark', 'erb']

describe('as escalas de frequência', () => {
  it.each(SCALES)('a escala %s cresce com a frequência e a volta devolve o Hz', (scale) => {
    let last = -Infinity
    for (const hz of [20, 100, 440, 1000, 3000, 8000, 20000]) {
      const position = scalePosition(scale, hz)
      expect(position).toBeGreaterThan(last)
      last = position
      expect(scaleFrequency(scale, position)).toBeCloseTo(hz, 6)
    }
  })

  it('bate com os pontos conhecidos que o servidor também usa', () => {
    expect(scalePosition('mel', 1000)).toBeCloseTo(1000, 0)
    expect(scalePosition('bark', 1000)).toBeCloseTo(8.5, 1)
    expect(scalePosition('erb', 1000)).toBeCloseTo(15.6, 1)
    expect(scalePosition('log', 1000)).toBeCloseTo(3, 9)
  })

  it('a fração da altura vai de 0 (menor frequência) a 1 (maior) e volta ao Hz', () => {
    const band = { min: 20, max: 12000 }
    for (const scale of SCALES) {
      expect(frequencyFraction(scale, 20, band)).toBeCloseTo(0, 9)
      expect(frequencyFraction(scale, 12000, band)).toBeCloseTo(1, 9)
      expect(fractionFrequency(scale, frequencyFraction(scale, 3000, band), band)).toBeCloseTo(3000, 5)
    }
  })

  it('a faixa respeita o Nyquist e o piso da escala logarítmica', () => {
    expect(effectiveBand({ ...DEFAULT_SPECTROGRAM, maxHz: 96000 }, 48000)).toEqual({ min: 0, max: 24000 })
    expect(effectiveBand({ ...DEFAULT_SPECTROGRAM, scale: 'log', minHz: 0 }, 48000).min).toBe(20)
  })
})

describe('a régua de frequência', () => {
  it('põe valores redondos em ordem de cima para baixo, sem apertar mais que o mínimo de pixels', () => {
    const ticks = frequencyTicks('linear', { min: 0, max: 24000 }, 400)
    expect(ticks.length).toBeGreaterThan(3)
    const ys = ticks.map((tick) => (1 - tick.fraction) * 400)
    for (let index = 1; index < ys.length; index += 1) expect((ys[index] as number) - (ys[index - 1] as number)).toBeGreaterThanOrEqual(26)
    expect(ticks.every((tick) => tick.hz > 0 && tick.hz < 24000)).toBe(true)
  })

  it('na escala logarítmica as marcas são de oitavas aproximadas', () => {
    const labels = frequencyTicks('log', { min: 20, max: 20000 }, 500).map((tick) => tick.label)
    expect(labels).toContain('1 kHz')
    expect(labels).toContain('100 Hz')
  })

  it('formata Hz e kHz em português', () => {
    expect(formatHz(440)).toBe('440 Hz')
    expect(formatHz(2500)).toBe('2,5 kHz')
    expect(formatHz(3000)).toBe('3 kHz')
    expect(formatHz(12000)).toBe('12 kHz')
    expect(centerFrequency(2800, 3200)).toBeCloseTo(2993.3, 1)
  })
})

describe('as cores', () => {
  it('cada esquema vai do preto ao claro (ou o contrário) em 256 degraus', () => {
    const gray = palette('gray')
    expect([...gray.slice(0, 3)]).toEqual([0, 0, 0])
    expect([...gray.slice(255 * 3)]).toEqual([255, 255, 255])
    expect([...palette('inverse').slice(0, 3)]).toEqual([255, 255, 255])
    for (const scheme of ['colors', 'flame'] as const) {
      const table = palette(scheme)
      expect(table).toHaveLength(768)
      expect(table[0]! + table[1]! + table[2]!).toBeLessThan(60)
      expect(table[765]! + table[766]! + table[767]!).toBeGreaterThan(600)
    }
  })

  it('pinta o cinza do canal vermelho com a tabela e deixa opaco', () => {
    const pixels = new Uint8ClampedArray([0, 0, 0, 255, 255, 255, 255, 255, 128, 9, 9, 3])
    colorize(pixels, palette('inverse'))
    expect([...pixels.slice(0, 4)]).toEqual([255, 255, 255, 255])
    expect([...pixels.slice(4, 8)]).toEqual([0, 0, 0, 255])
    expect(pixels[8]).toBe(127)
    expect(pixels[11]).toBe(255)
  })
})

describe('o retângulo da seleção', () => {
  it('põe a seleção espectral no pixel da frequência, e uma seleção só de tempo fica sem retângulo', () => {
    const band = { min: 0, max: 24000 }
    const rectangle = selectionBox({ start: 1, end: 2, low_hz: 6000, high_hz: 12000 }, (time) => time * 100, DEFAULT_SPECTROGRAM, band, 400)
    expect(rectangle).toEqual({ left: 100, right: 200, top: 200, bottom: 300 })
    expect(selectionBox({ start: 1, end: 2 }, (time) => time, DEFAULT_SPECTROGRAM, band, 400)).toBeNull()
  })
})
