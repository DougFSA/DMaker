import { afterEach, describe, expect, it, vi } from 'vitest'
import { spectrumAnalysis } from '@/test/spectrumFixtures'
import { stubFetch } from '@/test/fetch'
import { ApiError } from './http'
import { analyzeSpectrum, detectMusicTempo } from './audioAnalysis'

afterEach(() => vi.unstubAllGlobals())

const params = { algorithm: 'spectrum', window: 'hann', size: 4096, axis: 'log' } as const

describe('cliente da análise de áudio', () => {
  it('pede o espectro do item com o analisador e os parâmetros no corpo', async () => {
    const fetch = stubFetch(spectrumAnalysis())
    const result = await analyzeSpectrum('minha entrevista', { target: 'audio.voiceover.0', params, points: 512 })
    expect(fetch.last()).toMatchObject({
      url: '/api/projects/minha%20entrevista/audio-analysis',
      method: 'POST',
      body: { analyzer: 'spectrum', target: 'audio.voiceover.0', start: null, end: null, params, points: 512 },
    })
    expect(result.peak_hz).toBe(1000)
    expect(result.curve.frequencies).toHaveLength(result.curve.levels_db.length)
  })

  it('sem `points` deixa o servidor escolher e leva o trecho quando há', async () => {
    const fetch = stubFetch(spectrumAnalysis())
    await analyzeSpectrum('demo', { target: 'output', start: 1.5, end: 4, params })
    expect(fetch.last().body).toEqual({ analyzer: 'spectrum', target: 'output', start: 1.5, end: 4, params })
  })

  it('o pedido recusado vira ApiError com o motivo do servidor', async () => {
    stubFetch({ detail: 'o projeto não tem música (audio.music)' }, 400)
    const failure = await analyzeSpectrum('demo', { target: 'audio.music', params }).catch((error: unknown) => error)
    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).status).toBe(400)
    expect((failure as ApiError).message).toContain('não tem música')
  })

  it('sugere o andamento da música do projeto pela rota que só lê', async () => {
    const detection = { source: 'loop.wav', bpm: 100, beat_offset: 0.12, confidence: 0.98, alternatives: [50, 200], warnings: [] }
    const fetch = stubFetch(detection)
    const result = await detectMusicTempo('minha entrevista')
    expect(fetch.last()).toMatchObject({ url: '/api/projects/minha%20entrevista/audio-tempo/detect', method: 'POST' })
    expect(result).toEqual(detection)
  })

  it('a música sem andamento a achar vira ApiError com o motivo', async () => {
    stubFetch({ detail: 'o projeto não tem música (audio.music) para detectar o andamento' }, 400)
    const failure = await detectMusicTempo('demo').catch((error: unknown) => error)
    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).message).toContain('não tem música')
  })
})
