/* Tipos do catálogo dos efeitos de áudio (GET /api/audio-effects, ui/audio_effect_routes.py), com os nomes de campo do
   backend. O painel "Efeitos de áudio" monta o menu e o formulário só a partir dele: efeito novo aparece sem mexer aqui. */

export type AudioEffectParamKind = 'number' | 'integer' | 'boolean' | 'choice'

/** O valor de um parâmetro na spec: número, caixa de marcar ou uma das opções de uma escolha. */
export type AudioEffectValue = number | boolean | string

export interface AudioEffectParam {
  /** O nome do campo na spec (`gain_db`). */
  name: string
  label: string
  kind: AudioEffectParamKind
  /** "dB", "s"... ou vazio. */
  unit: string
  default: AudioEffectValue | null
  /** Os limites do valor; nulos quando o parâmetro não tem. */
  minimum: number | null
  maximum: number | null
  hint: string
  /** As opções de uma escolha (`kind: 'choice'`); vazio nos outros. */
  options: string[]
}

export interface AudioEffectInfo {
  /** O `type` do efeito na spec (`amplify`). */
  type: string
  /** O nome em português. */
  label: string
  /** O nome do mesmo efeito no Audacity, para quem vem de lá. */
  audacity_name: string
  summary: string
  /** A saída dura diferente da entrada (Repetir): só vale onde o item pode crescer. */
  changes_duration: boolean
  parameters: AudioEffectParam[]
}

/** Onde uma cadeia de efeitos pode ficar, escrito como o caminho dela na spec (`audio.voiceover.N`). */
export interface AudioEffectTarget {
  target: string
  label: string
  /** O item pode crescer, então um efeito que muda a duração (Repetir) é aceito ali. */
  may_grow: boolean
}

export interface AudioEffectCatalog {
  effects: AudioEffectInfo[]
  /** Os campos comuns a todo efeito: `enabled`, `start` e `end`. */
  common: AudioEffectParam[]
  targets: AudioEffectTarget[]
}

/** Um efeito como mora na spec: o `type`, o bypass, o intervalo e os parâmetros do tipo (que o catálogo descreve). */
export interface AudioEffectSettings {
  type: string
  /** Omitido vale ligado. */
  enabled?: boolean
  /** O intervalo do item, em segundos; omitidos valem o item todo. */
  start?: number | null
  end?: number | null
  [parameter: string]: unknown
}
