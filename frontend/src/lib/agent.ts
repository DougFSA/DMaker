/* Conversa com o agente local: transforma os eventos do SSE do job em itens da conversa (funções puras).
   A transcrição salva pelo servidor vira os mesmos itens em `agentTranscript.ts`. */
import type {
  AgentEvent,
  AgentKit,
  AgentStage,
  ConfirmationType,
  JobEvent,
  NoticeCode,
  NoticeLevel,
} from '@/api'
import type { AttachmentCard } from './agentAttachments'

export type ToolState = 'running' | 'done' | 'blocked' | 'error' | 'interrupted'
export type ConfirmationState = 'pending' | 'approved' | 'refused' | 'unconfirmed'

export interface UserItem {
  kind: 'user'
  id: string
  text: string
  /** Os arquivos que seguiram com a mensagem; a chave só existe quando houve anexo. */
  attachments?: AttachmentCard[]
}
export interface KitsItem {
  kind: 'kits'
  id: string
  kits: string[]
  method: string
}
/** O raciocínio do modelo, que a tela recolhe: a pessoa abre se quiser ler. */
export interface ThinkingItem {
  kind: 'thinking'
  id: string
  text: string
  /** Ainda chegando: o texto cresce com os trechos. */
  streaming: boolean
}
export interface ToolItem {
  kind: 'tool'
  id: string
  name: string
  arguments: Record<string, unknown>
  state: ToolState
  /** Primeira linha do resultado (ou o motivo de a chamada ter sido barrada). */
  detail: string
  /** O resultado completo (cortado em 800 caracteres), para a pessoa abrir quando a primeira linha não basta. */
  result: string
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
  /** A pessoa parou a resposta: o texto é só o que chegou até aí. */
  interrupted: boolean
  /** Ainda chegando: o texto cresce com os trechos. */
  streaming: boolean
}
/** Um aviso do agente (conversa aparada, resposta parada, turno que o DMaker fechou pela metade). */
export interface NoticeItem {
  kind: 'notice'
  id: string
  level: NoticeLevel
  code: NoticeCode
  text: string
}
export interface ErrorItem {
  kind: 'error'
  id: string
  text: string
}
export type ChatItem =
  | UserItem
  | KitsItem
  | ThinkingItem
  | ToolItem
  | ConfirmationItem
  | AnswerItem
  | NoticeItem
  | ErrorItem

export type StreamEvent = AgentEvent | JobEvent

/** A etapa em que o agente está agora (o evento `status`), com o instante em que a tela soube dela. */
export interface StageInfo {
  stage: AgentStage
  label: string
  tool?: string
}

const FIRST_LINE_LIMIT = 160
const ARGUMENT_LIMIT = 60
const RESULT_LIMIT = 800

/** O mesmo texto que o servidor grava quando a pessoa para a resposta antes de qualquer texto. */
export const STOPPED_BEFORE_START = 'Você parou a resposta antes de ela começar.'
export const STOPPED = 'Você parou a resposta.'

function firstLine(text: string): string {
  const line = (text.split('\n')[0] ?? '').trim()
  return line.length > FIRST_LINE_LIMIT ? `${line.slice(0, FIRST_LINE_LIMIT - 1)}…` : line
}

