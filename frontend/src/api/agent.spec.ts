import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test/fetch'
import { agentApi } from './agent'

afterEach(() => vi.unstubAllGlobals())

describe('cliente do agente', () => {
  it('lê o estado do servidor do modelo e o catálogo de modelos', async () => {
    const fetch = stubFetch({})
    await agentApi.status()
    expect(fetch.last()).toMatchObject({ url: '/api/agent/status', method: 'GET' })
    await agentApi.models()
    expect(fetch.last()).toMatchObject({ url: '/api/agent/models', method: 'GET' })
  })

  it('lista as conversas e devolve só a lista', async () => {
    const fetch = stubFetch({ conversations: [{ id: 'c1' }] })
    expect(await agentApi.conversations.list()).toEqual([{ id: 'c1' }])
    expect(fetch.last()).toMatchObject({ url: '/api/agent/conversations', method: 'GET' })
  })

  it('cria, abre, renomeia, para e apaga uma conversa pelo id codificado', async () => {
    const fetch = stubFetch({})
    await agentApi.conversations.create({ mode: 'free', model: 'gpt-oss:20b', effort: 'low' })
    expect(fetch.last()).toMatchObject({
      url: '/api/agent/conversations',
      method: 'POST',
      body: { mode: 'free', model: 'gpt-oss:20b', effort: 'low' },
    })
    await agentApi.conversations.get('a b')
    expect(fetch.last()).toMatchObject({ url: '/api/agent/conversations/a%20b', method: 'GET' })
    await agentApi.conversations.update('c1', { title: 'Novo nome' })
    expect(fetch.last()).toMatchObject({ url: '/api/agent/conversations/c1', method: 'PATCH', body: { title: 'Novo nome' } })
    await agentApi.conversations.stop('c1')
    expect(fetch.last()).toMatchObject({ url: '/api/agent/conversations/c1/stop', method: 'POST' })
    await agentApi.conversations.remove('c1')
    expect(fetch.last()).toMatchObject({ url: '/api/agent/conversations/c1', method: 'DELETE' })
  })

  it('o esforço nulo vai no corpo para voltar ao padrão do modelo', async () => {
    const fetch = stubFetch({})
    await agentApi.conversations.update('c1', { effort: null })
    expect(fetch.last().body).toEqual({ effort: null })
  })

  it('manda a mensagem com o modelo e o esforço escolhidos', async () => {
    const fetch = stubFetch({ job_id: 'j1', conversation_id: 'c1' })
    await agentApi.send({ message: 'oi', conversation_id: null, mode: 'operate', model: 'gpt-oss:20b', effort: 'high' })
    expect(fetch.last()).toMatchObject({
      url: '/api/agent/messages',
      method: 'POST',
      body: { message: 'oi', conversation_id: null, mode: 'operate', model: 'gpt-oss:20b', effort: 'high' },
    })
  })

  it('responde à confirmação com o id da conversa na query', async () => {
    const fetch = stubFetch({ approved: true })
    await agentApi.confirm('c 1', 'cf1', true)
    expect(fetch.last()).toMatchObject({
      url: '/api/agent/confirmations/cf1?conversation_id=c%201',
      method: 'POST',
      body: { approve: true },
    })
  })
})
