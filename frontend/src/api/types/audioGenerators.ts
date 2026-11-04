/* Tipos do catálogo dos geradores de som (GET /api/audio-generators, ui/audio_effect_routes.py), com os nomes de campo do
   backend. O bloco "Sons gerados" monta o menu e o formulário só a partir dele: gerador novo aparece sem mexer aqui. Os
   parâmetros têm a mesma forma dos de um efeito de áudio. */
import type { AudioEffectParam, AudioEffectSettings, AudioEffectValue } from './audioEffects'

export interface AudioGeneratorInfo {
  /** O `type` do gerador na spec (`tone`). */
  type: string
  /** O nome em português. */
  label: string
  /** O nome do mesmo gerador no Audacity, para quem vem de lá. */
  audacity_name: string
  summary: string
  /** O grupo do menu: tons, ruído, telefonia, instrumentos, ritmo ou dados. */
  family: string
  /** A duração que o gerador pede com os parâmetros padrão (as batidas do ritmo, as teclas do DTMF), ou 1 s. */
  default_duration: number
  has_natural_duration: boolean
  parameters: AudioEffectParam[]
}

export interface AudioGeneratorCatalog {
  generators: AudioGeneratorInfo[]
  /** Os campos que todo som gerado tem na spec, além do gerador. */
  item: Array<{ name: string; label: string; unit: string; hint: string }>
  /** Onde a cadeia de efeitos do som mora (`audio.generated.N`) e a trilha da linha do tempo (`SFX`). */
  target: string
  track: string
}

/** Um som gerado como a spec o guarda (`audio.generated[]`): `params` pode estar incompleto, o servidor completa os padrões. */
export interface GeneratedSoundSettings {
  generator: string
  params: Record<string, AudioEffectValue>
  start: number
  duration: number
  volume?: number
  pan?: number
  effects?: AudioEffectSettings[]
}
