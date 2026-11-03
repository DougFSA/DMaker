import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { jobsApi } from './jobs'

afterEach(() => vi.unstubAllGlobals())

describe('cliente dos jobs', () => {
  it('lista, limpa os terminados e monta o endereço do SSE', async () => {
    const fetch = stubFetch([])
    await jobsApi.list()
    expect(fetch.last()).toMatchObject({ url: '/api/jobs', method: 'GET' })
    await jobsApi.clearFinished()
    expect(fetch.last()).toMatchObject({ url: '/api/jobs/finished', method: 'DELETE' })
    expect(jobsApi.eventsUrl('a b')).toBe('/api/jobs/a%20b/events')
  })

  it('pede para o job parar', async () => {
    const fetch = stubFetch({})
    await jobsApi.cancel('j1')
    expect(fetch.last()).toMatchObject({ url: '/api/jobs/j1/cancel', method: 'POST' })
  })
})
