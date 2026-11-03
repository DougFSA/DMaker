/* Regras da fila de narrações que não dependem da tela: o que cada estado permite fazer, como o andamento e o
   resumo viram frase e quais itens ainda podem subir ou descer. Sem rede e sem DOM, para testar direto. */
import type { QueueItem, QueueItemState, QueueView } from '@/api'
import type { BadgeTone } from '@/components/ui/AppBadge.vue'
import { speedLabel } from './narration'

/** Os formatos de roteiro que o servidor sabe ler. */
export const SCRIPT_ACCEPT = '.txt,.md,.docx'
/** O tamanho máximo do arquivo de roteiro, o mesmo do servidor (MAX_FILE_BYTES): barrar aqui poupa o envio. */
export const MAX_SCRIPT_BYTES = 20 * 1024 * 1024

export type QueueAction = 'pause' | 'resume' | 'cancel' | 'up' | 'down' | 'retry' | 'remove'

/** O que cada estado deixa fazer, na ordem em que os botões aparecem (a mesma regra do servidor). */
const ACTIONS_BY_STATE: Record<QueueItemState, readonly QueueAction[]> = {
  pending: ['pause', 'cancel', 'up', 'down'],
  running: ['pause', 'cancel'],
  paused: ['resume', 'cancel', 'up', 'down'],
  failed: ['retry', 'remove'],
  cancelled: ['retry', 'remove'],
  done: ['remove'],
}

export const ACTION_LABELS: Record<QueueAction, string> = {
  pause: 'Pausar',
  resume: 'Retomar',
  cancel: 'Cancelar',
  up: 'Subir',
  down: 'Descer',
  retry: 'Tentar de novo',
  remove: 'Remover',
}

/** A dica de cada botão: o que acontece com o item e com o que já foi narrado. */
export const ACTION_HINTS: Record<QueueAction, string> = {
  pause: 'Para na próxima fala e guarda o que já foi narrado',
  resume: 'Volta para a fila, na mesma posição',
  cancel: 'Desiste do item; o que já foi narrado fica guardado',
  up: 'Roda antes do item de cima',
  down: 'Roda depois do item de baixo',
  retry: 'Refaz o item; as falas que já saíram vêm do cache',
  remove: 'Tira o item da lista (os áudios continuam na pasta)',
}

/** O que o aviso diz quando o servidor recusa a ação. */
export const ACTION_FAILURES: Record<QueueAction, string> = {
  pause: 'Não consegui pausar o item',
  resume: 'Não consegui retomar o item',
  cancel: 'Não consegui cancelar o item',
  up: 'Não consegui subir o item',
  down: 'Não consegui descer o item',
  retry: 'Não consegui tentar o item de novo',
  remove: 'Não consegui remover o item',
}

/** Cancelar e remover descartam trabalho, então os botões deles pedem a cor de perigo. */
export const DANGEROUS_ACTIONS: ReadonlySet<QueueAction> = new Set<QueueAction>(['cancel', 'remove'])

const SOURCE_LABELS: Record<QueueItem['source']['kind'], string> = { text: 'texto', file: 'arquivo' }

const STATE_TONES: Record<QueueItemState, BadgeTone> = {
  pending: 'neutral',
  running: 'accent',
  paused: 'warning',
  cancelled: 'neutral',
  done: 'success',
  failed: 'error',
}

/** Os botões que fazem sentido num estado; um estado que o servidor passe a ter e a tela não conheça não mostra nenhum. */
export function actionsFor(state: string): readonly QueueAction[] {
  return ACTIONS_BY_STATE[state as QueueItemState] ?? []
}

export function stateTone(state: string): BadgeTone {
  return STATE_TONES[state as QueueItemState] ?? 'neutral'
}

/** O item ainda não terminou: a barra de andamento só faz sentido enquanto ele espera, roda ou está parado no meio. */
export function showsProgress(state: string): boolean {
  return state === 'pending' || state === 'running' || state === 'paused'
}

/** "2 h 05 min", "12 min" ou "40 s": o mesmo formato do servidor, para os tempos da tela baterem com os dele. */
export function formatAudioLength(seconds: number): string {
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (hours) return `${hours} h ${String(minutes).padStart(2, '0')} min`
  if (minutes) return `${minutes} min`
  return `${total % 60} s`
}

/** A primeira linha de um erro de job, sem o nome da exceção (o resto é para quem for depurar). */
export function firstLine(text: string | null | undefined): string {
  return String(text ?? '')
    .split('\n')[0]!
    .replace(/^\w+(Error|Exception):\s*/, '')
}

