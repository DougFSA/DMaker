/* Funções puras das telas de áudio da Voz (isolar, corrigir fala e trocar voz): agrupar as palavras da transcrição,
   escolher o trecho a trocar, validar o intervalo e escrever o resumo do que o servidor fez. Sem rede e sem DOM. */
import type { ConversionResult, FixSpeechResult, SpeechWord } from '@/api'

/** Pausa que o falante usa para tomar fôlego; o servidor devolve o mesmo valor junto das palavras. */
export const BREATH_PAUSE_S = 0.25

/** O trecho entre duas palavras clicadas: os índices na lista, o tempo e o texto que as palavras formam. */
export interface WordSelection {
  first: number
  last: number
  start: number
  end: number
  text: string
}

/** Palavras em grupos de fôlego: uma pausa de `pause` segundos ou mais entre duas palavras abre um grupo novo. */
export function groupWordsByBreath(words: readonly SpeechWord[], pause: number = BREATH_PAUSE_S): number[][] {
  const groups: number[][] = []
  words.forEach((word, index) => {
    const group = groups.at(-1)
    const previous = group ? words[group[group.length - 1]!] : undefined
    if (group && previous && word.start - previous.end < pause) group.push(index)
    else groups.push([index])
  })
  return groups
}

/** O trecho entre duas palavras clicadas, em qualquer ordem. Índice fora da lista não tem trecho. */
export function selectionFor(words: readonly SpeechWord[], a: number, b: number): WordSelection | null {
  const first = Math.min(a, b)
  const last = Math.max(a, b)
  const firstWord = words[first]
  const lastWord = words[last]
  if (!firstWord || !lastWord) return null
  return {
    first,
    last,
    start: firstWord.start,
    end: lastWord.end,
    text: words
      .slice(first, last + 1)
      .map((word) => word.text)
      .join(' '),
  }
}

const seconds1 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const seconds2 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Segundos com uma casa e vírgula: "21,4". */
export function formatSeconds(value: number): string {
  return seconds1.format(value)
}

/** Segundos com duas casas e vírgula, para o instante exato de uma palavra: "2,50". */
export function formatSecondsPrecise(value: number): string {
  return seconds2.format(value)
}

/** Texto do trecho escolhido na transcrição, ou o passo seguinte quando ainda não há trecho. */
export function describeSelection(selection: WordSelection | null, anchorPicked: boolean): string {
  if (selection) {
    return `Trecho escolhido: "${selection.text}" (${formatSecondsPrecise(selection.start)} a ${formatSecondsPrecise(selection.end)} s)`
  }
  return anchorPicked ? 'Agora clique na última palavra do trecho.' : 'Nenhum trecho escolhido.'
}

export const RANGE_ORDER_ERROR = 'O fim precisa ser maior que o início.'

/** O intervalo opcional de início e fim em segundos: vazio vale o arquivo inteiro; "" quando está certo. */
export function rangeProblem(start: number | null, end: number | null): string {
  if (start !== null && start < 0) return 'O início não pode ser negativo.'
  if (end !== null && end < 0) return 'O fim não pode ser negativo.'
  if (start !== null && end !== null && end <= start) return RANGE_ORDER_ERROR
  return ''
}

/** Frase de resumo do que a correção fez: o que saiu, o que entrou, onde e como a duração foi tratada. */
export function describeFix(result: FixSpeechResult): string {
  const [from, to] = result.region
  const region = `${formatSeconds(from)} a ${formatSeconds(to)} s`
  const warning = result.squeezed ? ' Atenção: a fala ficou apertada, tente um texto mais curto.' : ''
  return `Trocado "${result.old_text}" por "${result.new_text}" (região ${region}). Duração: ${result.rule}.${warning}`
}

/** Frase de resumo da troca de voz: trecho ou arquivo, blocos e o ajuste de volume que igualou ao original. */
export function describeConversion(result: ConversionResult): string {
  const gain = result.gain_db
  const level =
    Math.abs(gain) < 0.05
      ? 'volume igual ao original'
      : `volume ${gain > 0 ? 'subiu' : 'desceu'} ${formatSeconds(Math.abs(gain))} dB para igualar ao original`
  const part = result.excerpt ? 'Trecho convertido' : 'Arquivo convertido'
  return `${part} para a voz ${result.voice}: ${formatSeconds(result.seconds)} s em ${result.blocks} bloco(s); ${level}.`
}

/** O arquivo trocado só substitui o original no projeto quando cobre o arquivo inteiro. */
export function canUseConversion(result: Pick<ConversionResult, 'excerpt'> | null, hasEntry: boolean): boolean {
  return !!result && hasEntry && !result.excerpt
}

/**
 * Rótulo de uma voz da biblioteca no seletor. As prontas já trazem o gênero no nome ("Dora (feminina)"), então ficam
 * como estão; as clonadas e as desenhadas ganham como foram feitas, para não se confundirem com uma pronta.
 */
export function voiceLabel(voice: { name: string; kind: 'clone' | 'design' | 'preset' }): string {
  if (voice.kind === 'preset') return voice.name
  return `${voice.name} (${voice.kind === 'clone' ? 'clonada' : 'desenhada'})`
}

/** O mesmo endereço pedindo o arquivo como anexo (`download=true`), sem perder os parâmetros que já tem. */
export function downloadUrl(url: string): string {
  return `${url}${url.includes('?') ? '&' : '?'}download=true`
}
