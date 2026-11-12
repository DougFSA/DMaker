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

export const KIND_LABELS: Record<PersonaKind, string> = { '2d': 'Ilustrada 2D', '3d': 'Personagem 3D', realistic: 'Realista' }

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
