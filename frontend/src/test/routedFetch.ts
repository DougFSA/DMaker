/* Apoio dos testes das telas: um `fetch` falso que responde por rota ("GET /api/projects/a"), para uma tela que
   chama várias rotas na mesma abertura. Cada rota devolve o JSON (ou `reply(status, corpo)` para um erro). */
import { vi } from 'vitest'

export interface RoutedCall {
  method: string
  /** O caminho sem a query. */
  path: string
  url: string
  body: unknown
}

export interface ReplyWith {
  status: number
  body: unknown
}

type Handler = unknown | ((call: RoutedCall) => unknown)

/** Resposta com status diferente de 200. */
export function reply(status: number, body: unknown): ReplyWith {
  return { status, body }
}

function isReply(value: unknown): value is ReplyWith {
  return !!value && typeof value === 'object' && 'status' in value && 'body' in value
}

export interface RoutedFetch {
  calls: RoutedCall[]
  /** As chamadas a uma rota, na ordem. */
  to: (route: string) => RoutedCall[]
  /** Troca a resposta de uma rota no meio do teste. */
  set: (route: string, handler: Handler) => void
}

/**
 * Troca o `fetch` global. A chave é "MÉTODO /caminho"; rota sem handler responde 404, que é como o teste
 * descobre uma chamada que a tela não devia fazer.
 */
export function routedFetch(routes: Record<string, Handler>): RoutedFetch {
  const table = new Map(Object.entries(routes))
  const calls: RoutedCall[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const [path = ''] = String(input).split('?')
      const call: RoutedCall = {
        method,
        path,
        url: String(input),
        body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
      }
      calls.push(call)
      const handler = table.get(`${method} ${path}`)
      if (handler === undefined) {
        return Promise.resolve(new Response(JSON.stringify({ detail: `sem rota no teste: ${method} ${path}` }), { status: 404 }))
      }
      const result = typeof handler === 'function' ? (handler as (call: RoutedCall) => unknown)(call) : handler
      // o handler pode devolver uma promessa para o teste decidir quando a resposta chega
      return Promise.resolve(result).then((settled) => {
        const status = isReply(settled) ? settled.status : 200
        const body = isReply(settled) ? settled.body : settled
        return new Response(JSON.stringify(body), { status })
      })
    }),
  )
  return {
    calls,
    to: (route) => calls.filter((call) => `${call.method} ${call.path}` === route),
    set: (route, handler) => void table.set(route, handler),
  }
}
