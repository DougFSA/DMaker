/* O que cada formulário da aba Propriedades mostra: uma lista de campos por tipo de trecho, sobreposição e seção.
   É só dado. Opções e limites de cada campo vêm do schema (`editorSchema.ts`), pela definição e propriedade que o campo
   aponta; aqui ficam o rótulo, o passo das setas e o que é opcional. O componente `SpecField` lê estas listas. */
import { CAPTION_MODEL_VALUES, optionItems, optionLabel, type OptionItem } from './editorLabels'
import type { FieldInfo } from './editorSchema'

export type FieldKind = 'text' | 'number' | 'select' | 'check' | 'file'

export interface FieldDef {
  /** Caminho dentro do item da spec: "start", "transition.type", "reframe.focus.0". */
  key: string
  label: string
  kind: FieldKind
  /** A definição do schema (`$defs`) de onde vêm as opções e os limites: "ClipSegment", "Transition"... */
  def: string
  /** O campo dentro dela; padrão: o último trecho de `key`. */
  prop?: string
  /** Passo das setas do campo numérico. */
  step?: number
  /** Limites do campo quando o schema não os dá (os do schema valem primeiro). */
  min?: number
  max?: number
  /** Vazio quer dizer "usar o padrão do servidor": o campo some da spec em vez de ficar com zero. */
  optional?: boolean
  placeholder?: string
  hint?: string
  /** Texto da opção vazia de uma lista que aceita "nenhuma" ("Automática", "Padrão do tema"). */
  emptyLabel?: string
  /** O que mostrar quando a spec não tem o campo e o schema não diz o padrão. */
  fallback?: string | number | boolean
  /** Valores da lista quando o schema não os traz (campo de texto livre no servidor). */
  values?: string[]
  /** O que o navegador de arquivos mostra para este campo. */
  media?: 'video' | 'image' | 'audio'
  /** Lista que o servidor mantém fora do schema (as transições do catálogo, os formatos): quem desenha o campo a traz. */
  choicesFrom?: 'transitions' | 'presets'
}

type Extra = Partial<Omit<FieldDef, 'key' | 'label' | 'kind' | 'def'>>

const num = (def: string, key: string, label: string, extra: Extra = {}): FieldDef => ({
  key,
  label,
  kind: 'number',
  def,
  step: 0.1,
  ...extra,
})
const text = (def: string, key: string, label: string, extra: Extra = {}): FieldDef => ({
  key,
  label,
  kind: 'text',
  def,
  ...extra,
})
const select = (def: string, key: string, label: string, extra: Extra = {}): FieldDef => ({
  key,
  label,
  kind: 'select',
  def,
  ...extra,
})
const check = (def: string, key: string, label: string, extra: Extra = {}): FieldDef => ({
  key,
  label,
  kind: 'check',
  def,
  ...extra,
})
const file = (def: string, key: string, label: string, media: FieldDef['media'], extra: Extra = {}): FieldDef => ({
  key,
  label,
  kind: 'file',
  def,
  media,
  ...extra,
})

/* ---------- saída ---------- */

/** O formato e a marca: as opções vêm do servidor (`/api/state`), não do schema, então entram como `choices`. */
export const PRESET_FIELD: FieldDef = select('Output', 'preset', 'Formato')
export const BRAND_FIELD: FieldDef = select('Project', 'brand', 'Marca', { emptyLabel: 'Nenhuma' })

export const OUTPUT_FIELDS = {
  quality: select('Output', 'quality', 'Qualidade'),
  encoder: select('Output', 'encoder', 'Encoder'),
  fps: num('Output', 'fps', 'FPS (opcional)', { step: 1, optional: true, placeholder: 'do formato' }),
  guides: check('Output', 'guides', 'Mostrar guias de zona segura'),
}

/* ---------- fontes sincronizadas ---------- */

/** A fonte principal é o relógio da sessão; as opções são os nomes das fontes. */
export const MASTER_FIELD: FieldDef = select('Project', 'master', 'Fonte principal (relógio)')

export const SOURCE_FIELDS: FieldDef[] = [
  num('SourceRef', 'audio_stream', 'Faixa de áudio', { step: 1 }),
  text('SourceRef', 'label', 'Rótulo (opcional)', { optional: true }),
]

/** O deslocamento só existe no modo manual (no automático o valor da spec é a palavra "auto"). */
export const SOURCE_OFFSET_FIELD: FieldDef = num('SourceRef', 'sync', 'Deslocamento (s)', { step: 0.01, fallback: 0 })

/* ---------- trechos ---------- */

export const CLIP_FIELDS: FieldDef[] = [
  num('ClipSegment', 'start', 'Início (s)'),
  num('ClipSegment', 'end', 'Fim (s, opcional)', { optional: true }),
  num('ClipSegment', 'speed', 'Velocidade'),
  num('ClipSegment', 'volume', 'Volume'),
  check('ClipSegment', 'mute', 'Mudo'),
  num('ClipSegment', 'fade_in', 'Fade in (s)'),
  num('ClipSegment', 'fade_out', 'Fade out (s)'),
]

