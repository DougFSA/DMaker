import { afterEach, describe, expect, it, vi } from 'vitest'
import { audioEffectCatalog } from '@/test/audioEffectsFixtures'
import { stubFetch } from '@/test/fetch'
import { ApiError } from './http'
import { fetchAudioEffects } from './audioEffects'

afterEach(() => vi.unstubAllGlobals())

describe('cliente do catálogo de efeitos de áudio', () => {
  it('lê o catálogo inteiro: efeitos, campos comuns e lugares', async () => {
    const fetch = stubFetch(audioEffectCatalog())
    const catalog = await fetchAudioEffects()
    expect(fetch.last()).toMatchObject({ url: '/api/audio-effects', method: 'GET' })
    expect(catalog.effects.map((effect) => effect.type)).toEqual(['amplify', 'normalize', 'invert', 'reverse', 'repeat'])
    expect(catalog.common.map((param) => param.name)).toEqual(['enabled', 'start', 'end'])
    expect(catalog.targets.find((target) => target.target === 'audio.music')?.may_grow).toBe(true)
  })

  it('pede um efeito só pelo nome, com a query codificada', async () => {
    const fetch = stubFetch({ effects: [], common: [], targets: [] })
    await fetchAudioEffects('amplify')
    expect(fetch.last()).toMatchObject({ url: '/api/audio-effects?type=amplify', method: 'GET' })
    await fetchAudioEffects('a b')
    expect(fetch.last().url).toBe('/api/audio-effects?type=a%20b')
  })

  it('um efeito que não existe vira ApiError com a mensagem do servidor', async () => {
    stubFetch({ detail: "Efeito de áudio desconhecido: 'eco'. Use um de: amplify, invert" }, 404)
    const failure = await fetchAudioEffects('eco').catch((error: unknown) => error)
    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).status).toBe(404)
    expect((failure as ApiError).message).toContain('Efeito de áudio desconhecido')
  })
})
