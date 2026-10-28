import type { TransitionCurve, TransitionInfo } from '@/api'

export type TransitionKindFilter = 'all' | TransitionInfo['kind']

export const CURVE_LABELS: Record<TransitionCurve, string> = {
  linear: 'Linear',
  ease: 'Suave',
  spring: 'Mola',
}

/** O que cada curva faz com o ritmo da troca, para o seletor da galeria. */
export const CURVE_HINTS: Record<TransitionCurve, string> = {
  linear: 'Velocidade constante, do começo ao fim da troca.',
  ease: 'Parte e chega devagar, e corre no meio.',
  spring: 'Corre logo no começo, passa um pouco do ponto final e assenta.',
}

/** Transições que combinam com a busca (nome ou descrição, sem diferenciar maiúsculas) e com o tipo. */
export function filterTransitions(
  transitions: TransitionInfo[],
  query: string,
  kind: TransitionKindFilter,
): TransitionInfo[] {
  const needle = query.trim().toLowerCase()
  return transitions.filter((item) => {
    if (kind !== 'all' && item.kind !== kind) return false
    if (!needle) return true
    return item.name.toLowerCase().includes(needle) || item.summary.toLowerCase().includes(needle)
  })
}

/** Trecho de spec pronto para copiar: como pedir esta transição com a curva escolhida. */
export function specSnippet(name: string, curve: TransitionCurve): string {
  const curvePart = curve === 'linear' ? '' : `, "curve": "${curve}"`
  return `"transition": { "type": "${name}", "duration": 0.5${curvePart} }`
}
