import type { LookEffectName, LookInfo } from '@/api'

export type LookSourceFilter = 'all' | LookInfo['source']

/** Nome de cada efeito de acabamento como a interface o mostra (o campo da spec fica no trecho copiável). */
export const EFFECT_LABELS: Record<LookEffectName, string> = {
  vignette: 'vinheta',
  glow: 'brilho',
  aberration: 'aberração',
  light_leak: 'vazamento de luz',
  grain: 'grão',
}

/** Efeitos que o look liga, na ordem em que a galeria os mostra, com a quantidade de cada um. */
export function effectChips(look: LookInfo): Array<{ name: LookEffectName; label: string; amount: number }> {
  const order = Object.keys(EFFECT_LABELS) as LookEffectName[]
  return order
    .filter((name) => (look.effects[name] ?? 0) > 0)
    .map((name) => ({ name, label: EFFECT_LABELS[name], amount: look.effects[name] ?? 0 }))
}

/** Looks que combinam com a busca (nome ou descrição, sem diferenciar maiúsculas) e com a origem. */
export function filterLooks(looks: LookInfo[], query: string, source: LookSourceFilter): LookInfo[] {
  const needle = query.trim().toLowerCase()
  return looks.filter((item) => {
    if (source !== 'all' && item.source !== source) return false
    if (!needle) return true
    return item.name.toLowerCase().includes(needle) || item.summary.toLowerCase().includes(needle)
  })
}

/** Trecho de spec pronto para copiar: como pedir este look no projeto inteiro. */
export function specSnippet(name: string): string {
  return `"look": "${name}"`
}
