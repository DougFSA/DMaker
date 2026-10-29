/* O servidor de mentira da tela da Fila: devolve a fila que o teste montou e guarda as chamadas. O andamento ao vivo
   o teste empurra pelo `FakeEventSource`. */
import { vi } from 'vitest'
import type { QueueItem, QueueView } from '@/api'
import { VOICES, type ServerCall } from './speechServer'

export interface QueueCall extends ServerCall {
  /** Os campos do multipart, quando a chamada enviou arquivo. */
  form: Record<string, string | File> | null
}

/** Um item da fila: um roteiro de texto, pendente, sem nada narrado ainda. */
export function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: 'q1',
    title: 'Primeiro roteiro',
    state: 'pending',
    state_label: 'Pendente',
    error: null,
    note: '',
    source: { kind: 'text', name: 'texto' },
    options: { voice: null, language: null, speed: 1, brand: null, draft: false, format: 'wav' },
    chapter: 0,
    chapters_total: 1,
    chapter_title: '',
    utterance: 0,
    utterances: 0,
    utterances_done: 0,
    utterances_total: 0,
    percent: 0,
    chars_left: 100,
    eta_seconds: 40,
    eta_label: '40 s',
    duration_s: null,
    output_dir: 'output/voz/primeiro-roteiro',
    files: [],
    created_at: 1_700_000_000,
    started_at: null,
    finished_at: null,
    ...overrides,
  }
}

export function queueView(items: QueueItem[] = [], overrides: Partial<QueueView> = {}): QueueView {
  const waiting = items.filter((item) => item.state === 'pending' || item.state === 'running')
  return {
    items,
    eta_seconds: waiting.length ? 40 * waiting.length : null,
    eta_label: waiting.length ? `${40 * waiting.length} s` : null,
    running: items.some((item) => item.state === 'running'),
    worker: true,
    ...overrides,
  }
}

/** Um item pronto, com o áudio e a legenda que a fila gera. */
export function finishedItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return queueItem({
    id: 'q9',
    title: 'Roteiro pronto',
    state: 'done',
    state_label: 'Concluído',
    percent: 100,
    chars_left: 0,
    eta_seconds: null,
    eta_label: null,
    duration_s: 125,
    files: [
      { name: 'roteiro-pronto.wav', url: '/api/voices/queue/q9/files/roteiro-pronto.wav', audio: true },
      { name: 'roteiro-pronto.srt', url: '/api/voices/queue/q9/files/roteiro-pronto.srt', audio: false },
    ],
    ...overrides,
  })
}

export interface QueueServerOptions {
  /** A fila que as leituras devolvem. */
  view?: QueueView
  /** A resposta de cada rota de ação ou de entrada, pela chave "MÉTODO caminho"; o padrão é a fila sem mudança. */
  replies?: Record<string, { body: unknown; status?: number }>
  /** Faz a leitura da fila falhar com este erro (o servidor sem o arquivo da fila, por exemplo). */
  listFailure?: string
}

export interface QueueServer {
  calls: QueueCall[]
}

function readForm(form: FormData): Record<string, string | File> {
  const fields: Record<string, string | File> = {}
  form.forEach((value, key) => {
    fields[key] = value
  })
  return fields
}

/** Instala o `fetch` falso. As rotas de ação respondem com a fila sem mudança, a menos que `replies` diga outra coisa. */
export function stubQueueServer(options: QueueServerOptions = {}): QueueServer {
  const server: QueueServer = { calls: [] }
  const view = options.view ?? queueView()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const isForm = init.body instanceof FormData
      const body = init.body && !isForm ? JSON.parse(String(init.body)) : undefined
      server.calls.push({ method, url, body, form: isForm ? readForm(init.body as FormData) : null })
      const path = url.split('?')[0]!
      const reply = (payload: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(payload), { status }))

      const scripted = options.replies?.[`${method} ${path}`]
      if (scripted) return reply(scripted.body, scripted.status)
      if (path === '/api/voices/queue' && method === 'GET') {
        return options.listFailure ? reply({ detail: options.listFailure }, 500) : reply(view)
      }
      if (path === '/api/voices' && method === 'GET') return reply(VOICES)
      if (path === '/api/voices/design-options') return reply({ languages: [{ value: 'pt', label: 'Português' }] })
      if (path === '/api/state') return reply({ presets: [], brands: [], projects: [] })
      if (path === '/api/templates') return reply([])
      if (path.startsWith('/api/voices/queue')) {
        return reply(path === '/api/voices/queue/upload' ? { id: 'novo', ...view } : view)
      }
      return reply({ detail: `rota sem resposta no teste: ${method} ${url}` }, 404)
    }),
  )
  return server
}

/** As chamadas a uma rota, na ordem. */
export function queueCallsTo(server: QueueServer, method: string, url: string): QueueCall[] {
  return server.calls.filter((call) => call.method === method && call.url === url)
}
