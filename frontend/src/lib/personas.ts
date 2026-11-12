/* Contas puras da tela de Personas: os campos de aparência de cada tipo e a aparência inicial. O servidor valida de
   verdade (cada motor confere a sua); aqui só se descreve o formulário. */
import type { PersonaKind } from '@/api'

export interface AppearanceField {
  key: string
  label: string
  kind: 'color' | 'choice' | 'text'
  options?: { value: string; label: string }[]
  hint?: string
}

const FIELDS: Record<PersonaKind, AppearanceField[]> = {
  '2d': [
    { key: 'skin', label: 'Pele', kind: 'color' },
    { key: 'hair_color', label: 'Cor do cabelo', kind: 'color' },
    {
      key: 'hair_style',
      label: 'Cabelo',
      kind: 'choice',
      options: [
        { value: 'short', label: 'Curto' },
        { value: 'long', label: 'Longo' },
        { value: 'bun', label: 'Coque' },
      ],
    },
    { key: 'eye_color', label: 'Cor dos olhos', kind: 'color' },
    { key: 'outfit_color', label: 'Cor da roupa', kind: 'color' },
  ],
  '3d': [
    { key: 'outfit_color', label: 'Cor da roupa', kind: 'color', hint: 'A roupa do personagem pronto é lisa nesta cor.' },
    {
      key: 'model',
      label: 'Modelo',
      kind: 'text',
      hint: '"mpfb" é o personagem pronto; outro nome é um arquivo .glb na pasta da persona.',
    },
  ],
  realistic: [],
}

const DEFAULTS: Record<PersonaKind, Record<string, string>> = {
  '2d': { skin: '#E8B796', hair_color: '#3B2A20', hair_style: 'short', eye_color: '#4A7BA7', outfit_color: '#2F6FDE' },
  '3d': { model: 'mpfb', outfit_color: '#3A4A5E' },
  realistic: {},
}

export const KIND_LABELS: Record<PersonaKind, string> = {
  '2d': 'Ilustrada 2D',
  '3d': 'Personagem 3D',
  realistic: 'Realista (uma foto que fala)',
}

export const PHOTO_RIGHTS_NOTICE = 'Use só foto sua ou de quem autorizou o uso da imagem.'

/** Os nomes em português das expressões e dos gestos dos dois motores; a chave é o identificador da spec. */
export const CAPABILITY_LABELS: Record<string, string> = {
  neutral: 'neutra',
  happy: 'alegre',
  sad: 'triste',
  surprised: 'surpresa',
  nod: 'sim com a cabeça',
  shake: 'não com a cabeça',
  tilt: 'cabeça inclinada',
  wave: 'aceno com a mão',
  handup: 'mão levantada',
  index: 'dedo indicador',
  ok: 'sinal de ok',
  thumbup: 'joinha',
  thumbdown: 'polegar para baixo',
  side: 'mão para o lado',
  shrug: 'dar de ombros',
}

/** "alegre (`happy`)": o nome em português com o identificador da spec ao lado (o próprio id se não houver nome). */
export function capabilityLabel(id: string): string {
  const label = CAPABILITY_LABELS[id]
  return label ? `${label} (${id})` : id
}

export function capabilityList(ids: readonly string[]): string {
  return ids.map(capabilityLabel).join(', ')
}

/** O que a tela diz de expressões e gestos de um tipo: a realista só tem a expressão da foto. */
export function capabilitySummary(kind: PersonaKind, expressions: readonly string[], gestures: readonly string[]): string {
  if (kind === 'realistic') return 'Só a expressão da foto; sem gestos.'
  return `Expressões: ${capabilityList(expressions)}. Gestos: ${capabilityList(gestures)}.`
}

/** "uns 11 min", "uns 45 s", "uns 1 h 55 min": a estimativa de tempo dita como gente. */
export function approximateDuration(seconds: number): string {
  if (seconds < 90) return `uns ${Math.max(Math.round(seconds), 1)} s`
  if (seconds < 5400) return `uns ${Math.round(seconds / 60)} min`
  const minutes = Math.round(seconds / 60)
  return `uns ${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`
}

/** A frase ao lado do botão da prévia; vazia quando o motor é rápido e não há estimativa. */
export function previewEstimateText(estimate: { seconds: number | null; device_label?: string } | undefined): string {
  if (!estimate || estimate.seconds === null) return ''
  const where = estimate.device_label ? ` (${estimate.device_label})` : ''
  return `A prévia leva ${approximateDuration(estimate.seconds)} neste computador${where}, com ele livre.`
}

export function appearanceFields(kind: PersonaKind): AppearanceField[] {
  return FIELDS[kind]
}

/** A aparência inicial do tipo, para o formulário abrir já preenchido. */
export function defaultAppearance(kind: PersonaKind): Record<string, string> {
  return { ...DEFAULTS[kind] }
}

/** A aparência de uma persona com os padrões do tipo no que faltar (uma persona antiga pode não ter todos os campos). */
export function appearanceWithDefaults(kind: PersonaKind, appearance: Record<string, string>): Record<string, string> {
  return { ...defaultAppearance(kind), ...appearance }
}
