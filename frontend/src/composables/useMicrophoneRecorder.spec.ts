import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { createMicrophone, MAX_RECORDING_MS } from '@/lib/microphone'
import { FakeRecorder, fakeEnvironment, type FakeEnvironment } from '@/test/recorder'
import { useMicrophoneRecorder } from './useMicrophoneRecorder'

beforeEach(() => {
  FakeRecorder.reset()
  vi.useFakeTimers()
  // o jsdom não implementa os endereços de blob
  URL.createObjectURL = vi.fn(() => 'blob:gravacao')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

/** Deixa as promessas pendentes andarem; o `flushPromises` do test-utils depende de timers e trava com os falsos. */
const settle = () => vi.advanceTimersByTimeAsync(0)

function recorderWith(environment: FakeEnvironment = fakeEnvironment()) {
  const scope = effectScope()
  const recorder = scope.run(() => useMicrophoneRecorder(createMicrophone(() => environment)))!
  return { recorder, scope, environment }
}

describe('useMicrophoneRecorder', () => {
  it('começa parado, sem gravação e com o relógio zerado', () => {
    const { recorder } = recorderWith()
    expect(recorder.phase.value).toBe('idle')
    expect(recorder.recording.value).toBeNull()
    expect(recorder.elapsedMs.value).toBe(0)
    expect(recorder.supported).toBe(true)
  })

  it('grava, o relógio anda e, ao parar, a gravação fica pronta para tocar', async () => {
    const { recorder } = recorderWith()
    await recorder.start()
    expect(recorder.phase.value).toBe('recording')

    vi.advanceTimersByTime(6000)
    expect(recorder.elapsedMs.value).toBe(6000)

    recorder.stop()
    await settle()
    expect(recorder.phase.value).toBe('recorded')
    expect(recorder.recording.value?.filename).toBe('gravacao.webm')
    expect(recorder.elapsedMs.value).toBe(6000)
    expect(recorder.playbackUrl.value).toBe('blob:gravacao')
  })

  it('aos 30 segundos a gravação termina sozinha', async () => {
    const { recorder } = recorderWith()
    await recorder.start()
    vi.advanceTimersByTime(MAX_RECORDING_MS)
    await settle()
    expect(recorder.phase.value).toBe('recorded')
    expect(recorder.elapsedMs.value).toBe(MAX_RECORDING_MS)
  })

  it('permissão negada fica como mensagem e a fase continua parada', async () => {
    const { recorder } = recorderWith(fakeEnvironment({ reject: 'NotAllowedError' }))
    await recorder.start()
    expect(recorder.phase.value).toBe('idle')
    expect(recorder.error.value).toContain('Libere a permissão no navegador')
    expect(recorder.starting.value).toBe(false)
  })

  it('gravar de novo descarta a anterior e libera o endereço dela', async () => {
    const { recorder } = recorderWith()
    await recorder.start()
    recorder.stop()
    await settle()
    expect(recorder.phase.value).toBe('recorded')

    await recorder.start()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:gravacao')
    expect(recorder.recording.value).toBeNull()
    expect(recorder.phase.value).toBe('recording')
    expect(recorder.elapsedMs.value).toBe(0)
  })

  it('pedir para gravar duas vezes seguidas só abre o microfone uma vez', async () => {
    const { recorder, environment } = recorderWith()
    const first = recorder.start()
    const second = recorder.start()
    await Promise.all([first, second])
    expect(environment.requests).toHaveLength(1)
  })

  it('descartar volta ao começo, solta o microfone e limpa o erro', async () => {
    const { recorder, environment } = recorderWith()
    await recorder.start()
    recorder.discard()
    await settle()
    expect(recorder.phase.value).toBe('idle')
    expect(recorder.error.value).toBe('')
    expect(environment.stream.released).toBe(true)
  })

  it('ao sair da tela, a gravação em andamento é descartada e o microfone solto', async () => {
    const { recorder, scope, environment } = recorderWith()
    await recorder.start()
    scope.stop()
    await settle()
    expect(environment.stream.released).toBe(true)
    expect(recorder.phase.value).toBe('idle')
    expect(recorder.error.value).toBe('')
  })

  it('navegador sem microfone: não suportado, e iniciar só mostra a mensagem', async () => {
    const { recorder } = recorderWith(fakeEnvironment({ noMicrophone: true }))
    expect(recorder.supported).toBe(false)
    await recorder.start()
    expect(recorder.error.value).toContain('Envie um arquivo de áudio')
  })
})