function shortResult(text: string): string {
  return text.length > RESULT_LIMIT ? `${text.slice(0, RESULT_LIMIT - 1)}…` : text
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

/** O título curto de cada aviso; o texto longo vem do servidor. */
const NOTICE_TITLES: Record<NoticeCode, string> = {
  history_trimmed: 'Conversa aparada',
  interrupted: 'Resposta parada',
  unfinished: 'Resposta incompleta',
  save_failed: 'Conversa não salva',
  error: 'Erro',
}

export function noticeTitle(code: NoticeCode): string {
  return NOTICE_TITLES[code] ?? 'Aviso'
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

/** Anexa o trecho ao último item do tipo que ainda está chegando; sem ele, abre um item novo. */
function appendDelta(items: ChatItem[], kind: 'thinking' | 'answer', text: string, nextId: () => string): ChatItem[] {
  const last = items[items.length - 1]
  if (last && last.kind === kind && last.streaming) {
    return [...items.slice(0, -1), { ...last, text: last.text + text }]
  }
  const item: ThinkingItem | AnswerItem =
    kind === 'thinking'
      ? { kind, id: nextId(), text, streaming: true }
      : { kind, id: nextId(), text, interrupted: false, streaming: true }
  return [...items, item]
}

/** O texto final do raciocínio substitui o que foi juntando dos trechos; sem trechos (motor sem fluxo), entra inteiro. */
function settleThinking(items: ChatItem[], text: string, nextId: () => string): ChatItem[] {
  const index = lastIndexWhere(items, (item) => item.kind === 'thinking' && item.streaming)
  if (index < 0) return [...items, { kind: 'thinking', id: nextId(), text, streaming: false }]
  const next = items.slice()
  next[index] = { ...(items[index] as ThinkingItem), text, streaming: false }
  return next
}

/** A resposta final: troca a que vinha em trechos (é sempre o último item do turno) ou entra inteira. */
function settleAnswer(items: ChatItem[], text: string, interrupted: boolean, base: number, nextId: () => string): ChatItem[] {
  const last = items.length - 1
  const tail = last >= base ? items[last] : undefined
  const streamed = tail?.kind === 'answer' && tail.streaming ? tail : null
  if (interrupted && !text.trim()) {
    // parou antes de qualquer texto: não fica balão vazio, só o aviso (como na transcrição do servidor)
    const rest = streamed ? items.slice(0, -1) : items
    return [...rest, { kind: 'notice', id: nextId(), level: 'info', code: 'interrupted', text: STOPPED_BEFORE_START }]
  }
  const answer: AnswerItem = { kind: 'answer', id: streamed?.id ?? nextId(), text, interrupted, streaming: false }
  return streamed ? [...items.slice(0, -1), answer] : [...items, answer]
}

/** Fecha o que ainda estava chegando (o turno acabou, por erro ou parada, antes do texto final). */
function settleStreams(items: ChatItem[]): ChatItem[] {
  return items.map((item) =>
    (item.kind === 'thinking' || item.kind === 'answer') && item.streaming ? { ...item, streaming: false } : item,
  )
}

/** A etapa de um evento `status`; qualquer outro evento devolve `null`. */
export function stageOf(event: StreamEvent): StageInfo | null {
  if (event.kind !== 'status') return null
  return { stage: event.stage, label: event.label, ...(event.tool ? { tool: event.tool } : {}) }
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
    case 'thinking_delta':
      return appendDelta(items, 'thinking', event.text, nextId)
    case 'answer_delta':
      return appendDelta(items, 'answer', event.text, nextId)
    case 'model_reply': {
      // uma volta que pediu ferramentas não é uma resposta: o texto que chegou antes delas não entra na conversa
      const last = items[items.length - 1]
      return event.tool_calls > 0 && last?.kind === 'answer' && last.streaming ? items.slice(0, -1) : items
    }
    case 'thinking':
      return settleThinking(items, event.text, nextId)
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
          result: '',
          percent: null,
          label: '',
        },
      ]
    case 'tool_blocked':
      return updateTool(items, event.name, (tool) => ({ ...tool, state: 'blocked', detail: firstLine(event.reason) }))
    case 'tool_result':
      return updateTool(items, event.name, (tool): ToolItem => {
        const withResult = { ...tool, result: shortResult(event.result) }
        if (tool.state === 'blocked') return withResult // a chamada barrada guarda o motivo, não o resultado do bloqueio
        return {
          ...withResult,
          state: event.result.startsWith('erro:') ? 'error' : 'done',
          detail: firstLine(event.result),
          percent: tool.percent === null ? null : 100,
        }
      })
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
    case 'history_trimmed':
      return [...items, { kind: 'notice', id: nextId(), level: 'info', code: 'history_trimmed', text: event.text }]
    case 'answer':
      return settleAnswer(items, event.text, event.interrupted === true, base, nextId)
    case 'end':
      return endTurn(settleStreams(items), event, nextId)
    default:
      return items
  }
}

/** Parar é uma parada normal (a resposta parcial já está na conversa); só o erro de verdade vira mensagem de erro. */
function endTurn(items: ChatItem[], event: Extract<JobEvent, { kind: 'end' }>, nextId: () => string): ChatItem[] {
  if (event.status === 'error') return [...items, { kind: 'error', id: nextId(), text: errorSummary(event.error) }]
  if (event.status === 'cancelled' && !isInterrupted(event.result)) {
    return [...items, { kind: 'notice', id: nextId(), level: 'info', code: 'interrupted', text: STOPPED }]
  }
  return items
}

/** O job cancelado trouxe a resposta parcial (`result.interrupted`): o `answer` ou o aviso já contaram a parada. */
export function isInterrupted(result: unknown): boolean {
  return !!result && typeof result === 'object' && (result as { interrupted?: unknown }).interrupted === true
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

/**
 * A conversa até a última mensagem da pessoa, sem o que veio depois. Recarregar a página no meio de um turno traz
 * do disco o que o turno já tinha feito, e o SSE reenvia o turno inteiro desde o começo: o que vem depois da
 * mensagem sai daqui para não aparecer duas vezes.
 */
export function dropAfterLastUser(items: ChatItem[]): ChatItem[] {
  const index = lastIndexWhere(items, (item) => item.kind === 'user')
  return index < 0 ? [] : items.slice(0, index + 1)
}
