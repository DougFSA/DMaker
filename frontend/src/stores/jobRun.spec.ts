import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource, stubFetch } from '@/test/fetch'
import { createJobRun, QUEUED_LABEL } from './jobRun'

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

interface Output {
  output: string
}

const started = (id = 'j1') => () => Promise.resolve({ job_id: id })

/** Deixa o `run` chegar ao `followJob` (o POST de início resolve numa microtarefa). */
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

describe('createJobRun', () => {
  it('começa na fila e acompanha etapa, porcentagem e log até o resultado', async () => {
    const job = createJobRun<Output>()
    const pending = job.run(started())
    expect(job.running).toBe(true)
    expect(job.label).toBe(QUEUED_LABEL)
    await settle()

    const source = FakeEventSource.latest()
    expect(source.url).toBe('/api/jobs/j1/events')
    source.emit({ kind: 'log', t: 1, message: 'Aguardando outro trabalho de voz terminar' })
    expect(job.label).toBe('Aguardando outro trabalho de voz terminar')
    source.emit({ kind: 'progress', t: 2, label: 'bloco 1 de 4', done: 1, total: 4, percent: 25 })
    expect(job.label).toBe('bloco 1 de 4')
    expect(job.percent).toBe(25)
    expect(job.log).toEqual(['Aguardando outro trabalho de voz terminar'])

    source.emit({ kind: 'end', t: 3, status: 'done', error: null, result: { output: 'a.wav' } })
    await expect(pending).resolves.toEqual({ output: 'a.wav' })
    expect(job.running).toBe(false)
    expect(job.error).toBe('')
    expect(job.cancelled).toBe(false)
  })

  it('guarda só as últimas linhas do log', async () => {
    const job = createJobRun<Output>()
    const pending = job.run(started())
    await settle()
    const source = FakeEventSource.latest()
    for (let line = 1; line <= 9; line += 1) source.emit({ kind: 'log', t: line, message: `linha ${line}` })
    expect(job.log).toEqual(['linha 4', 'linha 5', 'linha 6', 'linha 7', 'linha 8', 'linha 9'])
    source.emit({ kind: 'end', t: 10, status: 'done', error: null, result: { output: 'a' } })
    await pending
  })

  it('erro do job vira texto limpo em `error` e o resultado é nulo', async () => {
    const job = createJobRun<Output>()
    const pending = job.run(started())
    await settle()
    FakeEventSource.latest().emit({
      kind: 'end',
      t: 1,
      status: 'error',
      error: 'ValueError: Não achei "Pedro" na fala.\nTraceback (most recent call last)...',
      result: null,
    })
    await expect(pending).resolves.toBeNull()
    expect(job.error).toBe('Não achei "Pedro" na fala.')
    expect(job.running).toBe(false)
  })

  it('recusa do POST de início (400) também vira erro, sem abrir o SSE', async () => {
    const job = createJobRun<Output>()
    const result = await job.run(() => Promise.reject(new Error('O fim precisa ser maior que o início.')))
    expect(result).toBeNull()
    expect(job.error).toBe('O fim precisa ser maior que o início.')
    expect(job.running).toBe(false)
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('um início que devolve `null` é a pessoa desistindo: nada roda, nada é mostrado e o próximo pedido funciona', async () => {
    const job = createJobRun<Output>()
    await expect(job.run(() => Promise.resolve(null))).resolves.toBeNull()
    expect(job.running).toBe(false)
    expect(job.error).toBe('')
    expect(job.cancelled).toBe(false)
    expect(job.startedAtMs).toBeNull()
    expect(FakeEventSource.instances).toHaveLength(0)

    const pending = job.run(started())
    await settle()
    FakeEventSource.latest().emit({ kind: 'end', t: 1, status: 'done', error: null, result: { output: 'a' } })
    await expect(pending).resolves.toEqual({ output: 'a' })
  })

  it('parar a pedido marca `cancelled`, sem erro', async () => {
    const calls = stubFetch({ ok: true })
    const job = createJobRun<Output>()
    const pending = job.run(started('j7'))
    await settle()
    await job.cancel()
    expect(calls.last()).toMatchObject({ method: 'POST', url: '/api/jobs/j7/cancel' })
    expect(job.cancelling).toBe(true)

    FakeEventSource.latest().emit({ kind: 'end', t: 2, status: 'cancelled', error: null, result: null })
    await expect(pending).resolves.toBeNull()
    expect(job.cancelled).toBe(true)
    expect(job.error).toBe('')
    expect(job.cancelling).toBe(false)
  })

  it('pedido de parar que o servidor recusa mostra o erro e deixa tentar de novo', async () => {
    stubFetch({ detail: 'este tipo de trabalho não pode ser cancelado' }, 409)
    const job = createJobRun<Output>()
    const pending = job.run(started())
    await settle()
    await job.cancel()
    expect(job.error).toBe('este tipo de trabalho não pode ser cancelado')
    expect(job.cancelling).toBe(false)
    FakeEventSource.latest().emit({ kind: 'end', t: 2, status: 'done', error: null, result: { output: 'a' } })
    await pending
  })

  it('um segundo pedido durante o primeiro é ignorado', async () => {
    const job = createJobRun<Output>()
    const first = job.run(started('j1'))
    const second = job.run(started('j2'))
    await expect(second).resolves.toBeNull()
    await settle()
    expect(FakeEventSource.instances).toHaveLength(1)
    FakeEventSource.latest().emit({ kind: 'end', t: 1, status: 'done', error: null, result: { output: 'a' } })
    await first
  })

  it('um novo trabalho começa limpo, sem o erro do anterior', async () => {
    const job = createJobRun<Output>()
    await job.run(() => Promise.reject(new Error('falhou')))
    expect(job.error).toBe('falhou')
    const pending = job.run(started())
    expect(job.error).toBe('')
    await settle()
    FakeEventSource.latest().emit({ kind: 'end', t: 1, status: 'done', error: null, result: { output: 'a' } })
    await pending
  })

  it('`clear` esquece o erro, mas não mexe no que está rodando', async () => {
    const job = createJobRun<Output>()
    await job.run(() => Promise.reject(new Error('falhou')))
    job.clear()
    expect(job.error).toBe('')

    const pending = job.run(started())
    await settle()
    job.clear()
    expect(job.running).toBe(true)
    expect(job.label).toBe(QUEUED_LABEL)
    FakeEventSource.latest().emit({ kind: 'end', t: 1, status: 'done', error: null, result: { output: 'a' } })
    await pending
  })
})
