/* Comparação A/B (antes e depois) de uma gravação: a janela que se escuta em volta do trecho trocado. */

/** Quanto antes e depois do trecho trocado a comparação toca, para ouvir a emenda no contexto. */
export const AB_PADDING_S = 1.5

export interface AbRange {
  start: number
  end: number
}

/** A região trocada com uma folga de cada lado (o início nunca fica abaixo de zero). */
export function abWindow(region: readonly [number, number], padding: number = AB_PADDING_S): AbRange {
  return { start: Math.max(0, region[0] - padding), end: region[1] + padding }
}
