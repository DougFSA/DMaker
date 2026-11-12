/* Tipos da API das personas (persona_routes.py). */

export type PersonaKind = '2d' | '3d' | 'realistic'

export interface Persona {
  id: string
  name: string
  kind: PersonaKind
  voice: string | null
  /** Os campos dependem do tipo: 2D (cores e cabelo) ou 3D (modelo e cor da roupa). */
  appearance: Record<string, string>
  expressions: string[]
  gestures: string[]
  /** Pronta, do repositório: só leitura. */
  builtin: boolean
  created: string
  /** Só a persona realista: a miniatura da foto dela. */
  photo_url?: string
}

/** O que um tipo de persona sabe fazer e, se não está pronto neste computador, a mensagem do motor em português. */
export interface PersonaEngineInfo {
  kind: PersonaKind
  expressions: string[]
  gestures: string[]
  unavailable: string | null
}

export interface PersonaCatalog {
  personas: Persona[]
  engines: PersonaEngineInfo[]
}

export interface PersonaDraft {
  name: string
  kind: PersonaKind
  voice: string | null
  appearance: Record<string, string>
}

export interface PersonaChanges {
  name?: string
  voice?: string | null
  appearance?: Record<string, string>
}

export interface PersonaUse {
  project: string
  text: string
  placement: 'segment' | 'overlay'
  start?: number
}

/** Quanto a prévia deve levar neste computador (a realista); `seconds` nulo nos motores rápidos. */
export interface PersonaEstimate {
  seconds: number | null
  frames?: number
  device?: 'gpu' | 'cpu'
  device_label?: string
  speech_seconds?: number
}

export interface PersonaPreviewResult {
  output: string
  output_url: string
  duration_s: number
  warnings: string[]
}
