/* Assinante genérico de SSE (EventSource) que reabre a conexão sozinho. O navegador já tenta de novo
   quando a rede cai, mas desiste (`CLOSED`) se o servidor responde com erro ou é reiniciado; para a fila
   de narrações, que fica aberta o tempo todo, desistir seria a tela congelar sem aviso. */

export type SseStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface SseOptions {
  /** O corpo de cada evento `data:`, ainda em texto. */
  onMessage: (data: string) => void
  /** Avisa quando a conexão abre, cai, volta ou é encerrada. */
  onStatus?: (status: SseStatus) => void
  /** Pausas, em ms, antes de cada nova tentativa depois que o navegador desistiu; a última se repete. */
  retryDelaysMs?: number[]
  /** Tentativas seguidas antes de desistir de vez (o padrão é nunca desistir). */
  maxRetries?: number
}

export interface SseSubscription {
  close: () => void
}

/** `EventSource.CLOSED`: lido por valor para os testes poderem trocar a classe por uma de mentira. */
const EVENT_SOURCE_CLOSED = 2

/** Começa curto para uma queda rápida passar despercebida e cresce para não martelar um servidor fora do ar. */
export const DEFAULT_RETRY_DELAYS_MS = [500, 1000, 2000, 5000, 10000]

export function subscribeSse(url: string, options: SseOptions): SseSubscription {
  const delays = options.retryDelaysMs?.length ? options.retryDelaysMs : DEFAULT_RETRY_DELAYS_MS
  const maxRetries = options.maxRetries ?? Infinity

  let source: EventSource | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let retries = 0
  let stopped = false

  const report = (status: SseStatus) => options.onStatus?.(status)

  function open(): void {
    const current = new EventSource(url)
    source = current
    current.onopen = () => {
      retries = 0
      report('open')
    }
    current.onmessage = (message: MessageEvent<string>) => options.onMessage(message.data)
    current.onerror = () => {
      if (stopped || source !== current) return
      if (current.readyState !== EVENT_SOURCE_CLOSED) {
        report('reconnecting') // o navegador está tentando de novo por conta própria
        return
      }
      current.close()
      source = null
      if (retries >= maxRetries) {
        stopped = true
        report('closed')
        return
      }
      const delay = delays[Math.min(retries, delays.length - 1)] ?? 0
      retries += 1
      report('reconnecting')
      timer = setTimeout(() => {
        timer = null
        if (!stopped) open()
      }, delay)
    }
  }

  report('connecting')
  open()

  return {
    close() {
      if (stopped) return
      stopped = true
      if (timer) clearTimeout(timer)
      timer = null
      source?.close()
      source = null
      report('closed')
    },
  }
}

/** Como `subscribeSse`, mas entrega o JSON já lido; linha quebrada é ignorada (o próximo evento corrige). */
export function subscribeJson<T>(
  url: string,
  onData: (data: T) => void,
  options: Omit<SseOptions, 'onMessage'> = {},
): SseSubscription {
  return subscribeSse(url, {
    ...options,
    onMessage(text) {
      let parsed: T
      try {
        parsed = JSON.parse(text) as T
      } catch {
        return
      }
      onData(parsed)
    },
  })
}
