import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { editorRoutes } from '@/test/editorMount'
import { projectSpec } from '@/test/editorFixtures'
import { reply, routedFetch, type RoutedFetch } from '@/test/routedFetch'
import { useEditorStore } from './editor'
import { FRAME_POLL_MS, useRealFrameStore } from './realFrame'

const KEY = '0123456789abcdef'
let fetch: RoutedFetch

function serve(extra: Record<string, unknown> = {}): RoutedFetch {
  fetch = routedFetch(editorRoutes(projectSpec(), extra))
  return fetch
}

async function open() {
  const editor = useEditorStore()
  await editor.open('demo')
  await flushPromises()
  return { editor, frame: useRealFrameStore() }
}

const ready = (extra: Record<string, unknown> = {}) => ({ key: KEY, status: 'ready', t: 1.5, notes: [], url: '/api/file?path=q.png', ...extra })
const pending = (extra: Record<string, unknown> = {}) => ({ key: KEY, status: 'pending', t: 1.5, notes: [], label: 'Montando o quadro', percent: 40, ...extra })

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('o quadro real do cursor', () => {
  it('pede o quadro do projeto no instante do cursor, com a edição que está na tela', async () => {
    serve({ 'POST /api/projects/demo/frame': () => ready() })
    const { editor, frame } = await open()
    editor.setPlayhead(1.5)
    editor.setField('overlays.0.text', 'Outro texto')
    await frame.request()
    const [call] = fetch.to('POST /api/projects/demo/frame')
    expect(call?.body).toMatchObject({ t: 1.5, spec: { overlays: [{ text: 'Outro texto' }] } })
    expect(frame.state).toBe('ready')
    expect(frame.url).toBe('/api/file?path=q.png')
  })

  it('mostra o instante que o servidor devolveu (na grade de quadros) e as notas, e não o instante pedido', async () => {
    serve({ 'POST /api/projects/demo/frame': () => ready({ t: 1.4667, notes: ['A legenda automática não entrou: falta a transcrição.'] }) })
    const { editor, frame } = await open()
    editor.setPlayhead(1.47)
    await frame.request()
    expect(frame.at).toBe(1.4667)
    expect(frame.notes).toEqual(['A legenda automática não entrou: falta a transcrição.'])
  })

  it('pendente: consulta a chave a cada poucos décimos de segundo e mostra a etapa e o percentual', async () => {
    let answers = 0
    serve({
      'POST /api/projects/demo/frame': () => pending(),
      [`GET /api/projects/demo/frame/${KEY}`]: () => (++answers < 3 ? pending({ percent: 40 + answers * 20 }) : ready()),
    })
    const { frame } = await open()
    await frame.request()
    expect(frame.state).toBe('pending')
    expect(frame.label).toBe('Montando o quadro')
    expect(frame.percent).toBe(40)
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS)
    await flushPromises()
    expect(fetch.to(`GET /api/projects/demo/frame/${KEY}`)).toHaveLength(1)
    expect(frame.percent).toBe(60)
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS)
    await flushPromises()
    expect(frame.state).toBe('ready')
    // pronto, as consultas param
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS * 3)
    expect(fetch.to(`GET /api/projects/demo/frame/${KEY}`)).toHaveLength(3)
  })

  it('o erro do servidor aparece em português e as consultas param', async () => {
    serve({ 'POST /api/projects/demo/frame': () => ({ key: KEY, status: 'error', t: null, notes: [], error: 'O vídeo do trecho 1 sumiu.' }) })
    const { frame } = await open()
    await frame.request()
    expect(frame.state).toBe('error')
    expect(frame.error).toBe('O vídeo do trecho 1 sumiu.')
  })

  it('um erro de rede ao pedir vira erro na tela, sem derrubar nada', async () => {
    serve({ 'POST /api/projects/demo/frame': () => reply(422, { detail: 'preset desconhecido' }) })
    const { frame } = await open()
    await frame.request()
    expect(frame.state).toBe('error')
    expect(frame.error).toBe('preset desconhecido')
  })

  it('superado por um pedido mais novo: a tela volta ao aproximado e a chave deixa de ser consultada', async () => {
    serve({
      'POST /api/projects/demo/frame': () => pending(),
      [`GET /api/projects/demo/frame/${KEY}`]: () => ({ key: KEY, status: 'superseded', t: 1.5, notes: [] }),
    })
    const { frame } = await open()
    await frame.request()
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS)
    await flushPromises()
    expect(frame.state).toBe('idle')
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS * 4)
    expect(fetch.to(`GET /api/projects/demo/frame/${KEY}`)).toHaveLength(1)
  })

  it('resposta velha é descartada: um pedido novo vale mais que a resposta do anterior', async () => {
    const waiting: Array<(value: unknown) => void> = []
    serve({
      'POST /api/projects/demo/frame': () => new Promise((resolve) => waiting.push(resolve)),
    })
    const { frame } = await open()
    const first = frame.request()
    const second = frame.request()
    waiting[0]?.(ready({ url: '/api/file?path=velho.png' }))
    await first
    expect(frame.state).toBe('pending')
    waiting[1]?.(ready({ url: '/api/file?path=novo.png' }))
    await second
    expect(frame.url).toBe('/api/file?path=novo.png')
  })

  it('mudar a spec devolve a tela ao aproximado e para as consultas', async () => {
    serve({
      'POST /api/projects/demo/frame': () => pending(),
      [`GET /api/projects/demo/frame/${KEY}`]: () => pending(),
    })
    const { editor, frame } = await open()
    await frame.request()
    editor.setField('overlays.0.text', 'Mudou')
    await flushPromises()
    expect(frame.state).toBe('idle')
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS * 3)
    expect(fetch.to(`GET /api/projects/demo/frame/${KEY}`)).toHaveLength(0)
  })

  it('mexer no cursor também devolve a tela ao aproximado', async () => {
    serve({ 'POST /api/projects/demo/frame': () => ready() })
    const { editor, frame } = await open()
    editor.setPlayhead(1)
    await frame.request()
    expect(frame.state).toBe('ready')
    editor.setPlayhead(1.2)
    await flushPromises()
    expect(frame.state).toBe('idle')
    expect(frame.url).toBe('')
  })

  it('uma mudança da spec que veio antes do pedido não derruba o próprio pedido', async () => {
    serve({ 'POST /api/projects/demo/frame': () => ready() })
    const { editor, frame } = await open()
    editor.setField('overlays.0.text', 'Antes do pedido')
    await frame.request()
    await flushPromises()
    expect(frame.state).toBe('ready')
  })

  it('o botão alterna: pede o quadro e, com ele na tela, volta à prévia aproximada', async () => {
    serve({ 'POST /api/projects/demo/frame': () => ready() })
    const { frame } = await open()
    await frame.toggle()
    expect(frame.state).toBe('ready')
    await frame.toggle()
    expect(frame.state).toBe('idle')
    // depois de um erro o botão tenta de novo
    fetch.set('POST /api/projects/demo/frame', () => reply(500, { detail: 'caiu' }))
    await frame.toggle()
    expect(frame.state).toBe('error')
    fetch.set('POST /api/projects/demo/frame', () => ready())
    await frame.toggle()
    expect(frame.state).toBe('ready')
  })

  it('sem a linha do tempo calculada não há o que pedir', async () => {
    serve({ 'POST /api/projects/demo/frame': () => ready(), 'POST /api/projects/demo/timeline': () => reply(422, { detail: 'spec incompleta' }) })
    const { frame } = await open()
    await frame.request()
    expect(fetch.to('POST /api/projects/demo/frame')).toHaveLength(0)
    expect(frame.state).toBe('idle')
  })

  it('invalidar para as consultas e descarta o que chegar depois', async () => {
    serve({
      'POST /api/projects/demo/frame': () => pending(),
      [`GET /api/projects/demo/frame/${KEY}`]: () => ready(),
    })
    const { frame } = await open()
    await frame.request()
    frame.invalidate()
    await vi.advanceTimersByTimeAsync(FRAME_POLL_MS * 3)
    await flushPromises()
    expect(frame.state).toBe('idle')
    expect(fetch.to(`GET /api/projects/demo/frame/${KEY}`)).toHaveLength(0)
  })
})
