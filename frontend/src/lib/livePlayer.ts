/* Toca as falas da narração na ordem em que chegam, sem esperar o roteiro inteiro (Web Audio). O `AudioContext` entra
   por injeção: a tela entrega o do navegador, os testes entregam um falso e as contas ficam em `livePreview.ts`. */
import { LIVE_STOP_FADE_S, planLiveChunk, playingIndexAt, type PlacedChunk } from './livePreview'

/** O áudio já decodificado; o player só precisa saber quanto ele dura. */
export interface LiveBuffer {
  readonly duration: number
}

/** O volume de um nó: o player agenda rampas nele para o fade das pontas. */
export interface LiveParam {
  value: number
  setValueAtTime(value: number, time: number): unknown
  linearRampToValueAtTime(value: number, time: number): unknown
  cancelScheduledValues(time: number): unknown
}

export interface LiveGain {
  readonly gain: LiveParam
  connect(destination: unknown): unknown
  disconnect(): void
}

export interface LiveSource {
  buffer: LiveBuffer | null
  onended: (() => void) | null
  connect(destination: unknown): unknown
  start(when: number): void
  stop(when: number): void
}

/** O pedaço do `AudioContext` que o player usa. */
export interface LiveAudioContext {
  readonly currentTime: number
  readonly destination: unknown
  createGain(): LiveGain
  createBufferSource(): LiveSource
  decodeAudioData(bytes: ArrayBuffer): Promise<LiveBuffer>
  resume(): Promise<void>
}

/** Entrega o contexto de áudio, ou `null` quando o navegador não tem Web Audio (a narração segue só com o arquivo final). */
export type LiveAudioFactory = () => LiveAudioContext | null

/** Uma fala que ficou pronta: o endereço do pedaço de áudio e a pausa que o roteiro pede depois dela. */
export interface LiveChunk {
  index: number
  url: string
  pauseAfter: number
}

export interface LivePlayer {
  /** Decodifica e agenda a fala. A ordem de chegada é mantida mesmo que a decodificação de uma demore mais que a da seguinte. */
  enqueue(chunk: LiveChunk): Promise<void>
  /** Silencia em 20 ms (rampa, não corte seco) e descarta o que faltava tocar. */
  stop(): void
  /** O que já foi agendado, na ordem. */
  readonly plans: readonly PlacedChunk[]
  /** Quantas falas já foram agendadas. */
  ready(): number
  /** A fala que toca agora (a partir de 1), ou `null`. */
  playingIndex(): number | null
}

type ContextWindow = Window & { AudioContext?: new () => unknown; webkitAudioContext?: new () => unknown }

let shared: { ctor: unknown; context: LiveAudioContext } | null = null

/**
 * O contexto de áudio do navegador. É um só para a página toda (o navegador limita quantos podem existir) e é criado
 * na primeira vez que se pede, dentro do clique que gera a narração, que é o que libera o áudio. Lê o navegador na
 * hora de usar, e não ao carregar o módulo, para os testes poderem trocar o `AudioContext`.
 */
export function browserLiveAudio(): LiveAudioContext | null {
  if (typeof window === 'undefined') return null
  const scope = window as ContextWindow
  const Context = scope.AudioContext ?? scope.webkitAudioContext
  if (!Context) return null
  if (!shared || shared.ctor !== Context) {
    // o cast é só de tipo: o AudioContext de verdade tem tudo o que `LiveAudioContext` usa, com tipos mais largos
    shared = { ctor: Context, context: new Context() as unknown as LiveAudioContext }
  }
  return shared.context
}

/** Baixa os bytes de uma fala pronta (o endereço sai do evento `utterance` do job). */
export async function fetchChunkBytes(url: string): Promise<ArrayBuffer> {
  const response = await fetch(url)
  if (!response.ok) throw new Error('Não consegui carregar uma fala da prévia ao vivo.')
  return response.arrayBuffer()
}

export function createLivePlayer(
  context: LiveAudioContext,
  loadChunk: (url: string) => Promise<ArrayBuffer>,
  onError?: (error: unknown) => void,
): LivePlayer {
  const master = context.createGain()
  master.connect(context.destination)
  const plans: PlacedChunk[] = []
  const sources: LiveSource[] = []
  let cursor: number | null = null
  let chain: Promise<void> = Promise.resolve()
  let stopped = false

  function place(chunk: LiveChunk, buffer: LiveBuffer): void {
    const plan = planLiveChunk(cursor, context.currentTime, buffer.duration, chunk.pauseAfter)
    const source = context.createBufferSource()
    source.buffer = buffer
    const gain = context.createGain()
    // sobe e desce em 5 ms nas duas pontas: o corte seco de uma amostra que não é zero soa como estalo
    gain.gain.setValueAtTime(0, plan.startAt)
    gain.gain.linearRampToValueAtTime(1, plan.startAt + plan.fade)
    gain.gain.setValueAtTime(1, plan.endAt - plan.fade)
    gain.gain.linearRampToValueAtTime(0, plan.endAt)
    source.connect(gain)
    gain.connect(master)
    source.onended = () => gain.disconnect()
    source.start(plan.startAt)
    sources.push(source)
    cursor = plan.nextCursor
    plans.push({ index: chunk.index, ...plan })
  }

  return {
    enqueue(chunk) {
      chain = chain
        .then(async () => {
          if (stopped) return
          const buffer = await context.decodeAudioData(await loadChunk(chunk.url))
          if (!stopped) place(chunk, buffer)
        })
        .catch((error: unknown) => onError?.(error))
      return chain
    },
    stop() {
      stopped = true
      const now = context.currentTime
      master.gain.cancelScheduledValues(now)
      master.gain.setValueAtTime(master.gain.value, now)
      master.gain.linearRampToValueAtTime(0, now + LIVE_STOP_FADE_S)
      for (const source of sources) {
        try {
          source.stop(now + LIVE_STOP_FADE_S + 0.005)
        } catch {
          // já terminou: parar de novo o mesmo nó lança, e não há mais nada a silenciar
        }
      }
    },
    plans,
    ready: () => plans.length,
    playingIndex: () => playingIndexAt(plans, context.currentTime),
  }
}
