import { describe, expect, it } from 'vitest'
import { clockText, MAX_SCHEDULE_SECONDS, parseLocalDateTime, resolveSchedule } from './recordingSchedule'

const now = new Date(2026, 10, 4, 19, 0, 0)
const at = (hours: number, minutes: number) => new Date(2026, 10, 4, hours, minutes, 0)

describe('a gravação com hora marcada', () => {
  it('início e duração: espera até o início e grava pelo tempo pedido', () => {
    const result = resolveSchedule({ startAt: at(19, 30), durationSeconds: 3600 }, now)
    expect(result).toEqual({ ok: true, schedule: { waitMs: 30 * 60_000, durationSeconds: 3600 } })
  })

  it('início e fim: a duração é a diferença', () => {
    const result = resolveSchedule({ startAt: at(19, 30), endAt: at(21, 0) }, now)
    expect(result).toEqual({ ok: true, schedule: { waitMs: 30 * 60_000, durationSeconds: 5400 } })
  })

  it('só a duração começa agora', () => {
    expect(resolveSchedule({ durationSeconds: 120 }, now)).toEqual({
      ok: true,
      schedule: { waitMs: 0, durationSeconds: 120 },
    })
  })

  it('só o fim começa agora e para nele', () => {
    expect(resolveSchedule({ endAt: at(19, 10) }, now)).toEqual({
      ok: true,
      schedule: { waitMs: 0, durationSeconds: 600 },
    })
  })

  it('sem nada grava até a pessoa parar', () => {
    expect(resolveSchedule({}, now)).toEqual({ ok: true, schedule: { waitMs: 0, durationSeconds: null } })
  })

  it('o minuto do campo de data já em curso não é um início no passado', () => {
    const result = resolveSchedule({ startAt: at(19, 0), durationSeconds: 60 }, new Date(2026, 10, 4, 19, 0, 40))
    expect(result.ok).toBe(true)
  })

  it('recusa início que já passou, fim antes do início, duração zero, valores que não batem e mais de 24 horas', () => {
    expect(resolveSchedule({ startAt: at(18, 0) }, now)).toMatchObject({ ok: false })
    expect(resolveSchedule({ startAt: at(20, 0), endAt: at(19, 30) }, now)).toMatchObject({ ok: false })
    expect(resolveSchedule({ durationSeconds: 0 }, now)).toMatchObject({ ok: false })
    expect(resolveSchedule({ startAt: at(20, 0), endAt: at(21, 0), durationSeconds: 600 }, now)).toMatchObject({ ok: false })
    expect(resolveSchedule({ durationSeconds: MAX_SCHEDULE_SECONDS + 1 }, now)).toMatchObject({ ok: false })
  })
})

describe('o relógio e o campo de data', () => {
  it('mostra mm:ss, e h:mm:ss a partir de uma hora', () => {
    expect(clockText(0)).toBe('00:00')
    expect(clockText(75.9)).toBe('01:15')
    expect(clockText(3725)).toBe('1:02:05')
    expect(clockText(-3)).toBe('00:00')
  })

  it('lê o valor do datetime-local; vazio ou inválido vira nada', () => {
    expect(parseLocalDateTime('2026-11-04T19:30')?.getHours()).toBe(19)
    expect(parseLocalDateTime('')).toBeNull()
    expect(parseLocalDateTime('ontem')).toBeNull()
  })
})
