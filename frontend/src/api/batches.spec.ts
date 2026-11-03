import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './index'

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })))
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

function lastCall(): { url: string; method: string; body: unknown } {
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit]
  return { url, method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined }
}

describe('cliente da API de lotes', () => {
  it('valida e inicia com o pedido completo', async () => {
    await api.batches.validate({ template: 'stories-medlycare', sheet: 'D:/p/semana.csv', name_column: 'titulo' })
    expect(lastCall()).toMatchObject({
      url: '/api/batches/validate',
      method: 'POST',
      body: { template: 'stories-medlycare', sheet: 'D:/p/semana.csv', name_column: 'titulo' },
    })
    await api.batches.start({ template: 't', sheet: 's.csv', skip_invalid: true, preview: true, name: 'serie' })
    expect(lastCall()).toMatchObject({
      url: '/api/batches',
      method: 'POST',
      body: { skip_invalid: true, preview: true, name: 'serie' },
    })
  })

  it('consulta, pausa, retoma e remove com o nome codificado', async () => {
    await api.batches.get('minha série')
    expect(lastCall()).toMatchObject({ url: '/api/batches/minha%20s%C3%A9rie', method: 'GET' })
    await api.batches.pause('a')
    expect(lastCall()).toMatchObject({ url: '/api/batches/a/pause', method: 'POST' })
    await api.batches.resume('a', { rows: [2, 4], force: true })
    expect(lastCall()).toMatchObject({ url: '/api/batches/a/resume', method: 'POST', body: { rows: [2, 4], force: true } })
    await api.batches.resume('a')
    expect(lastCall().body).toEqual({})
    await api.batches.remove('a')
    expect(lastCall()).toMatchObject({ url: '/api/batches/a', method: 'DELETE' })
    await api.batches.list()
    expect(lastCall().url).toBe('/api/batches')
  })

  it('pede ao navegador de arquivos só as planilhas quando é o caso', async () => {
    await api.files.browse('D:/planilhas', 'sheet')
    expect(lastCall().url).toBe(`/api/browse?path=${encodeURIComponent('D:/planilhas')}&kind=sheet`)
    await api.files.browse(undefined, 'sheet')
    expect(lastCall().url).toBe('/api/browse?kind=sheet')
    await api.files.browse('D:/videos')
    expect(lastCall().url).toBe(`/api/browse?path=${encodeURIComponent('D:/videos')}`)
  })
})
