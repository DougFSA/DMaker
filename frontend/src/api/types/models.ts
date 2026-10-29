/* Tipos dos modelos de IA instalados (src/dmaker/ui/models_routes.py). */

/** `installed` está inteiro, `partial` tem um download interrompido, `absent` não foi baixado. */
export type ModelState = 'installed' | 'partial' | 'absent'

export interface ModelStatus {
  id: string
  name: string
  purpose: string
  engine: string
  license: string
  /** As funções do DMaker que dependem do modelo. */
  required_by: string[]
  state: ModelState
  size_bytes: number
  size_label: string
  expected_bytes: number
  expected_label: string
}

/** Pasta ou arquivo em cache/models que nenhum modelo conhecido reivindica. */
export interface ModelLeftover {
  /** Relativo a cache/models, com barras normais. */
  path: string
  size_bytes: number
  size_label: string
  is_dir: boolean
}

/** GET /api/models. */
export interface ModelInventory {
  models_dir: string
  models: ModelStatus[]
  leftovers: ModelLeftover[]
  total_bytes: number
  total_label: string
  leftover_bytes: number
  leftover_label: string
  disk_free_bytes: number | null
  disk_free_label: string | null
}

/** O que apagar um modelo (ou as sobras) levaria embora; `warning` é a frase pronta para o diálogo. */
export interface ModelRemovalPlan {
  title: string
  paths: string[]
  freed_bytes: number
  freed_label: string
  stops_working: string[]
  warning: string
}

/** Resposta de apagar um modelo ou as sobras: o plano que foi executado. */
export interface ModelRemoved {
  removed: ModelRemovalPlan
}

/** Resultado do job de baixar um modelo: o estado final dele. */
export type ModelDownloadResult = ModelStatus
