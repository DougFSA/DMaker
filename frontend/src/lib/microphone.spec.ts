import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeRecorder, fakeEnvironment } from '@/test/recorder'
import {
  browserEnvironment,
  createMicrophone,
  MAX_RECORDING_MS,
  MicrophoneError,
  type MicrophoneEnvironment,
} from './microphone'

beforeEach(() => {
  FakeRecorder.reset()
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const microphoneWith = (environment: MicrophoneEnvironment) => createMicrophone(() => environment)

async function failureOf(promise: Promise<unknown>): Promise<MicrophoneError> {
  try {
    await promise
  } catch (error) {
    return error as MicrophoneError
  }
  throw new Error('devia ter falhado')
}

describe('gravar pelo microfone', () => {
  it('pede só áudio, grava, e ao parar entrega o arquivo com o tempo gravado', async () => {
    const environment = fakeEnvironment()
    const handle = await microphoneWith(environment).start()
    expect(environment.requests).toEqual([{ audio: true }])
    expect(FakeRecorder.latest().state).toBe('recording')

    vi.advanceTimersByTime(6200)
    handle.stop()
    const recording = await handle.finished

    expect(recording.durationMs).toBe(6200)
    expect(recording.mimeType).toBe('audio/webm;codecs=opus')
    expect(recording.filename).toBe('gravacao.webm')
    expect(recording.blob.size).toBeGreaterThan(0)
  })

  it('solta o microfone quando a gravação acaba', async () => {
    const environment = fakeEnvironment()
    const handle = await microphoneWith(environment).start()
    expect(environment.stream.released).toBe(false)
    handle.stop()
    await handle.finished
    expect(environment.stream.released).toBe(true)
  })

  it('avisa o tempo gravado a cada 200 ms, começando do zero', async () => {
    const ticks: number[] = []
    const handle = await microphoneWith(fakeEnvironment()).start({ onTick: (elapsed) => ticks.push(elapsed) })
    vi.advanceTimersByTime(600)
    handle.stop()
    await handle.finished
    // 0, 200, 400 e 600 do relógio, mais o tempo exato do instante em que a pessoa parou
    expect(ticks).toEqual([0, 200, 400, 600, 600])
  })

  it('parar de novo, ou parar depois de acabar, não faz nada', async () => {
    const handle = await microphoneWith(fakeEnvironment()).start()
    handle.stop()
    handle.stop()
    await handle.finished
    handle.stop()
    expect(FakeRecorder.latest().stopCalls).toBe(1)
  })
})

describe('tampa de tempo', () => {
  it('para sozinha aos 30 segundos e o arquivo sai com 30 s', async () => {
    const handle = await microphoneWith(fakeEnvironment()).start()
    vi.advanceTimersByTime(MAX_RECORDING_MS - 1)
    expect(FakeRecorder.latest().state).toBe('recording')

    vi.advanceTimersByTime(1)
    const recording = await handle.finished
    expect(FakeRecorder.latest().state).toBe('inactive')
    expect(recording.durationMs).toBe(MAX_RECORDING_MS)
  })

  it('o relógio não passa da tampa', async () => {
    const ticks: number[] = []
    const handle = await microphoneWith(fakeEnvironment()).start({ onTick: (elapsed) => ticks.push(elapsed) })
    vi.advanceTimersByTime(MAX_RECORDING_MS + 5000)
    await handle.finished
    expect(Math.max(...ticks)).toBe(MAX_RECORDING_MS)
    expect(ticks.at(-1)).toBe(MAX_RECORDING_MS)
  })

  it('a tampa pode ser outra', async () => {
    const handle = await microphoneWith(fakeEnvironment()).start({ maxMs: 2000 })
    vi.advanceTimersByTime(2000)
    expect((await handle.finished).durationMs).toBe(2000)
  })

  it('parar antes da tampa cancela a contagem: nada para duas vezes', async () => {
    const handle = await microphoneWith(fakeEnvironment()).start()
    vi.advanceTimersByTime(3000)
    handle.stop()
    await handle.finished
    vi.advanceTimersByTime(MAX_RECORDING_MS)
    expect(FakeRecorder.latest().stopCalls).toBe(1)
  })
})

describe('extensão pelo tipo do arquivo gravado', () => {
  it.each([
    ['audio/webm;codecs=opus', 'gravacao.webm'],
    ['audio/ogg;codecs=opus', 'gravacao.ogg'],
    ['audio/mp4', 'gravacao.m4a'],
    ['audio/wav', 'gravacao.wav'],
  ])('%s vira %s', async (mimeType, filename) => {
    const handle = await microphoneWith(fakeEnvironment({ mimeType })).start()
    handle.stop()
    const recording = await handle.finished
    expect(recording.filename).toBe(filename)
    expect(recording.blob.type).toBe(mimeType)
  })

  it('sem tipo informado pelo gravador, assume webm', async () => {
    const handle = await microphoneWith(fakeEnvironment({ mimeType: '' })).start()
    handle.stop()
    const recording = await handle.finished
    expect(recording.mimeType).toBe('audio/webm')
    expect(recording.filename).toBe('gravacao.webm')
  })
})

describe('quando não dá para gravar', () => {
  it('permissão negada vira uma mensagem clara e o microfone não fica aberto', async () => {
    const environment = fakeEnvironment({ reject: 'NotAllowedError' })
    const error = await failureOf(microphoneWith(environment).start())
    expect(error).toBeInstanceOf(MicrophoneError)
    expect(error.reason).toBe('denied')
    expect(error.message).toBe('Sem acesso ao microfone. Libere a permissão no navegador ou envie um arquivo.')
    expect(FakeRecorder.instances).toHaveLength(0)
  })

  it.each([
    ['SecurityError', 'denied'],
    ['NotFoundError', 'not-found'],
    ['NotReadableError', 'busy'],
    ['QualquerOutra', 'failed'],
  ])('a exceção %s do navegador vira %s', async (name, reason) => {
    const error = await failureOf(microphoneWith(fakeEnvironment({ reject: name })).start())
    expect(error.reason).toBe(reason)
  })

  it('navegador sem getUserMedia ou sem MediaRecorder: não suportado, com a saída por arquivo', async () => {
    for (const environment of [fakeEnvironment({ noMicrophone: true }), fakeEnvironment({ noRecorder: true })]) {
      const microphone = microphoneWith(environment)
      expect(microphone.isSupported()).toBe(false)
      const error = await failureOf(microphone.start())
      expect(error.reason).toBe('unsupported')
      expect(error.message).toContain('Envie um arquivo de áudio')
    }
  })

  it('um gravador que não consegue começar solta o microfone', async () => {
    const environment = fakeEnvironment()
    environment.createRecorder = () => {
      const recorder = new FakeRecorder()
      recorder.start = () => {
        throw new Error('InvalidStateError')
      }
      return recorder
    }
    const error = await failureOf(microphoneWith(environment).start())
    expect(error.reason).toBe('failed')
    expect(environment.stream.released).toBe(true)
  })

  it('um gravador que quebra no meio rejeita e solta o microfone', async () => {
    const environment = fakeEnvironment()
    const handle = await microphoneWith(environment).start()
    FakeRecorder.latest().fail()
    expect((await failureOf(handle.finished)).reason).toBe('failed')
    expect(environment.stream.released).toBe(true)
  })

  it('uma gravação sem nenhum áudio é recusada, em vez de seguir vazia para o servidor', async () => {
    const handle = await microphoneWith(fakeEnvironment({ bytes: '' })).start()
    handle.stop()
    expect((await failureOf(handle.finished)).reason).toBe('empty')
  })
})

describe('descartar', () => {
  it('cancelar solta o microfone, para o gravador e rejeita com "cancelled"', async () => {
    const environment = fakeEnvironment()
    const handle = await microphoneWith(environment).start()
    handle.cancel()
    expect((await failureOf(handle.finished)).reason).toBe('cancelled')
    expect(environment.stream.released).toBe(true)
    expect(FakeRecorder.latest().state).toBe('inactive')
    // a tampa não dispara depois do descarte
    vi.advanceTimersByTime(MAX_RECORDING_MS)
    expect(FakeRecorder.latest().stopCalls).toBe(1)
  })

  it('cancelar depois de acabar não muda o resultado', async () => {
    const handle = await microphoneWith(fakeEnvironment()).start()
    handle.stop()
    const recording = await handle.finished
    handle.cancel()
    await expect(handle.finished).resolves.toBe(recording)
  })
})

describe('o ambiente do navegador', () => {
  class BrowserRecorder extends FakeRecorder {}

  it('usa o MediaRecorder e o getUserMedia globais, lidos na hora de usar', async () => {
    const stream = fakeEnvironment().stream
    const getUserMedia = vi.fn().mockResolvedValue(stream)
    vi.stubGlobal('MediaRecorder', BrowserRecorder)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })

    const microphone = createMicrophone()
    expect(microphone.isSupported()).toBe(true)
    const handle = await microphone.start()
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(FakeRecorder.latest()).toBeInstanceOf(BrowserRecorder)
    handle.stop()
    await handle.finished
  })

  it('sem mediaDevices (página que não é segura) ou sem MediaRecorder, nada é suportado', () => {
    vi.stubGlobal('navigator', {})
    vi.stubGlobal('MediaRecorder', BrowserRecorder)
    expect(browserEnvironment().getUserMedia).toBeNull()
    expect(createMicrophone().isSupported()).toBe(false)

    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } })
    vi.stubGlobal('MediaRecorder', undefined)
    expect(browserEnvironment().createRecorder).toBeNull()
    expect(createMicrophone().isSupported()).toBe(false)
  })
})
