import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { JobEvent, JobSnapshot } from '@/api'
import { useJobsStore } from './jobs'

/** EventSource de mentira: o teste empurra os eventos que o servidor mandaria. */
class FakeEventSource {
  static instances: FakeEventSource[] = []
  static readonly CLOSED = 2
  readonly url: string
  readyState = 1
  closed = false
  onmessage: ((message: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close(): void {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }

  emit(event: JobEvent): void {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>)
  }
}

function snapshot(overrides: Partial<JobSnapshot> = {}): JobSnapshot {
  return {
    job_id: 'j1',
    description: 'demo: preview',
    status: 'running',
    elapsed_s: 4,
    progress: {},
    error: null,
    focus: false,
    project: 'demo',
    ...overrides,
  }
}

function stubJobsApi(list: JobSnapshot[]): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') return Promise.resolve(new Response('{"removed":1}'))
      return Promise.resolve(new Response(JSON.stringify(list)))
    }),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

describe('useJobsStore', () => {
  it('traz os jobs da API e passa a acompanhar os que estão rodando', async () => {
    stubJobsApi([snapshot(), snapshot({ job_id: 'j2', status: 'done' })])
    const jobs = useJobsStore()
    await jobs.refresh()

    expect(jobs.list.map((job) => job.id)).toEqual(['j1', 'j2']) // rodando vem primeiro
    expect(jobs.runningCount).toBe(1)
    expect(FakeEventSource.instances.map((source) => source.url)).toEqual(['/api/jobs/j1/events'])
  })

  it('atualiza progresso e log ao vivo pelos eventos', () => {
    const jobs = useJobsStore()
    jobs.track('j1', { project: 'demo', description: 'demo: preview' })
    const source = FakeEventSource.instances[0]!

    source.emit({ kind: 'start', t: 0, description: 'demo: preview' })
    source.emit({ kind: 'log', t: 1, message: 'montando mezanino' })
    source.emit({ kind: 'progress', t: 2, label: 'encode', done: 5, total: 10, percent: 50 })

    const job = jobs.jobs['j1']!
    expect(job.progress).toEqual({ label: 'encode', done: 5, total: 10, percent: 50 })
    expect(job.log).toEqual(['montando mezanino'])
    expect(jobs.forProject('demo')).toHaveLength(1)
  })

  it('reconectar reenvia tudo desde o start sem duplicar o log', () => {
    const jobs = useJobsStore()
    jobs.track('j1')
    const source = FakeEventSource.instances[0]!
    source.emit({ kind: 'start', t: 0, description: 'x' })
    source.emit({ kind: 'log', t: 1, message: 'a' })
    source.emit({ kind: 'start', t: 0, description: 'x' })
    source.emit({ kind: 'log', t: 1, message: 'a' })
    expect(jobs.jobs['j1']!.log).toEqual(['a'])
  })

  it('o evento final fecha o SSE, guarda o resultado e avisa os ouvintes uma vez', () => {
    const jobs = useJobsStore()
    const ended = vi.fn()
    jobs.onJobEnd(ended)
    jobs.track('j1')
    const source = FakeEventSource.instances[0]!

    source.emit({ kind: 'end', t: 9, status: 'done', error: null, result: { output: 'a.mp4' } })
    source.emit({ kind: 'end', t: 9, status: 'done', error: null, result: { output: 'a.mp4' } })

    expect(jobs.jobs['j1']).toMatchObject({ status: 'done', result: { output: 'a.mp4' } })
    expect(source.closed).toBe(true)
    expect(ended).toHaveBeenCalledTimes(1)
    expect(jobs.runningCount).toBe(0)
  })

  it('erro no job vira status error com a mensagem', () => {
    const jobs = useJobsStore()
    jobs.track('j1')
    FakeEventSource.instances[0]!.emit({ kind: 'end', t: 1, status: 'error', error: 'FFmpegError: x', result: null })
    expect(jobs.jobs['j1']).toMatchObject({ status: 'error', error: 'FFmpegError: x' })
  })

  it('a consulta periódica encerra o job quando o SSE se perdeu', async () => {
    const jobs = useJobsStore()
    const ended = vi.fn()
    jobs.onJobEnd(ended)
    jobs.track('j1')
    stubJobsApi([snapshot({ status: 'done' })])
    await jobs.refresh()
    expect(jobs.jobs['j1']!.status).toBe('done')
    expect(ended).toHaveBeenCalledTimes(1)
  })

  it('acompanhar o mesmo job duas vezes abre um só SSE', () => {
    const jobs = useJobsStore()
    jobs.track('j1')
    jobs.track('j1')
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('marca o servidor como inacessível quando a consulta falha', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    const jobs = useJobsStore()
    await jobs.refresh()
    expect(jobs.reachable).toBe(false)
  })

  it('limpar concluídos remove só os que terminaram', async () => {
    stubJobsApi([snapshot(), snapshot({ job_id: 'j2', status: 'done' })])
    const jobs = useJobsStore()
    await jobs.refresh()
    await jobs.clearFinished()
    expect(jobs.list.map((job) => job.id)).toEqual(['j1'])
  })
})
