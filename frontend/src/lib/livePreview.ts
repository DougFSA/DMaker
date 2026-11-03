/* Contas da prévia ao vivo da narração: quando tocar cada fala e qual delas está tocando. Funções puras: quem toca
   (Web Audio) está em `livePlayer.ts` e recebe o relógio de fora. */

/** Fade nas pontas de cada fala: tira o degrau que um corte seco numa amostra diferente de zero faz (o estalo). */
export const LIVE_FADE_S = 0.005
/** Folga para agendar a primeira fala (ou uma que chegou atrasada) no futuro do relógio de áudio. */
export const LIVE_LEAD_S = 0.06
/** Rampa de silêncio ao parar: um corte seco estalaria pelo mesmo motivo do fade. */
export const LIVE_STOP_FADE_S = 0.02

/** Onde e quando uma fala toca na linha do tempo do relógio de áudio. */
export interface LiveChunkPlan {
  startAt: number
  endAt: number
  /** Duração do fade das duas pontas. */
  fade: number
  /** Onde a fala seguinte começa se chegar a tempo: o fim desta mais a pausa do roteiro. */
  nextCursor: number
  /** A fala chegou depois do ponto previsto: a CPU não acompanhou e ela toca assim que dá. */
  late: boolean
}

/** Uma fala já agendada, com o número dela no roteiro (a partir de 1). */
export interface PlacedChunk extends LiveChunkPlan {
  index: number
}

/**
 * Onde e quando tocar a próxima fala. Funde as falas na linha do tempo do relógio de áudio: cada uma começa onde a
 * anterior terminou mais a pausa do roteiro (`cursor`), então a emenda não depende de timers (que oscilam dezenas
 * de ms). O fade nunca passa de metade da fala, para não apagar uma fala curtíssima.
 */
export function planLiveChunk(cursor: number | null, now: number, duration: number, pauseAfter: number): LiveChunkPlan {
  const earliest = now + LIVE_LEAD_S
  const late = cursor !== null && cursor < now
  const startAt = cursor !== null && !late ? cursor : earliest
  const endAt = startAt + duration
  return {
    startAt,
    endAt,
    fade: Math.min(LIVE_FADE_S, duration / 2),
    nextCursor: endAt + Math.max(0, pauseAfter || 0),
    late,
  }
}

/**
 * O número (a partir de 1) da fala que toca no instante `time`, contando a pausa depois dela. Nada agendado, ou tudo
 * o que chegou já terminado, dá `null`. `plans` vem na ordem de chegada.
 */
export function playingIndexAt(plans: readonly Pick<PlacedChunk, 'index' | 'nextCursor'>[], time: number): number | null {
  return plans.find((plan) => time < plan.nextCursor)?.index ?? null
}

export interface LiveStatusView {
  /** Quantas falas o roteiro tem; 0 até a primeira chegar. */
  total: number
  /** Quantas já foram agendadas. */
  ready: number
  playing: number | null
  /** Depois de qual fala a narração foi parada; `null` enquanto não foi. */
  stoppedAfter: number | null
}

/** A frase de andamento da prévia ao vivo. */
export function liveStatusText(view: LiveStatusView): string {
  const { total, ready, playing, stoppedAfter } = view
  if (stoppedAfter === 0) return 'Parado antes de a primeira fala ficar pronta.'
  if (stoppedAfter !== null) {
    return `Parado depois da fala ${stoppedAfter} de ${total}. O que já saiu ficou guardado.`
  }
  if (!ready) return 'Esperando a primeira fala ficar pronta...'
  if (playing) return `Tocando fala ${playing} de ${total}${ready < total ? ` · ${ready} prontas` : ''}`
  if (ready < total) return `Esperando a fala ${ready + 1} de ${total} ficar pronta...`
  return 'Prévia ao vivo terminada.'
}

export const LIVE_MUTED_TEXT = 'Prévia ao vivo silenciada. A geração continua.'
