/* Tipos das rotas do editor (src/dmaker/ui/server.py): salvar a spec, legendas, linha do tempo, edição por
   operação, tema, proxies, sondagem de mídia, forma de onda, sincronização, conferência do vídeo e layouts. */
import type { JobSnapshot } from '../types'

/** A spec do projeto como o servidor a aceita (PUT /api/projects/{nome}); a validação completa é do backend. */
export type SpecDocument = Record<string, unknown>

/** PUT /api/projects/{nome}. */
export interface SaveProjectResponse {
  ok: boolean
  spec_path: string
}

/* ---------- legendas automáticas ---------- */

export interface CaptionWord {
  start: number
  end: number
  text: string
  /** Confiança do modelo (0 a 1); ausente em legenda que não veio do Whisper. */
  probability?: number | null
}

export interface CaptionCue {
  start: number
  end: number
  text: string
  words?: CaptionWord[]
}

/** GET /api/projects/{nome}/captions: o arquivo captions.auto.json do projeto. */
export interface CaptionsDocument {
  language: string
  cues: CaptionCue[]
  [extra: string]: unknown
}

/** PUT /api/projects/{nome}/captions. */
export interface CaptionsSaved {
  ok: boolean
  cues: number
}

/* ---------- linha do tempo ---------- */

export type TrackKind = 'video' | 'audio' | 'text' | 'graphics' | 'captions'

/** Um item de uma trilha da vista (trecho, sobreposição, faixa de áudio, narração, música ou legenda). */
export interface TimelineItem {
  id: string
  kind: string
  /** Posição de origem do item: em `timeline`, `overlays` ou `audio.tracks`. */
  index: number
  label: string
  start: number
  end: number
  in_point: number
  out_point: number | null
  src: string | null
  source: string | null
  transition: Record<string, unknown> | null
  muted: boolean
  /** Detalhes que dependem do tipo (velocidade, posição, pedaços de fonte com `parts`, narração estimada). */
  extra: Record<string, unknown>
  /** Caminho absoluto resolvido pelo servidor; nulo em cartão, texto e logo. */
  path: string | null
}

export interface TimelineTrack {
  id: string
  kind: TrackKind
  label: string
  muted: boolean
  hidden: boolean
  locked: boolean
  items: TimelineItem[]
}

/** Uma fonte sincronizada na vista, com o caminho já resolvido. */
export interface TimelineSource {
  src: string
  parts: string[]
  offset: number
  in_point: number
  path: string
}

/** POST /api/projects/{nome}/timeline e o campo `timeline` da resposta de editar. */
export interface TimelineView {
  total: number
  fps: number
  width: number
  height: number
  tracks: TimelineTrack[]
  sources: Record<string, TimelineSource>
  warnings: string[]
}

/** As dez operações de POST /api/projects/{nome}/edit. */
export type EditOperation =
  | { type: 'split'; index: number; at: number }
  | { type: 'remove'; index: number }
  | { type: 'move'; index: number; to: number }
  | { type: 'trim'; index: number; side: 'in' | 'out'; delta: number }
  | { type: 'duplicate'; index: number }
  | { type: 'insert'; index: number; segment: Record<string, unknown> }
  | { type: 'overlay_span'; index: number; start: number; end?: number | null }
  | { type: 'overlay_remove'; index: number }
  | { type: 'overlay_duplicate'; index: number }
  | { type: 'set_field'; path: string; value: unknown }

export interface EditResponse {
  spec: SpecDocument
  timeline: TimelineView
}

/* ---------- tema e cartões ---------- */

/** GET /api/projects/{nome}/theme: o que o player precisa para desenhar texto e logo como o render. */
export interface ProjectTheme {
  colors: Record<string, string>
  font: string
  logos: Record<string, string | null>
  no_dash: boolean
}

/** Campos do cartão para GET /api/card-preview (PNG); só `title` é obrigatório. */
export interface CardPreviewParams {
  title: string
  brand?: string | null
  preset?: string
  subtitle?: string | null
  variant?: string | null
  logo?: boolean
  background?: string | null
  width?: number
}

/* ---------- proxies de prévia ---------- */

export interface ProxyEntry {
  src: string
  proxy: string
  ready: boolean
  url: string | null
}

/** POST /api/projects/{nome}/proxies: `job` é o snapshot do job que gera os que faltam (nulo se já estão prontos). */
export interface ProxiesBuild {
  job: JobSnapshot | null
  proxies: ProxyEntry[]
}

/* ---------- sondagem, forma de onda e sincronização ---------- */

export type ProbeKind = 'image' | 'video' | 'audio'

/** Um arquivo sondado por POST /api/probe; os que falham voltam só com `error`. */
export type ProbeEntry =
  | {
      path: string
      url: string | null
      kind: ProbeKind
      width: number
      height: number
      duration_s: number
      fps: number
      has_audio: boolean
      orientation: string
      error?: undefined
    }
  | { path: string; error: string }

/** GET /api/waveform. */
export interface Waveform {
  duration: number
  peaks_per_second: number
  peaks: number[]
}

export interface SyncRequest {
  master: string
  others: string[]
  master_stream?: number
  stream?: number
}

export interface SyncResult {
  path: string
  offset_s: number
  confidence: number
  reliable: boolean
}

/* ---------- conferência do vídeo renderizado ---------- */

export interface QaSheetRequest {
  video: string
  cols?: number
  rows?: number
  width?: number
}

export interface QaSheetResponse {
  image: string
  url: string | null
}

export interface QaFrameRequest {
  video: string
  /** Instante do quadro, em segundos. */
  t: number
  width?: number
}

export interface QaFrameResponse extends QaSheetResponse {
  t: number
}

/* ---------- layouts de tela ---------- */

/** Layout salvo: onde cada painel fica, o tamanho dos divisores e o que está oculto. */
export interface ScreenLayout {
  version?: number
  areas: Record<string, string>
  sizes: Record<string, number>
  hidden: string[]
  /** Aba aberta ao aplicar o layout (`timeline` ou `voice`); sem valor, a aba atual fica. */
  tab?: string | null
}

export type LayoutPanel = 'player' | 'filters' | 'media' | 'timeline' | 'progress' | 'properties' | 'sidebar' | 'voice'
