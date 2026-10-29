/* Os elementos de mídia do player e o que os mantém presos ao relógio da linha do tempo: o vídeo do trecho (sempre
   mudo), a mixagem de áudio do servidor (um `<audio>` só) e, enquanto ela não está pronta, o som ao vivo por
   trilha. O relógio é o do store do player; aqui só se decide o que cada elemento faz a cada quadro. */
import { clampPlaybackRate, playableTime, shouldSeek, type SeekMemory } from './player'
import type { LiveChannel, LivePlan } from './playerAudio'

/** O pedaço do `HTMLMediaElement` que o player usa, para os testes trocarem o elemento por um objeto simples. */
export interface MediaElementLike {
  currentTime: number
  paused: boolean
  muted: boolean
  volume: number
  playbackRate: number
  duration: number
  readyState: number
  src: string
  play(): Promise<void> | void
  pause(): void
  /** O navegador tem os dois; o objeto simples dos testes pode não ter. */
  removeAttribute?(name: string): void
  load?(): void
  remove?(): void
}

/** Parado, o vídeo mostra o quadro exato: a tolerância é menos que um quadro a 30 fps. */
export const PAUSED_TOLERANCE_S = 0.02

function play(element: MediaElementLike, onBlocked: () => void): void {
  try {
    const started = element.play()
    if (started && typeof started.catch === 'function') started.catch(onBlocked)
  } catch {
    onBlocked()
  }
}

export interface VideoTarget {
  /** O ponto do arquivo que o instante pede. */
  fileTime: number
  /** A velocidade do trecho. */
  speed: number
  /** A velocidade do relógio (0 = parado, negativo = voltando). */
  rate: number
  /** O elemento falhou ao carregar (o proxy ainda não existe): não adianta tentar tocar. */
  errored?: boolean
}

/** Prende o `<video>` do trecho (ou do PiP) ao relógio. Ele é sempre mudo: o som é da mixagem. Tocando, só busca
 * quando se afasta além da tolerância; parado (ou voltando, que o navegador não toca), mostra o quadro do instante. */
export function syncVideo(element: MediaElementLike, target: VideoTarget): void {
  element.muted = true
  element.volume = 0
  const wanted = Math.max(0, target.fileTime)
  if (target.rate > 0 && !target.errored) {
    element.playbackRate = clampPlaybackRate(target.speed * target.rate)
    if (Math.abs(element.currentTime - wanted) > 0.15) element.currentTime = wanted
    if (element.paused) play(element, () => undefined)
    return
  }
  if (!element.paused) element.pause()
  if (Math.abs(element.currentTime - wanted) > PAUSED_TOLERANCE_S) element.currentTime = wanted
}

export interface ChannelFrame {
  /** O ponto do arquivo a tocar agora; nulo pausa (o item não cobre o instante, ou o ponto está fora do arquivo). */
  target: number | null
  /** Segundos de arquivo por segundo de relógio, para a carência de busca. */
  mediaRate: number
  /** A velocidade do relógio (0 = parado, negativo = voltando). */
  rate: number
  speed: number
  muted: boolean
  volume: number
  now: number
}

/** Um `<audio>` preso ao relógio: troca de arquivo quando o item muda, busca só quando precisa e toca ou pausa. */
export class AudioChannel {
  url: string | null = null
  path: string | null = null
  errored = false
  private lastSeek: SeekMemory | null = null

  constructor(
    readonly element: MediaElementLike,
    private readonly onBlocked: () => void = () => undefined,
  ) {}

  /** Passa a tocar `url` (`path` é o arquivo de origem, para avisar de erro). Igual ao de agora, não faz nada;
   * nulo solta o arquivo. */
  load(url: string | null, path: string | null = null): void {
    if (url === this.url) return
    if (!url) {
      this.release()
      return
    }
    this.url = url
    this.path = path
    this.errored = false
    this.lastSeek = null
    this.element.src = url
  }

  sync(frame: ChannelFrame): void {
    if (!this.url || frame.target === null) {
      this.silence()
      return
    }
    this.element.muted = frame.muted
    this.element.volume = frame.volume
    if (shouldSeek(this.element.currentTime, frame.target, frame.now, this.lastSeek, frame.rate > 0 ? frame.mediaRate : 0)) {
      this.element.currentTime = frame.target
      this.lastSeek = { target: frame.target, at: frame.now }
    }
    if (frame.rate > 0 && !this.errored) {
      this.element.playbackRate = clampPlaybackRate(frame.speed * frame.rate)
      if (this.element.paused) play(this.element, this.onBlocked)
    } else if (!this.element.paused) {
      this.element.pause()
    }
  }

