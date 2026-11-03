import { describe, expect, it } from 'vitest'
import type { ConversionResult, FixSpeechResult, SpeechWord } from '@/api'
import {
  BREATH_PAUSE_S,
  canUseConversion,
  describeConversion,
  describeFix,
  describeSelection,
  downloadUrl,
  formatSeconds,
  formatSecondsPrecise,
  groupWordsByBreath,
  RANGE_ORDER_ERROR,
  rangeProblem,
  selectionFor,
  voiceLabel,
} from './speech'

const WORDS: SpeechWord[] = [
  { start: 1.0, end: 1.4, text: 'Hoje' },
  { start: 1.4, end: 1.9, text: 'é' },
  { start: 2.5, end: 3.0, text: 'o' },
  { start: 3.0, end: 3.6, text: 'casamento' },
  { start: 5.0, end: 5.4, text: 'Depois' },
]

describe('groupWordsByBreath', () => {
  it('abre um grupo novo quando a pausa chega a 0,25 s', () => {
    expect(BREATH_PAUSE_S).toBe(0.25)
    expect(groupWordsByBreath(WORDS)).toEqual([[0, 1], [2, 3], [4]])
  })

  it('aceita outra pausa e uma lista vazia', () => {
    expect(groupWordsByBreath(WORDS, 1)).toEqual([[0, 1, 2, 3], [4]])
    expect(groupWordsByBreath([])).toEqual([])
  })

  it('palavra colada na anterior fica no mesmo grupo', () => {
    const tight: SpeechWord[] = [
      { start: 0, end: 0.5, text: 'a' },
      { start: 0.6, end: 1, text: 'b' },
    ]
    expect(groupWordsByBreath(tight)).toEqual([[0, 1]])
  })

  it('uma pausa de exatamente 0,25 s já separa os grupos', () => {
    const edge: SpeechWord[] = [
      { start: 0, end: 1, text: 'a' },
      { start: 1.25, end: 2, text: 'b' },
    ]
    expect(groupWordsByBreath(edge)).toEqual([[0], [1]])
  })
})

describe('selectionFor', () => {
  it('une as palavras entre os dois cliques, em qualquer ordem', () => {
    const forward = selectionFor(WORDS, 2, 3)
    expect(forward).toEqual({ first: 2, last: 3, start: 2.5, end: 3.6, text: 'o casamento' })
    expect(selectionFor(WORDS, 3, 2)).toEqual(forward)
  })

  it('duas vezes a mesma palavra escolhe só ela', () => {
    expect(selectionFor(WORDS, 4, 4)).toEqual({ first: 4, last: 4, start: 5.0, end: 5.4, text: 'Depois' })
  })

  it('índice fora da lista não tem trecho', () => {
    expect(selectionFor(WORDS, 3, 9)).toBeNull()
    expect(selectionFor([], 0, 0)).toBeNull()
  })
})

describe('textos de tempo', () => {
  it('formata segundos com vírgula', () => {
    expect(formatSeconds(21.44)).toBe('21,4')
    expect(formatSeconds(3)).toBe('3,0')
    expect(formatSecondsPrecise(2.5)).toBe('2,50')
  })

  it('descreve o trecho escolhido e o passo seguinte', () => {
    expect(describeSelection(selectionFor(WORDS, 2, 3), false)).toBe('Trecho escolhido: "o casamento" (2,50 a 3,60 s)')
    expect(describeSelection(null, true)).toBe('Agora clique na última palavra do trecho.')
    expect(describeSelection(null, false)).toBe('Nenhum trecho escolhido.')
  })
})

describe('rangeProblem', () => {
  it('vazio e intervalo certo não têm problema', () => {
    expect(rangeProblem(null, null)).toBe('')
    expect(rangeProblem(2, null)).toBe('')
    expect(rangeProblem(null, 8)).toBe('')
    expect(rangeProblem(0, 5)).toBe('')
  })

  it('fim menor ou igual ao início é recusado', () => {
    expect(rangeProblem(5, 5)).toBe(RANGE_ORDER_ERROR)
    expect(rangeProblem(8, 2)).toBe(RANGE_ORDER_ERROR)
  })

  it('número negativo é recusado', () => {
    expect(rangeProblem(-1, null)).toContain('início')
    expect(rangeProblem(null, -3)).toContain('fim')
  })
})

describe('describeFix', () => {
  const fix: FixSpeechResult = {
    output: 'output/correcao/a.corrigido-1.wav',
    audio_url: '/api/voices/audio?path=a',
    original: 'a.wav',
    original_url: '/api/file?path=a.wav',
    region: [21.44, 23.4],
    old_text: 'João',
    new_text: 'Pedro',
    spoken: 'de Pedro e',
    rule: 'duração mantida (1.2 s)',
    squeezed: false,
    voice: 'automática',
  }

  it('diz o que saiu, o que entrou, onde e a regra de duração', () => {
    expect(describeFix(fix)).toBe('Trocado "João" por "Pedro" (região 21,4 a 23,4 s). Duração: duração mantida (1.2 s).')
  })

  it('avisa quando a fala ficou apertada', () => {
    const summary = describeFix({ ...fix, squeezed: true })
    expect(summary).toContain('Atenção: a fala ficou apertada, tente um texto mais curto.')
  })
})

describe('describeConversion', () => {
  const conversion: ConversionResult = {
    output: 'o.wav',
    audio_url: '/api/voices/audio?path=o',
    original: 'a.wav',
    original_url: '/api/file?path=a.wav',
    voice: 'dora',
    seconds: 30,
    blocks: 2,
    gain_db: -3.04,
    excerpt: false,
  }

  it('diz o arquivo, a voz, os blocos e o ajuste de volume', () => {
    expect(describeConversion(conversion)).toBe(
      'Arquivo convertido para a voz dora: 30,0 s em 2 bloco(s); volume desceu 3,0 dB para igualar ao original.',
    )
  })

  it('trecho com volume praticamente igual', () => {
    const summary = describeConversion({ ...conversion, voice: 'alex', seconds: 20, blocks: 1, gain_db: 0.01, excerpt: true })
    expect(summary.startsWith('Trecho convertido para a voz alex')).toBe(true)
    expect(summary).toContain('volume igual ao original')
  })

  it('volume que subiu', () => {
    expect(describeConversion({ ...conversion, gain_db: 2.5 })).toContain('volume subiu 2,5 dB')
  })
})

describe('canUseConversion', () => {
  it('só o arquivo inteiro, de um projeto, substitui o original', () => {
    expect(canUseConversion({ excerpt: false }, true)).toBe(true)
    expect(canUseConversion({ excerpt: true }, true)).toBe(false)
    expect(canUseConversion({ excerpt: false }, false)).toBe(false)
    expect(canUseConversion(null, true)).toBe(false)
  })
})

describe('voiceLabel e downloadUrl', () => {
  it('rotula a clonada e a desenhada pelo jeito que foram feitas; a pronta já traz o gênero no nome', () => {
    expect(voiceLabel({ name: 'Dora (feminina)', kind: 'preset' })).toBe('Dora (feminina)')
    expect(voiceLabel({ name: 'Entrevistado', kind: 'clone' })).toBe('Entrevistado (clonada)')
    expect(voiceLabel({ name: 'Locutora', kind: 'design' })).toBe('Locutora (desenhada)')
  })

  it('pede o arquivo como anexo sem perder os parâmetros', () => {
    expect(downloadUrl('/api/voices/audio?path=a.wav')).toBe('/api/voices/audio?path=a.wav&download=true')
    expect(downloadUrl('/arquivo.wav')).toBe('/arquivo.wav?download=true')
  })
})
