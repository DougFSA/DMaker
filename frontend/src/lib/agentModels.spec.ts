import { describe, expect, it } from 'vitest'
import type { AgentModel } from '@/api'
import {
  cannotOperate,
  capabilityLabels,
  defaultEffortLabel,
  effortAfterModelChange,
  findModel,
  formatBytes,
  imageModels,
  memoryNotice,
  modelOptionLabel,
  needsMemoryConfirmation,
  readsImages,
  sameModel,
  sortModels,
  toolsNotice,
  usesTools,
} from './agentModels'

const GIB = 1024 ** 3

function model(overrides: Partial<AgentModel> = {}): AgentModel {
  return {
    name: 'gpt-oss:20b',
    size: Math.round(12.8 * GIB),
    family: 'gptoss',
    capabilities: ['tools', 'thinking'],
    context_length: 131072,
    effort_levels: [
      { value: 'low', label: 'Baixo' },
      { value: 'medium', label: 'Médio' },
      { value: 'high', label: 'Alto' },
    ],
    default_effort: 'medium',
    fit: 'fits',
    loaded: false,
    ...overrides,
  }
}

describe('modelos', () => {
  it('a tag :latest é opcional na hora de achar o modelo', () => {
    expect(sameModel('llama3', 'llama3:latest')).toBe(true)
    expect(sameModel('gpt-oss:20b', 'gpt-oss:latest')).toBe(false)
    expect(findModel([model(), model({ name: 'llama3:latest' })], 'llama3')?.name).toBe('llama3:latest')
    expect(findModel(undefined, 'x')).toBeUndefined()
  })

  it('o tamanho aparece em GB com vírgula, e o motor que não informa fica sem tamanho', () => {
    expect(formatBytes(Math.round(12.8 * GIB))).toBe('12,8 GB')
    expect(formatBytes(512 * 1024 * 1024)).toBe('512 MB')
    expect(formatBytes(null)).toBe('')
  })

  it('os selos seguem a ordem do servidor e pulam a capacidade que a tela não conhece', () => {
    expect(capabilityLabels(['vision', 'tools', 'thinking'])).toEqual(['Imagem', 'Ferramentas', 'Raciocínio'])
    expect(capabilityLabels(['tools', 'embedding'])).toEqual(['Ferramentas'])
    expect(capabilityLabels([])).toEqual([])
  })

  it('a opção do seletor diz o tamanho, se está carregado e se não cabe', () => {
    expect(modelOptionLabel(model())).toBe('gpt-oss:20b · 12,8 GB')
    expect(modelOptionLabel(model({ loaded: true }))).toBe('gpt-oss:20b · 12,8 GB · carregado')
    expect(modelOptionLabel(model({ name: 'qwen3:30b-a3b', size: Math.round(17.3 * GIB), fit: 'too_big' }))).toBe(
      'qwen3:30b-a3b · 17,3 GB · não cabe na memória',
    )
    expect(modelOptionLabel(model({ fit: 'tight' }))).toContain('memória apertada')
    expect(modelOptionLabel(model({ size: null }))).toBe('gpt-oss:20b')
  })
})

describe('ordem do seletor', () => {
  it('o padrão vem primeiro, o que não cabe por último, e o resto mantém a ordem do servidor', () => {
    const big = model({ name: 'qwen3:30b-a3b', fit: 'too_big' })
    const small = model({ name: 'llama3:8b' })
    const other = model({ name: 'mistral:7b' })

    expect(sortModels([big, small, model(), other], 'gpt-oss:20b').map((item) => item.name)).toEqual([
      'gpt-oss:20b',
      'llama3:8b',
      'mistral:7b',
      'qwen3:30b-a3b',
    ])
  })

  it('o padrão com ":latest" também sobe ao topo', () => {
    const names = sortModels([model({ name: 'a' }), model({ name: 'llama3:latest' })], 'llama3').map((item) => item.name)
    expect(names).toEqual(['llama3:latest', 'a'])
  })
})

