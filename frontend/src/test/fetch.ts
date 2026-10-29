/* Apoio dos testes dos clientes da API: troca o `fetch` por um falso que guarda o que foi pedido. */
import { vi } from 'vitest'

export interface RecordedCall {
  url: string
  method: string
  /** O corpo JSON, já lido; indefinido quando a chamada não mandou corpo ou mandou multipart. */
  body: unknown
  /** O multipart, quando a chamada enviou arquivo. */
  form: FormData | null
  headers: Record<string, string>
}

export interface FetchStub {
  calls: RecordedCall[]
  last: () => RecordedCall
}

/** `reply` é o JSON que cada chamada devolve; por padrão `{}`. Cada chamada ganha uma resposta nova (o corpo só lê uma vez). */
export function stubFetch(reply: unknown = {}, status = 200): FetchStub {
  const calls: RecordedCall[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const isForm = init.body instanceof FormData
      calls.push({
        url,
        method: init.method ?? 'GET',
        body: init.body && !isForm ? JSON.parse(String(init.body)) : undefined,
        form: isForm ? (init.body as FormData) : null,
        headers: (init.headers ?? {}) as Record<string, string>,
      })
      return Promise.resolve(new Response(JSON.stringify(reply), { status }))
    }),
  )
  return {
    calls,
    last: () => {
      const call = calls.at(-1)
      if (!call) throw new Error('nenhuma chamada ao fetch')
      return call
    },
  }
}

/** EventSource de mentira: o teste abre, empurra os eventos que o servidor mandaria e simula quedas. */
export class FakeEventSource {
  static instances: FakeEventSource[] = []
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  readonly url: string
  readyState = 0
  closed = false
  onopen: (() => void) | null = null
  onmessage: ((message: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  static reset(): void {
    FakeEventSource.instances = []
  }

  static latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1)
    if (!source) throw new Error('nenhum EventSource aberto')
    return source
  }

  close(): void {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }

  /** O servidor aceitou a conexão. */
  open(): void {
    this.readyState = FakeEventSource.OPEN
    this.onopen?.()
  }

  /** Chega um evento `data:`; objetos viram JSON, texto passa como veio. */
  emit(data: unknown): void {
    this.onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data) } as MessageEvent<string>)
  }

  /** O navegador perdeu a conexão e vai tentar de novo sozinho. */
  drop(): void {
    this.readyState = FakeEventSource.CONNECTING
    this.onerror?.()
  }

  /** O servidor respondeu com erro e o navegador desistiu. */
  fail(): void {
    this.readyState = FakeEventSource.CLOSED
    this.onerror?.()
  }
}
