/* Apoio dos testes de gravação: um MediaRecorder e um MediaStream de mentira, com o comportamento assíncrono do
   de verdade (parar entrega o último pedaço de áudio e só depois o evento `stop`). */
import type { MicrophoneEnvironment, RecorderLike, StreamLike } from '@/lib/microphone'

export class FakeTrack {
  stopped = false

  stop(): void {
    this.stopped = true
  }
}

export class FakeStream implements StreamLike {
  readonly tracks = [new FakeTrack()]

  getTracks(): FakeTrack[] {
    return this.tracks
  }

  get released(): boolean {
    return this.tracks.every((track) => track.stopped)
  }
}

export class FakeRecorder implements RecorderLike {
  static instances: FakeRecorder[] = []
  state = 'inactive'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  stopCalls = 0

  constructor(
    readonly mimeType = 'audio/webm;codecs=opus',
    private readonly bytes = 'audio',
  ) {
    FakeRecorder.instances.push(this)
  }

  static reset(): void {
    FakeRecorder.instances = []
  }

  static latest(): FakeRecorder {
    const recorder = FakeRecorder.instances.at(-1)
    if (!recorder) throw new Error('nenhum gravador criado')
    return recorder
  }

  start(): void {
    this.state = 'recording'
  }

  stop(): void {
    this.stopCalls += 1
    this.state = 'inactive'
    // como no navegador: o último pedaço de áudio e o `stop` chegam depois da chamada
    queueMicrotask(() => {
      if (this.bytes) this.ondataavailable?.({ data: new Blob([this.bytes], { type: this.mimeType }) })
      this.onstop?.()
    })
  }

  /** O gravador quebrou no meio da captura. */
  fail(): void {
    this.onerror?.(new Event('error'))
  }
}

export interface FakeEnvironment extends MicrophoneEnvironment {
  stream: FakeStream
  requests: Array<{ audio: boolean }>
}

/** Um ambiente em que o microfone responde; `reject` simula a recusa do navegador (o nome é o da exceção do DOM). */
export function fakeEnvironment(
  options: { reject?: string; mimeType?: string; bytes?: string; noRecorder?: boolean; noMicrophone?: boolean } = {},
): FakeEnvironment {
  const stream = new FakeStream()
  const requests: Array<{ audio: boolean }> = []
  return {
    stream,
    requests,
    getUserMedia: options.noMicrophone
      ? null
      : async (constraints) => {
          requests.push(constraints)
          if (options.reject) throw new DOMException('recusado', options.reject)
          return stream
        },
    createRecorder: options.noRecorder ? null : () => new FakeRecorder(options.mimeType, options.bytes),
  }
}
