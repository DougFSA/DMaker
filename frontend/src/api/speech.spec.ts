import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { speechApi } from './speech'

afterEach(() => vi.unstubAllGlobals())

describe('cliente da fala', () => {
  it('envia o arquivo em multipart com o nome dele', async () => {
    const fetch = stubFetch({ path: 'cache/uploads/x.mp4', name: 'x.mp4' })
    const file = new File(['abc'], 'entrevista.mp4', { type: 'video/mp4' })
    await speechApi.upload(file)
    const call = fetch.last()
    expect(call).toMatchObject({ url: '/api/speech/upload', method: 'POST' })
    expect((call.form?.get('file') as File).name).toBe('entrevista.mp4')
    await speechApi.upload(new Blob(['abc']), 'gravado.webm')
    expect((fetch.last().form?.get('file') as File).name).toBe('gravado.webm')
  })

  it('isola a voz de um trecho em wav ou mp3', async () => {
    const fetch = stubFetch({ job_id: 'j1' })
    await speechApi.isolate({ path: 'a.mp4', start: 1, end: 9.5, format: 'mp3' })
    expect(fetch.last()).toMatchObject({
      url: '/api/speech/isolate',
      method: 'POST',
      body: { path: 'a.mp4', start: 1, end: 9.5, format: 'mp3' },
    })
  })

  it('pede as palavras, corrige a fala e troca a voz', async () => {
    const fetch = stubFetch({ job_id: 'j1' })
    await speechApi.words({ path: 'a.mp4', language: 'pt' })
    expect(fetch.last()).toMatchObject({ url: '/api/speech/words', method: 'POST', body: { path: 'a.mp4', language: 'pt' } })
    await speechApi.fix({ path: 'a.mp4', text: 'março', start: 3.1, end: 3.6, expand: true, draft: true })
    expect(fetch.last()).toMatchObject({
      url: '/api/speech/fix',
      method: 'POST',
      body: { path: 'a.mp4', text: 'março', start: 3.1, end: 3.6, expand: true, draft: true },
    })
    await speechApi.convert({ path: 'a.mp4', voice: 'ana' })
    expect(fetch.last()).toMatchObject({ url: '/api/speech/convert', method: 'POST', body: { path: 'a.mp4', voice: 'ana' } })
  })

  it('monta o endereço de uma mídia para tocar', () => {
    expect(speechApi.fileUrl('X:/v/a b.mp4')).toBe('/api/file?path=X%3A%2Fv%2Fa%20b.mp4')
  })
})
