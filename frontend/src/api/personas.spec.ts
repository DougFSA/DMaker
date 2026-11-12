import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { personasApi } from './personas'

afterEach(() => vi.unstubAllGlobals())

describe('cliente das personas', () => {
  it('lista, cria e edita pelo cadastro', async () => {
    const fetch = stubFetch({})
    await personasApi.list()
    expect(fetch.last()).toMatchObject({ url: '/api/personas', method: 'GET' })
    const draft = { name: 'Ana', kind: '3d' as const, voice: null, appearance: { outfit_color: '#112233' } }
    await personasApi.create(draft)
    expect(fetch.last()).toMatchObject({ url: '/api/personas', method: 'POST', body: draft })
    await personasApi.update('ana', { name: 'Ana Maria' })
    expect(fetch.last()).toMatchObject({ url: '/api/personas/ana', method: 'PUT', body: { name: 'Ana Maria' } })
  })

  it('só apaga com a confirmação na rota', async () => {
    const fetch = stubFetch({ removed: 'ana' })
    await personasApi.remove('ana')
    expect(fetch.last()).toMatchObject({ url: '/api/personas/ana?confirm=true', method: 'DELETE' })
  })

  it('a prévia é um job com a frase', async () => {
    const fetch = stubFetch({ job_id: 'j1' })
    await personasApi.preview('ana', 'Oi')
    expect(fetch.last()).toMatchObject({ url: '/api/personas/ana/preview', method: 'POST', body: { phrase: 'Oi' } })
  })
})
