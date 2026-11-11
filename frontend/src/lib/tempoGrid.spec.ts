import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TimelineTempo } from '@/api'
import { snapFadeSeconds } from './audioFades'
import {
  barAxisTicks,
  barRulerTicks,
  barTime,
  beatNumberAt,
  beatTime,
  gridBars,
  gridBeats,
  gridSnapPoints,
  loadRulerMode,
  MIN_GRID_SNAP_PX,
  nearestGridPoint,
  positionLabel,
  RULER_MODE_KEY,
  saveRulerMode,
  snapAxisToGrid,
} from './tempoGrid'
import { snapPoints, snapTime } from './timeline'
import { timelineView } from '@/test/editorFixtures'

const fourFour: TimelineTempo = { bpm: 120, time_signature: '4/4', beats_per_bar: 4, offset: 0, period: 0.5 }
const waltz: TimelineTempo = { bpm: 120, time_signature: '3/4', beats_per_bar: 3, offset: 0, period: 0.5 }

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('a grade (o espelho de domain/tempo_grid.py)', () => {
  it('os tempos e os compassos contam de 1 a partir do offset', () => {
    const tempo = { ...fourFour, offset: 1 }
    expect(beatTime(tempo, 1)).toBe(1)
    expect(beatTime(tempo, 5)).toBe(3)
    expect(barTime(tempo, 9)).toBe(17) // 1 + 8 compassos de 2 s
    expect(beatNumberAt(tempo, 3)).toBe(5)
  })

  it('o compasso 9 de um projeto de 120 BPM em 4/4 cai aos 16 s (o mesmo caso do teste do servidor)', () => {
    expect(barTime(fourFour, 9)).toBe(16)
    expect(beatTime(fourFour, 17)).toBe(8)
  })

  it('lista os instantes de uma janela', () => {
    expect(gridBeats(fourFour, 0, 2)).toEqual([0, 0.5, 1, 1.5, 2])
    expect(gridBars(fourFour, 0, 6)).toEqual([0, 2, 4, 6])
    expect(gridBeats({ ...fourFour, bpm: 60, period: 1, offset: 0.25 }, 1, 3)).toEqual([1.25, 2.25])
    expect(gridBeats({ ...fourFour, offset: 5 }, 0, 4)).toEqual([])
  })

  it('lê o instante como compasso.tempo', () => {
    expect(positionLabel(fourFour, 0)).toBe('1.1')
    expect(positionLabel(fourFour, 1.5)).toBe('1.4')
    expect(positionLabel(fourFour, 2)).toBe('2.1')
    expect(positionLabel(waltz, 1.5)).toBe('2.1')
    expect(positionLabel(fourFour, 16)).toBe('9.1')
  })

  it('o tempo mais perto, e antes do tempo 1 vale o próprio tempo 1', () => {
    expect(nearestGridPoint(fourFour, 3.12)).toBe(3)
    expect(nearestGridPoint(fourFour, 3.95, 'bar')).toBe(4)
    expect(nearestGridPoint({ ...fourFour, offset: 1 }, 0.2)).toBe(1)
  })
})

