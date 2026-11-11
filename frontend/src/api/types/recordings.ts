/* Tipos da gravação pelo microfone (ui/recording_routes.py), com os nomes de campo do backend. */
import type { EditOperation } from './editor'

/** O trecho de uma voz gravada que o punch-in regrava (tempo da linha do tempo). */
export interface PunchRange {
  target: string
  start: number
  end: number
}

export interface RecordingOpenRequest {
  rate: number
  channels: number
  /** Onde o primeiro quadro cai na linha do tempo, com a latência já compensada. */
  start: number
  label?: string
  device?: string
  punch?: PunchRange
}

export interface RecordingStatus {
  id: string
  state: 'open' | 'finished'
  rate: number
  channels: number
  start: number
  label: string
  created_at: string
  /** Quantos pedaços estão no disco. */
  chunks: number
  frames: number
  duration: number
  /** Os números de pedaço que nunca chegaram (viram silêncio no arquivo). */
  gaps: number[]
  /** O WAV, relativo à pasta do projeto, depois de finalizada. */
  src: string | null
  punch: PunchRange | null
  device: string
}

/** A resposta do `finish`: a gravação e a operação que a põe na spec (voz nova, ou punch-in). */
export interface RecordingFinish extends RecordingStatus {
  op: EditOperation
  /** A mesma gravação como voz nova (o que a recuperação usa, porque o item do punch-in pode ter mudado). */
  recover_op: EditOperation
}
