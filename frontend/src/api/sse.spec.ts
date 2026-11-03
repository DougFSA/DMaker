import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource } from '@/test/fetch'
import { subscribeJson, subscribeSse, type SseStatus } from './sse'

beforeEach(() => {
  FakeEventSource.reset()
  vi.useFakeTimers()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('subscribeSse', () => {
  it('abre o endereço, entrega o texto de cada evento e informa o estado', () => {
    const messages: string[] = []
    const statuses: SseStatus[] = []
    subscribeSse('/api/x/events', { onMessage: (data) => messages.push(data), onStatus: (s) => statuses.push(s) })
    const source = FakeEventSource.latest()
    expect(source.url).toBe('/api/x/events')
    source.open()
    source.emit('um')
    source.emit({ a: 1 })
    expect(messages).toEqual(['um', '{"a":1}'])
    expect(statuses).toEqual(['connecting', 'open'])
  })

  it('deixa o navegador reconectar quando a rede cai e avisa que está reconectando', () => {
    const statuses: SseStatus[] = []
    subscribeSse('/api/x', { onMessage: () => {}, onStatus: (s) => statuses.push(s) })
    FakeEventSource.latest().open()
    FakeEventSource.latest().drop()
    expect(statuses).toEqual(['connecting', 'open', 'reconnecting'])
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('reabre a conexão com espera crescente quando o navegador desiste', () => {
    const statuses: SseStatus[] = []
    subscribeSse('/api/x', { onMessage: () => {}, onStatus: (s) => statuses.push(s), retryDelaysMs: [100, 300] })
    FakeEventSource.latest().fail()
    expect(FakeEventSource.instances).toHaveLength(1)
    vi.advanceTimersByTime(99)
    expect(FakeEventSource.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeEventSource.instances).toHaveLength(2)

    FakeEventSource.latest().fail()
    vi.advanceTimersByTime(299)
    expect(FakeEventSource.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeEventSource.instances).toHaveLength(3)

    // a última espera se repete
    FakeEventSource.latest().fail()
    vi.advanceTimersByTime(300)
    expect(FakeEventSource.instances).toHaveLength(4)
    expect(statuses.filter((s) => s === 'reconnecting')).toHaveLength(3)
  })

  it('zera a contagem de tentativas quando a conexão volta a abrir', () => {
    subscribeSse('/api/x', { onMessage: () => {}, retryDelaysMs: [100, 5000] })
    FakeEventSource.latest().fail()
    vi.advanceTimersByTime(100)
    FakeEventSource.latest().open()
    FakeEventSource.latest().fail()
    vi.advanceTimersByTime(100) // voltou à primeira espera, não pulou para 5 s
    expect(FakeEventSource.instances).toHaveLength(3)
  })

  it('desiste depois de maxRetries tentativas seguidas', () => {
    const statuses: SseStatus[] = []
    subscribeSse('/api/x', { onMessage: () => {}, onStatus: (s) => statuses.push(s), maxRetries: 2, retryDelaysMs: [10] })
    FakeEventSource.latest().fail()
    vi.advanceTimersByTime(10)
    FakeEventSource.latest().fail()
    vi.advanceTimersByTime(10)
    FakeEventSource.latest().fail()
    expect(statuses.at(-1)).toBe('closed')
    vi.advanceTimersByTime(60000)
    expect(FakeEventSource.instances).toHaveLength(3)
  })

  it('close encerra a conexão, cancela a tentativa pendente e não reabre', () => {
    const statuses: SseStatus[] = []
    const subscription = subscribeSse('/api/x', { onMessage: () => {}, onStatus: (s) => statuses.push(s), retryDelaysMs: [100] })
    FakeEventSource.latest().fail()
    subscription.close()
    vi.advanceTimersByTime(1000)
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(statuses.at(-1)).toBe('closed')

    const second = subscribeSse('/api/y', { onMessage: () => {} })
    const source = FakeEventSource.latest()
    second.close()
    expect(source.closed).toBe(true)
  })
})

describe('subscribeJson', () => {
  it('entrega o JSON já lido e ignora linha quebrada', () => {
    const received: Array<{ n: number }> = []
    subscribeJson<{ n: number }>('/api/x', (data) => received.push(data))
    const source = FakeEventSource.latest()
    source.emit({ n: 1 })
    source.emit('{quebrado')
    source.emit({ n: 2 })
    expect(received).toEqual([{ n: 1 }, { n: 2 }])
  })
})
