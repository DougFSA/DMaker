import { describe, expect, it } from 'vitest'
import { GPT_OSS } from '@/test/agentServer'
import {
  CONTEXT_WARNING,
  contextMax,
  contextProblem,
  expiryTime,
  hasOptions,
  loadedLabel,
  optionsFrom,
  sameOptions,
  seedProblem,
  temperatureProblem,
  valuesOf,
} from './agentAdvanced'

describe('contexto', () => {
  it('vai até o contexto máximo do modelo', () => {
    expect(contextMax(GPT_OSS)).toBe(131072)
    expect(contextMax({ ...GPT_OSS, context_length: null })).toBeNull()
    expect(contextMax(undefined)).toBeNull()
  })

  it('aceita o que está entre o mínimo do servidor e o máximo do modelo', () => {
    expect(contextProblem(512, GPT_OSS)).toBe('')
    expect(contextProblem(131072, GPT_OSS)).toBe('')
    expect(contextProblem(null, GPT_OSS)).toBe('')
  })

  it('recusa o que fica abaixo, acima ou não é inteiro, dizendo o limite', () => {
    expect(contextProblem(100, GPT_OSS)).toBe('O contexto mínimo é 512 tokens.')
    expect(contextProblem(200000, GPT_OSS)).toBe('Este modelo vai até 131.072 tokens.')
    expect(contextProblem(4096.5, GPT_OSS)).toBe('O contexto é um número inteiro de tokens.')
  })

  it('sem máximo conhecido não há teto', () => {
    expect(contextProblem(10_000_000, { ...GPT_OSS, context_length: null })).toBe('')
  })

  it('o aviso diz que mais contexto pede mais memória e que trocar recarrega o modelo, sem número fixo de máquina', () => {
    expect(CONTEXT_WARNING).toContain('mais memória')
    expect(CONTEXT_WARNING).toContain('recarregar')
    expect(CONTEXT_WARNING).toContain('alguns minutos')
    expect(CONTEXT_WARNING).not.toMatch(/\d/)
  })
})

describe('temperatura e semente', () => {
  it('a temperatura vai de 0 a 2', () => {
    expect(temperatureProblem(0)).toBe('')
    expect(temperatureProblem(2)).toBe('')
    expect(temperatureProblem(null)).toBe('')
    expect(temperatureProblem(2.1)).toBe('A temperatura vai de 0 a 2.')
    expect(temperatureProblem(-0.1)).toBe('A temperatura vai de 0 a 2.')
  })

  it('a semente é um número inteiro, e zero vale', () => {
    expect(seedProblem(0)).toBe('')
    expect(seedProblem(42)).toBe('')
    expect(seedProblem(null)).toBe('')
    expect(seedProblem(1.5)).toBe('A semente é um número inteiro.')
  })
})

describe('as opções da conversa', () => {
  it('guardam só o que tem valor, e o zero conta como valor', () => {
    expect(optionsFrom({ num_ctx: 8192, temperature: null, seed: null })).toEqual({ num_ctx: 8192 })
    expect(optionsFrom({ num_ctx: null, temperature: 0, seed: 0 })).toEqual({ temperature: 0, seed: 0 })
    expect(optionsFrom({ num_ctx: null, temperature: null, seed: null })).toEqual({})
  })

  it('o que o servidor devolve nulo volta como vazio', () => {
    expect(valuesOf({ num_ctx: null, seed: 7 })).toEqual({ num_ctx: null, temperature: null, seed: 7 })
  })

  it('sabem se há alguma opção e se duas são iguais', () => {
    expect(hasOptions({})).toBe(false)
    expect(hasOptions({ temperature: null })).toBe(false)
    expect(hasOptions({ seed: 0 })).toBe(true)
    expect(sameOptions({ num_ctx: 8192 }, { num_ctx: 8192, seed: null })).toBe(true)
    expect(sameOptions({ num_ctx: 8192 }, { num_ctx: 4096 })).toBe(false)
  })
})

describe('o modelo carregado', () => {
  it('diz o nome, quanta memória ocupa e o contexto com que foi carregado', () => {
    expect(loadedLabel({ name: 'gpt-oss:20b', size: Math.round(9.4 * 1024 ** 3), size_vram: 0, context_length: 16384, expires_at: null })).toBe(
      'gpt-oss:20b · 9,4 GB na memória · contexto 16.384',
    )
  })

  it('sem o contexto, só o nome e a memória', () => {
    expect(loadedLabel({ name: 'x', size: 1024 ** 3, size_vram: 0, context_length: null, expires_at: null })).toBe('x · 1 GB na memória')
  })

  it('a hora em que o modelo sai sozinho da memória, ou nada quando o servidor não disse', () => {
    expect(expiryTime(null)).toBe('')
    expect(expiryTime('isto não é uma data')).toBe('')
    expect(expiryTime('2026-10-30T15:35:00.000+00:00')).toMatch(/^\d{2}:\d{2}$/)
  })
})
