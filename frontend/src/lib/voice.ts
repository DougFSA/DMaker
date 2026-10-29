/* Regras puras da biblioteca de vozes e da gravação de referência: sem rede e sem DOM, para testar direto. */
import type { DesignVoiceRequest, VoiceKind, VoiceOption, VoiceProfile } from '@/api'
import { formatClock } from './format'

/** Faixa que o clone aproveita melhor: fala limpa de 5 a 8 segundos. */
export const RECOMMENDED_MIN_S = 5
export const RECOMMENDED_MAX_S = 8
/** O servidor só usa os primeiros 15 s da referência (o resto é descartado). */
export const MAX_USED_S = 15
/** Limite do arquivo enviado, o mesmo do servidor (MAX_UPLOAD_BYTES): barrar aqui poupa o envio. */
export const MAX_REFERENCE_BYTES = 50 * 1024 * 1024
/** O que o seletor de arquivo de referência aceita: áudio, ou vídeo do qual o servidor tira o áudio. */
export const REFERENCE_ACCEPT = 'audio/*,video/*,.wav,.mp3,.m4a,.ogg,.webm,.mp4'

/** Chave onde a última voz escolhida fica guardada; é a mesma da interface clássica, para as duas lembrarem juntas. */
export const LAST_VOICE_KEY = 'dmaker.voice.lastVoice'

export type AdviceLevel = 'bad' | 'ok' | 'good'

export interface RecordingAdvice {
  level: AdviceLevel
  text: string
}

/** Conselho sobre o tamanho da gravação de referência, para quem grava saber se já basta. */
export function recordingAdvice(seconds: number): RecordingAdvice {
  if (seconds < 3) return { level: 'bad', text: 'Muito curto: grave pelo menos 5 segundos de fala.' }
  if (seconds < RECOMMENDED_MIN_S) return { level: 'ok', text: 'Quase lá: o ideal são de 5 a 8 segundos.' }
  if (seconds <= RECOMMENDED_MAX_S) return { level: 'good', text: 'Ótimo: de 5 a 8 segundos de fala limpa.' }
  if (seconds <= MAX_USED_S) return { level: 'ok', text: 'Dá para usar, mas de 5 a 8 segundos já bastam.' }
  return { level: 'bad', text: `Só os primeiros ${MAX_USED_S} segundos serão usados.` }
}

/** O conselho de antes de gravar, quando ainda não há duração para avaliar. */
export const INITIAL_ADVICE: RecordingAdvice = {
  level: 'ok',
  text: 'Recomendado: 5 a 8 segundos de fala limpa.',
}

/** Extensão do arquivo gravado pelo MediaRecorder, a partir do tipo MIME (o servidor escolhe o leitor por ela). */
export function extensionForMime(mime: string | null | undefined): string {
  const type = String(mime ?? '').toLowerCase()
  if (type.includes('ogg')) return 'ogg'
  if (type.includes('mp4')) return 'm4a'
  if (type.includes('wav')) return 'wav'
  return 'webm'
}

const KIND_LABELS: Record<VoiceKind, string> = {
  clone: 'clonada',
  design: 'desenhada',
  preset: 'pronta',
}

export function voiceKindLabel(kind: VoiceKind): string {
  return KIND_LABELS[kind] ?? kind
}

/** "Ana (clonada)": como a voz aparece num seletor (a Narração usa o mesmo rótulo). */
export function voiceOptionLabel(voice: Pick<VoiceProfile, 'name' | 'kind'>): string {
  return `${voice.name} (${voiceKindLabel(voice.kind)})`
}

/** As marcas como opções de um seletor: o nome da marca, ou a pasta dela se o `brand.json` não der nome. */
export function brandOptions(brands: ReadonlyArray<{ key: string; name: string }>): VoiceOption[] {
  return brands.map((brand) => ({ value: brand.key, label: brand.name || brand.key }))
}

/** O nome do idioma em português; um código que a lista não conhece volta como está. */
export function languageLabel(code: string, languages: readonly VoiceOption[]): string {
  return languages.find((language) => language.value === code)?.label ?? code
}

/** A linha de detalhes de uma voz: idioma, marca, motor e descrição, só o que existe. */
export function voiceDetails(voice: VoiceProfile, languages: readonly VoiceOption[]): string {
  return [languageLabel(voice.language, languages), voice.brand, voice.engine, voice.instruct]
    .filter(Boolean)
    .join(' · ')
}

export interface PreviewStatus {
  text: string
  failed: boolean
}

/** A linha sob a voz enquanto a amostra é gerada (com o relógio e a etapa) ou quando ela falhou; vazia sem amostra. */
export function previewStatus(
  preview: { startedAtMs: number; label: string; error: string } | undefined,
  nowMs: number,
): PreviewStatus {
  if (!preview) return { text: '', failed: false }
  if (preview.error) return { text: `Não consegui gerar a amostra: ${preview.error}`, failed: true }
  const elapsed = formatClock(Math.max(0, nowMs - preview.startedAtMs) / 1000)
  const step = preview.label ? ` · ${preview.label}` : ''
  return { text: `Gerando amostra... ${elapsed}${step}`, failed: false }
}

/** As vozes prontas vêm com o motor e não podem ser apagadas; só as clonadas e as desenhadas saem da biblioteca. */
export function isRemovable(voice: Pick<VoiceProfile, 'kind'>): boolean {
  return voice.kind !== 'preset'
}

export interface CloneFormState {
  name: string
  /** Há um arquivo escolhido ou uma gravação pronta. */
  hasReference: boolean
  /** A caixa de permissão do dono da voz está marcada. */
  consent: boolean
}

/** O que ainda falta para clonar, em frases curtas, na ordem em que a pessoa preenche. */
export function cloneMissing(state: CloneFormState): string[] {
  const missing: string[] = []
  if (!state.name.trim()) missing.push('dar um nome à voz')
  if (!state.hasReference) missing.push('enviar um arquivo ou gravar pelo microfone')
  if (!state.consent) missing.push('marcar a permissão do dono da voz')
  return missing
}

export interface DesignFormState {
  name: string
  gender: string
  age: string
  pitch: string
  accent: string
  language: string
  brand: string
  whisper: boolean
  instruct: string
}

/** O pedido de "Desenhar": campos em branco viram `null` e a descrição livre perde os espaços das pontas. */
export function designRequest(form: DesignFormState): DesignVoiceRequest {
  return {
    name: form.name.trim(),
    gender: form.gender || null,
    age: form.age || null,
    pitch: form.pitch || null,
    accent: form.accent || null,
    whisper: form.whisper,
    instruct: form.instruct.trim() || null,
    brand: form.brand || null,
    language: form.language,
  }
}