export const IMAGE_FIELDS: FieldDef[] = [
  file('ImageSegment', 'src', 'Origem (imagem)', 'image'),
  num('ImageSegment', 'duration', 'Duração (s)'),
  select('ImageSegment', 'motion', 'Movimento'),
  num('ImageSegment', 'motion_amount', 'Intensidade do movimento', { step: 0.01 }),
  num('ImageSegment', 'fade_in', 'Fade in (s)'),
  num('ImageSegment', 'fade_out', 'Fade out (s)'),
]

export const CARD_FIELDS: FieldDef[] = [
  text('CardSegment', 'title', 'Título'),
  text('CardSegment', 'subtitle', 'Subtítulo (opcional)', { optional: true }),
  num('CardSegment', 'duration', 'Duração (s)'),
  select('CardSegment', 'variant', 'Variante', { emptyLabel: 'Padrão do tema' }),
  check('CardSegment', 'logo', 'Mostrar logo'),
  select('CardSegment', 'motion', 'Movimento'),
  num('CardSegment', 'motion_amount', 'Intensidade do movimento', { step: 0.01 }),
]

export const SEGMENT_LABEL_FIELD: FieldDef = text('ClipSegment', 'label', 'Rótulo (opcional)', {
  optional: true,
  prop: 'label',
})

/** A transição de entrada e o enquadramento valem para os três tipos de trecho. Sem transição, o trecho entra em corte seco. */
export const TRANSITION_TYPE_FIELD: FieldDef = select('Transition', 'transition.type', 'Tipo', {
  prop: 'type',
  fallback: 'cut',
})
export const TRANSITION_DURATION_FIELD: FieldDef = num('Transition', 'transition.duration', 'Duração (s)', {
  prop: 'duration',
  fallback: 0.5,
})

export const REFRAME_MODE_FIELD: FieldDef = select('Reframe', 'reframe.mode', 'Modo', { prop: 'mode', fallback: 'auto' })

/** O foco só vale no modo "cortar": diz de onde o corte se aproxima. */
export const REFRAME_FOCUS_FIELDS: FieldDef[] = [
  num('Reframe', 'reframe.focus.0', 'Foco X (0 a 1)', { prop: 'focus', step: 0.05, min: 0, max: 1, fallback: 0.5 }),
  num('Reframe', 'reframe.focus.1', 'Foco Y (0 a 1)', { prop: 'focus', step: 0.05, min: 0, max: 1, fallback: 0.5 }),
]

/* ---------- sobreposições ---------- */

export const TEXT_OVERLAY_FIELDS: FieldDef[] = [
  text('TextOverlay', 'text', 'Texto'),
  text('TextOverlay', 'secondary', 'Segunda linha (opcional)', { optional: true }),
  select('TextOverlay', 'role', 'Papel'),
  num('TextOverlay', 'start', 'Início (s)'),
  num('TextOverlay', 'end', 'Fim (s, opcional)', { optional: true }),
  select('TextOverlay', 'position', 'Posição', { emptyLabel: 'Automática' }),
  select('TextOverlay', 'animation', 'Animação', { emptyLabel: 'Padrão' }),
]

export const IMAGE_OVERLAY_FIELDS: FieldDef[] = [
  select('ImageOverlay', 'position', 'Posição'),
  num('ImageOverlay', 'width', 'Largura (fração)', { step: 0.01 }),
  num('ImageOverlay', 'opacity', 'Opacidade', { step: 0.05 }),
  num('ImageOverlay', 'start', 'Início (s)'),
  num('ImageOverlay', 'end', 'Fim (s, opcional)', { optional: true }),
]

export const VIDEO_OVERLAY_FIELDS: FieldDef[] = [
  num('VideoOverlay', 'start', 'Início na linha do tempo (s)'),
  num('VideoOverlay', 'end', 'Fim (s, opcional)', { optional: true }),
  num('VideoOverlay', 'offset', 'Ponto de entrada no arquivo (s)'),
  select('VideoOverlay', 'position', 'Posição'),
  num('VideoOverlay', 'x', 'X (0 a 1, opcional)', { step: 0.01, optional: true }),
  num('VideoOverlay', 'y', 'Y (0 a 1, opcional)', { step: 0.01, optional: true }),
  num('VideoOverlay', 'width', 'Largura (fração)', { step: 0.01 }),
  text('VideoOverlay', 'aspect', 'Proporção (ex.: 16:9, opcional)', { optional: true }),
  select('VideoOverlay', 'shape', 'Formato'),
  num('VideoOverlay', 'radius', 'Raio dos cantos (fração)', { step: 0.01 }),
  num('VideoOverlay', 'softness', 'Suavidade da borda (px)', { step: 1 }),
  num('VideoOverlay', 'border', 'Borda (px)', { step: 1 }),
  text('VideoOverlay', 'border_color', 'Cor da borda', { fallback: 'white' }),
  check('VideoOverlay', 'shadow', 'Sombra'),
  num('VideoOverlay', 'opacity', 'Opacidade', { step: 0.05 }),
  num('VideoOverlay', 'margin', 'Margem (px)', { step: 1 }),
  num('VideoOverlay', 'volume', 'Volume do PiP'),
  select('VideoOverlay', 'animation', 'Animação'),
  num('VideoOverlay', 'fade', 'Duração da animação (s)', { step: 0.05 }),
]

