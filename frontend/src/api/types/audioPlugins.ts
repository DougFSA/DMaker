/* Tipos dos plugins de efeito de terceiros (GET /api/audio-plugins, ui/audio_plugin_routes.py), com os nomes de campo do
   backend. Os controles de cada plugin são os que o próprio plugin declara, lidos pelo ffmpeg na varredura: a interface
   monta os campos a partir deles, sem saber de plugin nenhum. */

export type PluginFormat = 'lv2' | 'ladspa'

/** Um controle do plugin: `name` é a chave em `params` da spec (o símbolo da porta no LV2, `c0`, `c1`... no LADSPA). */
export interface PluginControl {
  name: string
  label: string
  default: number
  minimum: number | null
  maximum: number | null
  kind: 'number' | 'integer' | 'boolean'
}

export interface PluginInfo {
  /** O identificador curto das rotas (`lv2-1a2b3c4d5e`). */
  id: string
  format: PluginFormat
  /** Como a spec cita o plugin: a URI do LV2, ou `arquivo#rótulo` no LADSPA. */
  ref: string
  name: string
  path: string
  binary: string
  controls: PluginControl[]
  ports: { inputs: number; outputs: number }
  maker: string
  /** Falso quando o ffmpeg não consegue hospedar o plugin; `problem` diz por quê. */
  usable: boolean
  problem: string
  /** A escolha da pessoa (habilitar e desabilitar). */
  enabled: boolean
}

export interface PluginFolder {
  format: PluginFormat
  path: string
  exists: boolean
}

export interface PluginCatalog {
  plugins: PluginInfo[]
  /** O que a varredura não conseguiu ler (por exemplo, sem o ffmpeg que hospeda o formato). */
  notes: string[]
  /** O ffmpeg que hospeda cada formato, ou nulo quando nenhum tem o filtro. */
  hosts: Record<PluginFormat, string | null>
  folders: PluginFolder[]
  /** A pasta onde a pessoa pode pôr plugins só para o DMaker. */
  install_to: string
}
