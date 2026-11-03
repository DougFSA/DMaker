/* Regras puras do dicionário de pronúncia: a frase para ouvir um termo, a chave de cada entrada e o texto do escopo.
   Sem rede e sem DOM. */
import type { AddPronunciationRequest, VoiceOption } from '@/api'

/** O escopo que o servidor dá aos termos que valem para todas as marcas. */
export const GLOBAL_SCOPE = 'global'
export const DEFAULT_PRONUNCIATION_LANGUAGE = 'pt'

/**
 * A frase curta para ouvir um termo, no idioma dele. O termo aparece duas vezes: a primeira vez pode soar solta, e
 * a segunda deixa ouvir como a voz o diz de verdade.
 */
export function pronunciationPreviewText(term: string, language: string): string {
  const word = term.trim()
  const code = (language || DEFAULT_PRONUNCIATION_LANGUAGE).toLowerCase().split(/[-_]/)[0]
  if (code === 'en') return `I say ${word}. Again: ${word}.`
  return `Eu falo ${word}. Repito: ${word}.`
}

/** Identifica uma entrada do dicionário: o mesmo termo pode existir em idiomas diferentes. */
export function pronunciationKey(term: string, language: string): string {
  return `${language}:${term}`
}

/** "Todas as marcas" para o termo global, ou o nome da marca dona dele (a chave, se a marca já não existe). */
export function scopeLabel(scope: string, brands: readonly VoiceOption[]): string {
  if (scope === GLOBAL_SCOPE) return 'Todas as marcas'
  return brands.find((brand) => brand.value === scope)?.label ?? scope
}

export interface PronunciationForm {
  term: string
  spoken: string
  brand: string
  language: string
}

/** Só adiciona com o termo e como falá-lo preenchidos. */
export function canAddPronunciation(form: Pick<PronunciationForm, 'term' | 'spoken'>): boolean {
  return form.term.trim() !== '' && form.spoken.trim() !== ''
}

/** O pedido de adicionar: espaços das pontas fora, marca vazia vira o dicionário global. */
export function pronunciationRequest(form: PronunciationForm): AddPronunciationRequest {
  return {
    term: form.term.trim(),
    spoken: form.spoken.trim(),
    brand: form.brand || null,
    language: form.language || DEFAULT_PRONUNCIATION_LANGUAGE,
  }
}
