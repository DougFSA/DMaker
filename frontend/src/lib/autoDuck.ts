/* O Auto Duck na interface: quais trilhas podem comandar quais e como as regras de `audio.ducks` mudam na spec. Funções
   puras sobre a spec; a validação de verdade é do servidor, e aqui só se oferece o que ele aceita. */
import { getPath, setPath } from './editorPaths'

/** Uma regra como mora na spec (`audio.ducks`); o que falta vale o padrão do servidor. */
export interface DuckRule {
  background: string
  key: string
  amount_db?: number
  threshold_db?: number
  max_pause?: number
  outer_fade_down?: number
  inner_fade_down?: number
  inner_fade_up?: number
  outer_fade_up?: number
}

export const DUCKS_PATH = 'audio.ducks'

/** Os campos numéricos da regra, com o padrão e a faixa do Audacity (e do servidor). */
export const DUCK_FIELDS = [
  { name: 'amount_db', label: 'Quanto abaixa', unit: 'dB', fallback: -12, min: -100, max: 0 },
  { name: 'threshold_db', label: 'Limiar da chave', unit: 'dB', fallback: -30, min: -100, max: 0 },
  { name: 'max_pause', label: 'Pausa máxima', unit: 's', fallback: 1, min: 0, max: 60 },
  { name: 'outer_fade_down', label: 'Descida de fora', unit: 's', fallback: 0.5, min: 0, max: 10 },
  { name: 'inner_fade_down', label: 'Descida de dentro', unit: 's', fallback: 0, min: 0, max: 10 },
  { name: 'inner_fade_up', label: 'Subida de dentro', unit: 's', fallback: 0, min: 0, max: 10 },
  { name: 'outer_fade_up', label: 'Subida de fora', unit: 's', fallback: 0.5, min: 0, max: 10 },
] as const

export type DuckFieldName = (typeof DUCK_FIELDS)[number]['name']

/** A trilha é uma faixa externa (A2, A3...): o A1 é o som dos trechos. */
export function isExternalTrack(id: string): boolean {
  return /^A([2-9]|\d{2,})$/.test(id)
}

/** As trilhas de áudio que podem ser o fundo de uma regra (a SFX não aparece na linha do tempo). */
export function isDuckTrack(id: string): boolean {
  return id === 'A1' || isExternalTrack(id) || id === 'MUS' || id === 'NAR' || id === 'VO'
}

/** Quais trilhas podem comandar o fundo `background`: as combinações que o servidor aceita. A faixa externa só abaixa sob
 *  outra faixa externa (ela é misturada dentro do clipe, antes da música e das vozes existirem), e o A1, que já contém as
 *  faixas externas, não abaixa sob elas. */
export function keyOptions(background: string, present: readonly string[]): string[] {
  return present.filter((id) => {
    if (id === background || !isDuckTrack(id)) return false
    if (isExternalTrack(background)) return isExternalTrack(id)
    if (background === 'A1') return !isExternalTrack(id)
    return true
  })
}

/** As regras que abaixam a trilha `background`, cada uma com a posição dela em `audio.ducks`. */
export function rulesFor(spec: unknown, background: string): Array<{ rule: DuckRule; index: number }> {
  const list = getPath(spec, DUCKS_PATH)
  if (!Array.isArray(list)) return []
  return list.flatMap((rule: DuckRule, index: number) => (rule.background === background ? [{ rule, index }] : []))
}

/** Acrescenta uma regra com os padrões do servidor. Devolve a posição dela. */
export function addRuleIn(spec: Record<string, unknown>, background: string, key: string): number {
  const rule: DuckRule = { background, key }
  const list = getPath(spec, DUCKS_PATH)
  if (Array.isArray(list)) {
    list.push(rule)
    return list.length - 1
  }
  setPath(spec, DUCKS_PATH, [rule])
  return 0
}

/** Tira a regra. Ao esvaziar, a chave some da spec: projeto sem regra fica igual ao de antes de existirem. */
export function removeRuleIn(spec: Record<string, unknown>, index: number): boolean {
  const list = getPath(spec, DUCKS_PATH)
  if (!Array.isArray(list) || index < 0 || index >= list.length) return false
  list.splice(index, 1)
  if (list.length === 0) setPath(spec, DUCKS_PATH, undefined)
  return true
}

/** O valor de um campo da regra como a tela o mostra: o da spec, ou o padrão. */
export function duckValue(rule: DuckRule, name: DuckFieldName): number {
  const stored = rule[name]
  return typeof stored === 'number' ? stored : DUCK_FIELDS.find((field) => field.name === name)!.fallback
}

/** O valor limitado à faixa do campo. */
export function clampDuck(name: DuckFieldName, value: number): number {
  const field = DUCK_FIELDS.find((candidate) => candidate.name === name)!
  return Math.min(Math.max(value, field.min), field.max)
}
