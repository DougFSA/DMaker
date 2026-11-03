import { describe, expect, it } from 'vitest'
import { CAPTION_MODEL_VALUES } from './editorLabels'
import { FILTER_CATALOG, FILTER_TARGETS, groupsFor, parseFilterCatalog, type FilterTarget } from './filterCatalog'

const ITEM_TARGETS: FilterTarget[] = [
  'clip',
  'image',
  'card',
  'video',
  'text',
  'image-overlay',
  'progress-bar',
  'track',
  'music',
  'captions',
]

describe('catálogo de filtros', () => {
  it('traz os 38 grupos da interface clássica, cada um com id próprio e ao menos um campo', () => {
    expect(FILTER_CATALOG).toHaveLength(38)
    expect(new Set(FILTER_CATALOG.map((group) => group.id)).size).toBe(38)
    for (const group of FILTER_CATALOG) expect(group.fields.length, group.id).toBeGreaterThan(0)
  })

  it('todo tipo de item tem ao menos um grupo, e todo grupo vale para tipos que existem', () => {
    for (const target of ITEM_TARGETS) expect(groupsFor(target).length, target).toBeGreaterThan(0)
    for (const group of FILTER_CATALOG) {
      for (const target of group.applies) expect(FILTER_TARGETS[target], `${group.id}/${target}`).toBeDefined()
    }
  })

  it('os grupos de cada tipo saem na ordem do catálogo', () => {
    expect(groupsFor('clip').map((group) => group.id)).toEqual([
      'reframe',
      'color',
      'speed',
      'clip-audio',
      'fade',
      'transition',
      'label',
    ])
    expect(groupsFor('card').map((group) => group.id)).toEqual([
      'fade',
      'transition',
      'label',
      'motion-card',
      'duration-card',
      'card-text',
      'card-style',
    ])
    expect(groupsFor('video')).toHaveLength(7)
  })

  it('os grupos do projeto têm caminho fixo e a definição dos padrões', () => {
    const project = groupsFor('project')
    expect(project.map((group) => [group.id, group.base, group.defaultsDef])).toEqual([
      ['project-output', 'output', 'Output'],
      ['project-audio', 'audio', 'AudioSettings'],
    ])
    for (const group of FILTER_CATALOG.filter((candidate) => !candidate.applies.includes('project'))) {
      expect(group.base, group.id).toBeUndefined()
    }
  })

  it('cada campo herda do grupo a definição do schema de onde saem opções e limites', () => {
    const reframe = FILTER_CATALOG.find((group) => group.id === 'reframe')
    expect(reframe?.fields.every((field) => field.def === 'Reframe')).toBe(true)
    const fade = FILTER_CATALOG.find((group) => group.id === 'fade')
    expect(fade?.fields.map((field) => [field.key, field.def])).toEqual([
      ['fade_in', 'ClipSegment'],
      ['fade_out', 'ClipSegment'],
    ])
  })

  it('a lista dos modelos de legenda é a mesma da aba Propriedades', () => {
    const captions = FILTER_CATALOG.find((group) => group.id === 'captions-main')
    expect(captions?.fields.find((field) => field.key === 'model')?.values).toEqual(CAPTION_MODEL_VALUES)
  })

  it('listas do servidor fora do schema são marcadas: as transições e os formatos', () => {
    const marked = FILTER_CATALOG.flatMap((group) => group.fields.filter((field) => field.choicesFrom).map((field) => `${group.id}/${field.key}:${field.choicesFrom}`))
    expect(marked).toEqual(['transition/transition.type:transitions', 'project-output/preset:presets'])
  })

  it('o foco do reenquadramento aponta para a propriedade da lista, não para o índice', () => {
    const reframe = FILTER_CATALOG.find((group) => group.id === 'reframe')
    const focus = reframe?.fields.filter((field) => field.key.startsWith('reframe.focus'))
    expect(focus?.map((field) => [field.key, field.prop])).toEqual([
      ['reframe.focus.0', 'focus'],
      ['reframe.focus.1', 'focus'],
    ])
  })

  it('um campo com tipo desconhecido derruba a leitura, em vez de sumir da tela', () => {
    const broken = { groups: [{ id: 'g', label: 'G', applies: ['clip' as const], def: 'ClipSegment', fields: [{ kind: 'slider', key: 'x', label: 'X' }] }] }
    expect(() => parseFilterCatalog(broken)).toThrow(/g\/x/)
  })

  it('os textos de tela não usam travessão (regra da marca)', () => {
    const texts = [
      ...Object.values(FILTER_TARGETS).map((target) => target.title),
      ...FILTER_CATALOG.flatMap((group) => [group.label, ...group.fields.flatMap((field) => [field.label, field.emptyLabel ?? '', field.placeholder ?? ''])]),
    ]
    for (const text of texts) expect(text).not.toMatch(/[—–]/)
  })
})
