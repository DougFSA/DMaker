import { describe, expect, it } from 'vitest'
import {
  canDraw,
  clampView,
  columnExtent,
  extendSelection,
  fitProject,
  fitSelection,
  formatAxisTime,
  MIN_VIEW_SAMPLES,
  niceStep,
  normalizeSelection,
  panView,
  revealTime,
  sampleTicks,
  samplesPerPixel,
  showsSampleRuler,
  snapToSample,
  timeTicks,
  timeToX,
  xToTime,
  zoomAround,
} from './audioWave'

const RATE = 48000
const HOUR = 3600

describe('a janela de tempo', () => {
  it('não passa do áudio nem fica menor que algumas amostras', () => {
    expect(clampView({ start: -5, end: 10 }, 60, RATE)).toEqual({ start: 0, end: 15 })
    expect(clampView({ start: 55, end: 70 }, 60, RATE)).toEqual({ start: 45, end: 60 })
    const tiny = clampView({ start: 10, end: 10.0000001 }, 60, RATE)
    expect(tiny.end - tiny.start).toBeCloseTo(MIN_VIEW_SAMPLES / RATE, 9)
    expect(clampView({ start: 0, end: 500 }, 60, RATE)).toEqual({ start: 0, end: 60 })
  })

  it('aproxima mantendo no mesmo lugar da tela o instante âncora', () => {
    const view = { start: 100, end: 200 }
    const zoomed = zoomAround(view, 2, 125, 1000, RATE)
    expect(zoomed.end - zoomed.start).toBeCloseTo(50)
    // o instante 125 estava a 25% da tela e continua a 25%
    expect((125 - zoomed.start) / (zoomed.end - zoomed.start)).toBeCloseTo(0.25)
    const out = zoomAround(zoomed, 0.5, 125, 1000, RATE)
    expect(out.end - out.start).toBeCloseTo(100)
  })

  it('vai da hora inteira até a amostra em poucos passos e fica no limite', () => {
    let view = fitProject(HOUR)
    let steps = 0
    while (view.end - view.start > MIN_VIEW_SAMPLES / RATE + 1e-12 && steps < 40) {
      view = zoomAround(view, 2, 1800, HOUR, RATE)
      steps += 1
    }
    expect(steps).toBeLessThan(26)
    expect(view.end - view.start).toBeCloseTo(MIN_VIEW_SAMPLES / RATE, 9)
    expect(zoomAround(view, 2, 1800, HOUR, RATE).end - zoomAround(view, 2, 1800, HOUR, RATE).start).toBeCloseTo(MIN_VIEW_SAMPLES / RATE, 9)
  })

  it('anda sem mudar a largura e para nas pontas', () => {
    expect(panView({ start: 10, end: 20 }, 5, 100, RATE)).toEqual({ start: 15, end: 25 })
    expect(panView({ start: 10, end: 20 }, -50, 100, RATE)).toEqual({ start: 0, end: 10 })
    expect(panView({ start: 90, end: 100 }, 50, 100, RATE)).toEqual({ start: 90, end: 100 })
  })

  it('ajusta à seleção com uma folga e ao projeto inteiro', () => {
    expect(fitProject(30)).toEqual({ start: 0, end: 30 })
    const fitted = fitSelection({ start: 10, end: 20 }, 60, RATE)
    expect(fitted.start).toBeCloseTo(9.5)
    expect(fitted.end).toBeCloseTo(20.5)
    expect(fitSelection(null, 60, RATE)).toEqual({ start: 0, end: 60 })
  })

  it('só anda para mostrar o instante quando ele saiu da tela', () => {
    const view = { start: 10, end: 20 }
    expect(revealTime(view, 15, 100, RATE)).toBe(view)
    expect(revealTime(view, 25, 100, RATE)).toEqual({ start: 15, end: 25 })
    expect(revealTime(view, 5, 100, RATE)).toEqual({ start: 5, end: 15 })
  })

  it('converte segundo e pixel nos dois sentidos', () => {
    const view = { start: 10, end: 20 }
    expect(timeToX(15, view, 1000)).toBe(500)
    expect(xToTime(500, view, 1000)).toBe(15)
    expect(samplesPerPixel(view, 1000, RATE)).toBe(480)
  })

  it('só deixa desenhar quando cada amostra tem pelo menos 4 pixels', () => {
    const wide = { start: 0, end: 200 / RATE }
    expect(canDraw(wide, 1000, RATE)).toBe(true)
    expect(canDraw({ start: 0, end: 0.1 }, 1000, RATE)).toBe(false)
  })
})

