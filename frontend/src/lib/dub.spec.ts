import { describe, expect, it } from 'vitest'
import type { DubSegment, DubSegmentReport } from '@/api'
import {
  describeFit,
  describeProject,
  describeResult,
  describeSpan,
  describeStems,
  describeStretch,
  findProjectEntry,
  fitModeOf,
  formatGlossary,
  isNewSpeech,
  keepDbFrom,
  mediaKindOf,
  parseGlossary,
  rowsChanged,
  rowsFrom,
  sameLanguage,
  segmentEdits,
  speakerModeOf,
  statusLabel,
  statusTone,
} from './dub'
import type { MediaEntry } from './media'

const segment = (over: Partial<DubSegment> = {}): DubSegment => ({
  id: 's1',
  start: 0,
  end: 2.5,
  original: 'Olá a todos.',
  text: 'Hello everyone.',
  locked: false,
  speaker: null,
  ...over,
})

describe('parseGlossary', () => {
  it('separa por vírgula ou quebra de linha, sem vazios nem repetidos', () => {
    expect(parseGlossary('DMaker, MedlyCare\nzebeyond,, dmaker ,')).toEqual(['DMaker', 'MedlyCare', 'zebeyond'])
  })

  it('vazio dá lista vazia, e a lista volta ao campo separada por vírgula', () => {
    expect(parseGlossary('  ')).toEqual([])
    expect(formatGlossary(['DMaker', 'MedlyCare'])).toBe('DMaker, MedlyCare')
  })
})

describe('keepDbFrom', () => {
  it('vazio é "sem voz original" e o sinal não importa: 18 e -18 valem -18', () => {
    expect(keepDbFrom(null)).toBeNull()
    expect(keepDbFrom(18)).toBe(-18)
    expect(keepDbFrom(-18)).toBe(-18)
    expect(keepDbFrom(-6.5)).toBe(-6.5)
  })

  it('zero fica zero (nunca -0) e número inválido vira vazio', () => {
    expect(Object.is(keepDbFrom(0), 0)).toBe(true)
    expect(keepDbFrom(Number.NaN)).toBeNull()
  })
})

describe('modos do seletor', () => {
  it('só os modos conhecidos passam; o resto cai no padrão', () => {
    expect(speakerModeOf('single')).toBe('single')
    expect(speakerModeOf('per_segment')).toBe('per_segment')
    expect(speakerModeOf('coro')).toBe('per_speaker')
    expect(fitModeOf('misto')).toBe('misto')
    expect(fitModeOf('')).toBe('voz')
  })
})

describe('sameLanguage', () => {
  it('compara só a língua de base, como o servidor', () => {
    expect(sameLanguage('pt', 'pt-BR')).toBe(true)
    expect(sameLanguage('PT-br', 'pt')).toBe(true)
    expect(sameLanguage('pt', 'en')).toBe(false)
  })
})

describe('segmentEdits', () => {
  it('manda texto sem as pontas, a trava e o falante só quando há um escolhido', () => {
    const edits = segmentEdits([
      { id: 's1', text: '  Hello everyone. ', locked: true, speaker: 'Falante 2' },
      { id: 's2', text: 'Second', locked: false, speaker: null },
      { id: 's3', text: '', locked: false, speaker: '' },
    ])
    expect(edits).toEqual([
      { id: 's1', text: 'Hello everyone.', locked: true, speaker: 'Falante 2' },
      { id: 's2', text: 'Second', locked: false, speaker: undefined },
      { id: 's3', text: '', locked: false, speaker: undefined },
    ])
    // sem falante a chave não vai no JSON: o servidor mantém o que a fala já tinha
    expect(JSON.parse(JSON.stringify(edits[1]))).toEqual({ id: 's2', text: 'Second', locked: false })
  })
})

describe('rowsFrom e rowsChanged', () => {
  it('a tabela parte do projeto e só muda quando tradução, trava ou falante mudam', () => {
    const segments = [segment(), segment({ id: 's2', start: 3, end: 5, text: 'Two' })]
    const rows = rowsFrom(segments)
    expect(rows[1]).toEqual({ id: 's2', start: 3, end: 5, original: 'Olá a todos.', text: 'Two', locked: false, speaker: null })
    expect(rowsChanged(segments, rows)).toBe(false)
    expect(rowsChanged(segments, [{ ...rows[0]!, text: 'Hello everyone.  ' }, rows[1]!])).toBe(false)
    expect(rowsChanged(segments, [{ ...rows[0]!, text: 'Hi everyone.' }, rows[1]!])).toBe(true)
    expect(rowsChanged(segments, [rows[0]!, { ...rows[1]!, locked: true }])).toBe(true)
    expect(rowsChanged(segments, [rows[0]!, { ...rows[1]!, speaker: 'Falante 1' }])).toBe(true)
    expect(rowsChanged(segments, [rows[0]!])).toBe(true)
  })
})

