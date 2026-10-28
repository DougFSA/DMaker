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

describe('cliente da API', () => {
  it('chama as rotas de projeto com o nome codificado', async () => {
    await api.projects.validate('meu projeto')
    expect(lastCall()).toMatchObject({ url: '/api/projects/meu%20projeto/validate', method: 'POST' })
    await api.projects.qa('a')
    expect(lastCall()).toMatchObject({ url: '/api/projects/a/qa', method: 'POST' })
    await api.projects.get('a')
    expect(lastCall()).toMatchObject({ url: '/api/projects/a', method: 'GET' })
  })

  it('manda o pedido de render com os campos certos', async () => {
    await api.projects.render('a', { preview: true, segments: '1-3' })
    expect(lastCall()).toMatchObject({
      url: '/api/projects/a/render',
      method: 'POST',
      body: { preview: true, segments: '1-3' },
    })
  })

  it('exporta com a lista de presets', async () => {
    await api.projects.export('a', ['instagram/reels', 'youtube/shorts'])
    expect(lastCall()).toMatchObject({
      url: '/api/projects/a/export',
      body: { presets: ['instagram/reels', 'youtube/shorts'] },
    })
  })

  it('cria projeto a partir de template', async () => {
    await api.projects.create({ name: 'novo', template: 'stories-medlycare', params: { titulo: 'Oi' } })
    expect(lastCall()).toMatchObject({
      url: '/api/projects',
      method: 'POST',
      body: { name: 'novo', template: 'stories-medlycare', params: { titulo: 'Oi' } },
    })
  })

  it('inicia o corte automático e desfaz um corte da lista', async () => {
    await api.autocut.start({ source: 'D:/g.mp4', name: 'g-corte', intensity: 'agressiva', min_pause: 0.8 })
    expect(lastCall()).toMatchObject({
      url: '/api/autocut',
      method: 'POST',
      body: { source: 'D:/g.mp4', name: 'g-corte', intensity: 'agressiva', min_pause: 0.8 },
    })
    await api.projects.undoCut('meu corte', 3)
    expect(lastCall()).toMatchObject({ url: '/api/projects/meu%20corte/cuts/3/undo', method: 'POST' })
  })

  it('lista templates, saídas e jobs', async () => {
    await api.templates.list()
    expect(lastCall().url).toBe('/api/templates')
    await api.outputs.list()
    expect(lastCall().url).toBe('/api/outputs')
    await api.jobs.list()
    expect(lastCall().url).toBe('/api/jobs')
    await api.jobs.clearFinished()
    expect(lastCall()).toMatchObject({ url: '/api/jobs/finished', method: 'DELETE' })
  })

  it('navega pelo servidor com o caminho codificado', async () => {
    await api.files.browse('D:/Vídeos/casa')
    expect(lastCall().url).toBe(`/api/browse?path=${encodeURIComponent('D:/Vídeos/casa')}`)
    await api.files.browse()
    expect(lastCall().url).toBe('/api/browse')
  })

  it('monta a URL do SSE de um job', () => {
    expect(api.jobs.eventsUrl('abc123')).toBe('/api/jobs/abc123/events')
  })
})
