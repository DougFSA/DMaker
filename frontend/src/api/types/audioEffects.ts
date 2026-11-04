/* Tipos do catálogo dos efeitos de áudio (GET /api/audio-effects, ui/audio_effect_routes.py), com os nomes de campo do
   backend. O painel "Efeitos de áudio" monta o menu e o formulário só a partir dele: efeito novo aparece sem mexer aqui. */

/** `profile` é o nome de um perfil de ruído do projeto (`audio.noise_profiles`) ou `auto`: o campo se escolhe numa lista.
 *  `band_gains` é a lista fixa de ganhos (dB) do EQ Gráfico, um controle deslizante por banda (`options` traz a frequência de
 *  cada uma); `freq_points` é a lista de pontos {hz, db} do EQ por Curva, um gráfico de pontos arrastáveis. */
export type AudioEffectParamKind =
  | 'number'
  | 'integer'
  | 'boolean'
  | 'choice'
  | 'points'
  | 'profile'
  | 'band_gains'
  | 'freq_points'

/** Um ponto da curva do EQ por Curva: a frequência (Hz) e o ganho nela (dB). */
export interface CurvePoint {
  hz: number
  db: number
}

/** O valor de um parâmetro na spec: número, caixa de marcar, uma das opções de uma escolha ou uma das listas do EQ. */
export type AudioEffectValue = number | boolean | string | number[] | CurvePoint[]

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
  /** Só existe com uma seleção ou uma curva desenhada (Cortar, Envelope): o menu "+ Efeito" não o oferece. */
  needs_selection?: boolean
  /** Trabalha sobre as amostras do item (Redução de ruído, Reparar): não vale no master, que roda num grafo ao vivo. */
  sample_stage?: boolean
  /** Tem resposta de frequência calculada pelo servidor (os efeitos do EQ): a interface desenha o gráfico dele. */
  has_response?: boolean
  /** O que o efeito sabe fazer além de ser aplicado (o Noise Gate sugere o limiar a partir do ruído): um botão cada. */
  actions?: AudioEffectAction[]
}

/** Uma ação de um efeito: lê o som do item e devolve valores para os campos de `fills` (POST .../audio-effect-action). */
export interface AudioEffectAction {
  id: string
  label: string
  hint: string
  /** Os campos do efeito (nomes na spec) que a resposta preenche. */
  fills: string[]
  /** Mede um trecho do item (início e fim) ou o item todo. */
  needs_range: boolean
}

/** Uma cadeia pronta que o menu "+ Efeito" põe no item de uma vez, cada efeito separado e editável depois. */
export interface AudioEffectPreset {
  id: string
  label: string
  summary: string
  /** Os efeitos como a spec os escreve (só o que difere do padrão). */
  effects: Array<{ type: string; [parameter: string]: unknown }>
  /** De onde vem: `builtin` (embutida) ou `user` (salva pela pessoa, no arquivo effect-presets.json da pasta de dados). */
  origin?: 'builtin' | 'user'
}

/** A resposta de frequência de um efeito de equalização (POST /api/audio-effects/response): o ganho em dB em cada frequência. */
export interface EffectResponse {
  hz: number[]
  db: number[]
}

/** A resposta de uma ação de efeito. */
export interface AudioEffectActionResponse {
  effect: string
  action: string
  /** Campo da spec -> valor sugerido. */
  fills: Record<string, number>
  message?: string
  [detail: string]: unknown
}

/** O nível de um item como ele soa (POST .../audio-level): RMS e pico em dBFS e o LUFS integrado (nulo num trecho mudo). */
export interface AudioItemLevel {
  target: string
  rms_db: number
  peak_db: number
  lufs: number | null
  interval_s: [number, number]
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
  /** As predefinições (cadeias prontas). */
  presets?: AudioEffectPreset[]
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
