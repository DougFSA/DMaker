/** Erro de uma chamada à API, com a mensagem já legível para ir direto ao Toast. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

/** O FastAPI manda `detail` como texto (nossos erros) ou lista {loc, msg} (validação do Pydantic). */
export function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const { loc, msg } = item as { loc?: unknown; msg: unknown }
          return loc ? `${String(loc)}: ${String(msg)}` : String(msg)
        }
        return String(item)
      })
      .join('\n')
  }
  return fallback
}

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) {
    // sem Content-Type de propósito: o navegador o monta com o limite (boundary) do multipart
    init.body = body
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }

  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError(0, 'Não foi possível falar com o servidor do DMaker. Ele está rodando?')
  }

  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!response.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data ? (data as { detail: unknown }).detail : data
    throw new ApiError(
      response.status,
      messageFromDetail(detail, `Erro ${response.status} ao chamar ${path}`),
      data,
    )
  }
  return data as T
}

/** POST que devolve um arquivo (imagem): o erro sai igual ao das outras chamadas, a resposta boa vem como `Blob`. */
async function postForBlob(path: string, body: unknown): Promise<Blob> {
  let response: Response
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Não foi possível falar com o servidor do DMaker. Ele está rodando?')
  }
  if (!response.ok) {
    let data: unknown
    try {
      data = JSON.parse(await response.text())
    } catch {
      data = null
    }
    const detail =
      data && typeof data === 'object' && 'detail' in data ? (data as { detail: unknown }).detail : data
    throw new ApiError(
      response.status,
      messageFromDetail(detail, `Erro ${response.status} ao chamar ${path}`),
      data,
    )
  }
  return response.blob()
}

export const http = {
  postBlob: postForBlob,
  /** Envio de arquivo (multipart): clonar voz, roteiro da fila e arquivo da aba Voz. */
  postForm: <T>(path: string, form: FormData) => request<T>('POST', path, form),
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  delete: <T>(path: string) => request<T>('DELETE', path),
}

export type QueryValue = string | number | boolean | null | undefined

/** Acrescenta `?a=1&b=2` ao caminho, pulando o que não tem valor, para os clientes não montarem query na mão. */
export function withQuery(path: string, params: Record<string, QueryValue>): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
  }
  return parts.length ? `${path}?${parts.join('&')}` : path
}

/** Mensagem para mostrar ao usuário a partir de qualquer coisa lançada. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
