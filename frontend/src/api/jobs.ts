/* Cliente dos jobs em segundo plano (ui/server.py): listar, limpar, acompanhar por SSE e parar. */
import { http } from './http'
import type { JobSnapshot } from './types'

const enc = encodeURIComponent

export const jobsApi = {
  list: () => http.get<JobSnapshot[]>('/api/jobs'),
  clearFinished: () => http.delete<{ removed: number }>('/api/jobs/finished'),
  eventsUrl: (jobId: string) => `/api/jobs/${enc(jobId)}/events`,
  /** Pede ao job para parar no próximo ponto seguro. Só vale para os que `cancellable` diz que aceitam (409 nos outros). */
  cancel: (jobId: string) => http.post<JobSnapshot>(`/api/jobs/${enc(jobId)}/cancel`),
}
