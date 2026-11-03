/* As etapas de um render, deduzidas das mensagens que o job já manda (log e progresso), sem campo novo no servidor.
   As chaves vêm do que `pipeline/renderer.py` escreve em `ctx.log` e dos nomes dos comandos do ffmpeg de cada etapa:
   "trecho i/N" (pipeline/segments.py), "áudio para transcrição" (captions.py) e "montagem final" (assembly.py). */
import type { JobProgress } from '@/api'

export type RenderStageKey = 'sources' | 'segments' | 'captions' | 'text' | 'loudness' | 'assembly' | 'thumbnail'

export const RENDER_STAGES: Array<{ key: RenderStageKey; label: string }> = [
  { key: 'sources', label: 'Fontes e sincronização' },
  { key: 'segments', label: 'Trechos' },
  { key: 'captions', label: 'Legendas' },
  { key: 'text', label: 'Camada de texto' },
  { key: 'loudness', label: 'Loudness' },
  { key: 'assembly', label: 'Montagem final' },
  { key: 'thumbnail', label: 'Miniatura' },
]

export type StageStatus = 'done' | 'current' | 'pending'

export interface StageView {
  key: RenderStageKey
  label: string
  status: StageStatus
  /** Detalhe curto da etapa atual ("trecho 2/5", "42%"); vazio nas outras. */
  detail: string
}

/** A etapa que uma linha de log do renderer marca, ou null se a linha não marca nenhuma. */
export function stageFromLog(message: string): RenderStageKey | null {
  if (/^render /.test(message)) return 'sources'
  if (/^sincronizando /.test(message) || /come[cç]a em [+-]?\d/.test(message)) return 'sources'
  if (/^trechos: \d+/.test(message)) return 'segments'
  if (/^legendas: /.test(message)) return 'captions'
  if (message === 'montagem final') return 'assembly'
  if (/^pronto: /.test(message)) return 'thumbnail'
  return null
}

/** A etapa que o nome de um comando do ffmpeg (o `label` do progresso) marca, ou null. */
export function stageFromProgressLabel(label: string): RenderStageKey | null {
  if (/^(recorte do )?trecho \d+\/\d+/.test(label)) return 'segments'
  if (label === 'áudio para transcrição') return 'captions'
  if (label === 'montagem final') return 'assembly'
  if (label === 'thumbnail') return 'thumbnail'
  return null
}

function indexOfStage(key: RenderStageKey | null): number {
  return key ? RENDER_STAGES.findIndex((stage) => stage.key === key) : -1
}

/**
 * As sete etapas com o estado de cada uma. A etapa só avança: vale a mais adiantada que o log ou o comando em curso
 * já mostraram. Com o job terminado, todas contam como feitas. Sem nenhuma marca ainda (um job que não é render),
 * devolve a lista vazia, para a tela não mostrar etapas que não existem.
 */
export function renderStages(log: string[], progress: JobProgress | null, finished = false): StageView[] {
  const label = progress?.label ?? ''
  const fromProgress = indexOfStage(stageFromProgressLabel(label))
  const current = Math.max(fromProgress, ...log.map((line) => indexOfStage(stageFromLog(line))))
  if (current < 0) return []

  let detail = ''
  if (fromProgress === current) {
    detail = /trecho \d+\/\d+/.exec(label)?.[0] ?? (typeof progress?.percent === 'number' ? `${progress.percent}%` : '')
  }
  return RENDER_STAGES.map((stage, index) => ({
    ...stage,
    status: finished || index < current ? 'done' : index === current ? 'current' : 'pending',
    detail: !finished && index === current ? detail : '',
  }))
}