describe('a seleção', () => {
  it('põe as pontas na ordem e dentro do áudio, e descarta o que não é um trecho', () => {
    expect(normalizeSelection(8, 3, 10, RATE)).toEqual({ start: 3, end: 8 })
    expect(normalizeSelection(-1, 14, 10, RATE)).toEqual({ start: 0, end: 10 })
    expect(normalizeSelection(5, 5, 10, RATE)).toBeNull()
  })

  it('estende movendo a ponta que está mais perto', () => {
    const selection = { start: 10, end: 20 }
    expect(extendSelection(selection, 15, 22, 100, RATE)).toEqual({ start: 10, end: 22 })
    expect(extendSelection(selection, 15, 8, 100, RATE)).toEqual({ start: 8, end: 20 })
    expect(extendSelection(null, 5, 9, 100, RATE)).toEqual({ start: 5, end: 9 })
  })

  it('arredonda o instante para a amostra mais perto', () => {
    expect(snapToSample(1.00002, RATE)).toBeCloseTo(48001 / RATE, 12)
    expect(snapToSample(1.000004, RATE)).toBe(1)
  })
})

describe('a régua', () => {
  it('escolhe passos de 1, 2 ou 5 com a distância mínima em pixels', () => {
    expect(niceStep(0.01, 90)).toBe(1)
    expect(niceStep(0.0123, 90)).toBe(2)
    expect(niceStep(0.04, 90)).toBe(5)
    expect(niceStep(0.0004, 90)).toBeCloseTo(0.05)
  })

  it('escreve o tempo em minutos e segundos, com decimais quando o passo é curto', () => {
    expect(formatAxisTime(65, 1)).toBe('1:05')
    expect(formatAxisTime(65.25, 0.05)).toBe('1:05,25')
    expect(formatAxisTime(0.5, 0.001)).toBe('0:00,500')
  })

  it('põe os marcos dentro da janela e na posição do pixel', () => {
    const ticks = timeTicks({ start: 0, end: 10 }, 1000, 90)
    expect(ticks.length).toBeGreaterThan(3)
    for (const tick of ticks) {
      expect(tick.time).toBeGreaterThanOrEqual(0)
      expect(tick.time).toBeLessThanOrEqual(10)
      expect(tick.x).toBeCloseTo(tick.time * 100)
    }
    expect(timeTicks({ start: 0, end: 0 }, 1000)).toEqual([])
  })

  it('mostra a régua de amostras só quando a janela é pequena, e os marcos caem em amostras inteiras', () => {
    expect(showsSampleRuler({ start: 0, end: 10 }, 1000, RATE)).toBe(false)
    const view = { start: 1, end: 1 + 400 / RATE }
    expect(showsSampleRuler(view, 1000, RATE)).toBe(true)
    const ticks = sampleTicks(view, 1000, RATE)
    expect(ticks.length).toBeGreaterThan(2)
    for (const tick of ticks) expect(Number.isInteger(Number(tick.label))).toBe(true)
  })
})

describe('as colunas', () => {
  it('desenham da altura do máximo à do mínimo, com o zero no meio', () => {
    expect(columnExtent(-127, 127, 100)).toEqual({ top: 0, bottom: 100 })
    expect(columnExtent(-64, 64, 100).top).toBeCloseTo(24.8, 1)
    const silent = columnExtent(0, 0, 100)
    expect(silent.bottom - silent.top).toBe(1)
  })
})
