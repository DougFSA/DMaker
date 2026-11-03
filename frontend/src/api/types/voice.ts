/* Tipos do estúdio de voz (src/dmaker/ui/voice_routes.py). Os nomes dos campos seguem o backend. */

export type VoiceKind = 'clone' | 'design' | 'preset'
export type VoiceEngine = 'omnivoice' | 'kokoro'

/** Uma voz da biblioteca (GET /api/voices e o retorno de clonar e desenhar). */
export interface VoiceProfile {
  id: string
  name: string
  kind: VoiceKind
  engine: VoiceEngine
  /** Nome da voz pronta dentro do motor (só nas de `kind: 'preset'`). */
  preset: string | null
  language: string
  brand: string | null
  instruct: string | null
  /** Caminho do áudio de referência, quando a voz é um clone. */
  reference: string | null
  reference_text: string | null
  created: string
}

/** Uma opção dos selects da página: valor canônico para o servidor e rótulo em português. */
export interface VoiceOption {
  value: string
  label: string
}

/** GET /api/voices/design-options. */
export interface VoiceDesignOptions {
  gender: VoiceOption[]
  age: VoiceOption[]
  pitch: VoiceOption[]
  accent: VoiceOption[]
  languages: VoiceOption[]
}

/** Clonar a partir de uma gravação: o áudio vai em multipart, os outros campos são opcionais. */
export interface CloneVoiceRequest {
  name: string
  audio: Blob
  /** Nome do arquivo enviado; o servidor usa a extensão. Gravações do microfone não têm nome próprio. */
  filename?: string
  /** O que a gravação diz; sem ele o servidor transcreve. */
  reference_text?: string | null
  brand?: string | null
  language?: string
}

/** Desenhar uma voz por descrição (POST /api/voices/design). */
export interface DesignVoiceRequest {
  name: string
  gender?: string | null
  age?: string | null
  pitch?: string | null
  accent?: string | null
  whisper?: boolean
  /** Descrição livre; quando dada, vale no lugar dos campos acima. */
  instruct?: string | null
  brand?: string | null
  language?: string
}

/** Narrar um texto (POST /api/voices/speak); `speed` vai de 0,5 a 2 e o texto, até 20 mil caracteres. */
export interface SpeakRequest {
  text: string
  voice?: string | null
  language?: string | null
  speed?: number
  seed?: number | null
  instruct?: string | null
  /** Marca cujo dicionário de pronúncia vale; sem ela vale a da voz. */
  brand?: string | null
}

/** Uma fala da narração pronta (o resultado do job traz a lista). */
export interface NarrationCue {
  start: number
  end: number
  text: string
}

/** Resultado do job de narração e da prévia de uma voz. */
export interface NarrationResult {
  output: string
  audio_url: string
  duration_s: number
  cues: NarrationCue[]
}

/** Resultado de um job de narração parado a pedido: quantas falas já saíram. */
export interface NarrationStopped {
  ready: number
  total: number
}

/** Evento `utterance` do SSE de uma narração: cada fala pronta, para tocar ao vivo. */
export interface UtteranceEvent {
  kind: 'utterance'
  t: number
  index: number
  total: number
  audio_url: string
  duration_s: number
  pause_after_s: number
}

export interface PronunciationEntry {
  term: string
  spoken: string
  /** `global` ou a marca dona do termo. */
  scope: string
  language: string
}

/** Resposta de listar, adicionar e remover pronúncias: sempre a lista atual. */
export interface PronunciationList {
  brand: string | null
  entries: PronunciationEntry[]
}

export interface AddPronunciationRequest {
  term: string
  spoken: string
  brand?: string | null
  language?: string
}
