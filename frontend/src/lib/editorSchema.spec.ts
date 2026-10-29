import { describe, expect, it } from 'vitest'
import { fieldInfo, schemaDef } from './editorSchema'

/** Um pedaço do schema que o servidor devolve (Project.model_json_schema), com as formas que a spec usa. */
const schema = {
  $defs: {
    Output: {
      properties: {
        preset: { default: 'instagram/reels', type: 'string' },
        fps: { anyOf: [{ exclusiveMinimum: 0, maximum: 120, type: 'number' }, { type: 'null' }], default: null },
        encoder: { default: 'x264', enum: ['x264', 'auto', 'nvenc', 'amf', 'qsv'], type: 'string' },
        quality: { default: 'high', enum: ['max', 'high', 'medium', 'draft'], type: 'string' },
        guides: { default: false, type: 'boolean' },
      },
    },
    CardSegment: {
      properties: {
        variant: { anyOf: [{ enum: ['light', 'dark'], type: 'string' }, { type: 'null' }], default: null },
        motion_amount: { default: 0.04, maximum: 0.3, minimum: 0, type: 'number' },
      },
    },
    Transition: { properties: { curve: { $ref: '#/$defs/Curve' }, duration: { default: 0.5, maximum: 5, type: 'number' } } },
    Curve: { enum: ['linear', 'ease', 'spring'], type: 'string' },
    Reframe: { properties: { focus: { default: [0.5, 0.5], type: 'array' } } },
  },
}

describe('schemaDef', () => {
  it('acha a definição pelo nome', () => {
    expect(schemaDef(schema, 'Output')).toBe(schema.$defs.Output)
    expect(schemaDef(schema, 'Nao')).toBeNull()
    expect(schemaDef(null, 'Output')).toBeNull()
  })
})

describe('fieldInfo', () => {
  it('lê as opções de uma lista fechada, na ordem do schema', () => {
    expect(fieldInfo(schema, 'Output', 'quality')).toMatchObject({
      type: 'string',
      options: ['max', 'high', 'medium', 'draft'],
      default: 'high',
      nullable: false,
    })
    expect(fieldInfo(schema, 'Output', 'encoder')?.options).toEqual(['x264', 'auto', 'nvenc', 'amf', 'qsv'])
  })

  it('campo que aceita null é opcional e traz o tipo do outro lado', () => {
    expect(fieldInfo(schema, 'Output', 'fps')).toMatchObject({
      type: 'number',
      exclusiveMin: 0,
      max: 120,
      nullable: true,
    })
    expect(fieldInfo(schema, 'CardSegment', 'variant')).toMatchObject({
      options: ['light', 'dark'],
      nullable: true,
    })
  })

  it('lê os limites dos números', () => {
    expect(fieldInfo(schema, 'CardSegment', 'motion_amount')).toMatchObject({ min: 0, max: 0.3, default: 0.04 })
  })

  it('segue a referência para outra definição', () => {
    expect(fieldInfo(schema, 'Transition', 'curve')?.options).toEqual(['linear', 'ease', 'spring'])
  })

  it('texto livre não tem opções', () => {
    expect(fieldInfo(schema, 'Output', 'preset')).toMatchObject({ type: 'string', options: null })
  })

  it('devolve null quando o schema não conhece o campo', () => {
    expect(fieldInfo(schema, 'Output', 'nada')).toBeNull()
    expect(fieldInfo(schema, 'Nada', 'quality')).toBeNull()
    expect(fieldInfo(null, 'Output', 'quality')).toBeNull()
  })
})
