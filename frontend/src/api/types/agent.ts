/* Tipos do agente local (src/dmaker/ui/agent_routes.py e agent_conversations.py): o estado do servidor do modelo,
   o catálogo de modelos, as conversas salvas, a transcrição e os eventos do turno pelo SSE. */
import type { JobProgress } from '../types'

/** Um kit de ferramentas do agente local (GET /api/agent/status). */
export interface AgentKit {
  name: string
  title: string
  description: string
  /** Quantas ferramentas do kit o servidor tem de fato. */
  tools: number
}

export type AgentEngine = 'ollama' | 'openai'

export interface AgentStatus {
  engine: AgentEngine
  engine_label: string
  model: string
  url: string
  free_html: boolean
  reachable: boolean
  model_installed: boolean
  kits: AgentKit[]
}

/** "Operar o DMaker" usa as ferramentas; "Conversa livre" só conversa. O modo trava na primeira mensagem. */
export type AgentMode = 'operate' | 'free'

/** O que o modelo faz; o servidor pode mandar outras além destas. */
export type AgentCapability = 'vision' | 'tools' | 'thinking' | (string & {})

/** Cabe na memória do computador? `tight` sobra menos de 1,5 GB; `too_big` o modelo é maior que a memória inteira. */
export type AgentFit = 'fits' | 'tight' | 'too_big' | 'unknown'

/** Um nível do seletor de esforço: `value` é o que se guarda na conversa e `label` o que a tela mostra. */
export interface AgentEffortLevel {
  value: string
  label: string
}

/** Um modelo instalado (GET /api/agent/models). No motor compatível com a OpenAI vêm `size` nulo e listas vazias. */
export interface AgentModel {
  name: string
  size: number | null
  family: string
  capabilities: AgentCapability[]
  context_length: number | null
  effort_levels: AgentEffortLevel[]
  default_effort: string | null
  fit: AgentFit
  loaded: boolean
}

export interface AgentMemory {
  total: number
  available: number
}

export interface AgentModels {
  engine: AgentEngine
  default_model: string
  memory: AgentMemory | null
  models: AgentModel[]
}

/** As opções avançadas de uma conversa; o que é nulo vale o padrão do ambiente. */
export interface AgentOptions {
  num_ctx?: number | null
  temperature?: number | null
  seed?: number | null
}

/**
 * O que o servidor faz de cada tipo de anexo: `image` segue ao modelo como imagem, `media` (vídeo e áudio) e `sheet`
 * entram como caminho no texto, `text` (documento) entra como bloco de texto.
 */
export type AttachmentKind = 'image' | 'media' | 'sheet' | 'text'

/** A prévia de uma planilha anexada: as primeiras linhas. */
export interface AgentSheetPreview {
  columns: string[]
  rows: string[][]
  rows_total: number
  columns_total: number
}

/** Um anexo que ainda espera a mensagem (POST /conversations/{id}/attachments e `pending_attachments` do detalhe). */
export interface AgentAttachment {
  id: string
  kind: AttachmentKind
  name: string
  size: number
  /** Vídeo, áudio, planilha e a imagem do modo Operar: o caminho no computador, que entra no texto da mensagem. */
  path?: string
  /** Texto: quantos caracteres vão ao modelo com o contexto de agora, e quantos o arquivo tem. */
  chars?: number
  total_chars?: number
  truncated?: boolean
  preview?: AgentSheetPreview | { excerpt: string }
}

/** A ficha que a transcrição guarda na mensagem enviada: só a referência, nunca o texto nem a imagem. */
export interface AgentAttachmentSummary {
  id: string
  kind: AttachmentKind
  name: string
  size: number
  chars?: number | null
  total_chars?: number | null
  truncated?: boolean
}

/** Uma linha da lista de conversas (GET /api/agent/conversations), a mais recente primeiro. */
export interface AgentConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  mode: AgentMode
  model: string
  effort: string | null
  /** Quantas mensagens da pessoa a conversa tem; vazia é 0. */
  messages: number
  running: boolean
}

export type ConfirmationType = 'action' | 'voice_consent'
export type TranscriptToolState = 'running' | 'done' | 'error' | 'blocked' | 'interrupted'
export type TranscriptConfirmationState = 'pending' | 'approved' | 'refused' | 'unconfirmed'
export type NoticeLevel = 'info' | 'warning' | 'error'
export type NoticeCode = 'history_trimmed' | 'interrupted' | 'unfinished' | 'save_failed' | 'error'

