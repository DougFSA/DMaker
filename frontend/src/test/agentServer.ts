/* Apoio dos testes do agente: o servidor de mentira com as rotas de /api/agent, os modelos e as conversas de exemplo.
   O teste troca `state.conversations` e, quando precisa de outra resposta, passa a rota em `extra`. */
import type {
  AgentAttachment,
  AgentConversationDetail,
  AgentConversationPatch,
  AgentConversationSummary,
  AgentLoaded,
  AgentModel,
  AgentModels,
  AgentStatus,
} from '@/api'
import { reply, routedFetch, type ReplyWith, type RoutedCall, type RoutedFetch } from './routedFetch'

export const GIB = 1024 ** 3

export const STATUS: AgentStatus = {
  engine: 'ollama',
  engine_label: 'Ollama',
  model: 'gpt-oss:20b',
  url: 'http://127.0.0.1:11434',
  free_html: false,
  reachable: true,
  model_installed: true,
  kits: [
    { name: 'editing', title: 'Edição e render', description: 'Criar o vídeo e renderizar.', tools: 18 },
    { name: 'voice', title: 'Voz e narração', description: 'Narrar um texto.', tools: 13 },
  ],
}

export const GPT_OSS: AgentModel = {
  name: 'gpt-oss:20b',
  size: Math.round(12.8 * GIB),
  family: 'gptoss',
  capabilities: ['tools', 'thinking'],
  context_length: 131072,
  effort_levels: [
    { value: 'low', label: 'Baixo' },
    { value: 'medium', label: 'Médio' },
    { value: 'high', label: 'Alto' },
  ],
  default_effort: 'medium',
  fit: 'fits',
  loaded: false,
}

/** O modelo que não cabe nos 16 GB da máquina: aparece na lista, com o aviso, mas nunca é enviado de verdade. */
export const QWEN: AgentModel = {
  name: 'qwen3:30b-a3b',
  size: Math.round(17.3 * GIB),
  family: 'qwen3moe',
  capabilities: ['tools', 'thinking'],
  context_length: 262144,
  effort_levels: [
    { value: 'off', label: 'Desligado' },
    { value: 'on', label: 'Ligado' },
  ],
  default_effort: 'on',
  fit: 'too_big',
  loaded: false,
}

/** Um modelo com visão e sem ferramentas: não opera o DMaker, só serve à Conversa livre. */
export const GEMMA: AgentModel = {
  name: 'gemma3:4b',
  size: Math.round(3.1 * GIB),
  family: 'gemma3',
  capabilities: ['vision'],
  context_length: 131072,
  effort_levels: [],
  default_effort: null,
  fit: 'fits',
  loaded: false,
}

export const MODELS: AgentModels = {
  engine: 'ollama',
  default_model: 'gpt-oss:20b',
  memory: { total: Math.round(15.7 * GIB), available: 2 * GIB },
  models: [GPT_OSS, QWEN],
}

/** A lista de modelos com o gemma3 também instalado. */
export const MODELS_WITH_GEMMA: AgentModels = { ...MODELS, models: [GPT_OSS, GEMMA, QWEN] }

/** O gpt-oss carregado na memória, como o Ollama o informa. */
export const LOADED: AgentLoaded = {
  engine: 'ollama',
  models: [
    {
      name: 'gpt-oss:20b',
      size: Math.round(9.4 * GIB),
      size_vram: 0,
      context_length: 16384,
      expires_at: '2026-10-30T15:35:00.000+00:00',
    },
  ],
}

/** Um anexo de texto, como o servidor o devolve ao subir um .docx ou .pdf. */
export function textAttachment(overrides: Partial<AgentAttachment> = {}): AgentAttachment {
  return { id: 'a1', kind: 'text', name: 'roteiro.docx', size: 20480, chars: 1200, total_chars: 1200, truncated: false, ...overrides }
}

export function imageAttachment(overrides: Partial<AgentAttachment> = {}): AgentAttachment {
  return { id: 'a2', kind: 'image', name: 'foto.png', size: 51200, ...overrides }
}

export function mediaAttachment(overrides: Partial<AgentAttachment> = {}): AgentAttachment {
  return { id: 'a3', kind: 'media', name: 'aula.mp4', size: 4 * 1024 * 1024, path: 'C:/dm/cache/uploads/ab12-aula.mp4', ...overrides }
}

export function detail(overrides: Partial<AgentConversationDetail> = {}): AgentConversationDetail {
  return {
    id: 'c1',
    title: 'Valida o projeto',
    created_at: '2026-10-30T12:00:00.000+00:00',
    updated_at: '2026-10-30T12:05:00.000+00:00',
    mode: 'operate',
    model: 'gpt-oss:20b',
    effort: null,
    messages: 1,
    running: false,
    options: {},
    kits: [],
    mode_locked: true,
    running_job_id: null,
    pending_attachments: [],
    transcript: [],
    ...overrides,
  }
}

