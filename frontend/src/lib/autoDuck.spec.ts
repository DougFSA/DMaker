import { describe, expect, it } from 'vitest'
import { addRuleIn, clampDuck, duckValue, isDuckTrack, isExternalTrack, keyOptions, removeRuleIn, rulesFor } from './autoDuck'

const TRACKS = ['A1', 'A2', 'A3', 'MUS', 'NAR', 'VO']

describe('trilhas do Auto Duck', () => {
  it('separa a faixa externa do som dos clipes', () => {
    expect(isExternalTrack('A1')).toBe(false)
    expect(isExternalTrack('A2')).toBe(true)
    expect(isExternalTrack('A12')).toBe(true)
    expect(isExternalTrack('MUS')).toBe(false)
  })

  it('só aceita como fundo as trilhas de áudio da linha do tempo', () => {
    expect(['A1', 'A3', 'MUS', 'NAR', 'VO'].every(isDuckTrack)).toBe(true)
    expect(['V1', 'CC', 'MK', 'TX'].some(isDuckTrack)).toBe(false)
  })

  it('oferece como chave só as combinações que o servidor aceita', () => {
    // a faixa externa abaixa sob a câmera, outra faixa externa, a música e as vozes
    expect(keyOptions('A2', TRACKS)).toEqual(['A1', 'A3', 'MUS', 'NAR', 'VO'])
    // o A1 já contém as faixas externas
    expect(keyOptions('A1', TRACKS)).toEqual(['MUS', 'NAR', 'VO'])
    expect(keyOptions('MUS', TRACKS)).toEqual(['A1', 'A2', 'A3', 'NAR', 'VO'])
    expect(keyOptions('A2', ['A1', 'A2'])).toEqual(['A1'])
    expect(keyOptions('A2', ['A2'])).toEqual([])
  })
})

describe('regras na spec', () => {
  it('acrescenta com os padrões do servidor e acha as regras de uma trilha', () => {
    const spec: Record<string, unknown> = { audio: {} }
    expect(addRuleIn(spec, 'MUS', 'VO')).toBe(0)
    expect(addRuleIn(spec, 'A2', 'A3')).toBe(1)
    expect((spec.audio as { ducks: unknown[] }).ducks).toEqual([
      { background: 'MUS', key: 'VO' },
      { background: 'A2', key: 'A3' },
    ])
    expect(rulesFor(spec, 'A2').map((found) => found.index)).toEqual([1])
    expect(rulesFor(spec, 'NAR')).toEqual([])
  })

  it('apagar a última regra tira a chave da spec', () => {
    const spec: Record<string, unknown> = { audio: {} }
    addRuleIn(spec, 'MUS', 'VO')
    expect(removeRuleIn(spec, 0)).toBe(true)
    expect(spec.audio).toEqual({})
    expect(removeRuleIn(spec, 0)).toBe(false)
  })

  it('mostra o padrão do Audacity e limita o número à faixa', () => {
    expect(duckValue({ background: 'MUS', key: 'VO' }, 'amount_db')).toBe(-12)
    expect(duckValue({ background: 'MUS', key: 'VO', amount_db: -20 }, 'amount_db')).toBe(-20)
    expect(duckValue({ background: 'MUS', key: 'VO' }, 'outer_fade_up')).toBe(0.5)
    expect(clampDuck('amount_db', 5)).toBe(0)
    expect(clampDuck('threshold_db', -500)).toBe(-100)
  })
})
