import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentStatus } from '@/api'
import type { StreamEvent, ToolItem } from '@/lib/agent'
import { useAgentStore } from './agent'

/** EventSource de mentira: o teste empurra os eventos que o servidor mandaria. */
class FakeEventSource {
  static instances: FakeEventSource[] = []
  static readonly CLOSED = 2
  readonly url: string
  readyState = 1
  closed = false
  onmessage: ((message: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close(): void {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }

  emit(event: StreamEvent): void {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>)
  }
}

const STATUS: AgentStatus = {
  engine: 'ollama',
  engine_label: 'Ollama',
  model: 'gpt-oss:20b',
  url: 'http://127.0.0.1:11434',
  free_html: false,
  reachable: true,
  model_installed: true,
  kits: [{ name: 'editing', title: 'Edição e render', description: 'Editar.', tools: 18 }],
}

interface Call {
  method: string
  url: string
  body: unknown
}
let calls: Call[]

function stubServer(overrides: { status?: unknown; send?: () => Response } = {}): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }))
      if (url === '/api/agent/status') return json(overrides.status ?? STATUS)
      if (url === '/api/agent/messages') {
        return overrides.send ? Promise.resolve(overrides.send()) : json({ job_id: 'j1', conversation_id: 'c1' })
      }
      if (url.startsWith('/api/agent/confirmations/')) return json({ approved: true })
      if (url.startsWith('/api/agent/conversations/')) return json({ reset: 'c1' })
      return json({ detail: 'nada' }, 404)
    }),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  stubServer()
})
afterEach(() => vi.unstubAllGlobals())

describe('useAgentStore', () => {
  it('lê o motor, o modelo e se tudo está pronto para conversar', async () => {
    const agent = useAgentStore()
    await agent.loadStatus()

    expect(agent.status?.model).toBe('gpt-oss:20b')
    expect(agent.ready).toBe(true)
  })

  it('com o servidor do modelo parado, não está pronto', async () => {
    stubServer({ status: { ...STATUS, reachable: false, model_installed: false } })
    const agent = useAgentStore()
    await agent.loadStatus()

    expect(agent.ready).toBe(false)
  })

  it('um erro ao ler o status vira mensagem e deixa o status vazio', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('fora do ar')))
    const agent = useAgentStore()
    await agent.loadStatus()

    expect(agent.status).toBeNull()
    expect(agent.error).toContain('Não foi possível falar com o servidor')
  })

  it('envia a mensagem, segue o job pelo SSE e mostra a conversa ao vivo', async () => {
    const agent = useAgentStore()
    expect(await agent.send('  Valida o projeto meu-video  ')).toBe(true)

    expect(calls.find((call) => call.url === '/api/agent/messages')?.body).toEqual({
      message: 'Valida o projeto meu-video',
      conversation_id: null,
    })
    expect(agent.busy).toBe(true)
    expect(agent.conversationId).toBe('c1')
    const source = FakeEventSource.instances[0]!
    expect(source.url).toBe('/api/jobs/j1/events')

    source.emit({ kind: 'start', t: 0, description: 'agente' })
    source.emit({ kind: 'triage', t: 1, kits: ['editing'], method: 'keywords' })
    source.emit({ kind: 'tool_call', t: 2, name: 'validate_project', arguments: { name_or_path: 'meu-video' } })
    source.emit({ kind: 'tool_result', t: 3, name: 'validate_project', result: '{"name": "meu-video"}' })
    source.emit({ kind: 'answer', t: 4, text: 'O projeto está válido.' })
    source.emit({ kind: 'end', t: 5, status: 'done', error: null, result: {} })

    expect(agent.items.map((item) => item.kind)).toEqual(['user', 'kits', 'tool', 'answer'])
    expect((agent.items[2] as ToolItem).state).toBe('done')
    expect(agent.busy).toBe(false)
    expect(source.closed).toBe(true)
  })

  it('a segunda mensagem continua a mesma conversa', async () => {
    const agent = useAgentStore()
    await agent.send('oi')
    FakeEventSource.instances[0]!.emit({ kind: 'end', t: 1, status: 'done', error: null, result: {} })
    await agent.send('e agora?')

    const bodies = calls.filter((call) => call.url === '/api/agent/messages').map((call) => call.body)
    expect(bodies[1]).toEqual({ message: 'e agora?', conversation_id: 'c1' })
  })

  it('não manda mensagem vazia nem uma nova enquanto o agente responde', async () => {
    const agent = useAgentStore()
    expect(await agent.send('   ')).toBe(false)
    await agent.send('primeira')

    expect(await agent.send('segunda')).toBe(false)
    expect(calls.filter((call) => call.url === '/api/agent/messages')).toHaveLength(1)
  })

  it('um erro do servidor ao enviar aparece na tela e não deixa o agente ocupado', async () => {
    stubServer({
      send: () => new Response(JSON.stringify({ detail: 'O modelo local não está respondendo.' }), { status: 503 }),
    })
    const agent = useAgentStore()

    expect(await agent.send('oi')).toBe(false)
    expect(agent.error).toBe('O modelo local não está respondendo.')
    expect(agent.busy).toBe(false)
    expect(agent.items).toEqual([])
  })

  it('a confirmação espera o clique e o clique vai para o servidor', async () => {
    const agent = useAgentStore()
    await agent.send('renderiza o x')
    const source = FakeEventSource.instances[0]!
    source.emit({
      kind: 'confirmation_request',
      t: 1,
      id: 'cf1',
      tool: 'render_project',
      question: 'Posso gerar o vídeo final?',
      type: 'action',
    })
    expect(agent.waitingForYou?.confirmationId).toBe('cf1')

    await agent.answerConfirmation('cf1', true)
    source.emit({ kind: 'confirmation_answered', t: 2, id: 'cf1', approved: true })

    const posted = calls.find((call) => call.url.startsWith('/api/agent/confirmations/'))!
    expect(posted.url).toBe('/api/agent/confirmations/cf1?conversation_id=c1')
    expect(posted.body).toEqual({ approve: true })
    expect(agent.waitingForYou).toBeNull()
  })

  it('perder a conexão no meio da resposta libera a tela com um aviso', async () => {
    const agent = useAgentStore()
    await agent.send('oi')
    const source = FakeEventSource.instances[0]!
    source.readyState = FakeEventSource.CLOSED
    source.onerror?.()

    expect(agent.busy).toBe(false)
    expect(agent.error).toContain('Perdi a conexão')
  })

  it('nova conversa limpa a tela e avisa o servidor para esquecer o histórico', async () => {
    const agent = useAgentStore()
    await agent.send('oi')
    FakeEventSource.instances[0]!.emit({ kind: 'end', t: 1, status: 'done', error: null, result: {} })

    await agent.reset()

    expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/agent/conversations/c1')).toBe(true)
    expect(agent.items).toEqual([])
    expect(agent.conversationId).toBeNull()
  })
})
