/* Cliente da dublagem: preparar, revisar as traduções, gerar o vídeo dublado e exportar as trilhas
   (dub_routes.py). O projeto `.dub.json` vive em output/dublagem e o servidor só abre arquivos de lá. */
import { http, withQuery } from './http'
import type { JobStartResponse } from './types'
import type { DubPrepareRequest, DubProjectFile, DubProjectSummary, DubProjectUpdate } from './types/dub'

export const dubApi = {
  /** Os projetos de dublagem já preparados, do mais novo ao mais antigo. */
  projects: () => http.get<DubProjectFile[]>('/api/dub/projects'),
  /** Transcreve, separa os falantes e traduz (job); o resultado é o projeto pronto para revisar. */
  prepare: (request: DubPrepareRequest) => http.post<JobStartResponse>('/api/dub/prepare', request),
  project: (path: string) => http.get<DubProjectSummary>(withQuery('/api/dub/project', { path })),
  /** Grava as traduções, as travas, os falantes e as opções; devolve o projeto como ficou. */
  saveProject: (update: DubProjectUpdate) => http.put<DubProjectSummary>('/api/dub/project', update),
  /** Traduz de novo só as falas que não estão travadas (job). */
  retranslate: (project: string) => http.post<JobStartResponse>('/api/dub/retranslate', { project }),
  /** Gera o vídeo ou áudio dublado e a legenda .srt (job). `draft` troca qualidade por velocidade. */
  render: (project: string, draft = false) => http.post<JobStartResponse>('/api/dub/render', { project, draft }),
  /** Exporta as trilhas separadas num .zip (job). */
  stems: (project: string, draft = false) => http.post<JobStartResponse>('/api/dub/stems', { project, draft }),
  /** Endereço de um arquivo de output/dublagem (.srt, .zip ou .dub.json); `download` pede como anexo. */
  fileUrl: (path: string, download = false) =>
    withQuery('/api/dub/file', { path, download: download ? true : null }),
}
