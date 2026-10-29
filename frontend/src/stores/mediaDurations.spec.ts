import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reply, routedFetch, type RoutedFetch } from '@/test/routedFetch'
import { useMediaDurationsStore } from './mediaDurations'

let fetch: RoutedFetch

const ok = (path: string, duration_s: number) => ({
  path,
  url: null,
  kind: 'video',
  width: 1920,
  height: 1080,
  duration_s,
  fps: 30,
  has_audio: true,
  orientation: 'landscape',
})

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('durações do painel Mídia', () => {
  it('mede os arquivos num pedido só e guarda os segundos de cada um', async () => {
    fetch = routedFetch({ 'POST /api/probe': () => [ok('C:/a.mp4', 12.5), ok('C:/b.wav', 3)] })
    const store = useMediaDurationsStore()
    await store.ensure(['C:/a.mp4', 'C:/b.wav', 'C:/a.mp4'])
    expect(fetch.to('POST /api/probe')).toHaveLength(1)
    expect(fetch.to('POST /api/probe')[0]?.body).toEqual({ paths: ['C:/a.mp4', 'C:/b.wav'] })
    expect(store.seconds).toEqual({ 'C:/a.mp4': 12.5, 'C:/b.wav': 3 })
  })

  it('não mede de novo o que já foi medido, e só pede os que faltam', async () => {
    fetch = routedFetch({ 'POST /api/probe': (call: { body: { paths: string[] } }) => call.body.paths.map((path) => ok(path, 1)) })
    const store = useMediaDurationsStore()
    await store.ensure(['C:/a.mp4'])
    await store.ensure(['C:/a.mp4', 'C:/b.mp4'])
    await store.ensure(['C:/a.mp4', 'C:/b.mp4'])
    expect(fetch.to('POST /api/probe').map((call) => call.body)).toEqual([{ paths: ['C:/a.mp4'] }, { paths: ['C:/b.mp4'] }])
  })

  it('arquivo que o servidor não mede fica com null, sem pedir de novo', async () => {
    fetch = routedFetch({ 'POST /api/probe': () => [{ path: 'C:/sumiu.mp4', error: 'não encontrado' }] })
    const store = useMediaDurationsStore()
    await store.ensure(['C:/sumiu.mp4'])
    await store.ensure(['C:/sumiu.mp4'])
    expect(store.seconds['C:/sumiu.mp4']).toBeNull()
    expect(fetch.to('POST /api/probe')).toHaveLength(1)
  })

  it('arquivo que o servidor nem devolveu também fica com null', async () => {
    fetch = routedFetch({ 'POST /api/probe': () => [ok('C:/a.mp4', 2)] })
    const store = useMediaDurationsStore()
    await store.ensure(['C:/a.mp4', 'C:/b.mp4'])
    expect(store.seconds).toEqual({ 'C:/a.mp4': 2, 'C:/b.mp4': null })
  })

  it('sem resposta do servidor, a próxima mudança da lista tenta de novo', async () => {
    fetch = routedFetch({ 'POST /api/probe': reply(500, { detail: 'caiu' }) })
    const store = useMediaDurationsStore()
    await store.ensure(['C:/a.mp4'])
    expect(store.seconds).toEqual({})
    fetch.set('POST /api/probe', () => [ok('C:/a.mp4', 4)])
    await store.ensure(['C:/a.mp4'])
    expect(store.seconds['C:/a.mp4']).toBe(4)
  })

  it('lista vazia ou caminhos vazios não chamam o servidor', async () => {
    fetch = routedFetch({})
    const store = useMediaDurationsStore()
    await store.ensure([])
    await store.ensure([''])
    expect(fetch.calls).toHaveLength(0)
  })
})