  silence(): void {
    if (!this.element.paused) this.element.pause()
  }

  /** Solta o arquivo: o elemento deixa de segurar a conexão. Sem arquivo carregado, só garante o silêncio. */
  release(): void {
    this.silence()
    if (this.url === null) return
    this.url = null
    this.path = null
    this.lastSeek = null
    if (this.element.removeAttribute) this.element.removeAttribute('src')
    else this.element.src = ''
    this.element.load?.()
  }
}

export interface AudioFrame {
  /** O instante da linha do tempo (segundos). */
  time: number
  rate: number
  /** O volume geral, de 0 a 1. */
  volume: number
  /** A mixagem do servidor vale para a spec de agora; senão o som sai ao vivo, por trilha. */
  mixCurrent: boolean
  plan: LivePlan
  now: number
}

/** O som do player: a mixagem num `<audio>` só ou, enquanto ela não está pronta, um por trilha. Nunca os dois. */
export class PlayerAudio {
  readonly mix: AudioChannel
  private readonly live = new Map<string, AudioChannel>()

  constructor(
    private readonly createElement: () => HTMLAudioElement,
    private readonly onBlocked: () => void,
    private readonly onError: (path: string) => void,
    private readonly host: HTMLElement | null = null,
  ) {
    this.mix = new AudioChannel(this.make('mix', () => undefined), onBlocked)
  }

  private make(role: string, onFail: (path: string) => void): HTMLAudioElement {
    const element = this.createElement()
    element.preload = 'auto'
    element.dataset.player = role
    element.addEventListener('error', () => {
      if (element.getAttribute('src')) onFail(element.src)
    })
    this.host?.appendChild(element)
    return element
  }

  /** A mixagem que o servidor entregou; nula tira o arquivo do elemento. */
  setMix(url: string | null): void {
    this.mix.load(url)
  }

  update(frame: AudioFrame): void {
    if (frame.mixCurrent && this.mix.url) {
      for (const trackId of [...this.live.keys()]) this.dropLive(trackId)
      this.mix.sync({
        target: frame.time,
        mediaRate: frame.rate,
        rate: frame.rate,
        speed: 1,
        muted: false,
        volume: frame.volume,
        now: frame.now,
      })
      return
    }
    this.mix.silence()
    const playing = new Set<string>()
    for (const channel of frame.plan.channels) {
      playing.add(channel.trackId)
      this.syncLive(channel, frame)
    }
    for (const trackId of [...this.live.keys()]) {
      if (!playing.has(trackId)) this.dropLive(trackId)
    }
  }

  private syncLive(wanted: LiveChannel, frame: AudioFrame): void {
    let channel = this.live.get(wanted.trackId)
    if (!channel) {
      const element = this.make(`live:${wanted.trackId}`, (url) => this.onError(this.live.get(wanted.trackId)?.path ?? url))
      channel = new AudioChannel(element, this.onBlocked)
      this.live.set(wanted.trackId, channel)
    }
    channel.load(wanted.url, wanted.path)
    channel.sync({
      target: playableTime(wanted.fileTime, channel.element.duration, wanted.loop),
      mediaRate: wanted.speed * frame.rate,
      rate: frame.rate,
      speed: wanted.speed,
      muted: wanted.muted,
      volume: wanted.volume,
      now: frame.now,
    })
  }

  private dropLive(trackId: string): void {
    const channel = this.live.get(trackId)
    if (!channel) return
    channel.release()
    channel.element.remove?.()
    this.live.delete(trackId)
  }

  /** As trilhas ao vivo que têm elemento agora (para o aviso e as medidas). */
  get liveTracks(): string[] {
    return [...this.live.keys()]
  }

  pause(): void {
    this.mix.silence()
    for (const channel of this.live.values()) channel.silence()
  }

  dispose(): void {
    this.mix.release()
    this.mix.element.remove?.()
    for (const trackId of [...this.live.keys()]) this.dropLive(trackId)
  }
}
