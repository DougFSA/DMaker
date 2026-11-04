import { describe, expect, it } from 'vitest'
import { multiToolAt } from './audioTools'

describe('a multiferramenta', () => {
  it('mexe no envelope quando o ponteiro está sobre ele, mesmo no zoom de amostra', () => {
    expect(multiToolAt({ canDraw: false, overEnvelope: true })).toBe('envelope')
    expect(multiToolAt({ canDraw: true, overEnvelope: true })).toBe('envelope')
  })

  it('desenha no zoom máximo e seleciona nos outros lugares', () => {
    expect(multiToolAt({ canDraw: true, overEnvelope: false })).toBe('draw')
    expect(multiToolAt({ canDraw: false, overEnvelope: false })).toBe('select')
  })
})
