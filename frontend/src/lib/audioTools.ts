/* A multiferramenta do painel Áudio: com ela escolhida, o que o mouse faz depende de onde ele está. Sobre a linha do
   envelope (ou um ponto dela) ele mexe no envelope; no zoom máximo, onde cada amostra tem lugar para ser desenhada,
   desenha; em qualquer outro lugar, seleciona. Pura: recebe o que o componente mediu e devolve a ferramenta. */

export type ResolvedTool = 'select' | 'envelope' | 'draw'

export interface MultiToolContext {
  /** A janela está tão aproximada que cada amostra ocupa pixels suficientes para desenhar. */
  canDraw: boolean
  /** O ponteiro está sobre a linha do envelope ou sobre um ponto dela. */
  overEnvelope: boolean
}

export function multiToolAt(context: MultiToolContext): ResolvedTool {
  if (context.overEnvelope) return 'envelope'
  if (context.canDraw) return 'draw'
  return 'select'
}
