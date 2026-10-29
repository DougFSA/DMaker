/* Cliente tipado da API do DMaker: uma função por rota usada pela interface. */
import { http } from './http'
import type {
  AgentMessageResponse,
  AgentStatus,
  AppState,
  AutoCutRequest,
  BatchListItem,
  BatchReport,
  BatchResumeRequest,
  BatchStartRequest,
  BatchStartResponse,
  BatchValidateRequest,
  BatchValidation,
  BrowseResponse,
  CutReport,
  JobSnapshot,
  JobStartResponse,
  LookCatalog,
  NewProjectRequest,
  NewProjectResponse,
  OutputFile,
  ProjectDetail,
  ProjectListItem,
  QaReport,
  RenderRequest,
  TemplateInfo,
  TransitionCatalog,
  TransitionCurve,
  ValidationSummary,
} from './types'

const enc = encodeURIComponent

/** `?brand=` só quando há marca: sem ela a rota devolve os looks padrão. */
const brandQuery = (brand?: string) => (brand && brand !== 'default' ? `?brand=${enc(brand)}` : '')

export const api = {
  state: () => http.get<AppState>('/api/state'),

  projects: {
    list: () => http.get<ProjectListItem[]>('/api/projects'),
    get: (name: string) => http.get<ProjectDetail>(`/api/projects/${enc(name)}`),
    create: (request: NewProjectRequest) => http.post<NewProjectResponse>('/api/projects', request),
    validate: (name: string) => http.post<ValidationSummary>(`/api/projects/${enc(name)}/validate`),
    qa: (name: string) => http.post<QaReport>(`/api/projects/${enc(name)}/qa`),
    render: (name: string, request: RenderRequest) =>
      http.post<JobStartResponse>(`/api/projects/${enc(name)}/render`, request),
    export: (name: string, presets: string[]) =>
      http.post<JobStartResponse>(`/api/projects/${enc(name)}/export`, { presets }),
    /** Devolve ao projeto o trecho de um corte automático; responde com a lista de cortes atualizada. */
    undoCut: (name: string, cutId: number) =>
      http.post<CutReport>(`/api/projects/${enc(name)}/cuts/${cutId}/undo`),
  },

  autocut: {
    /** Corta as pausas, os vícios e as repetições de uma gravação num projeto novo (job com progresso). */
    start: (request: AutoCutRequest) => http.post<JobStartResponse>('/api/autocut', request),
  },

  templates: {
    list: () => http.get<TemplateInfo[]>('/api/templates'),
  },

  batches: {
    list: () => http.get<{ batches: BatchListItem[] }>('/api/batches'),
    /** Confere a planilha contra o modelo sem renderizar nada. */
    validate: (request: BatchValidateRequest) => http.post<BatchValidation>('/api/batches/validate', request),
    /** Cria um projeto por linha e renderiza tudo num job; linha com problema só fica de fora com `skip_invalid`. */
    start: (request: BatchStartRequest) => http.post<BatchStartResponse>('/api/batches', request),
    get: (name: string) => http.get<BatchReport>(`/api/batches/${enc(name)}`),
    resume: (name: string, request: BatchResumeRequest = {}) =>
      http.post<BatchStartResponse>(`/api/batches/${enc(name)}/resume`, request),
    /** Para depois do vídeo em andamento; nada se perde. */
    pause: (name: string) => http.post<{ name: string; pause_requested: boolean }>(`/api/batches/${enc(name)}/pause`),
    remove: (name: string) => http.delete<{ removed: string }>(`/api/batches/${enc(name)}`),
  },

  outputs: {
    list: () => http.get<OutputFile[]>('/api/outputs'),
  },

  transitions: {
    catalog: () => http.get<TransitionCatalog>('/api/transitions'),
    /** Folha de contato (PNG) da transição; o servidor gera na primeira vez e guarda em cache. */
    sheetUrl: (name: string, curve: TransitionCurve) => `/api/transitions/${enc(name)}/sheet?curve=${enc(curve)}`,
  },

  looks: {
    /** `brand` soma os looks do brand.json da marca (os dela valem no lugar dos padrões de mesmo nome). */
    catalog: (brand?: string) => http.get<LookCatalog>(`/api/looks${brandQuery(brand)}`),
    /** Folha de contato (JPEG) de um look: a cena de teste sem acabamento e com ele; gerada na primeira vez. */
    sheetUrl: (name: string, brand?: string) => `/api/looks/${enc(name)}/sheet${brandQuery(brand)}`,
    /** Folha com todos os looks lado a lado. */
    overviewUrl: (brand?: string) => `/api/looks/sheet${brandQuery(brand)}`,
  },

  agent: {
    /** Motor, modelo, se o servidor do modelo responde e os kits de ferramentas. */
    status: () => http.get<AgentStatus>('/api/agent/status'),
    /** Manda uma mensagem; o agente responde num job, acompanhado pelo SSE de `jobs.eventsUrl`. */
    send: (message: string, conversationId: string | null) =>
      http.post<AgentMessageResponse>('/api/agent/messages', { message, conversation_id: conversationId }),
    /** Responde ao botão de confirmação (render final, apagar, sobrescrever, autorização da voz). */
    confirm: (conversationId: string, confirmationId: string, approve: boolean) =>
      http.post<{ approved: boolean }>(
        `/api/agent/confirmations/${enc(confirmationId)}?conversation_id=${enc(conversationId)}`,
        { approve },
      ),
    reset: (conversationId: string) => http.delete<{ reset: string }>(`/api/agent/conversations/${enc(conversationId)}`),
  },

  jobs: {
    list: () => http.get<JobSnapshot[]>('/api/jobs'),
    clearFinished: () => http.delete<{ removed: number }>('/api/jobs/finished'),
    eventsUrl: (jobId: string) => `/api/jobs/${enc(jobId)}/events`,
  },

  files: {
    /** `kind: 'sheet'` mostra as planilhas de lote (.csv, .xlsx, .json) no lugar da mídia. */
    browse: (path?: string, kind: 'media' | 'sheet' = 'media') => {
      const query = [path ? `path=${enc(path)}` : '', kind === 'sheet' ? 'kind=sheet' : ''].filter(Boolean)
      return http.get<BrowseResponse>(query.length ? `/api/browse?${query.join('&')}` : '/api/browse')
    },
  },

  clients: {
    /** Avisa o servidor que há uma interface aberta (evita abrir outra aba em renders pela CLI/MCP). */
    ping: () => http.post<{ ok: boolean }>('/api/clients/ping'),
  },
}

export { ApiError, errorMessage } from './http'
export type * from './types'
