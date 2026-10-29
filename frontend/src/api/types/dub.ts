/* Tipos das rotas de dublagem (src/dmaker/ui/dub_routes.py). */

export type DubSpeakerMode = 'per_speaker' | 'per_segment' | 'single'

/** O que fazer quando a tradução não cabe no tempo da fala original: acelerar a voz, esticar o vídeo ou os dois. */
export type DubFitMode = 'voz' | 'video' | 'misto'

/** GET /api/dub/projects: os projetos .dub.json de output/dublagem, do mais novo ao mais antigo. */
export interface DubProjectFile {
  path: string
  name: string
}

/** Preparar a dublagem: transcreve, separa os falantes e traduz (POST /api/dub/prepare, um job). */
export interface DubPrepareRequest {
  path: string
  target_language: string
  source_language?: string
  speaker_mode?: DubSpeakerMode | null
  /** Quantas pessoas falam; de 1 a 12. */
  num_speakers?: number | null
  voice?: string | null
  /** Volume da voz original por baixo da dublada, em dB (zero ou negativo). */
  keep_original_db?: number | null
  glossary?: string[]
  fit_mode?: DubFitMode
}

export interface DubSegment {
  id: string
  start: number
  end: number
  original: string
  text: string
  locked: boolean
  speaker: string | null
}

/** O projeto de dublagem como a tela o edita (GET/PUT /api/dub/project e o resultado de preparar). */
export interface DubProjectSummary {
  project: string
  source: string
  source_url: string
  source_language: string
  target_language: string
  speaker_mode: DubSpeakerMode
  speakers: string[]
  voice: string | null
  keep_original_db: number | null
  fit_mode: DubFitMode
  glossary: string[]
  translator_model: string
  segments: DubSegment[]
}

/** Edição de uma fala ao salvar: o texto traduzido, se está travada e, opcionalmente, o falante. */
export interface DubSegmentEdit {
  id: string
  text: string
  locked?: boolean
  speaker?: string | null
}

export interface DubProjectUpdate {
  project: string
  segments: DubSegmentEdit[]
  keep_original_db?: number | null
  speaker_mode?: DubSpeakerMode | null
  voice?: string | null
  fit_mode?: DubFitMode | null
}

/** Corpo de retraduzir, gerar e exportar trilhas. `draft` usa menos passos de síntese. */
export interface DubRunRequest {
  project: string
  draft?: boolean
}

/** O que aconteceu com uma fala na geração: cabe, avança, comprimida, esticada, não coube ou vazia. */
export type DubSegmentStatus = 'fits' | 'advances' | 'squeezed' | 'stretched' | 'overflow' | 'empty'

export interface DubSegmentReport {
  id: string
  start: number
  end: number
  text: string
  natural_seconds: number
  speech_seconds: number
  played_seconds: number
  tempo: number
  video_stretch: number
  retimed_start: number | null
  status: DubSegmentStatus
  message: string
  cached: boolean
  speaker: string
  voice: string
}

export interface DubStretchedSegment {
  id: string
  start: number
  factor: number
  added_seconds: number
}

/** Resultado do job de gerar a dublagem. */
export interface DubRenderResult {
  output: string
  output_url: string
  download_url: string
  srt: string
  srt_url: string
  original: string
  original_url: string
  report: DubSegmentReport[]
  fit_mode: DubFitMode
  output_seconds: number
  stretched: DubStretchedSegment[]
  warnings: string[]
  regenerated: number
  timings: Record<string, number>
}

/** Resultado do job de exportar as trilhas separadas (um .zip). */
export interface DubStemsResult {
  folder: string
  files: string[]
  zip: string
  zip_url: string
  duration: number
  original_voice_db: number | null
}
