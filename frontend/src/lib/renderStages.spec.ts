import { describe, expect, it } from 'vitest'
import { RENDER_STAGES, renderStages, stageFromLog, stageFromProgressLabel } from './renderStages'

const statuses = (log: string[], progress: { label?: string; percent?: number } | null = null, finished = false) =>
  renderStages(log, progress, finished).map((stage) => stage.status)

describe('stageFromLog', () => {
  it.each([
    ['render meu: instagram/reels 540x960 (preview)', 'sources'],
    ['sincronizando 2 fontes', 'sources'],
    ['mesa começa em +0.35 s', 'sources'],
    ['trechos: 5 (5 a gerar, 0 em cache)', 'segments'],
    ['legendas: transcrição automática', 'captions'],
    ['montagem final', 'assembly'],
    ['pronto: C:/out/meu.mp4', 'thumbnail'],
  ])('a linha "%s" marca a etapa %s', (message, key) => {
    expect(stageFromLog(message)).toBe(key)
  })

  it('uma linha comum não marca etapa', () => {
    expect(stageFromLog('Iniciado: meu: preview')).toBeNull()
    expect(stageFromLog('')).toBeNull()
  })
})

describe('stageFromProgressLabel', () => {
  it('reconhece os comandos do ffmpeg de cada etapa', () => {
    expect(stageFromProgressLabel('trecho 2/5')).toBe('segments')
    expect(stageFromProgressLabel('recorte do trecho 1/3')).toBe('segments')
    expect(stageFromProgressLabel('áudio para transcrição')).toBe('captions')
    expect(stageFromProgressLabel('montagem final')).toBe('assembly')
    expect(stageFromProgressLabel('thumbnail')).toBe('thumbnail')
    expect(stageFromProgressLabel('outra coisa')).toBeNull()
  })
})

describe('renderStages', () => {
  it('são as sete etapas, na ordem do render', () => {
    expect(RENDER_STAGES.map((stage) => stage.label)).toEqual([
      'Fontes e sincronização',
      'Trechos',
      'Legendas',
      'Camada de texto',
      'Loudness',
      'Montagem final',
      'Miniatura',
    ])
  })

  it('sem nenhuma marca (um job que não é render), não mostra etapa', () => {
    expect(renderStages(['Iniciado: narração'], null)).toEqual([])
    expect(renderStages([], { label: 'fala 1 de 3', percent: 10 })).toEqual([])
  })

  it('marca como feitas as anteriores à atual e deixa as seguintes por fazer', () => {
    expect(statuses(['render a: x', 'trechos: 3 (3 a gerar, 0 em cache)'])).toEqual([
      'done',
      'current',
      'pending',
      'pending',
      'pending',
      'pending',
      'pending',
    ])
  })

  it('o detalhe da etapa atual sai do comando em curso: o trecho ou a porcentagem', () => {
    const log = ['render a: x', 'trechos: 3 (3 a gerar, 0 em cache)']
    expect(renderStages(log, { label: 'trecho 2/3', percent: 40 })[1]).toMatchObject({ status: 'current', detail: 'trecho 2/3' })
    expect(renderStages([...log, 'legendas: auto'], { label: 'áudio para transcrição', percent: 42 })[2]).toMatchObject({
      status: 'current',
      detail: '42%',
    })
  })

  it('o comando em curso adianta a etapa mesmo antes da linha do log chegar', () => {
    expect(statuses(['render a: x'], { label: 'montagem final' })).toEqual(['done', 'done', 'done', 'done', 'done', 'current', 'pending'])
  })

  it('a etapa não volta atrás quando chega um comando de uma etapa anterior', () => {
    const stages = renderStages(['render a: x', 'trechos: 3', 'legendas: auto'], { label: 'trecho 3/3', percent: 90 })
    expect(stages.find((stage) => stage.status === 'current')?.key).toBe('captions')
    expect(stages.find((stage) => stage.key === 'captions')?.detail).toBe('')
  })

  it('com o job terminado, todas contam como feitas e sem detalhe', () => {
    const stages = renderStages(['render a: x', 'pronto: a.mp4'], { label: 'thumbnail', percent: 100 }, true)
    expect(stages.every((stage) => stage.status === 'done' && stage.detail === '')).toBe(true)
  })
})