/** O erro tem mais coisa além da primeira linha? Então a tela deixa abrir o texto inteiro. */
export function hasErrorDetails(text: string | null | undefined): boolean {
  return String(text ?? '').trim().split('\n').length > 1
}

/** O tempo estimado que vale mostrar: uma estimativa que arredonda para 0 s (voz rápida, texto curto) não ajuda ninguém. */
function shownEta(label: string | null, seconds: number | null): string | null {
  return label && seconds ? label : null
}

/** O que o item está fazendo, numa linha: capítulo e fala em andamento, quanto falta ou o desfecho. */
export function describeProgress(item: QueueItem): string {
  const chapters = `${item.chapters_total} ${item.chapters_total === 1 ? 'capítulo' : 'capítulos'}`
  const eta = shownEta(item.eta_label, item.eta_seconds)
  const left = eta ? ` · faltam cerca de ${eta}` : ''
  switch (item.state) {
    case 'running': {
      if (!item.chapter) return `Preparando o roteiro${left}`
      const where = item.chapters_total > 1 ? `capítulo ${item.chapter} de ${item.chapters_total}, ` : ''
      return `${where}fala ${item.utterance} de ${item.utterances}${left}`
    }
    case 'pending':
      return `Aguardando a vez · ${chapters}${left}`
    case 'paused':
      return `Pausado em ${item.percent}% · ${chapters}`
    case 'done':
      return `Pronto · ${chapters}${item.duration_s ? ` · ${formatAudioLength(item.duration_s)} de áudio` : ''}`
    case 'cancelled':
      return `Cancelado em ${item.percent}%`
    case 'failed':
      return firstLine(item.error) || 'Falhou'
    default:
      return chapters
  }
}

/** De onde veio o roteiro, o nome dele, se é rascunho e o formato do áudio: a linha de dados sob o título. */
export function itemMeta(item: QueueItem): string[] {
  return [
    SOURCE_LABELS[item.source.kind] ?? item.source.kind,
    item.source.name,
    item.options.draft ? 'rascunho' : '',
    item.options.format.toUpperCase(),
  ].filter(Boolean)
}

export interface QueueSummary {
  /** A linha de resumo: quantos itens e quanto falta para esvaziar. */
  text: string
  /** Aviso que pede atenção (a fila não anda); nulo quando está tudo certo. */
  warning: string | null
}

/** Resumo no topo da lista. O aviso só aparece quando há o que narrar e nenhum executor para fazê-lo. */
export function queueSummary(view: QueueView): QueueSummary {
  const items = view.items
  if (items.length === 0) return { text: 'A fila está vazia.', warning: null }
  const waiting = items.some((item) => item.state === 'pending' || item.state === 'running')
  const parts = [`${items.length} ${items.length === 1 ? 'item' : 'itens'}`]
  const eta = shownEta(view.eta_label, view.eta_seconds)
  if (waiting && eta) parts.push(`tempo estimado para esvaziar: ${eta}`)
  // `worker` ausente é "não sei" (resposta antiga): só avisa quando o servidor diz que não há executor
  const stalled = waiting && !view.running && view.worker === false
  return {
    text: parts.join(' · '),
    warning: stalled
      ? 'Nenhum executor ativo: os itens esperam parados. Abra a fila pelo dmaker ui ou rode dmaker voice queue run.'
      : null,
  }
}

/** "Limpar concluídos" só tem o que tirar se há item pronto ou cancelado (os que falharam ficam, para se ler o erro). */
export function canClearFinished(view: QueueView): boolean {
  return view.items.some((item) => item.state === 'done' || item.state === 'cancelled')
}

export interface MoveLimits {
  up: boolean
  down: boolean
}

/**
 * Quais itens ainda podem subir ou descer: só os que esperam (pendentes e pausados) trocam de lugar entre si, então
 * o primeiro deles não sobe e o último não desce. O servidor ignora o pedido no limite; a tela nem oferece.
 */
export function moveLimits(items: readonly QueueItem[]): Record<string, MoveLimits> {
  const waiting = items.filter((item) => item.state === 'pending' || item.state === 'paused')
  const limits: Record<string, MoveLimits> = {}
  waiting.forEach((item, position) => {
    limits[item.id] = { up: position > 0, down: position < waiting.length - 1 }
  })
  return limits
}

/** Com que voz, idioma e velocidade o roteiro importado será narrado: o que a Narração tem escolhido agora. */
export function narrationSummary(voiceName: string | null, languageName: string | null, speed: number): string {
  return `${voiceName ?? 'Voz automática do motor'} · ${languageName ?? 'idioma da voz'} · velocidade ${speedLabel(speed)}`
}
