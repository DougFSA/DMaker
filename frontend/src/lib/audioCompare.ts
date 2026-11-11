/* O antes e depois de um efeito: dois trechos do mesmo som (sem e com o efeito) tocados em loop ao mesmo tempo, com um
   ganho em cada, de modo que trocar de lado não interrompe nem desloca o som, só muda qual dos dois se escuta. Usa o
   mesmo contexto de áudio injetável do motor de reprodução, então os testes põem um falso. */
import type { WavAudioContext, WavBuffer, WavGain, WavSource } from './audioPlayback'

export type CompareSide = 'before' | 'after'

interface Voice {
  source: WavSource
  gain: WavGain
}

export class ComparePlayer {
  private context: WavAudioContext | null = null
  private buffers: Record<CompareSide, WavBuffer | null> = { before: null, after: null }
  private voices: Partial<Record<CompareSide, Voice>> = {}
  private startedAt = 0
  private current: CompareSide = 'before'

  constructor(private readonly createContext: () => WavAudioContext) {}

  /** Decodifica o trecho dos dois lados; trocar o efeito proposto traz um `after` novo. */
  async load(before: ArrayBuffer, after: ArrayBuffer): Promise<void> {
    this.stop()
    const context = (this.context ??= this.createContext())
    const [first, second] = await Promise.all([context.decodeAudioData(before), context.decodeAudioData(after)])
    this.buffers = { before: first, after: second }
  }

  get loaded(): boolean {
    return this.buffers.before !== null && this.buffers.after !== null
  }

  get playing(): boolean {
    return Object.keys(this.voices).length > 0
  }

  get side(): CompareSide {
    return this.current
  }

  /** Os segundos do trecho que estão tocando agora (a volta do loop zera), ou 0 parado. */
  position(): number {
    const context = this.context
    const length = this.buffers.before?.duration ?? 0
    if (!context || !this.playing || length <= 0) return 0
    return (context.currentTime - this.startedAt) % length
  }

  /** Toca os dois lados em loop e deixa ouvir só o `side`. */
  async play(side: CompareSide): Promise<void> {
    const context = this.context
    if (!context || !this.loaded) return
    this.stop()
    await context.resume()
    const now = context.currentTime
    this.startedAt = now
    this.current = side
    for (const key of ['before', 'after'] as const) {
      const buffer = this.buffers[key]
      if (!buffer) continue
      const gain = context.createGain()
      gain.gain.value = key === side ? 1 : 0
      const source = context.createBufferSource()
      source.buffer = buffer
      source.loop = true
      source.connect(gain)
      gain.connect(context.destination)
      source.start(now)
      this.voices[key] = { source, gain }
    }
  }

  /** Troca o lado que se escuta sem parar nem deslocar o som; com o som parado, só lembra a escolha. */
  switchTo(side: CompareSide): void {
    this.current = side
    const context = this.context
    if (!context) return
    for (const key of ['before', 'after'] as const) {
      const voice = this.voices[key]
      if (!voice) continue
      voice.gain.gain.cancelScheduledValues(context.currentTime)
      voice.gain.gain.setValueAtTime(key === side ? 1 : 0, context.currentTime)
    }
  }

  stop(): void {
    for (const voice of Object.values(this.voices)) {
      try {
        voice.source.stop()
      } catch {
        // já tinha parado
      }
      voice.source.disconnect()
      voice.gain.disconnect()
    }
    this.voices = {}
  }

  dispose(): void {
    this.stop()
    void this.context?.close?.()
    this.context = null
    this.buffers = { before: null, after: null }
  }
}
