import { describe, expect, it } from 'vitest'
import {
  AUDIO_FIELDS,
  CAPTION_FIELDS,
  CARD_FIELDS,
  CLIP_FIELDS,
  IMAGE_FIELDS,
  IMAGE_OVERLAY_FIELDS,
  MUSIC_FIELDS,
  OUTPUT_FIELDS,
  PROGRESS_FIELDS,
  TEXT_OVERLAY_FIELDS,
  VIDEO_OVERLAY_FIELDS,
  labelKeyOf,
  numberLimits,
  propOf,
  selectChoices,
  type FieldDef,
} from './editorFields'
import { optionLabel, transitionItems } from './editorLabels'
import type { FieldInfo } from './editorSchema'

const info = (extra: Partial<FieldInfo>): FieldInfo => ({
  type: 'number',
  options: null,
  min: null,
  max: null,
  exclusiveMin: null,
  default: undefined,
  nullable: false,
  ...extra,
})

const field = (extra: Partial<FieldDef> = {}): FieldDef => ({
  key: 'speed',
  label: 'Velocidade',
  kind: 'number',
  def: 'ClipSegment',
  ...extra,
})

describe('listas de campos', () => {
  const all = [
    ...CLIP_FIELDS,
    ...IMAGE_FIELDS,
    ...CARD_FIELDS,
    ...TEXT_OVERLAY_FIELDS,
    ...IMAGE_OVERLAY_FIELDS,
    ...VIDEO_OVERLAY_FIELDS,
    ...PROGRESS_FIELDS,
    ...CAPTION_FIELDS,
    ...MUSIC_FIELDS,
    ...AUDIO_FIELDS,
    ...Object.values(OUTPUT_FIELDS),
  ]

  it('todo campo diz o rótulo e a definição do schema de onde vêm opções e limites', () => {
    for (const item of all) {
      expect(item.label, item.key).toBeTruthy()
      expect(item.def, item.key).toBeTruthy()
    }
  })

  it('nenhum rótulo usa travessão (regra da marca)', () => {
    for (const item of all) expect(item.label).not.toMatch(/[—–]/)
  })

  it('não repete a chave dentro de uma mesma lista', () => {
    for (const list of [CLIP_FIELDS, IMAGE_FIELDS, CARD_FIELDS, TEXT_OVERLAY_FIELDS, VIDEO_OVERLAY_FIELDS, CAPTION_FIELDS]) {
      const keys = list.map((item) => item.key)
      expect(new Set(keys).size).toBe(keys.length)
    }
  })
})

describe('propOf e labelKeyOf', () => {
  it('o campo do schema é o último trecho da chave, a não ser que o campo diga outro', () => {
    expect(propOf(field({ key: 'transition.type' }))).toBe('type')
    expect(propOf(field({ key: 'reframe.focus.0', prop: 'focus' }))).toBe('focus')
    expect(labelKeyOf(field({ key: 'mode', def: 'Reframe' }))).toBe('Reframe.mode')
  })
})

describe('numberLimits', () => {
  it('usa os limites do schema', () => {
    expect(numberLimits(field({ step: 0.1 }), info({ min: 0, max: 8 }))).toEqual({ step: 0.1, min: 0, max: 8 })
  })

  it('mínimo exclusivo vira o próprio passo, o menor valor que o servidor aceita', () => {
    expect(numberLimits(field({ step: 0.1 }), info({ exclusiveMin: 0 }))).toEqual({ step: 0.1, min: 0.1 })
    expect(numberLimits(field({ step: 0.01 }), info({ exclusiveMin: 0, max: 1 }))).toEqual({
      step: 0.01,
      min: 0.01,
      max: 1,
    })
  })

  it('o limite do campo vale quando o schema não dá nenhum', () => {
    expect(numberLimits(field({ min: 0, max: 1, step: 0.05 }), info({}))).toEqual({ step: 0.05, min: 0, max: 1 })
    expect(numberLimits(field({ min: 0 }), null)).toEqual({ step: 0.1, min: 0 })
  })

  it('sem nenhum limite, só o passo', () => {
    expect(numberLimits(field(), null)).toEqual({ step: 0.1 })
  })
})

describe('transitionItems', () => {
  it('põe o corte seco primeiro e depois as transições do catálogo, com rótulo quando há', () => {
    expect(transitionItems(['fade', 'wipeleft', 'crosszoom'])).toEqual([
      { value: 'cut', label: 'Corte seco' },
      { value: 'fade', label: 'Fade' },
      { value: 'wipeleft', label: 'Wipe esquerda' },
      { value: 'crosszoom', label: 'crosszoom' },
    ])
  })

  it('não repete o corte seco se o catálogo o traz', () => {
    expect(transitionItems(['fade', 'cut']).map((item) => item.value)).toEqual(['cut', 'fade'])
  })

  it('sem catálogo (a consulta falhou), usa as de sempre para o campo não ficar vazio', () => {
    const values = transitionItems([]).map((item) => item.value)
    expect(values[0]).toBe('cut')
    expect(values).toContain('dissolve')
    expect(values.length).toBeGreaterThan(10)
  })
})

describe('selectChoices', () => {
  const quality = field({ key: 'quality', def: 'Output', kind: 'select' })

  it('monta as opções do schema com o rótulo em português', () => {
    const items = selectChoices(quality, info({ type: 'string', options: ['max', 'draft'] }), 'max')
    expect(items).toEqual([
      { value: 'max', label: optionLabel('Output.quality', 'max') },
      { value: 'draft', label: 'Rascunho' },
    ])
  })

  it('valor que o schema ganhar e não tiver rótulo aparece com o próprio valor', () => {
    const items = selectChoices(quality, info({ type: 'string', options: ['high', 'ultra'] }), 'high')
    expect(items.at(-1)).toEqual({ value: 'ultra', label: 'ultra' })
  })

  it('o valor que a spec já tem entra mesmo se a lista não o conhece', () => {
    const items = selectChoices(quality, info({ type: 'string', options: ['high'] }), 'legado')
    expect(items.map((item) => item.value)).toEqual(['high', 'legado'])
  })

  it('opções de fora (o catálogo de transições) vencem o schema', () => {
    const items = selectChoices(quality, info({ options: ['high'] }), 'a', [{ value: 'a', label: 'A' }])
    expect(items).toEqual([{ value: 'a', label: 'A' }])
  })

  it('sem schema, usa a lista fixa do campo', () => {
    const model = field({ key: 'model', def: 'Captions', kind: 'select', values: ['tiny', 'small'] })
    expect(selectChoices(model, null, '').map((item) => item.value)).toEqual(['tiny', 'small'])
  })
})