/** A transcrição que o servidor guarda e a tela desenha com os mesmos componentes do turno ao vivo. */
export type TranscriptEntry =
  | { kind: 'user'; id: string; text: string; at: string; attachments?: AgentAttachmentSummary[] }
  | { kind: 'kits'; id: string; kits: string[]; method: string }
  | { kind: 'thinking'; id: string; text: string }
  | {
      kind: 'tool'
      id: string
      name: string
      arguments: Record<string, unknown>
      state: TranscriptToolState
      detail: string
      result: string
    }
  | {
      kind: 'confirmation'
      id: string
      confirmation_id: string
      tool: string
      question: string
      type: ConfirmationType
      state: TranscriptConfirmationState
    }
  | { kind: 'answer'; id: string; text: string; interrupted: boolean }
  | { kind: 'notice'; id: string; level: NoticeLevel; code: NoticeCode; text: string }

/** GET, POST e PATCH de uma conversa: o resumo, mais as opções, os kits e a transcrição. */
export interface AgentConversationDetail extends AgentConversationSummary {
  options: AgentOptions
  kits: string[]
  /** Verdadeiro depois da primeira mensagem: o modo não muda mais. */
  mode_locked: boolean
  /** O job do turno em andamento, quando a página foi recarregada no meio de uma resposta. */
  running_job_id: string | null
  /** Os anexos já enviados ao servidor que esperam a mensagem; sobrevivem a recarregar a página e a reiniciar o DMaker. */
  pending_attachments: AgentAttachment[]
  transcript: TranscriptEntry[]
}

export interface AgentMessageResponse {
  job_id: string
  conversation_id: string
}

/** Corpo de POST /api/agent/messages. Sem `conversation_id` o servidor cria a conversa com `mode`, `model` e o resto. */
export interface AgentMessageRequest {
  message: string
  conversation_id?: string | null
  mode?: AgentMode
  model?: string
  /** Sem a chave o esforço continua; `null` volta ao padrão do modelo. */
  effort?: string | null
  options?: AgentOptions
  /** Os ids dos anexos desta mensagem (no máximo 8); exige `conversation_id` e uma mensagem com ao menos um caractere. */
  attachments?: string[]
}

/** Corpo de PATCH /api/agent/conversations/{id}: só muda o que vier. */
export interface AgentConversationPatch {
  title?: string
  /** Só vale enquanto a conversa não teve mensagem (409 depois). */
  mode?: AgentMode
  model?: string
  effort?: string | null
  options?: AgentOptions | null
}

export interface AgentConversationCreate {
  mode?: AgentMode
  model?: string
  effort?: string | null
  options?: AgentOptions
}

/** Um modelo carregado na memória agora (GET /api/agent/loaded, só no Ollama). */
export interface AgentLoadedModel {
  name: string
  /** Bytes que o modelo ocupa na memória, e quantos deles estão na placa de vídeo. */
  size: number
  size_vram: number
  context_length: number | null
  /** Quando o Ollama descarrega o modelo sozinho, em ISO. */
  expires_at: string | null
}

export interface AgentLoaded {
  engine: AgentEngine
  models: AgentLoadedModel[]
}

/** O corpo cru do 422 de uma mensagem com imagem para um modelo que não enxerga. */
export interface AgentVisionRefusal {
  detail: string
  error: string
  suggested_models: string[]
}

/** As etapas do `status`: o que o agente está fazendo agora. */
export type AgentStage = 'loading_model' | 'reading' | 'thinking' | 'writing' | 'tool'

/** Eventos que o agente manda pelo SSE do job (além de start, progress, log e end, comuns a todo job). */
export type AgentEvent =
  | { kind: 'triage'; t: number; kits: string[]; method: string }
  | { kind: 'status'; t: number; stage: AgentStage; label: string; tool?: string }
  | { kind: 'model_reply'; t: number; seconds: number; tool_calls: number }
  | { kind: 'thinking_delta'; t: number; text: string }
  | { kind: 'answer_delta'; t: number; text: string }
  | { kind: 'thinking'; t: number; text: string }
  | { kind: 'tool_call'; t: number; name: string; arguments: Record<string, unknown> }
  | { kind: 'tool_blocked'; t: number; name: string; reason: string }
  | { kind: 'tool_result'; t: number; name: string; result: string }
  | { kind: 'tool_progress'; t: number; name: string; status: string | null; progress: Partial<JobProgress> }
  | { kind: 'confirmation_request'; t: number; id: string; tool: string; question: string; type: ConfirmationType }
  | { kind: 'confirmation_answered'; t: number; id: string; approved: boolean }
  | { kind: 'history_trimmed'; t: number; turns: number; text: string }
  /** `interrupted` só existe quando a pessoa parou a resposta. */
  | { kind: 'answer'; t: number; text: string; interrupted?: boolean }
