import { describe, expect, it } from 'vitest'
import {
  LIVE_FADE_S,
  LIVE_LEAD_S,
  liveStatusText,
  planLiveChunk,
  playingIndexAt,
  type LiveChunkPlan,
} from './livePreview'

describe('planLiveChunk', () => {
  it('encadeia cada fala logo depois da anterior mais a pausa do roteiro', () => {
    let cursor: number | null = null
    const plans: LiveChunkPlan[] = []
    for (const [duration, pause] of [
      [1.0, 0.35],
      [2.0, 0.7],
      [0.5, 0],
    ] as const) {
      const plan = planLiveChunk(cursor, 10, duration, pause)
      plans.push(plan)
      cursor = plan.nextCursor
    }
    // a primeira entra na folga de 60 ms; as outras seguem a fala anterior mais a pausa
    expect(plans.map((plan) => Number(plan.startAt.toFixed(6)))).toEqual([10.06, 11.41, 14.11])
    expect(plans.map((plan) => Number((plan.endAt - plan.startAt).toFixed(6)))).toEqual([1, 2, 0.5])
    expect(Number((plans[1]!.startAt - plans[0]!.endAt).toFixed(6))).toBe(0.35)
    expect(plans.map((plan) => plan.late)).toEqual([false, false, false])
  })

  it('a primeira fala usa a folga do relógio, nunca o instante exato de agora', () => {
    const plan = planLiveChunk(null, 3, 1, 0)
    expect(plan.startAt).toBeCloseTo(3 + LIVE_LEAD_S, 6)
    expect(plan.late).toBe(false)
  })

  it('marca a fala atrasada e nunca a agenda no passado', () => {
    const late = planLiveChunk(12, 20, 1, 0.35)
    expect(late.late).toBe(true)
    expect(late.startAt).toBeCloseTo(20.06, 6)
    const onTime = planLiveChunk(20.02, 20, 1, 0)
    expect(onTime.late).toBe(false)
    expect(onTime.startAt).toBeCloseTo(20.02, 6)
  })

  it('o fade é de 5 ms, mas nunca mais que a metade de uma fala curtíssima', () => {
    expect(planLiveChunk(null, 0, 1, 0).fade).toBe(LIVE_FADE_S)
    expect(planLiveChunk(null, 0, 0.004, 0).fade).toBe(0.002)
  })

  it('ignora uma pausa negativa ou ausente', () => {
    expect(planLiveChunk(null, 0, 1, -2).nextCursor).toBeCloseTo(LIVE_LEAD_S + 1, 6)
    expect(planLiveChunk(null, 0, 1, Number.NaN).nextCursor).toBeCloseTo(LIVE_LEAD_S + 1, 6)
  })
})

describe('playingIndexAt', () => {
  const plans = [
    { index: 1, nextCursor: 11.4 },
    { index: 2, nextCursor: 14 },
  ]

  it('diz qual fala toca no instante, contando a pausa depois dela', () => {
    expect([9, 10.5, 11.4, 13.9, 14].map((time) => playingIndexAt(plans, time))).toEqual([1, 1, 2, 2, null])
  })

  it('sem nada agendado não há fala tocando', () => {
    expect(playingIndexAt([], 3)).toBeNull()
  })
})

describe('liveStatusText', () => {
  it('acompanha o que toca e o que ainda está sendo gerado', () => {
    const text = (ready: number, playing: number | null, stoppedAfter: number | null = null) =>
      liveStatusText({ total: 5, ready, playing, stoppedAfter })
    expect(text(0, null)).toBe('Esperando a primeira fala ficar pronta...')
    expect(text(2, 1)).toBe('Tocando fala 1 de 5 · 2 prontas')
    expect(text(5, 4)).toBe('Tocando fala 4 de 5')
    expect(text(2, null)).toBe('Esperando a fala 3 de 5 ficar pronta...')
    expect(text(5, null)).toBe('Prévia ao vivo terminada.')
  })

  it('depois de parar, diz até onde foi e que o resto ficou guardado', () => {
    expect(liveStatusText({ total: 5, ready: 3, playing: 2, stoppedAfter: 3 })).toBe(
      'Parado depois da fala 3 de 5. O que já saiu ficou guardado.',
    )
  })

  it('parar antes da primeira fala não fala em "fala 0 de 0"', () => {
    expect(liveStatusText({ total: 0, ready: 0, playing: null, stoppedAfter: 0 })).toBe(
      'Parado antes de a primeira fala ficar pronta.',
    )
  })
})
