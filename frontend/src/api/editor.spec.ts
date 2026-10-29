import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { editorApi } from './editor'

afterEach(() => vi.unstubAllGlobals())

describe('cliente do editor: projeto, legendas e linha do tempo', () => {
  it('salva a spec no projeto com o nome codificado', async () => {
    const fetch = stubFetch({ ok: true, spec_path: 'x' })
    await editorApi.saveProject('meu projeto', { name: 'meu projeto', timeline: [] })
    expect(fetch.last()).toMatchObject({
      url: '/api/projects/meu%20projeto',
      method: 'PUT',
      body: { name: 'meu projeto', timeline: [] },
    })
  })

  it('lê e grava as legendas', async () => {
    const fetch = stubFetch({})
    await editorApi.captions.get('a')
    expect(fetch.last()).toMatchObject({ url: '/api/projects/a/captions', method: 'GET' })
    await editorApi.captions.put('a', [{ start: 0, end: 1, text: 'Olá' }])
    expect(fetch.last()).toMatchObject({
      url: '/api/projects/a/captions',
      method: 'PUT',
      body: { cues: [{ start: 0, end: 1, text: 'Olá' }] },
    })
  })

  it('pede a vista do arquivo ou da edição ainda não salva', async () => {
    const fetch = stubFetch({})
    await editorApi.timeline('a')
    expect(fetch.last()).toMatchObject({ url: '/api/projects/a/timeline', method: 'POST', body: { spec: null } })
    await editorApi.timeline('a', { name: 'a' })
    expect(fetch.last().body).toEqual({ spec: { name: 'a' } })
  })

  it('aplica uma operação à spec dada', async () => {
    const fetch = stubFetch({})
    await editorApi.edit('a', { name: 'a' }, { type: 'trim', index: 2, side: 'in', delta: 0.5 })
    expect(fetch.last()).toMatchObject({
      url: '/api/projects/a/edit',
      method: 'POST',
      body: { spec: { name: 'a' }, op: { type: 'trim', index: 2, side: 'in', delta: 0.5 } },
    })
    await editorApi.edit('a', {}, { type: 'set_field', path: 'audio.music.volume', value: 0.3 })
    expect(fetch.last().body).toMatchObject({ op: { type: 'set_field', path: 'audio.music.volume', value: 0.3 } })
  })

  it('lê o tema do projeto', async () => {
    const fetch = stubFetch({})
    await editorApi.theme('a')
    expect(fetch.last()).toMatchObject({ url: '/api/projects/a/theme', method: 'GET' })
  })

  it('consulta e gera os proxies de prévia', async () => {
    const fetch = stubFetch({})
    await editorApi.proxies.get('a')
    expect(fetch.last()).toMatchObject({ url: '/api/projects/a/proxies', method: 'GET' })
    await editorApi.proxies.build('a')
    expect(fetch.last()).toMatchObject({ url: '/api/projects/a/proxies', method: 'POST' })
  })
})

describe('cliente do editor: cartão, mídia e conferência', () => {
  it('monta o endereço do cartão só com o que foi dado', () => {
    expect(editorApi.cardPreviewUrl({ title: 'Olá mundo' })).toBe('/api/card-preview?title=Ol%C3%A1%20mundo')
    expect(
      editorApi.cardPreviewUrl({
        title: 'T',
        brand: 'medlycare',
        preset: 'instagram/reels',
        subtitle: 'S',
        variant: 'dark',
        logo: false,
        background: '#000',
        width: 270,
      }),
    ).toBe(
      '/api/card-preview?title=T&brand=medlycare&preset=instagram%2Freels&subtitle=S&variant=dark&logo=false&background=%23000&width=270',
    )
    expect(editorApi.cardPreviewUrl({ title: 'T', logo: true })).toBe('/api/card-preview?title=T')
  })

  it('lê o esquema, sonda arquivos e pede a forma de onda', async () => {
    const fetch = stubFetch({})
    await editorApi.schema()
    expect(fetch.last()).toMatchObject({ url: '/api/schema', method: 'GET' })
    await editorApi.probe(['a.mp4', 'b.wav'])
    expect(fetch.last()).toMatchObject({ url: '/api/probe', method: 'POST', body: { paths: ['a.mp4', 'b.wav'] } })
    await editorApi.waveform('X:/a.wav')
    expect(fetch.last()).toMatchObject({ url: '/api/waveform?path=X%3A%2Fa.wav&stream=0', method: 'GET' })
    await editorApi.waveform('X:/a.wav', 1)
    expect(fetch.last().url).toBe('/api/waveform?path=X%3A%2Fa.wav&stream=1')
  })

  it('sincroniza fontes pelo áudio', async () => {
    const fetch = stubFetch([])
    await editorApi.sync({ master: 'a.mp4', others: ['b.mp4'], master_stream: 0, stream: 1 })
    expect(fetch.last()).toMatchObject({
      url: '/api/sync',
      method: 'POST',
      body: { master: 'a.mp4', others: ['b.mp4'], master_stream: 0, stream: 1 },
    })
  })

  it('pede a grade de quadros e um quadro do vídeo renderizado', async () => {
    const fetch = stubFetch({})
    await editorApi.qa.sheet({ video: 'o.mp4', cols: 4, rows: 2, width: 200 })
    expect(fetch.last()).toMatchObject({
      url: '/api/qa/sheet',
      method: 'POST',
      body: { video: 'o.mp4', cols: 4, rows: 2, width: 200 },
    })
    await editorApi.qa.frame({ video: 'o.mp4', t: 12.5 })
    expect(fetch.last()).toMatchObject({ url: '/api/qa/frame', method: 'POST', body: { video: 'o.mp4', t: 12.5 } })
  })

  it('lista, salva e exclui layouts de tela', async () => {
    const fetch = stubFetch({})
    await editorApi.layouts.list()
    expect(fetch.last()).toMatchObject({ url: '/api/layouts', method: 'GET' })
    await editorApi.layouts.save('meu layout', { areas: { a: 'player' }, sizes: { col: 0.4 }, hidden: ['media'], tab: 'timeline' })
    expect(fetch.last()).toMatchObject({
      url: '/api/layouts/meu%20layout',
      method: 'PUT',
      body: { areas: { a: 'player' }, sizes: { col: 0.4 }, hidden: ['media'], tab: 'timeline' },
    })
    await editorApi.layouts.remove('meu layout')
    expect(fetch.last()).toMatchObject({ url: '/api/layouts/meu%20layout', method: 'DELETE' })
  })
})
