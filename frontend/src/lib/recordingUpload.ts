/* O envio dos pedaços de um segundo ao servidor, com recuperação: cada pedaço é numerado, vai em ordem, e uma falha de rede
   o põe de novo na fila com espera crescente. Como o servidor guarda o pedaço pelo número (reenviar não duplica), repetir
   é sempre seguro. O que ainda não foi confirmado fica em `pending`, para a tela mostrar "enviando" e para o fechar da aba
   avisar. Sem DOM e sem `fetch`: quem envia entra por injeção. */

export type PutChunk = (seq: number, bytes: Uint8Array<ArrayBuffer>) => Promise<unknown>

export interface UploaderOptions {
  /** Espera antes da primeira nova tentativa (ms); dobra a cada falha seguida até `maxDelayMs`. */
  baseDelayMs?: number
  maxDelayMs?: number
  /** Quem espera: os testes entregam um que não gasta tempo. */
  sleep?: (ms: number) => Promise<void>
  /** Avisado a cada falha de envio. */
  onRetry?: (seq: number, attempt: number, error: unknown) => void
  /** Uma falha que repetir não conserta (o servidor recusou o pedaço): o envio para e o `flush` rejeita com ela. */
  isFatal?: (error: unknown) => boolean
}

const realSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

export class ChunkUploader {
  private readonly queue: Array<{ seq: number; bytes: Uint8Array<ArrayBuffer> }> = []
  private running: Promise<void> | null = null
  private failures = 0
  private closed = false
  private error: unknown = null
  /** Os números já confirmados pelo servidor. */
  readonly acknowledged = new Set<number>()

  constructor(
    private readonly put: PutChunk,
    private readonly options: UploaderOptions = {},
  ) {}

  /** Quantos pedaços ainda não foram confirmados (na fila ou em envio). */
  get pending(): number {
    return this.queue.length
  }

  /** O envio foi abandonado (a pessoa desistiu, ou o servidor recusou um pedaço): nada mais sai. */
  get failed(): boolean {
    return this.closed
  }

  /** Põe o pedaço na fila e começa a enviar. */
  send(seq: number, bytes: Uint8Array<ArrayBuffer>): void {
    if (this.closed) return
    this.queue.push({ seq, bytes })
    this.running ??= this.drain()
  }

  /** Resolve quando a fila esvaziou (tudo confirmado). Rejeita se o envio foi abandonado por `abandon`. */
  async flush(): Promise<void> {
    while (this.running) await this.running
    if (this.error) throw this.error
  }

  /** Para de tentar (a pessoa desistiu da gravação): o que não foi confirmado fica de fora. */
  abandon(reason: unknown = new Error('envio interrompido')): void {
    this.closed = true
    this.error = reason
    this.queue.length = 0
  }

  private async drain(): Promise<void> {
    const sleep = this.options.sleep ?? realSleep
    const base = this.options.baseDelayMs ?? 500
    const cap = this.options.maxDelayMs ?? 8000
    try {
      while (this.queue.length > 0 && !this.closed) {
        const next = this.queue[0]
        if (!next) break
        try {
          await this.put(next.seq, next.bytes)
        } catch (error) {
          if (this.options.isFatal?.(error)) {
            this.abandon(error)
            break
          }
          this.failures += 1
          this.options.onRetry?.(next.seq, this.failures, error)
          await sleep(Math.min(base * 2 ** (this.failures - 1), cap))
          continue // o mesmo pedaço de novo, antes dos seguintes: a ordem de chegada se mantém
        }
        this.failures = 0
        this.acknowledged.add(next.seq)
        this.queue.shift()
      }
    } finally {
      this.running = null
    }
  }
}
