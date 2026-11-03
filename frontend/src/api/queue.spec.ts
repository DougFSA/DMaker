import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { queueApi } from './queue'

afterEach(() => vi.unstubAllGlobals())

describe('cliente da fila', () => {
  it('lê a fila e expõe o endereço do SSE', async () => {
    const fetch = stubFetch({ items: [] })
    await queueApi.list()
    expect(fetch.last()).toMatchObject({ url: '/api/voices/queue', method: 'GET' })
    expect(queueApi.eventsUrl).toBe('/api/voices/queue/events')
  })

  it('põe um roteiro digitado na fila com as opções', async () => {
    const fetch = stubFetch({ id: 'q1', items: [] })
    await queueApi.addText({ text: 'Capítulo 1', title: 'Livro', voice: 'ana', speed: 1.1, draft: true, format: 'mp3' })
    expect(fetch.last()).toMatchObject({
      url: '/api/voices/queue',
      method: 'POST',
      body: { text: 'Capítulo 1', title: 'Livro', voice: 'ana', speed: 1.1, draft: true, format: 'mp3' },
    })
  })

  it('importa um roteiro em multipart com o nome do arquivo e as opções', async () => {
    const fetch = stubFetch({ id: 'q1', items: [] })
    await queueApi.addFile({
      file: new File(['texto'], 'livro.docx'),
      title: 'Livro',
      voice: 'ana',
      speed: 0.9,
      draft: false,
      format: 'wav',
    })
    const call = fetch.last()
    expect(call).toMatchObject({ url: '/api/voices/queue/upload', method: 'POST' })
    expect((call.form?.get('file') as File).name).toBe('livro.docx')
    expect(call.form?.get('title')).toBe('Livro')
    expect(call.form?.get('voice')).toBe('ana')
    expect(call.form?.get('speed')).toBe('0.9')
    expect(call.form?.get('draft')).toBe('false')
    expect(call.form?.get('format')).toBe('wav')
    expect(call.form?.has('brand')).toBe(false)
  })

  it('pausa, retoma, tenta de novo, cancela e remove um item', async () => {
    const fetch = stubFetch({ items: [] })
    for (const action of ['pause', 'resume', 'retry', 'cancel'] as const) {
      await queueApi[action]('q 1')
      expect(fetch.last()).toMatchObject({ url: `/api/voices/queue/q%201/${action}`, method: 'POST' })
    }
    await queueApi.remove('q1')
    expect(fetch.last()).toMatchObject({ url: '/api/voices/queue/q1', method: 'DELETE' })
  })

  it('sobe e desce um item e limpa os concluídos', async () => {
    const fetch = stubFetch({ items: [] })
    await queueApi.move('q1', -1)
    expect(fetch.last()).toMatchObject({ url: '/api/voices/queue/q1/move', method: 'POST', body: { direction: -1 } })
    await queueApi.move('q1', 1)
    expect(fetch.last().body).toEqual({ direction: 1 })
    await queueApi.clearFinished()
    expect(fetch.last()).toMatchObject({ url: '/api/voices/queue/clear-finished', method: 'POST' })
  })

  it('monta o endereço de um arquivo pronto, para ouvir e para baixar', () => {
    expect(queueApi.fileUrl('q1', 'cap 01.wav')).toBe('/api/voices/queue/q1/files/cap%2001.wav')
    expect(queueApi.fileUrl('q1', 'cap.srt', true)).toBe('/api/voices/queue/q1/files/cap.srt?download=true')
  })
})
