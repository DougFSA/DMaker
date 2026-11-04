import { describe, expect, it } from 'vitest'
import { bandAt, channelAt, drawBlocker, EFFECT_SAMPLE_RATE, MAX_DRAW_SAMPLES, strokePixels, strokeSamples, valueAt, yOfValue } from './audioDraw'

const RATE = EFFECT_SAMPLE_RATE

describe('quando a Draw Tool vale', () => {
  it('só no zoom máximo e na taxa dos efeitos, e diz o que fazer em cada caso', () => {
    const near = { start: 1, end: 1 + 200 / RATE } // 200 amostras em 1000 px: 5 px cada
    expect(drawBlocker(near, 1000, RATE)).toBeNull()
    expect(drawBlocker({ start: 0, end: 1 }, 1000, RATE)).toContain('Aproxime mais o zoom')
    const wrongRate = drawBlocker({ start: 0, end: 200 / 44100 }, 1000, 44100)
    expect(wrongRate).toContain('48 kHz')
    expect(wrongRate).toContain('44,1 kHz')
  })
})

describe('canal e valor sob o mouse', () => {
  it('o canal de cima é o esquerdo, o de baixo o direito, e Shift vale nos dois', () => {
    expect(channelAt(40, 300, 2, false)).toBe('left')
    expect(channelAt(250, 300, 2, false)).toBe('right')
    expect(channelAt(250, 300, 2, true)).toBe('both')
    expect(channelAt(250, 300, 1, false)).toBe('both')
    expect(bandAt(10, 300, 2)).toBe(0)
    expect(bandAt(290, 300, 2)).toBe(1)
  })

  it('o meio do canal é zero, o topo é 1 e o fundo é -1, e o valor volta ao mesmo pixel', () => {
    // dois canais de 149 px com 2 de respiro: o primeiro vai de 0 a 149
    expect(valueAt(74.5, 300, 2, 0)).toBeCloseTo(0, 6)
    expect(valueAt(0, 300, 2, 0)).toBeCloseTo(1, 6)
    expect(valueAt(149, 300, 2, 0)).toBeCloseTo(-1, 6)
    expect(valueAt(-50, 300, 2, 0)).toBe(1) // o mouse fora do canal fica no limite
    for (const value of [-0.6, 0, 0.25, 0.9]) expect(valueAt(yOfValue(value, 1, 300, 2), 300, 2, 1)).toBeCloseTo(value, 6)
  })
})

describe('do traço às amostras', () => {
  it('liga os pontos do mouse por retas, sem buracos entre as amostras', () => {
    const stroke = strokeSamples([
      { sample: 100, value: 0 },
      { sample: 104, value: 0.8 },
    ])
    expect(stroke).toEqual({ first: 100, values: [0, 0.2, 0.4, 0.6, 0.8] })
  })

  it('o traço para a esquerda e o que passa por cima do mesmo ponto vale o último valor', () => {
    const stroke = strokeSamples([
      { sample: 10, value: 0.5 },
      { sample: 8, value: -0.5 },
      { sample: 10, value: 0.1 },
    ])
    expect(stroke?.first).toBe(8)
    expect(stroke?.values).toEqual([-0.5, -0.2, 0.1])
  })

  it('um ponto só desenha uma amostra, e sem pontos não há traço', () => {
    expect(strokeSamples([{ sample: 5, value: 0.3 }])).toEqual({ first: 5, values: [0.3] })
    expect(strokeSamples([])).toBeNull()
  })

  it('corta o traço no limite de amostras do efeito', () => {
    const stroke = strokeSamples([
      { sample: 0, value: 0 },
      { sample: 2000, value: 1 },
    ])
    expect(stroke?.values).toHaveLength(MAX_DRAW_SAMPLES)
  })

  it('mostra a prévia em uma linha por canal desenhado', () => {
    const stroke = { first: 100, values: [0, 0.5] }
    const view = { start: 100 / RATE, end: 110 / RATE }
    expect(strokePixels(stroke, 'left', view, 1000, 300, 2, RATE)).toHaveLength(1)
    expect(strokePixels(stroke, 'both', view, 1000, 300, 2, RATE)).toHaveLength(2)
    const [line] = strokePixels(stroke, 'left', view, 1000, 300, 2, RATE)
    expect(line?.split(' ')[0]).toBe('0.0,74.5')
  })
})
