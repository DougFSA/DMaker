import { describe, expect, it } from 'vitest'
import { announcesItself, isAgentTurn, jobDestination } from './jobDestination'

const renderResult = { output: 'output/a.mp4', preset: 'instagram/reels', output_url: '/api/file?path=a.mp4' }

describe('jobDestination', () => {
  it('quem gerou vídeo (render, preview, exportação) leva às Saídas', () => {
    expect(jobDestination({ description: 'meu: preview', project: 'meu', result: renderResult })).toEqual({
      label: 'Ver saídas',
      to: { name: 'outputs' },
    })
    expect(jobDestination({ description: 'meu: export a, b', project: 'meu', result: [renderResult, renderResult] })?.label).toBe(
      'Ver saídas',
    )
  })

  it.each([
    ['isolar voz (fala.wav)', 'voice-isolate'],
    ['corrigir fala (fala.wav)', 'voice-fix'],
    ['palavras de fala.wav', 'voice-fix'],
    ['trocar voz (fala.wav)', 'voice-swap'],
    ['narração (Ana, 120 caracteres)', 'voice-narration'],
    ['prévia da voz Ana', 'voice'],
    ['dublagem: gerar (aula.dub.json)', 'dubbing'],
    ['baixar modelo (Whisper)', 'models'],
    ['agente: corte o começo', 'agent'],
  ])('o job de áudio "%s" leva à tela que o disparou (%s), e não às Saídas', (description, route) => {
    const destination = jobDestination({ description, project: null, result: { ready: 2, total: 2 } })
    expect(destination?.to).toEqual({ name: route })
    expect(destination?.label).not.toBe('Ver saídas')
  })

  it('o job de um projeto sem tela própria leva ao projeto', () => {
    expect(jobDestination({ description: 'meu: proxies de prévia', project: 'meu', result: null })).toEqual({
      label: 'Ver projeto',
      to: { name: 'project', params: { name: 'meu' } },
    })
  })

  it('sem lugar melhor, não oferece botão nenhum', () => {
    expect(jobDestination({ description: 'quick clip.mp4', project: null, result: null })).toBeNull()
  })

  it('um resultado que não é de render (texto, lista vazia) não vale como vídeo', () => {
    expect(jobDestination({ description: 'quick clip.mp4', project: null, result: 'ok' })).toBeNull()
    expect(jobDestination({ description: 'quick clip.mp4', project: null, result: [] })).toBeNull()
  })
})

describe('announcesItself', () => {
  it('só o download de modelo, que a tela de Modelos já avisa', () => {
    expect(announcesItself({ description: 'baixar modelo (Whisper)' })).toBe(true)
    expect(announcesItself({ description: 'narração (Ana, 10 caracteres)' })).toBe(false)
  })
})

describe('isAgentTurn', () => {
  it('só o job que começa por "agente:" é um turno de conversa com o agente', () => {
    expect(isAgentTurn({ description: 'agente: corta as pausas' })).toBe(true)
    expect(isAgentTurn({ description: 'Agente: corta as pausas' })).toBe(true)
    expect(isAgentTurn({ description: 'narração do agente' })).toBe(false)
    expect(isAgentTurn({ description: 'meu: render final' })).toBe(false)
  })
})
