import { describe, expect, it } from 'vitest'
import type { InfographicInfo } from '@/api'
import {
  fieldProblem,
  filterInfographics,
  formProblems,
  initialValues,
  parseNumber,
  requestParams,
  specSnippet,
} from './infographics'

const COUNTER: InfographicInfo = {
  name: 'contador',
  title: 'Contador',
  description: 'Um número que conta de um valor até outro.',
  size: [900, 300],
  area: { x: 0.5, y: 0.26, width: 0.83, height: 0.16 },
  duration: 4,
  example: { ate: 10000, prefixo: '+ de R$' },
  anchors_to_caption: false,
  params: [
    { name: 'de', type: 'number', label: 'Começa em', required: false, default: 0, min: -1000, max: 1000 },
    { name: 'ate', type: 'number', label: 'Termina em', required: true, min: -1000000, max: 1000000 },
    { name: 'prefixo', type: 'text', label: 'Antes do número', required: false, default: '', max_length: 5 },
    { name: 'casas', type: 'integer', label: 'Casas decimais', required: false, default: 0, min: 0, max: 4 },
    { name: 'sombra', type: 'bool', label: 'Sombra suave', required: false, default: true },
  ],
}

describe('infográficos: o formulário a partir do esquema', () => {
  it('abre com o exemplo do modelo e, no resto, o padrão do esquema', () => {
    expect(initialValues(COUNTER)).toEqual({ de: 0, ate: 10000, prefixo: '+ de R$', casas: 0, sombra: true })
  })

  it('lê o número digitado à brasileira e descarta o que não é número', () => {
    expect(parseNumber('10000', false)).toBe(10000)
    expect(parseNumber(' 95,5 ', false)).toBe(95.5)
    expect(parseNumber('2,6', true)).toBe(3)
    expect(parseNumber('', false)).toBeUndefined()
    expect(parseNumber('dez mil', false)).toBeUndefined()
  })

  it('monta o pedido só com os campos que têm valor, cada um no seu tipo', () => {
    expect(requestParams(COUNTER, { de: '0', ate: '10000', prefixo: '', casas: '1', sombra: false })).toEqual({
      de: 0,
      ate: 10000,
      casas: 1,
      sombra: false,
    })
    // um número ilegível não vai no pedido: o formulário já o aponta como problema
    expect(requestParams(COUNTER, { ate: 'dez mil' })).toEqual({})
  })

  it('aponta cada valor fora do esquema com o rótulo do campo, como o servidor faz', () => {
    const ate = COUNTER.params[1]!
    expect(fieldProblem(ate, undefined)).toBe('Termina em: preencha este campo.')
    expect(fieldProblem(ate, 'dez mil')).toBe('Termina em: precisa ser um número.')
    expect(fieldProblem(ate, '2000000')).toBe('Termina em: não pode passar de 1000000.')
    expect(fieldProblem(ate, '10000')).toBeNull()
    expect(fieldProblem(COUNTER.params[3]!, '1,5')).toBe('Casas decimais: precisa ser um número inteiro.')
    expect(fieldProblem(COUNTER.params[2]!, '123456')).toBe('Antes do número: no máximo 5 caracteres.')
    expect(formProblems(COUNTER, { ate: 'x', de: '5000' })).toEqual({
      ate: 'Termina em: precisa ser um número.',
      de: 'Começa em: não pode passar de 1000.',
    })
  })

  it('dá o trecho de spec com o modelo e só os valores que diferem do padrão', () => {
    const snippet = JSON.parse(specSnippet(COUNTER, { de: 0, ate: 10000, prefixo: '+ de R$', sombra: true }))
    expect(snippet).toEqual({
      type: 'html',
      infographic: 'contador',
      region: 'topo',
      start: 0,
      end: 4,
      data: { ate: 10000, prefixo: '+ de R$' },
    })
  })

  it('filtra por nome, título ou descrição sem diferenciar maiúsculas', () => {
    const bar: InfographicInfo = { ...COUNTER, name: 'barra', title: 'Barra', description: 'Enche até um valor.' }
    expect(filterInfographics([COUNTER, bar], 'BARRA').map((item) => item.name)).toEqual(['barra'])
    expect(filterInfographics([COUNTER, bar], 'conta').map((item) => item.name)).toEqual(['contador'])
    expect(filterInfographics([COUNTER, bar], '')).toHaveLength(2)
    expect(filterInfographics([COUNTER, bar], 'zzz')).toEqual([])
  })
})
