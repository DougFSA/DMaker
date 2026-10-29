import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { modelsApi } from './models'

afterEach(() => vi.unstubAllGlobals())

describe('cliente dos modelos', () => {
  it('lê o inventário e o aviso de remoção de um modelo', async () => {
    const fetch = stubFetch({})
    await modelsApi.inventory()
    expect(fetch.last()).toMatchObject({ url: '/api/models', method: 'GET' })
    await modelsApi.removal('whisper-large')
    expect(fetch.last()).toMatchObject({ url: '/api/models/whisper-large/removal', method: 'GET' })
  })

  it('baixa um modelo como job', async () => {
    const fetch = stubFetch({ job_id: 'j1' })
    await modelsApi.download('omni voice')
    expect(fetch.last()).toMatchObject({ url: '/api/models/omni%20voice/download', method: 'POST' })
  })

  it('só apaga com a confirmação dentro do corpo', async () => {
    const fetch = stubFetch({ removed: {} })
    await modelsApi.remove('whisper-large', false)
    expect(fetch.last()).toMatchObject({
      url: '/api/models/whisper-large/remove',
      method: 'POST',
      body: { confirm: false },
    })
    await modelsApi.remove('whisper-large', true)
    expect(fetch.last().body).toEqual({ confirm: true })
  })

  it('limpa as sobras, todas ou só as que a pessoa viu', async () => {
    const fetch = stubFetch({ removed: {} })
    await modelsApi.prune(true)
    expect(fetch.last()).toMatchObject({ url: '/api/models/prune', method: 'POST', body: { confirm: true } })
    await modelsApi.prune(true, ['velho/modelo.bin'])
    expect(fetch.last().body).toEqual({ confirm: true, paths: ['velho/modelo.bin'] })
  })
})
