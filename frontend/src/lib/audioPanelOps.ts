/* O que cada comando do painel Áudio vira em operações do servidor, dado o alvo, o relógio do item e a seleção. Funções
   puras que devolvem as operações ou o aviso para a pessoa, como `lib/editorActions`; quem as executa é o store do painel.

   O painel fala em tempo do eixo do item (o tempo dos efeitos); as operações de edição de onda (silenciar, cortar,
   dividir, marcador) falam em tempo da linha do tempo do projeto, e o relógio faz a conversão. O efeito aplicado pela
   janela é a exceção: ele grava o intervalo direto em tempo do eixo, que é o que a spec guarda. */
import type { AudioEffectSettings, EditOperation } from '@/api'
import type { AxisSelection, ItemClockInfo } from './audioWave'
import type { Plan } from './editorActions'
import { roundSeconds } from './timeline'

const fail = (message: string): Plan => ({ ok: false, message })

/** Os efeitos espectrais (Apagar, Multiferramenta, EQ e Prateleiras) têm o tipo começando assim e levam `low_hz` e `high_hz`. */
export const SPECTRAL_PREFIX = 'spectral_'

/** Os segundos da seleção que a prévia de um efeito toca: o suficiente para ouvi-lo sem esperar um trecho longo ser processado. */
export const PREVIEW_SECONDS = 10

const NO_CLOCK =
  'Este som segue a sessão de gravação e não tem um lugar certo na linha do tempo: aplique efeitos ou silencie pelo painel Filtros.'

/** O instante do eixo como instante da linha do tempo, ou null quando o item não tem lugar nela. */
export function toProjectTime(clock: ItemClockInfo | null, axisTime: number): number | null {
  if (!clock) return null
  return roundSeconds(clock.start + (axisTime - clock.origin) / clock.speed)
}

/** O caminho de volta: o instante da linha do tempo do projeto como instante do eixo do item. */
export function toAxisTime(clock: ItemClockInfo, projectTime: number): number {
  return clock.origin + (projectTime - clock.start) * clock.speed
}

/** O caminho do alvo na spec que guarda os efeitos dele (`audio.voiceover.0` -> `audio.voiceover.0.effects`). */
export function effectsPathOf(target: string): string {
  return `${target}.effects`
}

/** O alvo é uma voz gravada (a única que aceita dividir). */
export const isVoiceTarget = (target: string): boolean => /^audio\.voiceover\.\d+$/.test(target)

/** O alvo é uma faixa externa (sincronizada por sessão: aceita efeito e silêncio, não corte nem colagem). */
export const isTrackTarget = (target: string): boolean => /^audio\.tracks\.\d+$/.test(target)

function interval(clock: ItemClockInfo | null, selection: AxisSelection | null): { start: number; end: number } | string {
  if (!selection) return 'Selecione um trecho na onda (arraste sobre ela).'
  const start = toProjectTime(clock, selection.start)
  const end = toProjectTime(clock, selection.end)
  if (start === null || end === null) return NO_CLOCK
  return { start, end }
}

/** Silenciar a seleção (Ctrl+L): o som do trecho zera, a duração do item não muda. */
export function planSilence(target: string, clock: ItemClockInfo | null, selection: AxisSelection | null): Plan {
  const span = interval(clock, selection)
  if (typeof span === 'string') return fail(span)
  return { ok: true, ops: [{ type: 'audio_silence', target, start: span.start, end: span.end }] }
}

/** Bipar a seleção: silencia o trecho no item e põe um Tom de 1 kHz sobre ele (a operação `censor_beep`, um passo só do desfazer). */
export function planCensorBeep(target: string, clock: ItemClockInfo | null, selection: AxisSelection | null): Plan {
  const span = interval(clock, selection)
  if (typeof span === 'string') return fail(span)
  return { ok: true, ops: [{ type: 'censor_beep', target, start: span.start, end: span.end }] }
}

/** Cortar a seleção (Delete): na voz gravada o item encolhe e os seguintes recuam; nos presos à imagem o fim completa com silêncio. */
export function planCut(target: string, clock: ItemClockInfo | null, selection: AxisSelection | null): Plan {
  if (isTrackTarget(target)) {
    return fail('A faixa externa segue a sessão e não aceita cortar: silencie o trecho, ou corte o item que a alimenta.')
  }
  const span = interval(clock, selection)
  if (typeof span === 'string') return fail(span)
  return { ok: true, ops: [{ type: 'audio_cut', target, start: span.start, end: span.end }] }
}

/** Dividir no cursor (Ctrl+I): só a voz gravada se divide em dois itens; nos outros, a divisão é o corte da linha do tempo. */
export function planSplitAt(target: string, clock: ItemClockInfo | null, cursor: number): Plan {
  if (!isVoiceTarget(target)) {
    return fail('Dividir o som vale para a voz gravada. Para o clipe use o corte da linha do tempo (S), que divide imagem e som juntos.')
  }
  const at = toProjectTime(clock, cursor)
  if (at === null) return fail(NO_CLOCK)
  return { ok: true, ops: [{ type: 'audio_split', target, at }] }
}

