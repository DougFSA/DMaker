/* Legendas automáticas editáveis: refazer o tempo das palavras quando o texto de uma frase muda, e o tempo na tabela. */
import type { CaptionCue, CaptionWord } from '@/api'

/**
 * Reparte o tempo de uma frase entre as palavras do texto novo, mantendo o início e o fim dela. Com a mesma
 * quantidade de palavras, cada uma só troca o texto e guarda o seu tempo; com outra quantidade, a duração se divide
 * pelo tamanho de cada palavra, que é o que mais se aproxima de quanto tempo cada uma leva para ser dita.
 */
export function redistributeWords(cue: Pick<CaptionCue, 'start' | 'end' | 'words'>, newText: string): CaptionWord[] {
  const tokens = newText.trim().split(/\s+/).filter(Boolean)
  const words = cue.words ?? []
  if (tokens.length === 0) return []
  if (words.length === tokens.length) {
    return tokens.map((text, i) => ({ start: (words[i] as CaptionWord).start, end: (words[i] as CaptionWord).end, text }))
  }
  const start = words.length ? (words[0] as CaptionWord).start : cue.start
  const end = words.length ? (words[words.length - 1] as CaptionWord).end : cue.end
  const totalDuration = Math.max(end - start, 0.001)
  const totalChars = tokens.reduce((sum, token) => sum + token.length, 0) || tokens.length
  let cursor = start
  return tokens.map((text) => {
    const share = (text.length / totalChars) * totalDuration
    const wordStart = cursor
    const wordEnd = Math.min(cursor + share, end)
    cursor = wordEnd
    return { start: wordStart, end: wordEnd, text }
  })
}

/** O tempo da tabela de legendas, "01:05.30" (minutos, segundos e centésimos). */
export function formatCueTime(seconds: number): string {
  const total = Math.max(0, seconds || 0)
  const minutes = Math.floor(total / 60)
  const rest = (total % 60).toFixed(2).padStart(5, '0')
  return `${String(minutes).padStart(2, '0')}:${rest}`
}

/** Troca o texto de uma frase e refaz o tempo das palavras dela; devolve a frase nova, sem alterar a antiga. */
export function withCueText(cue: CaptionCue, text: string): CaptionCue {
  return { ...cue, text, words: redistributeWords(cue, text) }
}
