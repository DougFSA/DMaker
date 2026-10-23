import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, http, messageFromDetail } from './http'

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(body === undefined ? '' : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => vi.unstubAllGlobals())

describe('http', () => {
  it('devolve o JSON de uma resposta ok', async () => {
    stubFetch(200, [{ name: 'a' }])
    expect(await http.get('/api/projects')).toEqual([{ name: 'a' }])
  })

  it('manda o corpo como JSON nos POST', async () => {
    const fetchMock = stubFetch(200, { job_id: 'x' })
    await http.post('/api/projects/a/render', { preview: true })
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"preview":true}')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
  })

  it('usa o detail em texto como mensagem do ApiError', async () => {
    stubFetch(404, { detail: 'Spec não encontrada' })
    const error = await http.get('/api/projects/x').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, message: 'Spec não encontrada' })
  })

  it('junta a lista de erros de validação do Pydantic', async () => {
    stubFetch(422, { detail: [{ loc: 'timeline.0.type', msg: 'campo inválido' }, { msg: 'outro erro' }] })
    const error = await http.post('/api/x').catch((e: unknown) => e)
    expect((error as ApiError).message).toBe('timeline.0.type: campo inválido\noutro erro')
  })

  it('explica quando o servidor não responde', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const error = await http.get('/api/state').catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 0 })
    expect((error as ApiError).message).toContain('servidor do DMaker')
  })

  it('cai numa mensagem genérica quando não há detail', () => {
    expect(messageFromDetail(undefined, 'Erro 500')).toBe('Erro 500')
  })
})