/** Marcador na seleção (Ctrl+B): uma região quando há seleção, um instante no cursor quando não há. */
export function planLabel(clock: ItemClockInfo | null, selection: AxisSelection | null, cursor: number): Plan {
  if (selection) {
    const span = interval(clock, selection)
    if (typeof span === 'string') return fail(span)
    // o marcador de uma seleção espectral guarda a faixa de frequência (o formato de troca com o Audacity a leva)
    const band = selection.low_hz !== undefined && selection.high_hz !== undefined ? { low_hz: selection.low_hz, high_hz: selection.high_hz } : {}
    return { ok: true, ops: [{ type: 'marker_add', start: span.start, end: span.end, text: '', ...band }] }
  }
  const at = toProjectTime(clock, cursor)
  if (at === null) return fail(NO_CLOCK)
  return { ok: true, ops: [{ type: 'marker_add', at, text: '' }] }
}

/**
 * Aplicar um efeito do catálogo: o efeito entra ao fim da cadeia, com o intervalo da seleção em tempo do eixo (sem
 * seleção, o item inteiro). `params` são os valores do formulário; os campos vazios e iguais ao padrão não precisam ir.
 */
export function planEffect(
  target: string,
  type: string,
  params: Record<string, unknown>,
  selection: AxisSelection | null,
): Plan {
  const effect: AudioEffectSettings = { type, ...params }
  if (selection) {
    effect.start = roundSeconds(selection.start)
    effect.end = roundSeconds(selection.end)
  }
  if (selection?.low_hz !== undefined && effect.low_hz === undefined && type.startsWith(SPECTRAL_PREFIX)) effect.low_hz = selection.low_hz
  if (selection?.high_hz !== undefined && effect.high_hz === undefined && type.startsWith(SPECTRAL_PREFIX)) effect.high_hz = selection.high_hz
  return { ok: true, ops: [{ type: 'audio_effect', action: 'add', target, effect }] }
}

/* ---------- envelope ---------- */

export interface EnvelopePoint {
  at: number
  db: number
}

/** O ganho mais baixo que o envelope mostra e aceita ao arrastar; abaixo disso o som já é silêncio para o ouvido. */
export const ENVELOPE_MIN_DB = -60
/** O mais alto: 12 dB acima do original cobre a correção de uma gravação baixa sem deixar o ponto sair da tela. */
export const ENVELOPE_MAX_DB = 12

/** A curva em ordem de tempo e sem dois pontos no mesmo instante (a spec recusa), com o ganho dentro da faixa. */
export function tidyEnvelope(points: readonly EnvelopePoint[], minGap = 0.001): EnvelopePoint[] {
  const sorted = [...points]
    .map((point) => ({
      at: Math.max(0, roundSeconds(point.at)),
      db: Math.min(ENVELOPE_MAX_DB, Math.max(ENVELOPE_MIN_DB, Math.round(point.db * 10) / 10)),
    }))
    .sort((a, b) => a.at - b.at)
  const result: EnvelopePoint[] = []
  for (const point of sorted) {
    const last = result[result.length - 1]
    if (last && point.at - last.at < minGap) result[result.length - 1] = point
    else result.push(point)
  }
  return result
}

/** O ganho da curva num instante do eixo (reta em dB entre os pontos, a ponta fora deles), igual ao do servidor. */
export function envelopeGainAt(points: readonly EnvelopePoint[], time: number): number {
  if (points.length === 0) return 0
  const first = points[0] as EnvelopePoint
  if (time <= first.at) return first.db
  for (let index = 1; index < points.length; index += 1) {
    const before = points[index - 1] as EnvelopePoint
    const after = points[index] as EnvelopePoint
    if (time <= after.at) return before.db + ((after.db - before.db) * (time - before.at)) / (after.at - before.at)
  }
  return (points[points.length - 1] as EnvelopePoint).db
}

/** Grava a curva: a primeira vez cria o efeito pela operação `audio_envelope` (tempo do projeto); as seguintes trocam os
 *  pontos do efeito que já está na cadeia (`index`), em tempo do eixo, sem empilhar outro envelope. */
export function planEnvelope(
  target: string,
  clock: ItemClockInfo | null,
  points: readonly EnvelopePoint[],
  existingIndex: number | null,
): Plan {
  const tidy = tidyEnvelope(points)
  if (tidy.length === 0) return fail('A curva precisa de ao menos um ponto.')
  if (existingIndex !== null) {
    return {
      ok: true,
      ops: [{ type: 'audio_effect', action: 'set', target, index: existingIndex, params: { points: tidy } }],
    }
  }
  const converted: Array<{ at: number; db: number }> = []
  for (const point of tidy) {
    const at = toProjectTime(clock, point.at)
    if (at === null) return fail(NO_CLOCK)
    converted.push({ at, db: point.db })
  }
  return { ok: true, ops: [{ type: 'audio_envelope', target, points: converted }] }
}

/** Muda o estado de uma trilha de áudio (solo, ganho, pan) pela operação `track_set`. */
export function trackSetOp(track: string, changes: { solo?: boolean; gain_db?: number; pan?: number }): EditOperation {
  return { type: 'track_set', track, ...changes }
}
