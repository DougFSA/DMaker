import { describe, expect, it } from 'vitest'
import {
  CHART_MAX_HZ,
  CHART_MIN_HZ,
  MAX_CURVE_POINTS,
  addPoint,
  chartRange,
  curvePath,
  dbTicks,
  dbToY,
  formatFrequency,
  formatGain,
  hzToX,
  movePoint,
  removePoint,
  responseAt,
  xToHz,
  yToDb,
} from './eqChart'

describe('o eixo do gráfico', () => {
  it('leva o Hz à posição em oitavas e de volta', () => {
    expect(hzToX(CHART_MIN_HZ, 480)).toBe(0)
    expect(hzToX(CHART_MAX_HZ, 480)).toBe(480)
    // 20 Hz a 20 kHz são dez oitavas: 200 Hz fica na terça parte, 2 kHz nas duas
    expect(hzToX(200, 480)).toBeCloseTo(480 * (Math.log2(10) / Math.log2(1000)), 6)
    for (const hz of [20, 63, 440, 3150, 20000]) expect(xToHz(hzToX(hz, 480), 480)).toBeCloseTo(hz, 6)
  })

  it('prende o que está fora do eixo nas pontas', () => {
    expect(hzToX(5, 480)).toBe(0)
    expect(hzToX(40000, 480)).toBe(480)
    expect(xToHz(-10, 480)).toBeCloseTo(CHART_MIN_HZ, 9)
    expect(xToHz(900, 480)).toBeCloseTo(CHART_MAX_HZ, 6)
  })

  it('leva o dB à altura, com o máximo no alto, e de volta', () => {
    const range = { min: -24, max: 12 }
    expect(dbToY(12, range, 200)).toBe(0)
    expect(dbToY(-24, range, 200)).toBe(200)
    expect(yToDb(dbToY(-6, range, 200), range, 200)).toBeCloseTo(-6, 9)
    expect(dbToY(99, range, 200)).toBe(0)
    expect(yToDb(-50, range, 200)).toBe(12)
  })
})

describe('a faixa de dB e a grade', () => {
  it('mostra sempre o 0 dB e arredonda para fora de 6 em 6', () => {
    expect(chartRange(null)).toEqual({ min: -12, max: 6 })
    expect(chartRange({ hz: [100, 200], db: [-3, 7.5] })).toEqual({ min: -12, max: 12 })
    expect(chartRange({ hz: [100, 200], db: [-25, 2] })).toEqual({ min: -30, max: 6 })
  })

  it('um filtro fundo não puxa a faixa abaixo de -72 dB, e os pontos entram na conta', () => {
    expect(chartRange({ hz: [20, 40], db: [-200, -100] }).min).toBe(-72)
    expect(chartRange(null, [{ hz: 100, db: 18 }]).max).toBe(18)
  })

  it('a faixa pedida vence', () => {
    expect(chartRange({ hz: [1], db: [-90] }, [], { min: -48, max: 24 })).toEqual({ min: -48, max: 24 })
  })

  it('a grade anda de 6, 12 ou 24 em 24 dB conforme a faixa', () => {
    expect(dbTicks({ min: -12, max: 12 })).toEqual([-12, -6, 0, 6, 12])
    expect(dbTicks({ min: -48, max: 24 })).toEqual([-48, -36, -24, -12, 0, 12, 24])
    expect(dbTicks({ min: -72, max: 6 })).toEqual([-72, -48, -24, 0])
  })
})

describe('o traço da curva', () => {
  it('liga os pontos da resposta com M e L na posição do desenho', () => {
    const path = curvePath({ hz: [20, 20000], db: [0, -12] }, { min: -12, max: 12 }, { width: 100, height: 50 })
    expect(path).toBe('M0.0 25.0 L100.0 50.0')
    expect(curvePath(null, { min: -12, max: 12 }, { width: 100, height: 50 })).toBe('')
  })

  it('acha o ganho da frequência mais perto', () => {
    const curve = { hz: [20, 200, 2000], db: [-12, -6, 0] }
    expect(responseAt(curve, 180)).toBe(-6)
    expect(responseAt(curve, 1500)).toBe(0)
    expect(responseAt(null, 100)).toBeNull()
  })
})

const flat = [
  { hz: 20, db: 0 },
  { hz: 1000, db: 0 },
  { hz: 20000, db: 0 },
]

describe('os pontos do EQ por Curva', () => {
  it('move um ponto sem passar do vizinho e sem tocar nos outros', () => {
    const moved = movePoint(flat, 1, 5000, 6)
    expect(moved.map((point) => point.db)).toEqual([0, 6, 0])
    expect(moved[1]?.hz).toBe(5000)
    expect(moved[0]).toEqual(flat[0])
    const blocked = movePoint(flat, 1, 90000, 3)
    expect(blocked[1]?.hz).toBeLessThan(20000)
    expect(blocked[1]?.hz).toBeGreaterThan(19000)
    expect(movePoint(flat, 1, 1, 3)[1]?.hz).toBeGreaterThan(20)
    expect(flat[1]).toEqual({ hz: 1000, db: 0 }) // a lista de entrada nunca muda
  })

  it('limita o ganho a ±40 dB e arredonda para o que se lê', () => {
    expect(movePoint(flat, 1, 1234.5, 99)[1]).toEqual({ hz: 1230, db: 40 })
    expect(movePoint(flat, 1, 51.26, -2.26)[1]).toEqual({ hz: 51.3, db: -2.3 })
    expect(movePoint(flat, 1, 333.4, 1)[1]).toEqual({ hz: 333, db: 1 })
  })

  it('acrescenta um ponto no lugar da ordem e recusa o que se encavala', () => {
    const added = addPoint(flat, 200, 4)
    expect(added.map((point) => point.hz)).toEqual([20, 200, 1000, 20000])
    expect(added[1]?.db).toBe(4)
    expect(addPoint(flat, 1001, 4)).toHaveLength(3) // quase na mesma frequência de outro
    const full = Array.from({ length: MAX_CURVE_POINTS }, (_, index) => ({ hz: 20 * 1.15 ** index, db: 0 }))
    expect(addPoint(full, 5000, 1)).toHaveLength(MAX_CURVE_POINTS)
  })

  it('tira um ponto, mas guarda ao menos dois', () => {
    expect(removePoint(flat, 1).map((point) => point.hz)).toEqual([20, 20000])
    expect(removePoint(flat.slice(0, 2), 0)).toHaveLength(2)
    expect(removePoint(flat, 9)).toHaveLength(3)
  })
})

describe('os textos', () => {
  it('escreve a frequência e o ganho como a pessoa lê', () => {
    expect(formatFrequency(63)).toBe('63 Hz')
    expect(formatFrequency(3150)).toBe('3,15 kHz')
    expect(formatFrequency(20000)).toBe('20 kHz')
    expect(formatGain(6)).toBe('+6,0 dB')
    expect(formatGain(-3.5)).toBe('-3,5 dB')
    expect(formatGain(0)).toBe('+0,0 dB')
  })
})
