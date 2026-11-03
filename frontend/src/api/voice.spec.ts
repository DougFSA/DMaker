import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { voiceApi } from './voice'

afterEach(() => vi.unstubAllGlobals())

describe('cliente da voz', () => {
  it('lista a biblioteca, com a marca só quando ela existe', async () => {
    const fetch = stubFetch([])
    await voiceApi.list()
    expect(fetch.last()).toMatchObject({ url: '/api/voices', method: 'GET' })
    await voiceApi.list('medlycare')
    expect(fetch.last().url).toBe('/api/voices?brand=medlycare')
    await voiceApi.list('')
    expect(fetch.last().url).toBe('/api/voices')
  })

  it('pede as opções de desenho e monta o endereço do áudio', async () => {
    const fetch = stubFetch()
    await voiceApi.designOptions()
    expect(fetch.last()).toMatchObject({ url: '/api/voices/design-options', method: 'GET' })
    expect(voiceApi.audioUrl('X:/out/voz 1.wav')).toBe('/api/voices/audio?path=X%3A%2Fout%2Fvoz%201.wav')
    expect(voiceApi.audioUrl('a.wav', true)).toBe('/api/voices/audio?path=a.wav&download=true')
  })

  it('clona enviando o áudio em multipart com os campos do formulário', async () => {
    const fetch = stubFetch({ id: 'ana' })
    const audio = new Blob(['xx'], { type: 'audio/webm' })
    await voiceApi.clone({
      name: 'Ana',
      audio,
      filename: 'gravacao.webm',
      reference_text: 'Olá, tudo bem',
      brand: 'medlycare',
      language: 'pt',
    })
    const call = fetch.last()
    expect(call).toMatchObject({ url: '/api/voices/clone', method: 'POST' })
    expect(call.headers).toEqual({}) // o navegador define o Content-Type com o limite do multipart
    expect(call.form?.get('name')).toBe('Ana')
    expect((call.form?.get('audio') as File).name).toBe('gravacao.webm')
    expect(call.form?.get('reference_text')).toBe('Olá, tudo bem')
    expect(call.form?.get('brand')).toBe('medlycare')
    expect(call.form?.get('language')).toBe('pt')
  })

  it('não manda no multipart o que ficou em branco', async () => {
    const fetch = stubFetch()
    await voiceApi.clone({ name: 'Ana', audio: new Blob(['x']), reference_text: '', brand: null })
    const form = fetch.last().form
    expect(form?.has('reference_text')).toBe(false)
    expect(form?.has('brand')).toBe(false)
    expect((form?.get('audio') as File).name).toBe('gravacao')
  })

  it('desenha, narra, ouve a amostra e remove', async () => {
    const fetch = stubFetch({ job_id: 'j1' })
    await voiceApi.design({ name: 'Voz', gender: 'female', whisper: true })
    expect(fetch.last()).toMatchObject({
      url: '/api/voices/design',
      method: 'POST',
      body: { name: 'Voz', gender: 'female', whisper: true },
    })
    await voiceApi.speak({ text: 'Olá', voice: 'ana', speed: 1.2, seed: 7 })
    expect(fetch.last()).toMatchObject({
      url: '/api/voices/speak',
      method: 'POST',
      body: { text: 'Olá', voice: 'ana', speed: 1.2, seed: 7 },
    })
    await voiceApi.preview('ana maria')
    expect(fetch.last()).toMatchObject({ url: '/api/voices/ana%20maria/preview', method: 'POST' })
    await voiceApi.remove('ana')
    expect(fetch.last()).toMatchObject({ url: '/api/voices/ana', method: 'DELETE' })
  })

  it('lista, adiciona e remove pronúncias', async () => {
    const fetch = stubFetch({ brand: null, entries: [] })
    await voiceApi.pronunciation.list('medlycare', 'pt')
    expect(fetch.last()).toMatchObject({ url: '/api/voices/pronunciation?brand=medlycare&language=pt', method: 'GET' })
    await voiceApi.pronunciation.list()
    expect(fetch.last().url).toBe('/api/voices/pronunciation')
    await voiceApi.pronunciation.add({ term: 'SQL', spoken: 'esse quê éle', brand: 'medlycare', language: 'pt' })
    expect(fetch.last()).toMatchObject({
      url: '/api/voices/pronunciation',
      method: 'POST',
      body: { term: 'SQL', spoken: 'esse quê éle', brand: 'medlycare', language: 'pt' },
    })
    await voiceApi.pronunciation.remove('SQL', 'medlycare', 'pt')
    expect(fetch.last()).toMatchObject({
      url: '/api/voices/pronunciation?term=SQL&brand=medlycare&language=pt',
      method: 'DELETE',
    })
  })
})
