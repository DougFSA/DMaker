/* Cliente da fila de narrações longas (queue_routes.py). O andamento chega por SSE em `eventsUrl`:
   a fila inteira a cada mudança (use `subscribeJson`). */
import { http } from './http'
import type {
  QueueAdded,
  QueueCleared,
  QueueDirection,
  QueueFileRequest,
  QueueTextRequest,
  QueueView,
} from './types/queue'

const enc = encodeURIComponent
const base = '/api/voices/queue'

const action = (id: string, name: string) => `${base}/${enc(id)}/${name}`

export const queueApi = {
  /** Endereço do SSE com a fila inteira (uma foto a cada mudança). */
  eventsUrl: `${base}/events`,
  list: () => http.get<QueueView>(base),
  /** Põe um roteiro digitado ou colado no fim da fila. */
  addText: (request: QueueTextRequest) => http.post<QueueAdded>(base, request),
  /** Importa um roteiro de .txt, .md ou .docx. */
  addFile: (request: QueueFileRequest) => {
    const form = new FormData()
    form.append('file', request.file, request.filename ?? (request.file instanceof File ? request.file.name : 'roteiro.txt'))
    if (request.title) form.append('title', request.title)
    if (request.voice) form.append('voice', request.voice)
    if (request.language) form.append('language', request.language)
    if (request.speed !== undefined) form.append('speed', String(request.speed))
    if (request.brand) form.append('brand', request.brand)
    if (request.draft !== undefined) form.append('draft', String(request.draft))
    if (request.format) form.append('format', request.format)
    return http.postForm<QueueAdded>(`${base}/upload`, form)
  },
  /** Tira da fila os itens concluídos e cancelados; os que falharam ficam, para se ler o erro. */
  clearFinished: () => http.post<QueueCleared>(`${base}/clear-finished`),
  pause: (id: string) => http.post<QueueView>(action(id, 'pause')),
  resume: (id: string) => http.post<QueueView>(action(id, 'resume')),
  retry: (id: string) => http.post<QueueView>(action(id, 'retry')),
  cancel: (id: string) => http.post<QueueView>(action(id, 'cancel')),
  /** Sobe (-1) ou desce (1) um item que ainda não rodou. */
  move: (id: string, direction: QueueDirection) => http.post<QueueView>(action(id, 'move'), { direction }),
  remove: (id: string) => http.delete<QueueView>(`${base}/${enc(id)}`),
  /** Endereço de um arquivo pronto do item; `download` pede como anexo. */
  fileUrl: (id: string, name: string, download = false) =>
    `${base}/${enc(id)}/files/${enc(name)}${download ? '?download=true' : ''}`,
}
