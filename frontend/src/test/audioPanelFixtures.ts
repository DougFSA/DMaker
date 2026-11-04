/* Dados de mentira do painel Áudio para os testes: a spec de um projeto com voz gravada, a vista dele, a resposta da onda
   e um AudioContext falso (o jsdom não tem Web Audio). */
import type { AudioWave, TimelineView } from '@/api'
import type { WavAnalyser, WavAudioContext, WavBuffer, WavGain, WavNode, WavParam, WavSource } from '@/lib/audioPlayback'
import { timelineItem, timelineTrack } from './editorFixtures'

export const COLUMNS = 256

/** A resposta da onda de uma voz gravada de 12 s que começa em 0,5 s do projeto, estéreo a 48 kHz. */
export function audioWave(extra: Partial<AudioWave> = {}): AudioWave {
  const channel = (value: number) => new Array<number>(COLUMNS).fill(value)
  return {
    target: 'audio.voiceover.0',
    label: 'voz.wav',
    state: 'ready',
    key: 'chave-1',
    gain: 1,
    percent: 100,
    stage: '',
    error: null,
    duration: 12,
    origin: 0,
    rate: 48000,
    channels: 2,
    frames: 576000,
    clock: { start: 0.5, speed: 1 },
    notes: [],
    start: 0,
    end: 12,
    columns: COLUMNS,
    ready_until: 12,
    mode: 'peaks',
    mins: [channel(-40), channel(-40)],
    maxs: [channel(60), channel(60)],
    ...extra,
  }
}

/** A spec do projeto com uma voz gravada que começa em 0,5 s. */
export function voiceSpec(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    sources: {},
    timeline: [{ type: 'card', title: 'Fim', duration: 13, logo: true, motion: 'zoom-in', motion_amount: 0.04 }],
    overlays: [],
    audio: { voice_gain: 1, normalize: 'off', mute_clips: false, voiceover: [{ src: 'voz.wav', start: 0.5, offset: 0, volume: 1 }] },
    ...extra,
  }
}

/** A vista com a trilha VO e o item da voz gravada. */
export function voiceView(): TimelineView {
  return {
    total: 13,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [
      timelineTrack('V1', [timelineItem(0, { id: 'V1-0', kind: 'card', start: 0, end: 13, label: 'Fim' })]),
      timelineTrack('VO', [timelineItem(0, { id: 'VO-0', kind: 'voiceover', start: 0.5, end: 12.5, label: 'voz.wav', src: 'voz.wav' })], {
        kind: 'audio',
        label: 'VO',
        gain_db: 0,
        pan: 0,
        solo: false,
      }),
    ],
    sources: {},
    warnings: [],
  }
}

/* ---------- um AudioContext falso ---------- */

class Param implements WavParam {
  value = 1
  setValueAtTime(): this {
    return this
  }
  linearRampToValueAtTime(): this {
    return this
  }
  cancelScheduledValues(): this {
    return this
  }
}

class Node implements WavNode {
  connect(): void {}
  disconnect(): void {}
}

class Gain extends Node implements WavGain {
  readonly gain = new Param()
}

class Analyser extends Node implements WavAnalyser {
  fftSize = 1024
  getFloatTimeDomainData(target: Float32Array): void {
    target.fill(0.25)
  }
}

export class FakeSource extends Node implements WavSource {
  buffer: WavBuffer | null = null
  loop = false
  readonly playbackRate = new Param()
  onended: ((event: Event) => unknown) | null = null
  started: Array<{ when?: number; offset?: number; duration?: number }> = []
  start(when?: number, offset?: number, duration?: number): void {
    this.started.push({ when, offset, duration })
  }
  stop(): void {}
}

export class FakeWebAudio implements WavAudioContext {
  static instances: FakeWebAudio[] = []
  currentTime = 0
  readonly destination = {}
  readonly sources: FakeSource[] = []
  constructor() {
    FakeWebAudio.instances.push(this)
  }
  createGain(): Gain {
    return new Gain()
  }
  createBufferSource(): FakeSource {
    const source = new FakeSource()
    this.sources.push(source)
    return source
  }
  createAnalyser(): Analyser {
    return new Analyser()
  }
  createChannelSplitter(): WavNode {
    return new Node()
  }
  async decodeAudioData(bytes: ArrayBuffer): Promise<WavBuffer> {
    return { duration: Math.max(bytes.byteLength / 100, 0.01) }
  }
  async resume(): Promise<void> {}
}
