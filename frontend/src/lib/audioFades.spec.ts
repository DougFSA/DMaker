import { describe, expect, it } from 'vitest'
import {
  draggedFadeDuration,
  FADE_CURVES,
  fadeGain,
  fadeInGain,
  fadeOperation,
  fadeShadePoints,
  fadeTarget,
  itemFades,
  itemSpeed,
  MIN_FADE_SECONDS,
} from './audioFades'

describe('as curvas do fade', () => {
  it('as cinco sobem sem recuar, partem do silêncio e chegam ao nível original', () => {
    for (const curve of FADE_CURVES) {
      let previous = -1
      for (let step = 0; step <= 100; step += 1) {
        const gain = fadeInGain(curve, step / 100)
        expect(gain).toBeGreaterThanOrEqual(previous - 1e-12)
        previous = gain
      }
      expect(fadeInGain(curve, 0)).toBeLessThan(0.01)
      expect(fadeInGain(curve, 1)).toBeCloseTo(1, 6)
    }
  })

  it('dão os mesmos números do afade (os que o servidor mede no ffmpeg)', () => {
    expect(fadeInGain('linear', 0.25)).toBeCloseTo(0.25, 6)
    expect(fadeInGain('logarithmic', 0.5)).toBeCloseTo(0.9398, 3)
    expect(fadeInGain('exponential', 0.9)).toBeCloseTo(0.3162, 3)
    expect(fadeInGain('sine', 0.25)).toBeCloseTo(0.1464, 3)
    expect(fadeInGain('quadratic', 0.9)).toBeCloseTo(0.81, 6)
  })

  it('a saída é a entrada de trás para a frente', () => {
    for (const curve of FADE_CURVES) {
      expect(fadeGain('out', curve, 0.3)).toBeCloseTo(fadeInGain(curve, 0.7), 9)
      expect(fadeGain('out', curve, 0)).toBeCloseTo(1, 6)
    }
  })
})

describe('o que o item da vista diz dos fades', () => {
  it('lê a duração e a curva das duas pontas', () => {
    const fades = itemFades({ extra: { fades: { in: { duration: 1.5, curve: 'sine' }, out: { duration: 2, curve: 'quadratic' } } } })
    expect(fades).toEqual({ in: { duration: 1.5, curve: 'sine' }, out: { duration: 2, curve: 'quadratic' } })
  })

  it('item sem fades, ou com valor torto, devolve vazio e uma curva desconhecida vira linear', () => {
    expect(itemFades({ extra: {} })).toEqual({})
    expect(itemFades({ extra: { fades: 'x' } })).toEqual({})
    expect(itemFades({ extra: { fades: { in: { duration: 0, curve: 'sine' }, out: { duration: 1, curve: 'zigzag' } } } })).toEqual({
      out: { duration: 1, curve: 'linear' },
    })
  })

  it('a velocidade do clipe vem do extra e o padrão é 1', () => {
    expect(itemSpeed({ extra: { speed: 2 } })).toBe(2)
    expect(itemSpeed({ extra: {} })).toBe(1)
  })
})

describe('a alça', () => {
  it('só os itens com som próprio têm alça, e o alvo é o caminho da cadeia dele na spec', () => {
    expect(fadeTarget('A1', { index: 2, kind: 'clip-audio' })).toBe('timeline.2')
    expect(fadeTarget('MUS', { index: 0, kind: 'music' })).toBe('audio.music')
    expect(fadeTarget('NAR', { index: 1, kind: 'narration' })).toBe('audio.narration.1')
    expect(fadeTarget('VO', { index: 3, kind: 'voiceover' })).toBe('audio.voiceover.3')
    expect(fadeTarget('A2', { index: 0, kind: 'track' })).toBeNull() // a faixa externa é uma janela de um arquivo longo
    expect(fadeTarget('V1', { index: 0, kind: 'clip' })).toBeNull()
  })

  it('o arrasto leva a duração até o ponteiro, sem passar do item, e perto da borda tira o fade', () => {
    expect(draggedFadeDuration(1.234, 4)).toBe(1.234)
    expect(draggedFadeDuration(9, 4)).toBe(4)
    expect(draggedFadeDuration(-1, 4)).toBe(0)
    expect(draggedFadeDuration(MIN_FADE_SECONDS / 2, 4)).toBe(0)
  })

  it('num clipe acelerado a duração é em segundos do item, não da tela', () => {
    expect(draggedFadeDuration(1, 4, 2)).toBe(2)
    expect(draggedFadeDuration(10, 4, 2)).toBe(8)
  })

  it('a operação mantém a curva quando o gesto não a menciona', () => {
    expect(fadeOperation('timeline.0', 'out', 1.2)).toEqual({ type: 'audio_fade', target: 'timeline.0', side: 'out', duration: 1.2 })
    expect(fadeOperation('timeline.0', 'in', 1, 'sine')).toEqual({ type: 'audio_fade', target: 'timeline.0', side: 'in', duration: 1, curve: 'sine' })
  })

  it('o polígono da curva fecha pelo canto de cima da borda do item', () => {
    const entering = fadeShadePoints('in', 'linear', 100, 100, 4).split(' ')
    expect(entering[0]).toBe('0.00,100.00')
    expect(entering[entering.length - 2]).toBe('100.00,0.00')
    expect(entering[entering.length - 1]).toBe('0,0')
    const leaving = fadeShadePoints('out', 'linear', 100, 100, 4).split(' ')
    expect(leaving[0]).toBe('0.00,0.00')
    expect(leaving[leaving.length - 1]).toBe('100.00,0')
  })
})
