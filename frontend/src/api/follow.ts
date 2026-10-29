/* "Seguir job": acompanha um job pelo SSE e devolve uma promessa do resultado. É o que as telas de voz,
   fala, dublagem e modelos usam para esperar o trabalho que acabaram de iniciar (POST que devolve `job_id`),
   cada uma com o seu cartão de andamento. O estado global dos jobs (a barra do topo) é do `stores/jobs.ts`. */
import { jobsApi } from './jobs'
import { subscribeSse } from './sse'
import type { JobEvent, JobProgress } from './types'
import type { UtteranceEvent } from './types/voice'

export interface FollowJobHandlers {
  /** Todo evento, cru, na ordem em que chega (o servidor reenvia tudo desde o `start` se a conexão cair). */
  onEvent?: (event: JobEvent) => void
  /** Etapa e fração do trabalho: `label`, `done`, `total` e `percent`. */
  onProgress?: (progress: JobProgress) => void
  /** Uma linha do log do job ("Aguardando outro trabalho de voz terminar", por exemplo). */
  onLog?: (message: string) => void
  /** Uma fala da narração ficou pronta. Cada `index` chega uma vez só, mesmo que o SSE reconecte e reenvie. */
  onUtterance?: (utterance: UtteranceEvent) => void
  /** Largar o job sem pará-lo (a pessoa saiu da tela): `result` rejeita com um `AbortError`. */
  signal?: AbortSignal
}

export interface FollowedJob<T> {
  jobId: string
  /**
   * Resolve com o resultado do job. Rejeita com `JobCancelledError` se ele parou a pedido (o que já ficou
   * pronto vem em `.result`), com o texto do erro se falhou e com "A conexão com o servidor foi perdida."
   * se o SSE não voltou.
   */
  result: Promise<T>
  /** Pede ao servidor que pare o job; `result` rejeita com `JobCancelledError` quando ele de fato parar. */
  cancel: () => Promise<void>
}

/** O job parou porque a pessoa pediu. `result` guarda o que já estava pronto (por exemplo `{ ready, total }`). */
export class JobCancelledError extends Error {
  readonly result: unknown

  constructor(result: unknown = null) {
    super('Cancelado.')
    this.name = 'JobCancelledError'
    this.result = result
  }
}

export function isJobCancelled(error: unknown): error is JobCancelledError {
  return error instanceof JobCancelledError
}

/** O erro de um job chega como "ValueError: mensagem\nTraceback..."; a tela mostra só a primeira linha, sem o nome da exceção. */
export function jobErrorMessage(error: string | null | undefined): string {
  const first = String(error || 'Erro desconhecido').split('\n')[0] ?? ''
  return first.replace(/^\w+(Error|Exception):\s*/, '') || 'Erro desconhecido'
}

const CONNECTION_LOST = 'A conexão com o servidor foi perdida.'
/** Poucas tentativas: um job que o servidor esqueceu (reiniciado) não volta, e a pessoa precisa saber logo. */
const FOLLOW_RETRIES = 5

export function followJob<T = unknown>(jobId: string, handlers: FollowJobHandlers = {}): FollowedJob<T> {
  const delivered = new Set<number>()

  const result = new Promise<T>((resolve, reject) => {
    const { signal } = handlers
    if (signal?.aborted) {
      reject(new DOMException('Parei de acompanhar o job.', 'AbortError'))
      return
    }

    let settled = false

    const subscription = subscribeSse(jobsApi.eventsUrl(jobId), {
      maxRetries: FOLLOW_RETRIES,
      onStatus(status) {
        // sem fim do job e sem conexão: não há mais o que esperar
        if (status === 'closed' && !settled) fail(new Error(CONNECTION_LOST))
      },
      onMessage(text) {
        let event: JobEvent
        try {
          event = JSON.parse(text) as JobEvent
        } catch {
          return
        }
        handlers.onEvent?.(event)
        switch (event.kind) {
          case 'progress':
            handlers.onProgress?.(event)
            break
          case 'log':
            handlers.onLog?.(event.message)
            break
          case 'utterance':
            if (!delivered.has(event.index)) {
              delivered.add(event.index)
              handlers.onUtterance?.(event)
            }
            break
          case 'end':
            finish(event)
            break
        }
      },
    })

    function settle(): void {
      settled = true
      subscription.close()
      signal?.removeEventListener('abort', onAbort)
    }

    function fail(error: Error): void {
      if (settled) return
      settle()
      reject(error)
    }

    function finish(event: Extract<JobEvent, { kind: 'end' }>): void {
      if (settled) return
      settle()
      if (event.status === 'done') resolve(event.result as T)
      else if (event.status === 'cancelled') reject(new JobCancelledError(event.result))
      else reject(new Error(jobErrorMessage(event.error)))
    }

    function onAbort(): void {
      fail(new DOMException('Parei de acompanhar o job.', 'AbortError'))
    }

    signal?.addEventListener('abort', onAbort, { once: true })
  })

  return {
    jobId,
    result,
    cancel: async () => {
      await jobsApi.cancel(jobId)
    },
  }
}
