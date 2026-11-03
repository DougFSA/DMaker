import { describe, expect, it } from 'vitest'
import { formatCueTime, redistributeWords, withCueText } from './editorCaptions'

const cue = {
  start: 1,
  end: 3,
  text: 'olá mundo bonito',
  words: [
    { start: 1, end: 1.5, text: 'olá' },
    { start: 1.5, end: 2.2, text: 'mundo' },
    { start: 2.2, end: 3, text: 'bonito' },
  ],
}

describe('redistributeWords', () => {
  it('com a mesma quantidade de palavras só troca os textos e guarda o tempo de cada uma', () => {
    expect(redistributeWords(cue, 'oi mundo lindo')).toEqual([
      { start: 1, end: 1.5, text: 'oi' },
      { start: 1.5, end: 2.2, text: 'mundo' },
      { start: 2.2, end: 3, text: 'lindo' },
    ])
  })

  it('com outra quantidade, divide a duração pelo tamanho de cada palavra', () => {
    const words = redistributeWords(cue, 'aaaa bb')
    expect(words.map((w) => w.text)).toEqual(['aaaa', 'bb'])
    expect(words[0]?.start).toBe(1)
    expect(words[0]?.end).toBeCloseTo(1 + (4 / 6) * 2, 6)
    expect(words[1]?.start).toBeCloseTo(words[0]?.end as number, 6)
    expect(words[1]?.end).toBeCloseTo(3, 6)
  })

  it('mantém o início e o fim da frase mesmo com mais palavras', () => {
    const words = redistributeWords(cue, 'uma duas três quatro cinco')
    expect(words).toHaveLength(5)
    expect(words[0]?.start).toBe(1)
    expect(words.at(-1)?.end).toBeCloseTo(3, 6)
    for (let i = 1; i < words.length; i += 1) {
      expect(words[i]?.start).toBeCloseTo(words[i - 1]?.end as number, 6)
    }
  })

  it('texto vazio não deixa palavra nenhuma', () => {
    expect(redistributeWords(cue, '   ')).toEqual([])
  })

  it('frase sem palavras usa o início e o fim da própria frase', () => {
    const words = redistributeWords({ start: 0, end: 1, words: undefined }, 'a b')
    expect(words[0]?.start).toBe(0)
    expect(words[1]?.end).toBeCloseTo(1, 6)
  })

  it('ignora espaços repetidos e nas pontas', () => {
    expect(redistributeWords(cue, '  oi   mundo  lindo ').map((w) => w.text)).toEqual(['oi', 'mundo', 'lindo'])
  })
})

describe('formatCueTime', () => {
  it('mostra minutos, segundos e centésimos', () => {
    expect(formatCueTime(0)).toBe('00:00.00')
    expect(formatCueTime(65.3)).toBe('01:05.30')
    expect(formatCueTime(5.5)).toBe('00:05.50')
  })

  it('trata valor ausente ou negativo como zero', () => {
    expect(formatCueTime(-3)).toBe('00:00.00')
    expect(formatCueTime(Number.NaN)).toBe('00:00.00')
  })
})

describe('withCueText', () => {
  it('devolve a frase nova com as palavras refeitas e não mexe na antiga', () => {
    const next = withCueText(cue, 'só uma')
    expect(next.text).toBe('só uma')
    expect(next.words).toHaveLength(2)
    expect(cue.text).toBe('olá mundo bonito')
    expect(cue.words).toHaveLength(3)
  })
})