describe('textos da tela', () => {
  it('o tempo da fala usa vírgula', () => {
    expect(describeSpan(0, 2.5)).toBe('0,0 a 2,5 s')
  })

  it('o resumo do projeto cita o tradutor e, com mais de um falante, como corrigir', () => {
    const base = { segments: [segment(), segment({ id: 's2' })], source_language: 'pt', target_language: 'en', translator_model: 'gpt-oss:20b', speakers: [] }
    expect(describeProject(base)).toBe(
      '2 fala(s), pt para en. Tradução: gpt-oss:20b. Corrija o que precisar; as traduções travadas não mudam ao traduzir de novo.',
    )
    const two = describeProject({ ...base, translator_model: '', speakers: ['Falante 1', 'Falante 2'] })
    expect(two).toContain('2 falantes: troque o falante de uma fala se o programa errou; só essa fala é refeita.')
    expect(two).not.toContain('Tradução:')
  })

  it('o resumo da geração conta o que saiu agora, o que veio do cache e o tempo', () => {
    const report = [{}, {}, {}] as DubSegmentReport[]
    expect(describeResult({ report, regenerated: 1, timings: { Separação: 4.2, Síntese: 7.9 }, stretched: [], output_seconds: 40 })).toBe(
      '1 fala(s) sintetizada(s) agora e 2 reaproveitada(s) do cache, em 12 s.',
    )
  })

  it('o vídeo esticado entra no resumo com o total de segundos e a duração final', () => {
    const stretched = [
      { id: 's1', start: 0, factor: 1.2, added_seconds: 0.8 },
      { id: 's3', start: 8, factor: 1.1, added_seconds: 0.5 },
    ]
    expect(describeStretch([], 40)).toBe('')
    expect(describeStretch(stretched, 41.3)).toBe(' Vídeo esticado em 2 trecho(s), 1,3 s a mais. O vídeo final tem 41,3 s.')
    expect(describeStretch(stretched, 0)).toBe(' Vídeo esticado em 2 trecho(s), 1,3 s a mais.')
  })

  it('o resumo das trilhas lista os arquivos e diz a voz original só quando ela está no vídeo', () => {
    const stems = { files: ['voz-dublada.wav', 'fundo.wav', 'voz-original.wav'], duration: 40, original_voice_db: null }
    expect(describeStems(stems)).toBe('Trilhas prontas (voz-dublada.wav, fundo.wav, voz-original.wav), cada uma com 40,00 s.')
    expect(describeStems({ ...stems, original_voice_db: -18 })).toContain('usa a voz original a -18 dB; a trilha dela vem sem atenuar.')
  })
})

describe('situação de cada fala', () => {
  it('cada estado tem o nome da clássica e um tom', () => {
    expect(statusLabel('fits')).toBe('cabe')
    expect(statusLabel('advances')).toBe('avança na pausa')
    expect(statusLabel('squeezed')).toBe('comprimida')
    expect(statusLabel('stretched')).toBe('vídeo esticado')
    expect(statusLabel('overflow')).toBe('não coube')
    expect(statusLabel('empty')).toBe('sem tradução')
    expect([statusTone('fits'), statusTone('advances'), statusTone('squeezed'), statusTone('overflow'), statusTone('empty')]).toEqual([
      'success',
      'info',
      'warning',
      'error',
      'neutral',
    ])
  })

  it('o vídeo esticado mostra o fator, e a fala fora do cache é "nova"', () => {
    expect(describeFit({ status: 'stretched', video_stretch: 1.25 })).toBe('vídeo esticado 1,25x')
    expect(describeFit({ status: 'fits', video_stretch: 1 })).toBe('cabe')
    expect(isNewSpeech({ cached: false })).toBe(true)
    expect(isNewSpeech({ cached: true })).toBe(false)
  })
})

describe('mediaKindOf', () => {
  it('vídeo sai em player de vídeo e o resto em player de áudio', () => {
    expect(mediaKindOf('X:/saida/dublagem/entrevista.en.mp4')).toBe('video')
    expect(mediaKindOf('X:\\saida\\aula.en.MOV')).toBe('video')
    expect(mediaKindOf('X:/saida/dublagem/podcast.en.wav')).toBe('audio')
    expect(mediaKindOf('podcast.en.m4a')).toBe('audio')
  })
})

describe('findProjectEntry', () => {
  const entry = (path: string): MediaEntry => ({ id: `file:${path}`, kind: 'clip', label: 'x', path, src: path })

  it('acha a mídia do projeto pelo caminho, sem ligar para barra nem caixa', () => {
    const entries = [entry('D:/m/outro.mp4'), entry('D:\\M\\Entrevista.mp4')]
    expect(findProjectEntry(entries, 'd:/m/entrevista.mp4')).toBe(entries[1])
  })

  it('arquivo que o projeto não usa não tem entrada', () => {
    expect(findProjectEntry([entry('D:/m/a.mp4')], 'D:/m/b.mp4')).toBeNull()
    expect(findProjectEntry([], 'D:/m/b.mp4')).toBeNull()
  })
})
