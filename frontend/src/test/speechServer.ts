/* O servidor de mentira das telas de áudio: responde ao projeto aberto, à biblioteca de vozes, ao envio de arquivo e às
   quatro rotas de trabalho (cada uma devolve um `job_id`; o teste empurra os eventos pelo EventSource falso). */
import type { VueWrapper } from '@vue/test-utils'
import { vi } from 'vitest'

export const PROJECT = 'demo'
export const CLIP = 'D:/m/entrevista.mp4'

export const VOICES = [
  { id: 'dora', name: 'Dora (feminina)', kind: 'preset', engine: 'kokoro', preset: 'pf_dora', language: 'pt', brand: null, instruct: null, reference: null, reference_text: null, created: '' },
  { id: 'entrevistado', name: 'Entrevistado', kind: 'clone', engine: 'omnivoice', preset: null, language: 'pt', brand: null, instruct: null, reference: 'r.wav', reference_text: null, created: '' },
]

export interface ServerCall {
  method: string
  url: string
  body: unknown
}

export interface SpeechServerOptions {
  /** A spec do projeto aberto; o padrão tem um trecho de vídeo e um vídeo sobreposto do mesmo arquivo. */
  spec?: Record<string, unknown>
  /** Resposta da rota que inicia o trabalho (o padrão é 200 com `job_id`). */
  startReply?: { body: unknown; status: number }
}

const defaultSpec = {
  name: PROJECT,
  timeline: [{ type: 'clip', src: CLIP }],
  overlays: [{ type: 'video', src: CLIP }],
}

/** Instala o `fetch` falso e devolve as chamadas feitas, na ordem. */
export function stubSpeechServer(options: SpeechServerOptions = {}): ServerCall[] {
  const calls: ServerCall[] = []
  const spec = options.spec ?? defaultSpec
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const isForm = init.body instanceof FormData
      const body = init.body && !isForm ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })
      const reply = (payload: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(payload), { status }))

      if (url === `/api/projects/${PROJECT}` && method === 'GET') {
        return reply({ name: PROJECT, spec_path: 'p', spec, captions_exists: false, outputs: [], cuts: null })
      }
      if (url === `/api/projects/${PROJECT}/edit`) {
        const next = structuredClone(body.spec) as Record<string, unknown>
        const keys = String(body.op.path).split('.')
        let cursor = next
        for (const key of keys.slice(0, -1)) cursor = cursor[key] as Record<string, unknown>
        cursor[keys.at(-1)!] = body.op.value
        return reply({ spec: next, timeline: {} })
      }
      if (url === `/api/projects/${PROJECT}` && method === 'PUT') return reply({ ok: true, spec_path: 'p' })
      if (url === '/api/voices') return reply(VOICES)
      if (url === '/api/speech/upload') return reply({ path: 'cache/uploads/abc-voz.wav', name: 'abc-voz.wav' })
      if (/^\/api\/speech\/(isolate|words|fix|convert)$/.test(url)) {
        return options.startReply ? reply(options.startReply.body, options.startReply.status) : reply({ job_id: 'j1' })
      }
      return reply({ detail: `rota sem resposta no teste: ${url}` }, 404)
    }),
  )
  return calls
}

/** As chamadas a uma rota, com o corpo já lido. */
export function callsTo(calls: ServerCall[], method: string, url: string): ServerCall[] {
  return calls.filter((call) => call.method === method && call.url === url)
}

/** O botão com este texto. */
export function buttonLabelled(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll('button').find((node) => node.text().includes(label))
  if (!found) throw new Error(`botão "${label}" não encontrado`)
  return found
}

/**
 * Aperta o botão como o navegador faria. O jsdom não envia um formulário que não está no documento, e as telas montam
 * sem `attachTo`; então o botão de enviar dispara o `submit` do formulário dele, e só se não estiver desligado.
 */
export async function press(wrapper: VueWrapper, label: string): Promise<void> {
  const target = buttonLabelled(wrapper, label)
  if (target.attributes('disabled') !== undefined) return
  const form = wrapper.findAll('form').find((candidate) => candidate.element.contains(target.element))
  if (form && target.attributes('type') === 'submit') await form.trigger('submit')
  else await target.trigger('click')
}
