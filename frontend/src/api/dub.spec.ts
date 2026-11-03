import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { dubApi } from './dub'

afterEach(() => vi.unstubAllGlobals())

describe('cliente da dublagem', () => {
  it('lista os projetos e abre um pelo caminho', async () => {
    const fetch = stubFetch([])
    await dubApi.projects()
    expect(fetch.last()).toMatchObject({ url: '/api/dub/projects', method: 'GET' })
    await dubApi.project('X:/out/dublagem/a.en.dub.json')
    expect(fetch.last()).toMatchObject({
      url: '/api/dub/project?path=X%3A%2Fout%2Fdublagem%2Fa.en.dub.json',
      method: 'GET',
    })
  })

  it('prepara com idioma, modo de voz, pessoas, glossário e encaixe', async () => {
    const fetch = stubFetch({ job_id: 'j1' })
    await dubApi.prepare({
      path: 'a.mp4',
      target_language: 'en',
      source_language: 'pt',
      speaker_mode: 'per_speaker',
      num_speakers: 2,
      keep_original_db: -18,
      glossary: ['DMaker'],
      fit_mode: 'misto',
    })
    expect(fetch.last()).toMatchObject({
      url: '/api/dub/prepare',
      method: 'POST',
      body: {
        path: 'a.mp4',
        target_language: 'en',
        source_language: 'pt',
        speaker_mode: 'per_speaker',
        num_speakers: 2,
        keep_original_db: -18,
        glossary: ['DMaker'],
        fit_mode: 'misto',
      },
    })
  })

  it('prepara por cima só quando o pedido leva `overwrite`', async () => {
    const fetch = stubFetch({ job_id: 'j2' })
    await dubApi.prepare({ path: 'a.mp4', target_language: 'en', overwrite: true })
    expect(fetch.last()).toMatchObject({ url: '/api/dub/prepare', method: 'POST', body: { path: 'a.mp4', overwrite: true } })
    await dubApi.prepare({ path: 'a.mp4', target_language: 'en' })
    expect(fetch.last().body).not.toHaveProperty('overwrite')
  })

  it('salva as traduções com a trava e o falante de cada fala', async () => {
    const fetch = stubFetch({})
    await dubApi.saveProject({
      project: 'p.dub.json',
      segments: [{ id: 's1', text: 'Hello', locked: true, speaker: 'Ana' }],
      keep_original_db: -20,
      fit_mode: 'voz',
    })
    expect(fetch.last()).toMatchObject({
      url: '/api/dub/project',
      method: 'PUT',
      body: {
        project: 'p.dub.json',
        segments: [{ id: 's1', text: 'Hello', locked: true, speaker: 'Ana' }],
        keep_original_db: -20,
        fit_mode: 'voz',
      },
    })
  })

  it('traduz de novo, gera a dublagem e exporta as trilhas', async () => {
    const fetch = stubFetch({ job_id: 'j1' })
    await dubApi.retranslate('p.dub.json')
    expect(fetch.last()).toMatchObject({ url: '/api/dub/retranslate', method: 'POST', body: { project: 'p.dub.json' } })
    await dubApi.render('p.dub.json')
    expect(fetch.last()).toMatchObject({ url: '/api/dub/render', method: 'POST', body: { project: 'p.dub.json', draft: false } })
    await dubApi.render('p.dub.json', true)
    expect(fetch.last().body).toEqual({ project: 'p.dub.json', draft: true })
    await dubApi.stems('p.dub.json')
    expect(fetch.last()).toMatchObject({ url: '/api/dub/stems', method: 'POST', body: { project: 'p.dub.json', draft: false } })
  })

  it('monta o endereço de um arquivo da pasta de dublagem', () => {
    expect(dubApi.fileUrl('X:/o/d/a.srt')).toBe('/api/dub/file?path=X%3A%2Fo%2Fd%2Fa.srt')
    expect(dubApi.fileUrl('X:/o/d/a.zip', true)).toBe('/api/dub/file?path=X%3A%2Fo%2Fd%2Fa.zip&download=true')
  })
})
