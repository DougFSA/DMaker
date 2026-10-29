/* Cliente do editor: salvar a spec, legendas, linha do tempo, edição por operação, tema, proxies, mídia,
   forma de onda, sincronização, conferência do vídeo e layouts de tela (rotas de ui/server.py que a
   interface clássica já usava). Ler o projeto, validar, renderizar e exportar continuam em `api.projects`. */
import { http, withQuery } from './http'
import type {
  CaptionCue,
  CaptionsDocument,
  CaptionsSaved,
  CardPreviewParams,
  EditOperation,
  EditResponse,
  PreviewAudioStatus,
  ProbeEntry,
  ProjectTheme,
  ProxiesBuild,
  ProxyEntry,
  QaFrameRequest,
  QaFrameResponse,
  QaSheetRequest,
  QaSheetResponse,
  SaveProjectResponse,
  ScreenLayout,
  SpecDocument,
  SyncRequest,
  SyncResult,
  TimelineView,
  Waveform,
} from './types/editor'

const enc = encodeURIComponent
const project = (name: string) => `/api/projects/${enc(name)}`

export const editorApi = {
  /** Grava a spec do projeto (o servidor valida e responde 422 com a lista de erros se ela não vale). */
  saveProject: (name: string, spec: SpecDocument) => http.put<SaveProjectResponse>(project(name), spec),

  captions: {
    /** As legendas automáticas do projeto; 404 se ainda não foram geradas. */
    get: (name: string) => http.get<CaptionsDocument>(`${project(name)}/captions`),
    put: (name: string, cues: CaptionCue[]) => http.put<CaptionsSaved>(`${project(name)}/captions`, { cues }),
  },

  /** A vista multitrilha. Com `spec`, calcula sobre a edição ainda não salva; sem ela, sobre o arquivo do projeto. */
  timeline: (name: string, spec?: SpecDocument | null) =>
    http.post<TimelineView>(`${project(name)}/timeline`, { spec: spec ?? null }),
  /** Aplica uma operação de edição à spec dada e devolve a nova spec com a vista dela. Não grava nada. */
  edit: (name: string, spec: SpecDocument, op: EditOperation) =>
    http.post<EditResponse>(`${project(name)}/edit`, { spec, op }),
  previewAudio: {
    /** Pede a mixagem de áudio da prévia (a mesma do render, num arquivo leve) para a edição dada; já pronta no
     * cache volta com a URL, senão começa em segundo plano. Sem `spec`, vale a do arquivo do projeto. */
    request: (name: string, spec?: SpecDocument | null) =>
      http.post<PreviewAudioStatus>(`${project(name)}/preview-audio`, { spec: spec ?? null }),
    /** Como está a mixagem de uma chave pedida antes (consulta rápida enquanto ela é feita). */
    get: (name: string, key: string) =>
      http.get<PreviewAudioStatus>(withQuery(`${project(name)}/preview-audio`, { key })),
  },
  /** Cores, fonte e logos do projeto, para o player desenhar como o render. */
  theme: (name: string) => http.get<ProjectTheme>(`${project(name)}/theme`),

  proxies: {
    /** Se os proxies 540p (prévia ao vivo) de cada fonte de vídeo já existem. */
    get: (name: string) => http.get<ProxyEntry[]>(`${project(name)}/proxies`),
    /** Gera em segundo plano os que faltam; se já há um job rodando, devolve o mesmo. */
    build: (name: string) => http.post<ProxiesBuild>(`${project(name)}/proxies`),
  },

  /** Endereço do PNG de um cartão desenhado pelo servidor a partir só dos campos (prévia de edição não salva). */
  cardPreviewUrl: (params: CardPreviewParams) =>
    withQuery('/api/card-preview', {
      title: params.title,
      brand: params.brand,
      preset: params.preset,
      subtitle: params.subtitle,
      variant: params.variant,
      // o servidor assume logo ligado; só vale mandar quando a pessoa o desligou
      logo: params.logo === false ? false : null,
      background: params.background,
      width: params.width,
    }),

  /** O esquema JSON completo da spec (campos, tipos e padrões). */
  schema: () => http.get<Record<string, unknown>>('/api/schema'),
  /** Duração, tamanho e tipo de cada arquivo; os que falham voltam com `error` no lugar. */
  probe: (paths: string[]) => http.post<ProbeEntry[]>('/api/probe', { paths }),
  /** Picos da forma de onda de um áudio ou vídeo (gerados na primeira vez e guardados em cache). */
  waveform: (path: string, stream = 0) => http.get<Waveform>(withQuery('/api/waveform', { path, stream })),
  /** Deslocamento de cada fonte em relação à principal, medido pelo áudio. */
  sync: (request: SyncRequest) => http.post<SyncResult[]>('/api/sync', request),

  qa: {
    /** Grade de quadros igualmente espaçados do vídeo, numa imagem só. */
    sheet: (request: QaSheetRequest) => http.post<QaSheetResponse>('/api/qa/sheet', request),
    /** Um quadro do vídeo no instante `t`. */
    frame: (request: QaFrameRequest) => http.post<QaFrameResponse>('/api/qa/frame', request),
  },

  layouts: {
    /** Os layouts salvos pela pessoa; os embutidos (Edição, Efeitos...) vivem na própria interface. */
    list: () => http.get<{ layouts: Record<string, ScreenLayout> }>('/api/layouts'),
    save: (name: string, layout: ScreenLayout) => http.put<{ ok: boolean }>(`/api/layouts/${enc(name)}`, layout),
    remove: (name: string) => http.delete<{ ok: boolean }>(`/api/layouts/${enc(name)}`),
  },
}
