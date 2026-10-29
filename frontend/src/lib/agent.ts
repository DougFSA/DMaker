/* Conversa com o agente local: transforma os eventos do SSE do job em itens da conversa (funções puras). */
import type { AgentEvent, AgentKit, ConfirmationType, JobEvent } from '@/api'

export type ToolState = 'running' | 'done' | 'blocked' | 'error'
export type ConfirmationState = 'pending' | 'approved' | 'refused'

export interface UserItem {
  kind: 'user'
  id: string
  text: string
}
export interface KitsItem {
  kind: 'kits'
  id: string
  kits: string[]
  method: string
}
export interface ToolItem {
  kind: 'tool'
  id: string
  name: string
  arguments: Record<string, unknown>
  state: ToolState
  /** Primeira linha do resultado (ou o motivo de a chamada ter sido barrada). */
  detail: string
  percent: number | null
  label: string
}
export interface ConfirmationItem {
  kind: 'confirmation'
  id: string
  confirmationId: string
  tool: string
  question: string
  type: ConfirmationType
  state: ConfirmationState
}
export interface AnswerItem {
  kind: 'answer'
  id: string
  text: string
}
export interface ErrorItem {
  kind: 'error'
  id: string
  text: string
}
export type ChatItem = UserItem | KitsItem | ToolItem | ConfirmationItem | AnswerItem | ErrorItem

export type StreamEvent = AgentEvent | JobEvent

const FIRST_LINE_LIMIT = 160
const ARGUMENT_LIMIT = 60

function firstLine(text: string): string {
  const line = (text.split('\n')[0] ?? '').trim()
  return line.length > FIRST_LINE_LIMIT ? `${line.slice(0, FIRST_LINE_LIMIT - 1)}…` : line
}

/** `chave=valor` de cada argumento, com valores longos cortados, para caber numa linha da conversa. */
export function summarizeArguments(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([key, value]) => {
      const text = typeof value === 'string' ? value : JSON.stringify(value)
      const shown = text.length > ARGUMENT_LIMIT ? `${text.slice(0, ARGUMENT_LIMIT - 1)}…` : text
      return `${key}=${shown}`
    })
    .join(', ')
}

export function kitTitle(name: string, kits: AgentKit[]): string {
  return kits.find((kit) => kit.name === name)?.title ?? name
}

/** O botão de cada tipo de confirmação: a autorização da voz diz o que a pessoa está afirmando. */
export function confirmationLabels(type: ConfirmationType): { yes: string; no: string } {
  return type === 'voice_consent'
    ? { yes: 'O dono da voz autorizou', no: 'Não autorizou' }
    : { yes: 'Confirmar', no: 'Não fazer' }
}

function lastIndexWhere(items: ChatItem[], test: (item: ChatItem) => boolean): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (test(items[index]!)) return index
  }
  return -1
}

function updateTool(items: ChatItem[], name: string, change: (tool: ToolItem) => ToolItem): ChatItem[] {
  const index = lastIndexWhere(items, (item) => item.kind === 'tool' && item.name === name && item.state !== 'done')
  if (index < 0) return items
  const next = items.slice()
  next[index] = change(items[index] as ToolItem)
  return next
}

/**
 * Aplica um evento do SSE à conversa e devolve a lista nova. `nextId` dá um id novo a cada item.
 * Um evento `start` recomeça o turno (o servidor reenvia tudo ao reconectar): `base` é quantos itens vieram
 * antes dele (a mensagem da pessoa e as respostas anteriores).
 */
export function reduceEvent(items: ChatItem[], event: StreamEvent, base: number, nextId: () => string): ChatItem[] {
  switch (event.kind) {
    case 'start':
      return items.slice(0, base)
    case 'triage':
      return [...items, { kind: 'kits', id: nextId(), kits: event.kits, method: event.method }]
    case 'tool_call':
      return [
        ...items,
        {
          kind: 'tool',
          id: nextId(),
          name: event.name,
          arguments: event.arguments,
          state: 'running',
          detail: '',
          percent: null,
          label: '',
        },
      ]
    case 'tool_blocked':
      return updateTool(items, event.name, (tool) => ({ ...tool, state: 'blocked', detail: firstLine(event.reason) }))
    case 'tool_result':
      return updateTool(items, event.name, (tool) =>
        tool.state === 'blocked'
          ? tool
          : { ...tool, state: event.result.startsWith('erro:') ? 'error' : 'done', detail: firstLine(event.result), percent: tool.percent === null ? null : 100 },
      )
    case 'tool_progress':
      return updateTool(items, event.name, (tool) => ({
        ...tool,
        percent: event.progress.percent ?? tool.percent,
        label: event.progress.label ?? tool.label,
      }))
    case 'confirmation_request':
      return [
        ...items,
        {
          kind: 'confirmation',
          id: nextId(),
          confirmationId: event.id,
          tool: event.tool,
          question: event.question,
          type: event.type,
          state: 'pending',
        },
      ]
    case 'confirmation_answered':
      return items.map((item) =>
        item.kind === 'confirmation' && item.confirmationId === event.id
          ? { ...item, state: event.approved ? 'approved' : 'refused' }
          : item,
      )
    case 'answer':
      return [...items, { kind: 'answer', id: nextId(), text: event.text }]
    case 'end':
      return event.status === 'error' || event.status === 'cancelled'
        ? [...items, { kind: 'error', id: nextId(), text: errorSummary(event.error) }]
        : items
    default:
      return items
  }
}

/** Do rastro de erro de um job, só a última linha útil (a mensagem), sem o traceback. */
export function errorSummary(error: string | null): string {
  const lines = (error ?? '').split('\n').filter((line) => line.trim() && !line.startsWith(' '))
  return lines[0] ?? 'O agente parou sem uma resposta.'
}

/** Tem uma confirmação esperando o clique? Enquanto sim, o agente está parado e a tela deve destacar o botão. */
export function pendingConfirmation(items: ChatItem[]): ConfirmationItem | null {
  const found = items.find((item): item is ConfirmationItem => item.kind === 'confirmation' && item.state === 'pending')
  return found ?? null
}
