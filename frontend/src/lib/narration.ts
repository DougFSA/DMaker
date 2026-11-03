/* Regras puras da Narração: estimar a duração do roteiro, montar o item de `audio.narration`, achar onde a narração
   seguinte começa e acrescentá-la à spec. Sem rede e sem DOM, para testar direto. */
import type { SpecDocument, TimelineView } from '@/api'
import { formatDuration } from './format'

/** Ritmo médio da fala em português, para estimar a duração do roteiro (o servidor mede a real). */
export const CHARS_PER_SECOND = 14
/** Quantas narrações o histórico da sessão guarda. */
export const HISTORY_LIMIT = 30
export const EMPTY_SCRIPT_HINT = 'Escreva ou cole o roteiro da narração.'
/** O que o servidor aceita numa narração direta (cerca de 24 minutos de fala); a fila aceita muito mais. */
export const MAX_SCRIPT_CHARS = 20_000
export const SCRIPT_TOO_LONG = 'O roteiro passa de 20 mil caracteres, o limite de uma narração direta. Use Mandar para a fila.'

const PAUSE_MARKER = /\[pausa\s+(\d+(?:[.,]\d+)?)\]/gi
/** `[[termo|pronúncia]]` ou `[[pronúncia]]`: a pronúncia vale só naquela ocorrência. */
const INLINE_OVERRIDE = /\[\[([^\]]{0,256})\]\]/g

/** O texto como a voz o lê: `[[termo|pronúncia]]` vira a pronúncia (o servidor faz o mesmo). */
export function spokenForm(text: string): string {
  return text.replace(INLINE_OVERRIDE, (_match, inner: string) => inner.split('|').at(-1) ?? '')
}

/** Segundos estimados de fala: caracteres / 14 por segundo, ajustado pela velocidade, mais as pausas fixas de `[pausa 1.2]`. */
export function estimateSeconds(text: string, speed: number): number {
  let pauses = 0
  const spoken = spokenForm(text).replace(PAUSE_MARKER, (_match, value: string) => {
    pauses += Number.parseFloat(value.replace(',', '.'))
    return ' '
  })
  const characters = spoken.replace(/\s+/g, ' ').trim().length
  const rate = speed > 0 ? speed : 1
  return characters / CHARS_PER_SECOND / rate + pauses
}

/** A linha sob o roteiro: quantos caracteres e quanto tempo de fala isso dá. */
export function scriptStats(text: string, speed: number): string {
  if (!text.trim()) return EMPTY_SCRIPT_HINT
  const seconds = estimateSeconds(text, speed)
  return `${text.length} caracteres · duração estimada ${formatDuration(seconds)} (cerca de ${CHARS_PER_SECOND} caracteres por segundo)`
}

/** "" quando o roteiro cabe numa narração direta. */
export function scriptProblem(text: string): string {
  return text.length > MAX_SCRIPT_CHARS ? SCRIPT_TOO_LONG : ''
}

const speedFormat = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** A velocidade como a pessoa lê: "1,25x". */
export function speedLabel(speed: number): string {
  return `${speedFormat.format(speed)}x`
}

export const SEED_PROBLEM = 'A semente é um número inteiro, a partir de 0.'

/** A semente é opcional; quando existe, o servidor só aceita inteiro (e não negativo). "" quando está certa. */
export function seedProblem(seed: number | null): string {
  if (seed === null) return ''
  return Number.isInteger(seed) && seed >= 0 ? '' : SEED_PROBLEM
}

/** Primeiros caracteres do roteiro, para a lista do histórico. */
export function excerpt(text: string, limit = 70): string {
  return text.length > limit ? `${text.slice(0, limit)}...` : text
}

/** O que a narração precisa lembrar de um pedido para inserir no projeto e para refazer depois. */
export interface NarrationEntry {
  text: string
  voiceId: string | null
  speed: number
  language: string | null
  seed: number | null
}

/** Um item de `audio.narration` na spec do projeto. */
export interface SpecNarration {
  text: string
  start: number
  speed: number
  voice?: string
  language?: string
  seed?: number
}

/** O item de `audio.narration`: só leva voz, idioma e semente quando a pessoa escolheu, para o render usar o padrão. */
export function buildNarrationItem(entry: NarrationEntry, start: number): SpecNarration {
  const item: SpecNarration = {
    text: entry.text,
    start: Math.round(Math.max(0, start || 0) * 100) / 100,
    speed: entry.speed,
  }
  if (entry.voiceId) item.voice = entry.voiceId
  if (entry.language) item.language = entry.language
  if (entry.seed !== null && entry.seed !== undefined) item.seed = entry.seed
  return item
}

/**
 * Onde a próxima narração começa por padrão: o fim da última que o projeto já tem (a vista de linha do tempo dá a
 * duração real das que já foram sintetizadas e a estimada das outras). Sem narração no projeto, começa em 0.
 */
export function lastNarrationEnd(view: Pick<TimelineView, 'tracks'> | null): number {
  const track = view?.tracks.find((candidate) => candidate.id === 'NAR')
  const ends = (track?.items ?? []).map((item) => item.end).filter((end) => Number.isFinite(end))
  return ends.length ? Math.round(Math.max(...ends) * 100) / 100 : 0
}

/** A spec com a narração a mais em `audio.narration`; a original não é mexida. */
export function withNarration(spec: SpecDocument, item: SpecNarration): SpecDocument {
  const audio = (spec.audio ?? {}) as Record<string, unknown>
  const previous = Array.isArray(audio.narration) ? (audio.narration as unknown[]) : []
  return { ...spec, audio: { ...audio, narration: [...previous, item] } }
}
