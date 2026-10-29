import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource, stubFetch } from '@/test/fetch'
import { followJob, isJobCancelled, jobErrorMessage, JobCancelledError } from './follow'
import type { UtteranceEvent } from './types/voice'

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const utterance = (index: number): UtteranceEvent => ({
  kind: 'utterance',
  t: index,
  index,
  total: 3,
  audio_url: `/api/voices/audio?path=f${index}.wav`,
  duration_s: 1.5,
  pause_after_s: 0.3,
})

describe('followJob', () => {
  it('acompanha o SSE do job e resolve com o resultado quando ele termina', async () => {
    const followed = followJob<{ output: string }>('j1')
    const source = FakeEventSource.latest()
    expect(source.url).toBe('/api/jobs/j1/events')
    source.emit({ kind: 'start', t: 0, description: 'x' })
    source.emit({ kind: 'end', t: 3, status: 'done', error: null, result: { output: 'a.wav' } })
    await expect(followed.result).resolves.toEqual({ output: 'a.wav' })
    expect(source.closed).toBe(true)
  })

  it('repassa progresso, log e todos os eventos crus', async () => {
    const onEvent = vi.fn()
    const onProgress = vi.fn()
    const onLog = vi.fn()
    const followed = followJob('j1', { onEvent, onProgress, onLog })
    const source = FakeEventSource.latest()
    source.emit({ kind: 'log', t: 1, message: 'Aguardando outro trabalho de voz terminar' })
    source.emit({ kind: 'progress', t: 2, label: 'fala 1 de 3', done: 1, total: 3, percent: 0 })
    source.emit({ kind: 'end', t: 3, status: 'done', error: null, result: null })
    await followed.result
    expect(onLog).toHaveBeenCalledWith('Aguardando outro trabalho de voz terminar')
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ label: 'fala 1 de 3', percent: 0 }))
    expect(onEvent).toHaveBeenCalledTimes(3)
  })

  it('entrega cada fala pronta uma vez só, mesmo que o servidor reenvie tudo ao reconectar', async () => {
    const onUtterance = vi.fn()
    const followed = followJob('j1', { onUtterance })
    const source = FakeEventSource.latest()
    source.emit(utterance(1))
    source.emit(utterance(2))
    source.emit({ kind: 'start', t: 0, description: 'x' }) // reconectou: o servidor reenvia desde o começo
    source.emit(utterance(1))
    source.emit(utterance(2))
    source.emit(utterance(3))
    source.emit({ kind: 'end', t: 9, status: 'done', error: null, result: null })
    await followed.result
    expect(onUtterance.mock.calls.map(([fala]) => fala.index)).toEqual([1, 2, 3])
  })

  it('rejeita com a mensagem limpa quando o job falha', async () => {
    const followed = followJob('j1')
    FakeEventSource.latest().emit({
      kind: 'end',
      t: 1,
      status: 'error',
      error: 'ValueError: A voz não existe\nTraceback (most recent call last)...',
      result: null,
    })
    await expect(followed.result).rejects.toThrow('A voz não existe')
  })

  it('rejeita com JobCancelledError e o que já estava pronto quando o job é parado', async () => {
    const followed = followJob('j1')
    FakeEventSource.latest().emit({ kind: 'end', t: 1, status: 'cancelled', error: null, result: { ready: 2, total: 5 } })
    const error = await followed.result.catch((e: unknown) => e)
    expect(isJobCancelled(error)).toBe(true)
    expect(error).toBeInstanceOf(JobCancelledError)
    expect((error as JobCancelledError).result).toEqual({ ready: 2, total: 5 })
    expect(isJobCancelled(new Error('x'))).toBe(false)
  })

  it('cancelar manda o pedido ao servidor sem encerrar o acompanhamento', async () => {
    const fetch = stubFetch({ job_id: 'j1', cancellable: true })
    const followed = followJob('j1')
    await followed.cancel()
    expect(fetch.last()).toMatchObject({ url: '/api/jobs/j1/cancel', method: 'POST' })
    expect(FakeEventSource.latest().closed).toBe(false)
  })

  it('cancelar um job que não aceita vira o erro do servidor', async () => {
    stubFetch({ detail: 'este tipo de trabalho não pode ser cancelado' }, 409)
    const followed = followJob('j1')
    await expect(followed.cancel()).rejects.toThrow('este tipo de trabalho não pode ser cancelado')
  })

  it('rejeita quando a conexão se perde de vez antes do fim do job', async () => {
    vi.useFakeTimers()
    const followed = followJob('j1')
    const outcome = followed.result.catch((e: unknown) => e)
    for (let attempt = 0; attempt < 6; attempt += 1) {
      FakeEventSource.latest().fail()
      await vi.advanceTimersByTimeAsync(15000)
    }
    expect(await outcome).toMatchObject({ message: 'A conexão com o servidor foi perdida.' })
  })

  it('largar o job pelo signal fecha o SSE e rejeita com AbortError, sem cancelar o job', async () => {
    const fetch = stubFetch()
    const controller = new AbortController()
    const followed = followJob('j1', { signal: controller.signal })
    const source = FakeEventSource.latest()
    controller.abort()
    await expect(followed.result).rejects.toMatchObject({ name: 'AbortError' })
    expect(source.closed).toBe(true)
    expect(fetch.calls).toHaveLength(0)
  })

  it('um signal já abortado nem abre a conexão', async () => {
    const controller = new AbortController()
    controller.abort()
    const followed = followJob('j1', { signal: controller.signal })
    await expect(followed.result).rejects.toMatchObject({ name: 'AbortError' })
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('ignora linha que não é JSON', async () => {
    const followed = followJob('j1')
    const source = FakeEventSource.latest()
    source.emit('{quebrado')
    source.emit({ kind: 'end', t: 1, status: 'done', error: null, result: 7 })
    await expect(followed.result).resolves.toBe(7)
  })
})

describe('jobErrorMessage', () => {
  it('fica com a primeira linha, sem o nome da exceção', () => {
    expect(jobErrorMessage('ValueError: texto vazio\nTraceback...')).toBe('texto vazio')
    expect(jobErrorMessage('FFmpegError: falhou')).toBe('falhou')
    expect(jobErrorMessage('Algo deu errado')).toBe('Algo deu errado')
  })

  it('cai numa frase genérica sem erro', () => {
    expect(jobErrorMessage(null)).toBe('Erro desconhecido')
    expect(jobErrorMessage('')).toBe('Erro desconhecido')
  })
})
