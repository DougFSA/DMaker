/* O servidor de mentira das telas de Narração e Pronúncia: a biblioteca de vozes, o projeto aberto, a narração, a fila
   e o dicionário de pronúncia (que guarda o que foi adicionado e removido, como o de verdade). */
import { vi } from 'vitest'
import type { PronunciationEntry } from '@/api'
import { bytesOf } from './audioContext'
import { PROJECT, VOICES, type ServerCall } from './speechServer'

export { PROJECT, VOICES }

export const DESIGN_OPTIONS = {
  gender: [{ value: 'female', label: 'feminino' }],
  age: [{ value: 'middle-aged', label: 'meia-idade' }],
  pitch: [{ value: 'low pitch', label: 'grave' }],
  accent: [{ value: 'british accent', label: 'britânico' }],
  languages: [
    { value: 'pt', label: 'Português' },
    { value: 'en', label: 'Inglês' },
  ],
}

export const BRANDS = [
  { key: 'default', name: 'Padrão', colors: {} },
  { key: 'medlycare', name: 'MedlyCare', colors: {} },
]

const NAR_ITEM = {
  id: 'NAR-0',
  kind: 'narration',
  index: 0,
  label: 'fala',
  start: 2,
  end: 9.5,
  in_point: 0,
  out_point: null,
  src: null,
  source: null,
  transition: null,
  muted: false,
  extra: {},
  path: null,
}

/** A vista de linha do tempo de um projeto com uma narração que termina em 9,5 s. */
export const TIMELINE_WITH_NARRATION = {
  total: 20,
  fps: 30,
  width: 1080,
  height: 1920,
  warnings: [],
  sources: {},
  tracks: [{ id: 'NAR', kind: 'audio', label: 'NAR', muted: false, hidden: false, locked: false, items: [NAR_ITEM] }],
}

export interface VoiceServerOptions {
  /** A spec do projeto aberto. */
  spec?: Record<string, unknown>
  /** A vista de linha do tempo; `null` faz a rota falhar com 500, como um projeto de fonte ausente. */
  timeline?: unknown | null
  /** Os termos que o dicionário já tem. */
  pronunciation?: PronunciationEntry[]
  /** Resposta de gerar narração (o padrão é 200 com `job_id`). */
  speakReply?: { body: unknown; status: number }
  /** Resposta de salvar o projeto (o padrão é 200). */
  saveReply?: { body: unknown; status: number }
  /** Resposta de mandar para a fila (o padrão é 200 com a fila de um item). */
  queueReply?: { body: unknown; status: number }
}

export interface VoiceServer {
  calls: ServerCall[]
  /** O dicionário como o servidor de mentira o guarda agora. */
  entries: PronunciationEntry[]
}

const defaultSpec = { name: PROJECT, timeline: [{ type: 'clip', src: 'D:/m/a.mp4' }], audio: { normalize: 'two-pass' } }

/** Instala o `fetch` falso e devolve as chamadas feitas, na ordem. */
export function stubVoiceServer(options: VoiceServerOptions = {}): VoiceServer {
  const server: VoiceServer = { calls: [], entries: [...(options.pronunciation ?? [])] }
  const spec = options.spec ?? defaultSpec
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const isForm = init.body instanceof FormData
      const body = init.body && !isForm ? JSON.parse(String(init.body)) : undefined
      server.calls.push({ method, url, body })
      const path = url.split('?')[0]!
      const reply = (payload: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(payload), { status }))

      if (path === '/api/voices' && method === 'GET') return reply(VOICES)
      if (path === '/api/voices/design-options') return reply(DESIGN_OPTIONS)
      if (path === '/api/state') return reply({ presets: [], brands: BRANDS, projects: [] })
      if (path === '/api/templates') return reply([])
      // um objeto simples, e não uma Response: ler o corpo de uma Response leva voltas do laço de eventos e o teste
      // só espera as promessas pendentes
      if (path === '/api/voices/audio') return Promise.resolve({ ok: true, arrayBuffer: async () => bytesOf(1) } as Response)
      if (path === '/api/voices/speak') {
        return options.speakReply ? reply(options.speakReply.body, options.speakReply.status) : reply({ job_id: 'j1' })
      }
      if (path === '/api/jobs/j1/cancel') return reply({ ok: true })
      if (path === '/api/voices/queue') {
        return options.queueReply ? reply(options.queueReply.body, options.queueReply.status) : reply({ id: 'q1', items: [] })
      }
      if (path === `/api/projects/${PROJECT}` && method === 'GET') {
        return reply({ name: PROJECT, spec_path: 'p', spec, captions_exists: false, outputs: [], cuts: null })
      }
      if (path === `/api/projects/${PROJECT}` && method === 'PUT') {
        return options.saveReply ? reply(options.saveReply.body, options.saveReply.status) : reply({ ok: true, spec_path: 'p' })
      }
      if (path === `/api/projects/${PROJECT}/timeline`) {
        return options.timeline === null
          ? reply({ detail: 'fonte ausente' }, 500)
          : reply(options.timeline ?? { ...TIMELINE_WITH_NARRATION, tracks: [] })
      }
      if (path === '/api/voices/pronunciation') {
        const query = new URLSearchParams(url.split('?')[1] ?? '')
        if (method === 'POST') {
          server.entries = [
            ...server.entries,
            { term: body.term, spoken: body.spoken, scope: body.brand ?? 'global', language: body.language },
          ]
        }
        if (method === 'DELETE') {
          server.entries = server.entries.filter(
            (entry) => !(entry.term === query.get('term') && entry.language === query.get('language')),
          )
        }
        return reply({ brand: query.get('brand'), entries: server.entries })
      }
      return reply({ detail: `rota sem resposta no teste: ${method} ${url}` }, 404)
    }),
  )
  return server
}

/** O evento `utterance` que o servidor manda quando uma fala fica pronta. */
export function utterance(index: number, total: number, pause = 0.35) {
  return {
    kind: 'utterance',
    t: index,
    index,
    total,
    audio_url: `/api/voices/audio?path=fala-${index}`,
    duration_s: 1,
    pause_after_s: pause,
  }
}

/** O resultado de um job de narração. */
export const NARRATION_RESULT = {
  output: 'X:/saida/narracao-ab12.wav',
  audio_url: '/api/voices/audio?path=narracao-ab12',
  duration_s: 12.4,
  cues: [{ start: 0, end: 3, text: 'Olá.' }],
}
