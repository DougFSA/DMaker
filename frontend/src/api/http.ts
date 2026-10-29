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

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

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
  if (body !== undefined) {
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
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  delete: <T>(path: string) => request<T>('DELETE', path),
}

/** Mensagem para mostrar ao usuário a partir de qualquer coisa lançada. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
