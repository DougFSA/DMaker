/* Cliente tipado da API do DMaker: uma função por rota usada pela interface. */
import { http } from './http'
import type {
  AppState,
  AutoCutRequest,
  BrowseResponse,
  CutReport,
  JobSnapshot,
  JobStartResponse,
  NewProjectRequest,
  NewProjectResponse,
  OutputFile,
  ProjectDetail,
  ProjectListItem,
  QaReport,
  RenderRequest,
  TemplateInfo,
  ValidationSummary,
} from './types'

const enc = encodeURIComponent

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

  outputs: {
    list: () => http.get<OutputFile[]>('/api/outputs'),
  },

  jobs: {
    list: () => http.get<JobSnapshot[]>('/api/jobs'),
    clearFinished: () => http.delete<{ removed: number }>('/api/jobs/finished'),
    eventsUrl: (jobId: string) => `/api/jobs/${enc(jobId)}/events`,
  },

  files: {
    browse: (path?: string) =>
      http.get<BrowseResponse>(path ? `/api/browse?path=${enc(path)}` : '/api/browse'),
  },

  clients: {
    /** Avisa o servidor que há uma interface aberta (evita abrir outra aba em renders pela CLI/MCP). */
    ping: () => http.post<{ ok: boolean }>('/api/clients/ping'),
  },
}

export { ApiError, errorMessage } from './http'
export type * from './types'