export function summaryOf(item: AgentConversationDetail): AgentConversationSummary {
  const { id, title, created_at, updated_at, mode, model, effort, messages, running } = item
  return { id, title, created_at, updated_at, mode, model, effort, messages, running }
}

export interface AgentServer extends RoutedFetch {
  state: { conversations: AgentConversationDetail[] }
}

/** As rotas do agente respondendo com `state.conversations`; `extra` troca ou acrescenta rotas. */
export function stubAgentServer(extra: Record<string, unknown> = {}, conversations: AgentConversationDetail[] = []): AgentServer {
  const state = { conversations }
  const routed = routedFetch({
    'GET /api/agent/status': STATUS,
    'GET /api/agent/models': MODELS,
    'GET /api/agent/loaded': { engine: 'ollama', models: [] },
    'GET /api/agent/conversations': () => ({ conversations: state.conversations.map(summaryOf) }),
    'GET /api/agent/conversations/c1': () =>
      state.conversations.find((item) => item.id === 'c1') ?? reply(404, { detail: 'Conversa desconhecida.' }),
    'POST /api/agent/messages': { job_id: 'j1', conversation_id: 'c1' },
    'POST /api/agent/conversations/c1/stop': { stopping: true, job_id: 'j1' },
    'POST /api/agent/confirmations/cf1': { approved: true },
    'POST /api/agent/confirmations/cf2': { approved: true },
    ...extra,
  })
  return Object.assign(routed, { state })
}

// ---------- o servidor que guarda a conversa: anexos, criar, mudar e enviar ----------

let active: AgentServer | null = null

function changeConversation(change: (item: AgentConversationDetail) => AgentConversationDetail): void {
  if (active) active.state.conversations = active.state.conversations.map((item) => (item.id === 'c1' ? change(item) : item))
}

/** Aplica um PATCH à conversa como o servidor faria. */
function patched(item: AgentConversationDetail, patch: AgentConversationPatch): AgentConversationDetail {
  const next = { ...item }
  if (patch.mode) next.mode = patch.mode
  if (patch.model) next.model = patch.model
  if (patch.title) next.title = patch.title
  if ('effort' in patch) next.effort = patch.effort ?? null
  if ('options' in patch) next.options = patch.options ?? {}
  return next
}

/**
 * O servidor de mentira com a conversa `c1` que vive no estado: criar nasce vazia (modo ainda livre), o PATCH muda, enviar
 * mensagem esvazia os anexos pendentes. Assim a releitura da conversa (que a tela faz depois de cada passo) traz o que o
 * servidor de verdade traria.
 */
export function stubConversationServer(extra: Record<string, unknown> = {}, conversations: AgentConversationDetail[] = []): AgentServer {
  const server: AgentServer = stubAgentServer(
    {
      'POST /api/agent/conversations': (call: RoutedCall) => {
        const body = call.body as { mode?: 'operate' | 'free'; model?: string; effort?: string | null; options?: object }
        const fresh = detail({
          messages: 0,
          mode_locked: false,
          mode: body.mode ?? 'operate',
          model: body.model ?? 'gpt-oss:20b',
          effort: body.effort ?? null,
          options: body.options ?? {},
          title: 'Nova conversa',
        })
        server.state.conversations = [fresh, ...server.state.conversations.filter((item) => item.id !== fresh.id)]
        return fresh
      },
      'PATCH /api/agent/conversations/c1': (call: RoutedCall) => {
        changeConversation((item) => patched(item, call.body as AgentConversationPatch))
        return server.state.conversations.find((item) => item.id === 'c1')
      },
      'POST /api/agent/messages': () => {
        changeConversation((item) => ({ ...item, pending_attachments: [], messages: item.messages + 1, mode_locked: true }))
        return { job_id: 'j1', conversation_id: 'c1' }
      },
      ...extra,
    },
    conversations,
  )
  active = server
  return server
}

export type Upload = AgentAttachment | ReplyWith

/** A rota de envio de arquivo: devolve o anexo e o guarda na conversa, como o servidor faria. */
export function uploads(make: (call: RoutedCall) => Upload | Promise<Upload>) {
  return async (call: RoutedCall) => {
    const result = await make(call)
    if (!('status' in result)) changeConversation((item) => ({ ...item, pending_attachments: [...item.pending_attachments, result] }))
    return result
  }
}

/** A rota que apaga um anexo pendente e o tira da conversa guardada. */
export function removes(attachmentId: string) {
  return () => {
    changeConversation((item) => ({ ...item, pending_attachments: item.pending_attachments.filter((one) => one.id !== attachmentId) }))
    return { deleted: attachmentId }
  }
}

/** Uma resposta que só chega quando o teste deixa, para ver o que a tela mostra enquanto o arquivo sobe. */
export function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}
