/* Tipos da fila de narrações (src/dmaker/ui/queue_routes.py). */

export type QueueItemState = 'pending' | 'running' | 'paused' | 'cancelled' | 'done' | 'failed'
export type QueueAudioFormat = 'wav' | 'mp3'

/** Como o item é narrado: o que a pessoa escolheu ao mandar o roteiro para a fila. */
export interface QueueItemOptions {
  voice: string | null
  language: string | null
  speed: number
  brand: string | null
  draft: boolean
  format: QueueAudioFormat
}

/** Um arquivo pronto de um item: áudio ou legenda (.srt), com a URL para ouvir e baixar. */
export interface QueueFile {
  name: string
  url: string
  audio: boolean
}

export interface QueueItem {
  id: string
  title: string
  state: QueueItemState
  state_label: string
  error: string | null
  /** Aviso curto do momento, por exemplo "Aguardando outra síntese terminar". */
  note: string
  source: { kind: 'text' | 'file'; name: string }
  options: QueueItemOptions
  chapter: number
  chapters_total: number
  chapter_title: string
  utterance: number
  utterances: number
  utterances_done: number
  utterances_total: number
  percent: number
  chars_left: number
  eta_seconds: number | null
  eta_label: string | null
  duration_s: number | null
  output_dir: string
  files: QueueFile[]
  created_at: number
  started_at: number | null
  finished_at: number | null
}

/** A fila inteira, como GET /api/voices/queue e o SSE de eventos a mandam. */
export interface QueueView {
  items: QueueItem[]
  eta_seconds: number | null
  eta_label: string | null
  running: boolean
  /** Há um executor da fila ativo neste servidor? Sem ele, os itens esperam parados. */
  worker?: boolean
}

/** Resposta de criar item e de apagar os concluídos: a fila atual mais o que a ação fez. */
export type QueueAdded = QueueView & { id: string }
export type QueueCleared = QueueView & { removed: number }

/** Roteiro digitado ou colado (POST /api/voices/queue). */
export interface QueueTextRequest {
  text: string
  title?: string | null
  voice?: string | null
  language?: string | null
  speed?: number
  brand?: string | null
  draft?: boolean
  format?: QueueAudioFormat
}

/** Roteiro importado de um arquivo .txt, .md ou .docx (POST /api/voices/queue/upload, multipart). */
export interface QueueFileRequest {
  file: Blob
  /** Nome do arquivo, que o servidor usa para escolher o leitor pela extensão. */
  filename?: string
  title?: string | null
  voice?: string | null
  language?: string | null
  speed?: number
  brand?: string | null
  draft?: boolean
  format?: QueueAudioFormat
}

/** Para onde mover um item que ainda não rodou: -1 sobe, 1 desce. */
export type QueueDirection = -1 | 1
