/* Apoio dos testes do agente: o servidor de mentira com as rotas de /api/agent, os modelos e as conversas de exemplo.
   O teste troca `state.conversations` e, quando precisa de outra resposta, passa a rota em `extra`. */
import type { AgentConversationDetail, AgentConversationSummary, AgentModel, AgentModels, AgentStatus } from '@/api'
import { reply, routedFetch, type RoutedFetch } from './routedFetch'

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
