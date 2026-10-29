/* Tipos das rotas de áudio (src/dmaker/ui/speech_routes.py): isolar voz, corrigir fala e trocar voz. */

/** POST /api/speech/upload: o arquivo fica em cache/uploads e a página usa o `path` nas outras rotas. */
export interface SpeechUpload {
  path: string
  name: string
}

/** Trecho de uma mídia (segundos); sem início e fim vale o arquivo inteiro. */
export interface SpeechMediaRequest {
  path: string
  start?: number | null
  end?: number | null
}

export type StemFormat = 'wav' | 'mp3'

export interface IsolateRequest extends SpeechMediaRequest {
  format?: StemFormat
}

/** Resultado do job de isolar: a voz de um lado, a música e o ruído do outro. */
export interface IsolationResult {
  voice: string
  background: string
  voice_url: string
  background_url: string
}

export interface WordsRequest extends SpeechMediaRequest {
  language?: string
}

export interface SpeechWord {
  start: number
  end: number
  text: string
}

/** Resultado do job de palavras; `pause_seconds` é a pausa que o servidor usa para agrupar por fôlego. */
export interface WordsResult {
  words: SpeechWord[]
  pause_seconds: number
}

/** Corrigir uma fala (POST /api/speech/fix): o trecho vem de `start`/`end` ou de `find` + `occurrence`. */
export interface FixSpeechRequest extends SpeechMediaRequest {
  text: string
  find?: string | null
  occurrence?: number | null
  search_from?: number | null
  search_to?: number | null
  voice?: string | null
  /** Inclui as palavras vizinhas na troca, para a emenda soar natural. */
  expand?: boolean
  /** Guarda a voz do falante na biblioteca com este nome. */
  save_voice?: string | null
  language?: string
  brand?: string | null
  /** Rascunho: menos passos de síntese, bem mais rápido. */
  draft?: boolean
}

/** Resultado do job de corrigir fala. */
export interface FixSpeechResult {
  output: string
  audio_url: string
  original: string
  original_url: string
  /** Início e fim, em segundos, do trecho trocado. */
  region: [number, number]
  old_text: string
  new_text: string
  spoken: string
  rule: string
  squeezed: boolean
  voice: string
}

export interface ConvertVoiceRequest extends SpeechMediaRequest {
  voice: string
}

/** Resultado do job de trocar voz; `excerpt` é verdadeiro quando só um trecho foi convertido. */
export interface ConversionResult {
  output: string
  audio_url: string
  original: string
  original_url: string
  voice: string
  seconds: number
  blocks: number
  gain_db: number
  excerpt: boolean
}
