/* Cliente do agente local (ui/agent_routes.py): o estado do servidor do modelo, o catálogo de modelos, as conversas
   salvas, o envio de mensagens (cada uma vira um job acompanhado pelo SSE), o Parar e a confirmação. */
import { http } from './http'
import type {
  AgentConversationCreate,
  AgentConversationDetail,
  AgentConversationPatch,
  AgentConversationSummary,
  AgentMessageRequest,
  AgentMessageResponse,
  AgentModels,
  AgentStatus,
} from './types/agent'

const enc = encodeURIComponent
const conversationPath = (id: string) => `/api/agent/conversations/${enc(id)}`

export const agentApi = {
  /** Motor, modelo padrão, se o servidor do modelo responde e os kits de ferramentas. */
  status: () => http.get<AgentStatus>('/api/agent/status'),
  /** Os modelos instalados com tamanho, capacidades, níveis de esforço e se cabem na memória (503 com o servidor fora do ar). */
  models: () => http.get<AgentModels>('/api/agent/models'),

  conversations: {
    list: async () => (await http.get<{ conversations: AgentConversationSummary[] }>('/api/agent/conversations')).conversations,
    /** A conversa já nasce gravada em disco; sem `model` vale o padrão do ambiente. */
    create: (body: AgentConversationCreate = {}) => http.post<AgentConversationDetail>('/api/agent/conversations', body),
    get: (id: string) => http.get<AgentConversationDetail>(conversationPath(id)),
    /** Título, modelo, esforço e opções. Trocar de modelo limpa o esforço que o novo não tem (o detalhe devolvido mostra). */
    update: (id: string, patch: AgentConversationPatch) => http.patch<AgentConversationDetail>(conversationPath(id), patch),
    /** Apaga o arquivo da conversa e a pasta dos anexos; 409 se ela está respondendo. */
    remove: (id: string) => http.delete<{ deleted: string }>(conversationPath(id)),
    /** O Parar: o mesmo que cancelar o job do turno; 409 se não há resposta em andamento. */
    stop: (id: string) => http.post<{ stopping: boolean; job_id: string }>(`${conversationPath(id)}/stop`),
  },

  /** Manda uma mensagem; o agente responde num job, acompanhado pelo SSE de `jobs.eventsUrl`. */
  send: (request: AgentMessageRequest) => http.post<AgentMessageResponse>('/api/agent/messages', request),
  /** Responde ao botão de confirmação (render final, apagar, sobrescrever, autorização da voz). */
  confirm: (conversationId: string, confirmationId: string, approve: boolean) =>
    http.post<{ approved: boolean }>(
      `/api/agent/confirmations/${enc(confirmationId)}?conversation_id=${enc(conversationId)}`,
      { approve },
    ),
}
