import { describe, expect, it } from 'vitest'
import { AB_PADDING_S, abWindow } from './ab'

describe('abWindow', () => {
  it('abre uma folga de 1,5 s de cada lado da região trocada', () => {
    const range = abWindow([21.4, 23.4])
    expect(AB_PADDING_S).toBe(1.5)
    expect(range.start).toBeCloseTo(19.9)
    expect(range.end).toBeCloseTo(24.9)
  })

  it('nunca começa antes de zero', () => {
    expect(abWindow([0.5, 2], 1)).toEqual({ start: 0, end: 3 })
    expect(abWindow([0, 1]).start).toBe(0)
  })

  it('aceita outra folga', () => {
    expect(abWindow([10, 12], 0)).toEqual({ start: 10, end: 12 })
  })
})
