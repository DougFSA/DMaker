/* Tipos das respostas da API (src/dmaker/ui/server.py), escritos à mão a partir das respostas reais.
   Os nomes dos campos seguem o backend (snake_case) para não haver camada de tradução. */

export interface PresetInfo {
  id: string
  platform: string
  name: string
  width: number
  height: number
  fps: number
  max_duration_s: number | null
  notes: string
}

export interface BrandInfo {
  key: string
  name: string
  colors: Record<string, string>
}

export interface AppState {
  version: string
  build_id: string
  running_jobs: number
  root: string
  output_dir: string
  projects_dir: string
  ffmpeg: string
  presets: PresetInfo[]
  brands: BrandInfo[]
  projects: ProjectListItem[]
}

/** Item de GET /api/projects. Uma spec ilegível volta só com `error`. */
export interface ProjectListItem {
  name: string
  spec_path: string
  preset?: string | null
  brand?: string | null
  segments?: number
  mtime?: number
  error?: string
}

export interface OutputFile {
  path: string
  url: string | null
  name: string
  project: string
  preset: string | null
  kind: 'preview' | 'final'
  size_mb: number
  mtime: number
  thumbnail: string | null
}

export interface ProjectDetail {
  name: string
  spec_path: string
  spec: ProjectSpec
  captions_exists: boolean
  outputs: OutputFile[]
  /** A lista do que o corte automático removeu; null em projeto que não nasceu dele. */
  cuts: CutReport | null
}

export type CutIntensity = 'suave' | 'normal' | 'agressiva'

/** Um trecho removido pelo corte automático (tempos na gravação original). */
export interface CutItem {
  id: number
  start_s: number
  end_s: number
  duration_s: number
  reason: 'silence' | 'filler' | 'repetition'
  reason_label: string
  /** As palavras tiradas; vazio numa pausa. */
  text: string
  undone: boolean
}

export interface CutReport {
  source: string
  intensity: CutIntensity
  min_pause_s: number
  breath_s: number
  duration_before_s: number
  duration_after_s: number
  removed_s: number
  removed_percent: number
  /** Cortes ainda aplicados por motivo (silence, filler, repetition). */
  counts: Record<string, number>
  cuts: CutItem[]
}

export interface AutoCutRequest {
  source: string
  name: string
  intensity?: CutIntensity
  min_pause?: number
  breath?: number
  preset?: string
  brand?: string | null
  captions?: boolean
  language?: string
  model?: string
  overwrite?: boolean
}

/** Só o que a tela lê da spec; a validação completa fica no backend. */
export interface ProjectSpec {
  name: string
  brand?: string | null
  output?: { preset?: string; quality?: string }
  sources?: Record<string, unknown>
  timeline?: Array<{ type: string }>
  overlays?: unknown[]
  [key: string]: unknown
}

export interface NewProjectRequest {
  name: string
  template?: string | null
  params?: Record<string, TemplateParamValue>
  preset?: string
  brand?: string | null
  sources?: string[]
  captions?: boolean
  logo?: boolean
}

export interface NewProjectResponse {
  name: string
  spec_path: string
  spec: ProjectSpec
}

export type TemplateParamType = 'text' | 'path' | 'paths' | 'dir' | 'number' | 'bool' | 'list'
export type TemplateParamValue = string | number | boolean | string[]

export interface TemplateParam {
  description: string
  type: TemplateParamType
  default: TemplateParamValue | null
  required: boolean
}

export interface TemplateInfo {
  name: string
  description: string
  summary: string
  params: Record<string, TemplateParam>
}

export interface ValidationSegment {
  index: number
  type: string
  duration_s: number
  label: string | null
}

export interface ValidationSummary {
  name: string
  preset: string
  resolution: string
  theme: string
  total_s: number
  segments: ValidationSegment[]
  warnings: string[]
}

export type QaLevel = 'erro' | 'aviso' | 'info'

export interface QaFinding {
  level: QaLevel
  where: string
  message: string
  at: number | null
}

export interface QaReport {
  text: string
  project: string
  preset: string
  total: number
  findings: QaFinding[]
  checks: string[]
}

export interface RenderRequest {
  preview?: boolean
  preset?: string | null
  segments?: string | null
}

export interface RenderResult {
  output: string
  output_url: string | null
  thumbnail: string | null
  thumbnail_url: string | null
  duration_s: number
  size_mb: number
  preset: string
  resolution: string
  captions_file: string | null
  warnings: string[]
}

export interface JobStartResponse {
  job_id: string
}

export type JobStatus = 'running' | 'done' | 'error'

export interface JobProgress {
  label?: string
  done?: number
  total?: number
  percent?: number
}

/** Item de GET /api/jobs. */
export interface JobSnapshot {
  job_id: string
  description: string
  status: JobStatus
  elapsed_s: number
  progress: JobProgress
  error: string | null
  focus: boolean
  project: string | null
}

/** Eventos do SSE em /api/jobs/{id}/events. */
export type JobEvent =
  | { kind: 'start'; t: number; description: string }
  | { kind: 'log'; t: number; message: string }
  | ({ kind: 'progress'; t: number } & JobProgress)
  | { kind: 'end'; t: number; status: JobStatus; error: string | null; result: unknown }

export interface BrowseResponse {
  path: string
  parent: string | null
  dirs: string[]
  files: Array<{ path: string; name: string; size_mb: number }>
}
