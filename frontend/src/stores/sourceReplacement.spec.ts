import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MediaEntry } from '@/lib/media'
import { openEditor } from '@/test/editorMount'
import { timelineView } from '@/test/editorFixtures'
import { useSourceReplacementStore } from './sourceReplacement'

const spec = {
  name: 'demo',
  sources: { cam1: { src: 'D:/m/cam1.mp4' } },
  timeline: [{ type: 'clip', src: 'D:/m/a.mp4' }, { type: 'card' }, { type: 'clip', src: 'D:/m/a.mp4' }],
  overlays: [{ type: 'video', src: 'D:/m/a.mp4' }],
}

const fileEntry: MediaEntry = { id: 'file:D:/m/a.mp4', kind: 'clip', label: 'a.mp4', path: 'D:/m/a.mp4', src: 'D:/m/a.mp4' }

interface Call {
  method: string
  url: string
  body: unknown
}

/** O servidor de mentira: lê o projeto, aplica `set_field` como o /edit e grava na hora de salvar. */
function stubServer(options: { saveFails?: boolean } = {}): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const body = init.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })
      const answer = (payload: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(payload), { status }))
      if (method === 'GET') return answer({ name: 'demo', spec_path: 'p', spec, captions_exists: false, outputs: [], cuts: null })
      if (url.endsWith('/edit')) {
        const next = structuredClone(body.spec) as Record<string, unknown>
        const keys = String(body.op.path).split('.')
        let cursor = next as Record<string, unknown>
        for (const key of keys.slice(0, -1)) cursor = cursor[key] as Record<string, unknown>
        cursor[keys.at(-1)!] = body.op.value
        return answer({ spec: next, timeline: {} })
      }
      if (options.saveFails) return answer({ detail: 'Spec inválida.' }, 422)
      return answer({ ok: true, spec_path: 'p' })
    }),
  )
  return calls
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('sourceReplacement', () => {
  it('troca o arquivo em cada ponto que o projeto usa, uma operação por vez, e salva a spec final', async () => {
    const calls = stubServer()
    const store = useSourceReplacementStore()

    const points = await store.replace('demo', fileEntry, 'output/correcao/a.corrigido.mp4')

    expect(points).toBe(3)
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      'GET /api/projects/demo',
      'POST /api/projects/demo/edit',
      'POST /api/projects/demo/edit',
      'POST /api/projects/demo/edit',
      'PUT /api/projects/demo',
    ])
    expect(calls.slice(1, 4).map((call) => (call.body as { op: { path: string } }).op.path)).toEqual([
      'timeline.0.src',
      'timeline.2.src',
      'overlays.0.src',
    ])
    // cada operação parte da spec que a anterior devolveu
    const saved = calls.at(-1)!.body as typeof spec
    expect(saved.timeline.map((item) => ('src' in item ? item.src : null))).toEqual([
      'output/correcao/a.corrigido.mp4',
      null,
      'output/correcao/a.corrigido.mp4',
    ])
    expect(saved.overlays[0]!.src).toBe('output/correcao/a.corrigido.mp4')
    expect(saved.sources.cam1.src).toBe('D:/m/cam1.mp4')
    expect(store.busy).toBe(false)
  })

  it('fonte sincronizada (multicâmera) troca o `src` da fonte', async () => {
    const calls = stubServer()
    const store = useSourceReplacementStore()
    const source: MediaEntry = { id: 'source:cam1', kind: 'clip', label: 'cam1', path: 'D:/m/cam1.mp4', source: 'cam1' }

    expect(await store.replace('demo', source, 'novo.mp4')).toBe(1)
    expect((calls[1]!.body as { op: unknown }).op).toEqual({ type: 'set_field', path: 'sources.cam1.src', value: 'novo.mp4' })
  })

  it('arquivo que o projeto não usa não troca nem salva nada', async () => {
    const calls = stubServer()
    const store = useSourceReplacementStore()
    const stranger: MediaEntry = { ...fileEntry, id: 'file:D:/m/outro.mp4', src: 'D:/m/outro.mp4' }

    expect(await store.replace('demo', stranger, 'x.mp4')).toBe(0)
    expect(calls.map((call) => call.method)).toEqual(['GET'])
  })

  it('spec que o servidor recusa ao salvar volta como erro, e o botão destrava', async () => {
    stubServer({ saveFails: true })
    const store = useSourceReplacementStore()

    await expect(store.replace('demo', fileEntry, 'x.mp4')).rejects.toThrow('Spec inválida.')
    expect(store.busy).toBe(false)
  })

  it('com o editor aberto no projeto, a troca passa por ele: a cópia dele muda e o salvar grava', async () => {
    const { store: editor, fetch } = await openEditor(undefined, {
      'POST /api/projects/demo/edit': (call: { body: unknown }) => {
        const { spec: sent, op } = call.body as { spec: Record<string, unknown>; op: { path: string; value: string } }
        const next = structuredClone(sent) as { timeline: Array<Record<string, unknown>> }
        next.timeline[0]!.src = op.value
        return { spec: next, timeline: timelineView() }
      },
    })
    const store = useSourceReplacementStore()
    const entry: MediaEntry = { id: 'file:clip0.mp4', kind: 'clip', label: 'clip0.mp4', path: 'clip0.mp4', src: 'clip0.mp4' }

    expect(await store.replace('demo', entry, 'novo.mp4')).toBe(1)

    expect((editor.spec?.timeline as Array<{ src: string }>)[0]!.src).toBe('novo.mp4')
    expect(editor.dirty).toBe(false)
    // não leu o projeto do disco de novo (a spec do editor é a verdade) e gravou uma vez
    expect(fetch.to('PUT /api/projects/demo')).toHaveLength(1)
    expect(fetch.to('GET /api/projects/demo')).toHaveLength(1)
  })
})