export const PROGRESS_FIELDS: FieldDef[] = [
  select('ProgressBar', 'position', 'Posição'),
  num('ProgressBar', 'height', 'Altura (px)', { step: 1 }),
]

/* ---------- legendas e áudio ---------- */

export const CAPTION_FIELDS: FieldDef[] = [
  text('Captions', 'source', 'Origem (auto ou caminho .srt)'),
  text('Captions', 'language', 'Idioma'),
  select('Captions', 'model', 'Modelo', { values: CAPTION_MODEL_VALUES }),
  select('CaptionStyle', 'style.mode', 'Estilo', { prop: 'mode' }),
  num('CaptionStyle', 'style.max_words', 'Máx. palavras por linha', { prop: 'max_words', step: 1 }),
  num('CaptionStyle', 'style.max_chars', 'Máx. caracteres por linha', { prop: 'max_chars', step: 1 }),
  check('CaptionStyle', 'style.uppercase', 'Maiúsculas', { prop: 'uppercase' }),
  num('CaptionStyle', 'style.size', 'Tamanho', { prop: 'size', step: 1 }),
]

export const MUSIC_FIELDS: FieldDef[] = [
  file('Music', 'music.src', 'Arquivo de música', 'audio', { prop: 'src' }),
  num('Music', 'music.volume', 'Volume', { prop: 'volume', step: 0.01 }),
  check('Music', 'music.ducking', 'Abaixar sob a voz (ducking)', { prop: 'ducking' }),
  num('Music', 'music.fade_in', 'Fade in (s)', { prop: 'fade_in' }),
  num('Music', 'music.fade_out', 'Fade out (s)', { prop: 'fade_out' }),
  num('Music', 'music.start_at', 'Começar em (s)', { prop: 'start_at' }),
  check('Music', 'music.loop', 'Repetir em loop', { prop: 'loop' }),
]

export const AUDIO_FIELDS: FieldDef[] = [
  num('AudioSettings', 'voice_gain', 'Ganho da voz'),
  select('AudioSettings', 'normalize', 'Normalização'),
  check('AudioSettings', 'mute_clips', 'Silenciar áudio original dos clipes'),
]

export const AUDIO_TRACK_VOLUME_FIELD: FieldDef = num('AudioTrack', 'volume', 'Volume')

/** O campo do schema que o `FieldDef` aponta. */
export function propOf(field: FieldDef): string {
  return field.prop ?? (field.key.split('.').pop() as string)
}

/** Chave dos rótulos de uma lista ("Reframe.mode"), a mesma de `editorLabels`. */
export function labelKeyOf(field: FieldDef): string {
  return `${field.def}.${propOf(field)}`
}

export interface NumberLimits {
  min?: number
  max?: number
  step: number
}

/**
 * Limites do campo numérico: os do schema primeiro, os do `FieldDef` quando o schema não os dá. Um mínimo
 * "exclusivo" (maior que zero) vira o próprio passo, o menor valor que o campo aceita de verdade.
 */
export function numberLimits(field: FieldDef, info: FieldInfo | null): NumberLimits {
  const step = field.step ?? 0.1
  const min = info?.min ?? (info?.exclusiveMin != null ? Math.max(step, info.exclusiveMin) : null) ?? field.min
  const max = info?.max ?? field.max
  return { step, ...(min != null ? { min } : {}), ...(max != null ? { max } : {}) }
}

/**
 * As opções de um campo de lista: as de fora (`choices`, como as transições do catálogo), as do schema ou as fixas
 * do campo, nesta ordem. O valor que a spec já tem entra mesmo se a lista não o conhece, para o formulário não
 * esconder nem trocar sem querer o que está salvo.
 */
export function selectChoices(
  field: FieldDef,
  info: FieldInfo | null,
  current: string,
  choices?: OptionItem[],
): OptionItem[] {
  const base = choices ?? optionItems(labelKeyOf(field), info?.options ?? field.values ?? [])
  if (current && !base.some((option) => option.value === current)) {
    return [...base, { value: current, label: optionLabel(labelKeyOf(field), current) }]
  }
  return base
}
