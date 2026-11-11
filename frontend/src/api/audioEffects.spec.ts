import { afterEach, describe, expect, it, vi } from 'vitest'
import { audioEffectCatalog } from '@/test/audioEffectsFixtures'
import { stubFetch } from '@/test/fetch'
import { ApiError } from './http'
import { deleteUserPreset, fetchAudioEffects, fetchEffectResponse, fetchUserPresets, saveChainAsMacro, saveUserPreset } from './audioEffects'

afterEach(() => vi.unstubAllGlobals())

describe('cliente do catálogo de efeitos de áudio', () => {
  it('lê o catálogo inteiro: efeitos, campos comuns e lugares', async () => {
    const fetch = stubFetch(audioEffectCatalog())
    const catalog = await fetchAudioEffects()
    expect(fetch.last()).toMatchObject({ url: '/api/audio-effects', method: 'GET' })
    expect(catalog.effects.map((effect) => effect.type)).toEqual(['amplify', 'normalize', 'invert', 'reverse', 'repeat', 'spectral_delete'])
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

describe('cliente da resposta de frequência e das predefinições salvas', () => {
  it('pede a resposta de um efeito, com ou sem a quantidade de pontos', async () => {
    const fetch = stubFetch({ hz: [20, 20000], db: [-3, 0] })
    const response = await fetchEffectResponse({ type: 'highpass', frequency_hz: 80, slope_db: 24 })
    expect(fetch.last()).toMatchObject({
      url: '/api/audio-effects/response',
      method: 'POST',
      body: { effect: { type: 'highpass', frequency_hz: 80, slope_db: 24 } },
    })
    expect(response.db).toEqual([-3, 0])
    await fetchEffectResponse({ type: 'notch' }, 64)
    expect(fetch.last().body).toEqual({ effect: { type: 'notch' }, points: 64 })
  })

  it('um efeito sem resposta vira ApiError com o motivo do servidor', async () => {
    stubFetch({ detail: "o efeito 'amplify' não tem resposta de frequência (só os de equalização têm)" }, 422)
    const failure = await fetchEffectResponse({ type: 'amplify' }).catch((error: unknown) => error)
    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).message).toContain('não tem resposta de frequência')
  })

  it('lista, salva e apaga as predefinições da pessoa', async () => {
    const fetch = stubFetch({ presets: [{ id: 'meu-corte', label: 'Meu corte', summary: '', effects: [], origin: 'user' }] })
    expect((await fetchUserPresets()).map((preset) => preset.id)).toEqual(['meu-corte'])
    expect(fetch.last()).toMatchObject({ url: '/api/audio-effects/presets', method: 'GET' })

    await saveUserPreset('Minha voz', [{ type: 'highpass', slope_db: 24 }], 'limpa o grave')
    expect(fetch.last()).toMatchObject({
      url: '/api/audio-effects/presets',
      method: 'POST',
      body: { label: 'Minha voz', effects: [{ type: 'highpass', slope_db: 24 }], summary: 'limpa o grave' },
    })

    await deleteUserPreset('meu corte/x')
    expect(fetch.last()).toMatchObject({ url: '/api/audio-effects/presets/meu%20corte%2Fx', method: 'DELETE' })
  })
})

describe('cliente das macros (a marca e salvar a cadeia de um item)', () => {
  it('pede o catálogo e as macros salvas com a marca do projeto', async () => {
    const fetch = stubFetch({ effects: [], common: [], targets: [], presets: [] })
    await fetchAudioEffects(undefined, 'acme')
    expect(fetch.last()).toMatchObject({ url: '/api/audio-effects?brand=acme', method: 'GET' })
    await fetchUserPresets('acme')
    expect(fetch.last().url).toBe('/api/audio-effects/presets?brand=acme')
    await fetchUserPresets()
    expect(fetch.last().url).toBe('/api/audio-effects/presets')
  })

  it('salva na pasta da marca e apaga de lá, só quando a marca é dita', async () => {
    const fetch = stubFetch({ id: 'x', label: 'X', summary: '', effects: [], origin: 'user' })
    await saveUserPreset('X', [{ type: 'notch' }], '', 'acme')
    expect(fetch.last().body).toEqual({ label: 'X', effects: [{ type: 'notch' }], summary: '', brand: 'acme' })
    await deleteUserPreset('x', 'acme')
    expect(fetch.last()).toMatchObject({ url: '/api/audio-effects/presets/x?brand=acme', method: 'DELETE' })
  })

  it('salva a cadeia de um item com a spec da tela, o item e o escopo', async () => {
    const fetch = stubFetch({ id: 'minha-cadeia', label: 'Minha cadeia', summary: '', effects: [], origin: 'user', scope: 'global' })
    const saved = await saveChainAsMacro('meu projeto', { spec: { name: 'meu projeto' }, target: 'audio.voiceover.0', label: 'Minha cadeia', scope: 'global' })
    expect(saved.scope).toBe('global')
    expect(fetch.last()).toMatchObject({
      url: '/api/projects/meu%20projeto/audio-macros',
      method: 'POST',
      body: { spec: { name: 'meu projeto' }, target: 'audio.voiceover.0', label: 'Minha cadeia', scope: 'global' },
    })
  })
})
