/* Cliente da gravação pelo microfone (ui/recording_routes.py): abrir, mandar um pedaço de um segundo por vez, finalizar e
   listar o que a aba deixou aberta. Os pedaços vão como bytes crus (float32 intercalado), por isso o envio usa o `fetch`
   direto, e não o `http` que fala JSON. */
import { ApiError, http, messageFromDetail } from './http'
import type { EditOperation } from './types/editor'
import type {
  PunchRange,
  RecordingFinish,
  RecordingOpenRequest,
  RecordingStatus,
} from './types/recordings'

const base = (project: string) => `/api/projects/${encodeURIComponent(project)}/recordings`

export const recordingsApi = {
  open: (project: string, request: RecordingOpenRequest) => http.post<RecordingStatus>(base(project), request),

  /** Manda o pedaço `seq`. Repetir o mesmo número não duplica nada no servidor. */
  async putChunk(project: string, id: string, seq: number, bytes: Uint8Array<ArrayBuffer>): Promise<void> {
    let response: Response
    try {
      response = await fetch(`${base(project)}/${encodeURIComponent(id)}/chunks/${seq}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: bytes,
      })
    } catch {
      throw new ApiError(0, 'Não foi possível falar com o servidor do DMaker. Ele está rodando?')
    }
    if (!response.ok) {
      const detail = await response
        .json()
        .then((data: { detail?: unknown }) => data.detail)
        .catch(() => null)
      throw new ApiError(response.status, messageFromDetail(detail, `Erro ${response.status} ao enviar o pedaço ${seq}`))
    }
  },

  finish: (project: string, id: string, body: { start?: number; label?: string; punch?: PunchRange } = {}) =>
    http.post<RecordingFinish>(`${base(project)}/${encodeURIComponent(id)}/finish`, body),

  list: (project: string, unfinished = false) =>
    http.get<{ recordings: RecordingStatus[] }>(`${base(project)}${unfinished ? '?unfinished=true' : ''}`),

  discard: (project: string, id: string) => http.delete<{ discarded: string }>(`${base(project)}/${encodeURIComponent(id)}`),
}

export type { EditOperation }