describe('modelo sem ferramentas', () => {
  const gemma = model({ name: 'gemma3:4b', size: Math.round(3.1 * GIB), capabilities: ['vision'], effort_levels: [], default_effort: null })

  it('só o modelo de capacidades conhecidas e sem "tools" não usa ferramentas', () => {
    expect(usesTools(gemma)).toBe(false)
    expect(usesTools(model())).toBe(true)
    expect(usesTools(model({ capabilities: [] }))).toBe(true) // o motor openai não informa: nada muda
    expect(usesTools(undefined)).toBe(true)
  })

  it('não opera o DMaker, mas conversa livremente', () => {
    expect(cannotOperate(gemma, 'operate')).toBe(true)
    expect(cannotOperate(gemma, 'free')).toBe(false)
    expect(cannotOperate(model(), 'operate')).toBe(false)
  })

  it('a opção do seletor avisa "não opera o DMaker" só no modo Operar', () => {
    expect(modelOptionLabel(gemma, 'operate')).toBe('gemma3:4b · 3,1 GB · não opera o DMaker')
    expect(modelOptionLabel(gemma, 'free')).toBe('gemma3:4b · 3,1 GB')
    expect(modelOptionLabel(model(), 'operate')).toBe('gpt-oss:20b · 12,8 GB')
  })

  it('o aviso é o texto do servidor, e só aparece quando o modelo não serve ao modo', () => {
    expect(toolsNotice(gemma, 'operate')).toBe(
      'O modelo gemma3:4b não usa ferramentas. Para operar o DMaker, escolha um modelo com ferramentas; para conversar com ele, use a Conversa livre.',
    )
    expect(toolsNotice(gemma, 'free')).toBe('')
    expect(toolsNotice(model(), 'operate')).toBe('')
    expect(toolsNotice(undefined, 'operate')).toBe('')
  })
})

describe('aviso de memória', () => {
  const memory = { total: Math.round(15.7 * GIB), available: 2 * GIB }

  it('cabendo, não avisa nada', () => {
    expect(memoryNotice(model(), memory)).toBeNull()
    expect(memoryNotice(model({ fit: 'unknown' }), null)).toBeNull()
    expect(memoryNotice(undefined, memory)).toBeNull()
  })

  it('apertado é só um aviso e não pede confirmação', () => {
    const notice = memoryNotice(model({ fit: 'tight' }), memory)
    expect(notice?.tone).toBe('warning')
    expect(notice?.text).toContain('apertada')
    expect(needsMemoryConfirmation(model({ fit: 'tight' }))).toBe(false)
  })

  it('não cabe é erro, diz os dois tamanhos e pede confirmação antes de enviar', () => {
    const big = model({ name: 'qwen3:30b-a3b', size: Math.round(17.3 * GIB), fit: 'too_big' })
    const notice = memoryNotice(big, memory)
    expect(notice?.tone).toBe('error')
    expect(notice?.text).toContain('o modelo tem 17,3 GB')
    expect(notice?.text).toContain('o computador tem 15,7 GB de memória')
    expect(needsMemoryConfirmation(big)).toBe(true)
  })

  it('sem a leitura da memória, o aviso de "não cabe" ainda diz o tamanho do modelo', () => {
    const notice = memoryNotice(model({ fit: 'too_big' }), null)
    expect(notice?.text).toContain('o modelo tem 12,8 GB')
    expect(notice?.text).not.toContain('o computador tem')
  })
})

describe('esforço', () => {
  it('trocar de modelo mantém o esforço que o modelo novo tem e limpa o que não tem', () => {
    const switchOnly = model({
      name: 'qwen3:8b',
      effort_levels: [
        { value: 'off', label: 'Desligado' },
        { value: 'on', label: 'Ligado' },
      ],
    })
    expect(effortAfterModelChange('high', model())).toBe('high')
    expect(effortAfterModelChange('high', switchOnly)).toBeNull()
    expect(effortAfterModelChange('on', switchOnly)).toBe('on')
    expect(effortAfterModelChange('high', model({ effort_levels: [] }))).toBeNull()
  })

  it('sem esforço escolhido ou sem saber o modelo, nada muda', () => {
    expect(effortAfterModelChange(null, model())).toBeNull()
    expect(effortAfterModelChange('high', undefined)).toBe('high')
  })

  it('a opção "sem escolher" diz qual é o nível padrão do modelo', () => {
    expect(defaultEffortLabel(model())).toBe('Padrão do modelo (Médio)')
    expect(defaultEffortLabel(model({ default_effort: null }))).toBe('Padrão do modelo')
    expect(defaultEffortLabel(undefined)).toBe('Padrão do modelo')
  })
})

describe('imagem', () => {
  const seer = model({ name: 'gemma3:4b', capabilities: ['vision'] })

  it('o modelo de capacidades conhecidas lê imagem só com o selo de imagem', () => {
    expect(readsImages(seer)).toBe(true)
    expect(readsImages(model())).toBe(false)
  })

  it('capacidade desconhecida (motor compatível com a OpenAI) e modelo fora da lista contam como sim: o servidor recusa se for o caso', () => {
    expect(readsImages(model({ capabilities: [] }))).toBe(true)
    expect(readsImages(undefined)).toBe(true)
  })

  it('a lista dos modelos que leem imagem tem só os que têm o selo', () => {
    expect(imageModels([model(), seer, model({ capabilities: [] })]).map((item) => item.name)).toEqual(['gemma3:4b'])
  })
})
