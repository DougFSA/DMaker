/* O schema que os testes do painel Filtros consultam: o mesmo formato do `GET /api/schema` (padrões aninhados, listas
   fechadas, campos obrigatórios sem padrão), só com os campos que os grupos do catálogo usam. */
import { editorSchema } from './editorFixtures'

type Node = Record<string, unknown>

const nullable = (node: Node): Node => ({ anyOf: [node, { type: 'null' }], default: null })
const number = (value: number, extra: Node = {}): Node => ({ default: value, type: 'number', ...extra })
const bool = (value: boolean): Node => ({ default: value, type: 'boolean' })
const ref = (name: string, value: unknown): Node => ({ $ref: `#/$defs/${name}`, default: value })

const REFRAME_DEFAULT = { mode: 'auto', focus: [0.5, 0.5], zoom: 1, margin: 0.05, radius: 0.018, variant: null }
const COLOR_DEFAULT = {
  brightness: 0,
  contrast: 1,
  saturation: 1,
  gamma: 1,
  sharpen: 0,
  denoise: false,
  vignette: false,
  lut: null,
}

const SEGMENT_COMMON: Node = {
  label: nullable({ type: 'string' }),
  transition: { anyOf: [{ $ref: '#/$defs/Transition' }, { type: 'null' }], default: null },
  fade_in: number(0, { minimum: 0 }),
  fade_out: number(0, { minimum: 0 }),
  reframe: ref('Reframe', REFRAME_DEFAULT),
  color: ref('ColorAdjust', COLOR_DEFAULT),
}

/** O schema completo o bastante para o painel Filtros: `editorSchema` com as definições dos grupos por cima. */
export function filterSchema(): Record<string, unknown> {
  const base = (editorSchema.$defs ?? {}) as Record<string, Node>
  const extend = (name: string, properties: Node): Node => ({
    ...(base[name] ?? {}),
    properties: { ...((base[name]?.properties as Node | undefined) ?? {}), ...properties },
  })
  return {
    ...editorSchema,
    $defs: {
      ...base,
      ClipSegment: extend('ClipSegment', {
        ...SEGMENT_COMMON,
        speed: number(1, { exclusiveMinimum: 0, maximum: 8 }),
        volume: number(1, { minimum: 0, maximum: 4 }),
        mute: bool(false),
      }),
      ImageSegment: extend('ImageSegment', { ...SEGMENT_COMMON, motion_amount: number(0.12, { minimum: 0, maximum: 0.6 }) }),
      CardSegment: extend('CardSegment', { ...SEGMENT_COMMON, subtitle: nullable({ type: 'string' }) }),
      Reframe: extend('Reframe', {
        zoom: number(1, { minimum: 1, maximum: 3 }),
        margin: number(0.05, { minimum: 0, maximum: 0.3 }),
        radius: number(0.018, { minimum: 0, maximum: 0.2 }),
        variant: { anyOf: [{ enum: ['light', 'dark'], type: 'string' }, { type: 'null' }], default: null },
      }),
      ColorAdjust: {
        properties: {
          brightness: number(0, { minimum: -1, maximum: 1 }),
          contrast: number(1, { minimum: 0, maximum: 3 }),
          saturation: number(1, { minimum: 0, maximum: 3 }),
          gamma: number(1, { minimum: 0.1, maximum: 10 }),
          sharpen: number(0, { minimum: 0, maximum: 2 }),
          denoise: bool(false),
          vignette: { anyOf: [{ type: 'boolean' }, { type: 'number' }], default: false },
          lut: nullable({ type: 'string' }),
        },
      },
      Transition: extend('Transition', { type: { default: 'fade', type: 'string' } }),
      TextOverlay: extend('TextOverlay', {
        text: { type: 'string' },
        secondary: nullable({ type: 'string' }),
        style: ref('TextStyle', { size: null, color: null, uppercase: null, align: null, box: null }),
      }),
      TextStyle: {
        properties: {
          size: nullable({ exclusiveMinimum: 0, type: 'number' }),
          color: nullable({ type: 'string' }),
          uppercase: nullable({ type: 'boolean' }),
          align: nullable({ enum: ['left', 'center', 'right'], type: 'string' }),
          box: nullable({ type: 'boolean' }),
        },
      },
      ImageOverlay: { properties: { src: { default: 'logo', type: 'string' }, width: number(0.22, { maximum: 1 }) } },
      AudioTrack: { properties: { source: { type: 'string' }, volume: number(1, { minimum: 0, maximum: 4 }) } },
      Music: extend('Music', { src: { type: 'string' }, fade_in: number(1, { minimum: 0 }), loop: bool(true) }),
      AudioSettings: extend('AudioSettings', { target_lufs: number(-14, { minimum: -30, maximum: -5 }) }),
    },
  }
}