describe('o encaixe nos tempos (critério: um corte arrastado perto de um tempo cai exatamente nele)', () => {
  it('o ponto da grade atrai o que passa a até a tolerância e o devolve exato', () => {
    const tempo = { ...fourFour, offset: 0.1 }
    const points = gridBeats(tempo, 0, 10)
    expect(snapTime(3.12, points, 0.03)).toBe(3.1) // a 20 ms do tempo 7: cai nele, sem resto de ponto flutuante
    expect(snapTime(3.08, points, 0.03)).toBe(3.1)
    expect(snapTime(3.2, points, 0.03)).toBe(3.2) // longe de todo tempo: fica onde estava
  })

  it('os tempos entram no mesmo encaixe das bordas dos itens, sem um segundo mecanismo', () => {
    const view = timelineView() // dois trechos de 3 s: bordas em 0, 3 e 6
    const points = snapPoints(view, null, null, gridBeats(fourFour, 0, view.total))
    expect(points).toEqual([0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6])
    expect(snapPoints(view, null, null)).toEqual([0, 3, 6]) // sem andamento a lista é a de antes
  })

  it('com o zoom afastado a grade usa os compassos, e mais afastado ainda não atrai', () => {
    expect(gridSnapPoints(fourFour, 4, 60)).toEqual(gridBeats(fourFour, 0, 4)) // 30 px por tempo
    expect(gridSnapPoints(fourFour, 8, 20)).toEqual([0, 2, 4, 6, 8]) // 10 px por tempo, 40 px por compasso
    expect(gridSnapPoints(fourFour, 8, 8)).toEqual([]) // 16 px por compasso: nada
    expect(MIN_GRID_SNAP_PX).toBeGreaterThanOrEqual(16)
  })

  it('a ponta do fade cai exatamente no tempo mais perto', () => {
    const points = gridBeats(fourFour, 0, 10)
    // o fade de entrada de um item que começa em 1 s: o ponteiro está a 1,02 s da borda, perto do tempo 5 (2 s)
    expect(snapFadeSeconds('in', 1, 1.02, points, 0.1)).toBe(1) // a ponta cai em 2,0
    // o fade de saída de um item que termina em 6 s: o ponteiro a 1,48 s, a ponta em 4,52 s, perto de 4,5 s
    expect(snapFadeSeconds('out', 6, 1.48, points, 0.1)).toBe(1.5)
    expect(snapFadeSeconds('in', 1, 1.2, points, 0.05)).toBeCloseTo(1.2, 9) // longe de todo tempo
    expect(snapFadeSeconds('in', 1, 1.02, points, 0)).toBe(1.02) // encaixe desligado
  })
})

describe('a régua em compassos', () => {
  it('escreve o número do compasso no início dele e compasso.tempo nos tempos, quando cabem', () => {
    const ticks = barRulerTicks(fourFour, 0, 4, 120) // 60 px por tempo
    expect(ticks.slice(0, 5)).toEqual([
      { time: 0, label: '1', strong: true },
      { time: 0.5, label: '1.2', strong: false },
      { time: 1, label: '1.3', strong: false },
      { time: 1.5, label: '1.4', strong: false },
      { time: 2, label: '2', strong: true },
    ])
  })

  it('com o zoom afastado só os compassos, de tantos em tantos quantos os números precisarem', () => {
    const ticks = barRulerTicks(fourFour, 0, 40, 10) // 20 px por compasso: de 3 em 3
    expect(ticks.every((tick) => tick.strong)).toBe(true)
    expect(ticks.map((tick) => tick.label).slice(0, 4)).toEqual(['1', '4', '7', '10'])
  })

  it('no painel Áudio a janela vai ao tempo do projeto pelo relógio do item e as marcas voltam ao eixo', () => {
    // o item começa em 2 s da linha do tempo e o eixo dele em 0: o compasso 2 (2 s) cai no eixo em 0
    const clock = { start: 2, speed: 1, origin: 0 }
    const ticks = barAxisTicks({ start: 0, end: 4 }, 400, fourFour, clock)
    expect(ticks[0]).toMatchObject({ time: 0, label: '2', major: true, x: 0 })
    expect(ticks.find((tick) => tick.label === '3')).toMatchObject({ time: 2, x: 200 })
  })

  it('o encaixe do painel Áudio usa o mesmo relógio e a mesma tolerância em pixels', () => {
    const clock = { start: 2, speed: 1, origin: 0 }
    // 0,01 s por pixel: a tolerância de 8 px é 0,08 s; o tempo em 2 s do projeto cai no eixo em 0 s
    expect(snapAxisToGrid(0.04, clock, fourFour, 0.01)).toBe(0)
    expect(snapAxisToGrid(0.2, clock, fourFour, 0.01)).toBe(0.2)
    // com o zoom afastado (os tempos a menos de 24 px) não atrai
    expect(snapAxisToGrid(0.04, clock, fourFour, 0.1)).toBe(0.04)
  })
})

describe('a escolha da régua', () => {
  it('é lembrada no navegador, e sem armazenamento vale a de segundos', () => {
    expect(loadRulerMode()).toBe('seconds')
    saveRulerMode('bars')
    expect(window.localStorage.getItem(RULER_MODE_KEY)).toBe('bars')
    expect(loadRulerMode()).toBe('bars')
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('bloqueado')
      },
      setItem: () => {
        throw new Error('bloqueado')
      },
    })
    expect(loadRulerMode()).toBe('seconds')
    expect(() => saveRulerMode('bars')).not.toThrow()
  })
})
