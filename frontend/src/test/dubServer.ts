/* O servidor de mentira da tela de Dublagem. Soma às rotas do `speechServer` (projeto aberto, vozes, envio) as da
   dublagem: lista e abre projetos `.dub.json`, salva as edições como o servidor faria, e dá um `job_id` a cada
   trabalho (o teste empurra os eventos pelo EventSource falso). */
import { vi } from 'vitest'
import type { DubProjectSummary, DubSegment } from '@/api'
import { stubSpeechServer, CLIP, type ServerCall, type SpeechServerOptions } from './speechServer'

export const DUB_PATH = 'X:/saida/dublagem/entrevista.en.dub.json'

export const LANGUAGES = [
  { value: 'pt', label: 'Português' },
  { value: 'en', label: 'Inglês' },
  { value: 'es', label: 'Espanhol' },
]

export const SEGMENTS: DubSegment[] = [
  { id: 's1', start: 0, end: 2.5, original: 'Olá a todos.', text: 'Hello everyone.', locked: false, speaker: null },
  { id: 's2', start: 3, end: 5.5, original: 'Hoje vamos falar de vídeo.', text: 'Today we talk about video.', locked: true, speaker: null },
  { id: 's3', start: 6, end: 9, original: 'Até a próxima.', text: 'See you next time.', locked: false, speaker: null },
]

export function dubProject(over: Partial<DubProjectSummary> = {}): DubProjectSummary {
  return {
    project: DUB_PATH,
    source: CLIP,
    source_url: '/api/file?path=entrevista',
    source_language: 'pt',
    target_language: 'en',
    speaker_mode: 'per_segment',
    speakers: [],
    voice: null,
    keep_original_db: null,
    fit_mode: 'voz',
    glossary: [],
    translator_model: 'tradutor-falso',
    segments: SEGMENTS.map((segment) => ({ ...segment })),
    ...over,
  }
}

export interface DubServerOptions extends SpeechServerOptions {
  /** O projeto de dublagem que o servidor tem em disco (some se for `null`). */
  project?: DubProjectSummary | null
  /** Faz o salvar falhar com esta mensagem. */
  saveError?: string
}

export interface DubServer {
  calls: ServerCall[]
  /** O projeto como o servidor o guardou; muda quando o teste salva. */
  project: DubProjectSummary | null
  /** O corpo do último PUT /api/dub/project. */
  lastSave: () => Record<string, unknown> | undefined
}

/** Instala o `fetch` falso (as rotas da dublagem primeiro, as do projeto e das vozes pelo `speechServer`). */
export function stubDubServer(options: DubServerOptions = {}): DubServer {
  stubSpeechServer(options)
  const baseFetch = globalThis.fetch
  const calls: ServerCall[] = []
  const server: DubServer = {
    calls,
    project: options.project === undefined ? dubProject() : options.project,
    lastSave: () => calls.filter((call) => call.method === 'PUT' && call.url === '/api/dub/project').at(-1)?.body as Record<string, unknown> | undefined,
  }
  let jobs = 0

  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const body = init.body && !(init.body instanceof FormData) ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })
      const reply = (payload: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(payload), { status }))
      const path = url.split('?')[0]

      if (url === '/api/voices/design-options') return reply({ gender: [], age: [], pitch: [], accent: [], languages: LANGUAGES })
      if (url === '/api/dub/projects') return reply(server.project ? [{ path: server.project.project, name: 'entrevista.en.dub.json' }] : [])
      if (path === '/api/dub/project' && method === 'GET') {
        return server.project ? reply(server.project) : reply({ detail: 'Projeto de dublagem não encontrado: entrevista.en.dub.json' }, 404)
      }
      if (path === '/api/dub/project' && method === 'PUT') {
        if (options.saveError) return reply({ detail: options.saveError }, 400)
        const current = server.project
        if (!current) return reply({ detail: 'sem projeto' }, 404)
        const edits = new Map<string, { text: string; locked: boolean; speaker?: string }>(
          (body.segments as Array<{ id: string; text: string; locked: boolean; speaker?: string }>).map((edit) => [edit.id, edit]),
        )
        server.project = {
          ...current,
          keep_original_db: body.keep_original_db ?? null,
          speaker_mode: body.speaker_mode ?? current.speaker_mode,
          fit_mode: body.fit_mode ?? current.fit_mode,
          voice: body.voice ?? null,
          segments: current.segments.map((segment) => {
            const edit = edits.get(segment.id)
            return edit ? { ...segment, text: edit.text, locked: edit.locked, speaker: edit.speaker ?? segment.speaker } : segment
          }),
        }
        return reply(server.project)
      }
      if (/^\/api\/dub\/(prepare|retranslate|render|stems)$/.test(path ?? '')) {
        if (options.startReply) return reply(options.startReply.body, options.startReply.status)
        jobs += 1
        return reply({ job_id: `j${jobs}` })
      }
      if (/^\/api\/jobs\/[^/]+\/cancel$/.test(path ?? '')) return reply({ id: path?.split('/')[3], status: 'running', cancellable: true })
      return baseFetch(url, init)
    }),
  )
  return server
}

/** O resultado de gerar a dublagem, como o servidor o devolve. */
export function renderResult(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    output: 'X:/saida/dublagem/entrevista.en.mp4',
    output_url: '/api/voices/audio?path=dublado',
    download_url: '/api/voices/audio?path=dublado&download=true',
    srt: 'X:/saida/dublagem/entrevista.en.srt',
    srt_url: '/api/dub/file?path=legenda&download=true',
    original: CLIP,
    original_url: '/api/file?path=entrevista',
    report: [
      { id: 's1', start: 0, end: 2.5, text: 'Hello everyone.', natural_seconds: 1.2, speech_seconds: 1.2, played_seconds: 1.2, tempo: 1, video_stretch: 1, retimed_start: null, status: 'fits', message: 'Cabe no tempo.', cached: false, speaker: '', voice: 'dora' },
      { id: 's2', start: 3, end: 5.5, text: 'Today we talk about video.', natural_seconds: 3, speech_seconds: 2.5, played_seconds: 2.5, tempo: 1.2, video_stretch: 1, retimed_start: null, status: 'squeezed', message: 'Foi comprimida.', cached: true, speaker: '', voice: 'dora' },
      { id: 's3', start: 6, end: 9, text: 'See you next time.', natural_seconds: 4, speech_seconds: 4, played_seconds: 4, tempo: 1, video_stretch: 1.25, retimed_start: null, status: 'stretched', message: 'Vídeo esticado.', cached: false, speaker: '', voice: 'dora' },
    ],
    fit_mode: 'misto',
    output_seconds: 11.5,
    stretched: [{ id: 's3', start: 6, factor: 1.25, added_seconds: 1 }],
    warnings: [],
    regenerated: 2,
    timings: { 'Síntese das falas': 6.4, Montagem: 1.1 },
    ...over,
  }
}
