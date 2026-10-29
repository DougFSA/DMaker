import { describe, expect, it } from 'vitest'
import {
  canAddPronunciation,
  pronunciationKey,
  pronunciationPreviewText,
  pronunciationRequest,
  scopeLabel,
} from './pronunciation'

describe('pronunciationPreviewText', () => {
  it('diz o termo duas vezes, no idioma dele', () => {
    expect(pronunciationPreviewText(' DMaker ', 'pt')).toBe('Eu falo DMaker. Repito: DMaker.')
    expect(pronunciationPreviewText('DMaker', 'en')).toBe('I say DMaker. Again: DMaker.')
    expect(pronunciationPreviewText('DMaker', 'en-US')).toBe('I say DMaker. Again: DMaker.')
  })

  it('sem idioma ou com um que não tem frase própria, fala português', () => {
    expect(pronunciationPreviewText('DMaker', '')).toBe('Eu falo DMaker. Repito: DMaker.')
    expect(pronunciationPreviewText('DMaker', 'fr')).toBe('Eu falo DMaker. Repito: DMaker.')
  })
})

describe('pronunciationKey', () => {
  it('separa o mesmo termo em idiomas diferentes', () => {
    expect(pronunciationKey('API', 'pt')).not.toBe(pronunciationKey('API', 'en'))
  })
})

describe('scopeLabel', () => {
  const brands = [{ value: 'medlycare', label: 'MedlyCare' }]

  it('o termo global vale para todas as marcas', () => {
    expect(scopeLabel('global', brands)).toBe('Todas as marcas')
  })

  it('o termo de marca mostra o nome dela, ou a chave se a marca sumiu', () => {
    expect(scopeLabel('medlycare', brands)).toBe('MedlyCare')
    expect(scopeLabel('antiga', brands)).toBe('antiga')
  })
})

describe('adicionar', () => {
  it('exige o termo e como falá-lo', () => {
    expect(canAddPronunciation({ term: 'DMaker', spoken: '' })).toBe(false)
    expect(canAddPronunciation({ term: '  ', spoken: 'Di-mêiker' })).toBe(false)
    expect(canAddPronunciation({ term: 'DMaker', spoken: 'Di-mêiker' })).toBe(true)
  })

  it('o pedido tira os espaços das pontas e usa o dicionário global sem marca', () => {
    expect(pronunciationRequest({ term: ' DMaker ', spoken: ' Di-mêiker ', brand: '', language: 'pt' })).toEqual({
      term: 'DMaker',
      spoken: 'Di-mêiker',
      brand: null,
      language: 'pt',
    })
    expect(pronunciationRequest({ term: 'API', spoken: 'ei-pi-ai', brand: 'medlycare', language: '' })).toEqual({
      term: 'API',
      spoken: 'ei-pi-ai',
      brand: 'medlycare',
      language: 'pt',
    })
  })
})
