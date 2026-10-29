/* O som ao vivo do player: o plano do que tocar por elementos de áudio enquanto a mixagem do servidor não está
   pronta. Só o item que cobre o instante toca em cada trilha, com o arquivo e o ponto certos (fatiados por corte
   pela vista), o volume e o mudo de cada item, e nunca mais fluxos do que o navegador aguenta. É aproximado: não
   tem os fades e o ducking da música, a narração nem o `audio_mode`; a mixagem é que soa como o vídeo final. */
import type { SpecDocument, TimelineTrack, TimelineView } from '@/api'
import {
  audioGain,
  clipPlayback,
  fileTime,
  isExternalAudioTrack,
  itemAt,
  mediaUrl,
  type SourceOffsetOf,
} from './player'
import { sourceOffsetFor, sourcePathOf } from './playerStage'

/** Quantos arquivos o som ao vivo abre ao mesmo tempo. O Chrome fala com um servidor por, no máximo, seis conexões,
 * e a prévia ainda usa o vídeo do trecho, o que vem a seguir e o acompanhamento dos jobs. */
export const MAX_LIVE_STREAMS = 3

export interface LiveChannel {
  /** A trilha (A1, A2..., MUS): um elemento de áudio por trilha, que troca de arquivo quando o item muda. */
  trackId: string
  path: string
  url: string
  /** O ponto do arquivo que corresponde ao instante, ainda sem limitar ao tamanho dele. */
  fileTime: number
  /** Quantos segundos de arquivo passam por segundo de linha do tempo (a velocidade do trecho). */
  speed: number
  loop: boolean
  muted: boolean
  volume: number
}

export interface LivePlan {
  channels: LiveChannel[]
  /** As trilhas que tocariam e ficaram de fora por causa do limite de fluxos. */
  dropped: string[]
}

export interface LivePlanInput {
  view: TimelineView
  spec: SpecDocument
  proxyUrls: Readonly<Record<string, string>>
  master: number
  /** Quantos fluxos de áudio podem abrir agora (o limite menos o que o vídeo já usa). */
  maxStreams?: number
}

function segmentVolume(spec: SpecDocument, index: number): number {
  const timeline = spec.timeline
  const segment = Array.isArray(timeline) ? (timeline[index] as Record<string, unknown> | undefined) : undefined
  return typeof segment?.volume === 'number' ? segment.volume : 1
}

function liveChannel(
  track: TimelineTrack,
  t: number,
  input: LivePlanInput,
  offsetOf: SourceOffsetOf,
): LiveChannel | null {
  const item = itemAt(track.items, t)
  if (!item || item.missing) return null
  const { view, spec, master } = input
  if (track.id === 'A1') {
    // o som da câmera sai do arquivo do clipe: numa fonte em partes, da parte que grava o instante
    const speed = typeof item.extra?.speed === 'number' && item.extra.speed > 0 ? item.extra.speed : 1
    const playback = clipPlayback(item, t, speed, offsetOf, sourcePathOf(item, view))
    const url = mediaUrl(playback.path, input.proxyUrls)
    if (!playback.path || !url) return null
    const gain = audioGain(item, track.muted, master, segmentVolume(spec, item.index))
    return { trackId: track.id, path: playback.path, url, fileTime: playback.fileTime, speed, loop: false, ...gain }
  }
  const path = sourcePathOf(item, view)
  const url = mediaUrl(path, input.proxyUrls)
  if (!path || !url) return null
  const speed = typeof item.extra?.speed === 'number' && item.extra.speed > 0 ? item.extra.speed : 1
  const gain = audioGain(item, track.muted, master)
  return {
    trackId: track.id,
    path,
    url,
    fileTime: fileTime(item, t, speed, offsetOf),
    speed,
    loop: !!item.extra?.loop,
    ...gain,
  }
}

/** O que tocar ao vivo em `t`, na ordem de prioridade: o som da câmera (A1), as faixas externas e, por último, a
 * música. Acima do limite de fluxos, as últimas ficam de fora. */
export function liveAudioPlan(t: number, input: LivePlanInput): LivePlan {
  const offsetOf = sourceOffsetFor(input.view)
  const order = (track: TimelineTrack) => (track.id === 'A1' ? 0 : track.id === 'MUS' ? 2 : 1)
  const tracks = input.view.tracks
    .filter((track) => track.id === 'A1' || isExternalAudioTrack(track))
    .sort((a, b) => order(a) - order(b))
  const wanted = tracks.flatMap((track) => liveChannel(track, t, input, offsetOf) ?? [])
  const limit = Math.max(0, input.maxStreams ?? MAX_LIVE_STREAMS)
  // o que está mudo não precisa de fluxo: só as trilhas que se ouvem entram na conta do limite
  const audible = wanted.filter((channel) => !channel.muted)
  const kept = new Set(audible.slice(0, limit).map((channel) => channel.trackId))
  return {
    channels: wanted.filter((channel) => kept.has(channel.trackId)),
    dropped: audible.slice(limit).map((channel) => channel.trackId),
  }
}

/** A mixagem que o servidor entregou vale para a spec de agora? Depois de uma edição ela está velha até a nova
 * ficar pronta, e então o som volta a ser ao vivo. */
export function mixIsCurrent(mix: { state: string; key: string | null; url: string | null }, currentKey: string | null): boolean {
  return mix.state === 'ready' && !!mix.url && mix.key !== null && mix.key === currentKey
}
