import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TranscriptEntry } from '@/api'
import type { StreamEvent, ToolItem } from '@/lib/agent'
import { detail, GPT_OSS, MODELS, MODELS_WITH_GEMMA, QWEN, STATUS, stubAgentServer, type AgentServer } from '@/test/agentServer'
import { FakeEventSource } from '@/test/fetch'
import { reply } from '@/test/routedFetch'
import { OPEN_CONVERSATION_KEY, useAgentStore } from './agent'
import { useToastsStore } from './toasts'

const SAVED_TURN: TranscriptEntry[] = [
  { kind: 'user', id: 'e1', text: 'Valida o projeto meu-video', at: '2026-10-30T12:00:00.000+00:00' },
  { kind: 'answer', id: 'e2', text: 'Está válido.', interrupted: false },
]

let server: AgentServer

function stubServer(extra: Record<string, unknown> = {}): void {
  server = stubAgentServer(extra, server?.state.conversations ?? [])
}

function sse(): FakeEventSource {
  return FakeEventSource.latest()
}

function emit(event: StreamEvent): void {
  sse().emit(event)
}

const END_DONE: StreamEvent = { kind: 'end', t: 9, status: 'done', error: null, result: {} }

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  server = stubAgentServer()
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('abrir a tela', () => {
  it('lê o servidor do modelo, os modelos e as conversas, e começa numa conversa nova', async () => {
    server.state.conversations = [detail()]
    const agent = useAgentStore()
    await agent.init()

    expect(agent.status?.model).toBe('gpt-oss:20b')
    expect(agent.models?.models.map((model) => model.name)).toEqual(['gpt-oss:20b', 'qwen3:30b-a3b'])
    expect(agent.conversations.map((item) => item.id)).toEqual(['c1'])
    expect(agent.detail).toBeNull()
    expect(agent.modelName).toBe('gpt-oss:20b')
    expect(agent.mode).toBe('operate')
    expect(agent.ready).toBe(true)
  })

  it('volta à conversa que estava aberta e desenha a transcrição salva', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server.state.conversations = [detail({ transcript: SAVED_TURN })]
    const agent = useAgentStore()
    await agent.init()

    expect(agent.conversationId).toBe('c1')
    expect(agent.items.map((item) => item.kind)).toEqual(['user', 'answer'])
    expect(agent.busy).toBe(false)
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('a conversa lembrada que já não existe é esquecida e a tela fica na conversa nova', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    const agent = useAgentStore()
    await agent.init()

    expect(agent.detail).toBeNull()
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBeNull()
  })

  it('recarregar no meio de um turno segue o job e não duplica o que já estava salvo', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server.state.conversations = [
      detail({
        running: true,
        running_job_id: 'j7',
        transcript: [
          { kind: 'user', id: 'e1', text: 'Valida o projeto meu-video', at: '2026-10-30T12:00:00.000+00:00' },
          { kind: 'kits', id: 'e2', kits: ['editing'], method: 'keywords' },
          { kind: 'tool', id: 'e3', name: 'validate_project', arguments: {}, state: 'running', detail: '', result: '' },
        ],
      }),
    ]
    const agent = useAgentStore()
    await agent.init()

    expect(agent.busy).toBe(true)
    expect(agent.jobId).toBe('j7')
    expect(agent.items.map((item) => item.kind)).toEqual(['user'])
    expect(sse().url).toBe('/api/jobs/j7/events')

    // o servidor reenvia o turno desde o começo
    emit({ kind: 'start', t: 0, description: 'agente' })
    emit({ kind: 'triage', t: 1, kits: ['editing'], method: 'keywords' })
    emit({ kind: 'tool_call', t: 2, name: 'validate_project', arguments: {} })
    expect(agent.items.map((item) => item.kind)).toEqual(['user', 'kits', 'tool'])

    emit({ kind: 'tool_result', t: 3, name: 'validate_project', result: 'ok' })
    emit({ kind: 'answer', t: 4, text: 'Está válido.' })
    emit(END_DONE)
    await flushPromises()
    expect(agent.items.map((item) => item.kind)).toEqual(['user', 'kits', 'tool', 'answer'])
    expect(agent.busy).toBe(false)
  })
})

describe('mandar mensagem', () => {
  it('a conversa nova nasce com o modo, o modelo e o esforço escolhidos e passa a ser a aberta', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.setMode('free')
    await agent.setModel('gpt-oss:20b')
    await agent.setEffort('high')

    expect(await agent.send('  Me explica o que é LUFS  ')).toBe(true)

    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({
      message: 'Me explica o que é LUFS',
      mode: 'free',
      model: 'gpt-oss:20b',
      effort: 'high',
    })
    expect(agent.conversationId).toBe('c1')
    expect(agent.detail).toMatchObject({ mode: 'free', model: 'gpt-oss:20b', effort: 'high', mode_locked: true })
    expect(agent.modeLocked).toBe(true)
    expect(agent.conversations[0]?.id).toBe('c1')
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBe('c1')
    expect(agent.busy).toBe(true)
    expect(agent.items.map((item) => item.kind)).toEqual(['user'])
    expect(sse().url).toBe('/api/jobs/j1/events')
  })

  it('a conversa nova sem esforço escolhido não manda a chave effort', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')

    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({ message: 'oi', mode: 'operate', model: 'gpt-oss:20b' })
  })

  it('a segunda mensagem continua a mesma conversa, sem repetir o modo', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')
    emit(END_DONE)
    await flushPromises()
    await agent.send('e agora?')

    expect(server.to('POST /api/agent/messages')[1]?.body).toEqual({ message: 'e agora?', conversation_id: 'c1' })
  })

  it('não manda mensagem vazia nem uma nova enquanto o agente responde', async () => {
    const agent = useAgentStore()
    await agent.init()
    expect(await agent.send('   ')).toBe(false)
    await agent.send('primeira')

    expect(await agent.send('segunda')).toBe(false)
    expect(server.to('POST /api/agent/messages')).toHaveLength(1)
  })

  it('um erro do servidor ao enviar aparece na tela e não deixa o agente ocupado', async () => {
    stubServer({ 'POST /api/agent/messages': reply(503, { detail: 'O modelo local não está respondendo.' }) })
    const agent = useAgentStore()
    await agent.init()

    expect(await agent.send('oi')).toBe(false)
    expect(agent.error).toBe('O modelo local não está respondendo.')
    expect(agent.busy).toBe(false)
    expect(agent.items).toEqual([])
    expect(agent.detail).toBeNull()
  })

  it('o fim do turno atualiza a lista, o resumo da conversa e os modelos', async () => {
    const agent = useAgentStore()
    await agent.init()
    server.state.conversations = [detail({ title: 'Me explica o que é LUFS', messages: 1 })]
    await agent.send('Me explica o que é LUFS')
    await flushPromises()
    const before = server.calls.length
    emit(END_DONE)
    await flushPromises()

    const after = server.calls.slice(before).map((call) => `${call.method} ${call.path}`)
    expect(after).toEqual(expect.arrayContaining(['GET /api/agent/conversations', 'GET /api/agent/conversations/c1', 'GET /api/agent/models']))
    expect(agent.conversations[0]?.title).toBe('Me explica o que é LUFS')
  })
})

describe('a resposta ao vivo', () => {
  it('a etapa muda conforme o servidor informa, e a resposta cresce com os trechos', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')

    emit({ kind: 'start', t: 0, description: 'agente' })
    emit({ kind: 'status', t: 1, stage: 'loading_model', label: 'Carregando o modelo' })
    expect(agent.stage).toMatchObject({ stage: 'loading_model', label: 'Carregando o modelo' })
    emit({ kind: 'status', t: 2, stage: 'writing', label: 'Escrevendo a resposta' })
    emit({ kind: 'thinking_delta', t: 3, text: 'O usuário cumprimenta.' })
    emit({ kind: 'answer_delta', t: 4, text: 'Olá' })
    emit({ kind: 'answer_delta', t: 5, text: ', tudo bem?' })

    expect(agent.stage?.label).toBe('Escrevendo a resposta')
    expect(agent.items.map((item) => item.kind)).toEqual(['user', 'thinking', 'answer'])
    expect(agent.items[2]).toMatchObject({ text: 'Olá, tudo bem?', streaming: true })

    emit({ kind: 'thinking', t: 6, text: 'O usuário cumprimenta.' })
    emit({ kind: 'answer', t: 7, text: 'Olá, tudo bem?' })
    emit(END_DONE)
    await flushPromises()

    expect(agent.items[2]).toMatchObject({ text: 'Olá, tudo bem?', streaming: false })
    expect(agent.stage).toBeNull()
    expect(agent.busy).toBe(false)
  })

  it('conta a conversa ao vivo: kit, ferramenta com resultado e resposta', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('Valida o projeto meu-video')
    emit({ kind: 'triage', t: 1, kits: ['editing'], method: 'keywords' })
    emit({ kind: 'tool_call', t: 2, name: 'validate_project', arguments: { name_or_path: 'meu-video' } })
    emit({ kind: 'tool_result', t: 3, name: 'validate_project', result: '{"name": "meu-video"}' })
    emit({ kind: 'answer', t: 4, text: 'O projeto está válido.' })
    emit(END_DONE)
    await flushPromises()

    expect(agent.items.map((item) => item.kind)).toEqual(['user', 'kits', 'tool', 'answer'])
    expect((agent.items[2] as ToolItem).state).toBe('done')
    expect(agent.busy).toBe(false)
  })

  it('a confirmação espera o clique e o clique vai para o servidor', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('renderiza o x')
    emit({ kind: 'confirmation_request', t: 1, id: 'cf1', tool: 'render_project', question: 'Posso gerar o vídeo final?', type: 'action' })
    expect(agent.waitingForYou?.confirmationId).toBe('cf1')

    await agent.answerConfirmation('cf1', true)
    emit({ kind: 'confirmation_answered', t: 2, id: 'cf1', approved: true })

    const posted = server.to('POST /api/agent/confirmations/cf1')[0]!
    expect(posted.url).toBe('/api/agent/confirmations/cf1?conversation_id=c1')
    expect(posted.body).toEqual({ approve: true })
    expect(agent.waitingForYou).toBeNull()
  })

  it('perder a conexão de vez no meio da resposta libera a tela com um aviso', async () => {
    vi.useFakeTimers()
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')
    for (let attempt = 0; attempt < 8 && agent.busy; attempt += 1) {
      sse().fail()
      await vi.advanceTimersByTimeAsync(11_000)
    }

    expect(agent.busy).toBe(false)
    expect(agent.error).toContain('Perdi a conexão')
  })
})

describe('Parar', () => {
  it('pede a parada pela conversa, mostra "parando" e espera o fim do turno', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('Escreve um poema longo')
    emit({ kind: 'answer_delta', t: 1, text: 'O cinema,' })

    await agent.stop()

    expect(server.to('POST /api/agent/conversations/c1/stop')).toHaveLength(1)
    expect(agent.stopping).toBe(true)
    expect(agent.busy).toBe(true)

    emit({ kind: 'answer', t: 2, text: 'O cinema,', interrupted: true })
    emit({ kind: 'end', t: 3, status: 'cancelled', error: null, result: { answer: 'O cinema,', interrupted: true } })
    await flushPromises()

    expect(agent.busy).toBe(false)
    expect(agent.stopping).toBe(false)
    expect(agent.error).toBe('')
    expect(agent.items.map((item) => item.kind)).toEqual(['user', 'answer'])
    expect(agent.items[1]).toMatchObject({ text: 'O cinema,', interrupted: true, streaming: false })
  })

  it('depois de parar, a mensagem seguinte funciona', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('Escreve um poema longo')
    await agent.stop()
    emit({ kind: 'end', t: 3, status: 'cancelled', error: null, result: { answer: '', interrupted: true } })
    await flushPromises()

    expect(await agent.send('Deixa pra lá. Quanto é 2 + 2?')).toBe(true)
    expect(server.to('POST /api/agent/messages')[1]?.body).toEqual({ message: 'Deixa pra lá. Quanto é 2 + 2?', conversation_id: 'c1' })
  })

  it('se a resposta acabou entre o clique e a chamada, o 409 não vira erro', async () => {
    stubServer({ 'POST /api/agent/conversations/c1/stop': reply(409, { detail: 'Não há resposta em andamento para parar.' }) })
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')
    await agent.stop()

    expect(agent.error).toBe('')
  })

  it('parar de novo enquanto já está parando não repete o pedido', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')
    await agent.stop()
    await agent.stop()

    expect(server.to('POST /api/agent/conversations/c1/stop')).toHaveLength(1)
  })

  it('sem resposta em andamento, parar não faz nada', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.stop()

    expect(server.to('POST /api/agent/conversations/c1/stop')).toHaveLength(0)
  })
})

describe('conversa nova', () => {
  it('com a aberta ainda vazia, reaproveita a aberta e não cria outra', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server.state.conversations = [detail({ messages: 0, mode_locked: false, title: 'Nova conversa', transcript: [] })]
    const agent = useAgentStore()
    await agent.init()

    agent.startNew()

    expect(agent.conversationId).toBe('c1')
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBe('c1')
    expect(server.calls.filter((call) => call.method !== 'GET')).toEqual([])
  })

  it('com a aberta já usada, volta à conversa nova, esquece a lembrada e começa do padrão', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server.state.conversations = [detail({ transcript: SAVED_TURN, mode: 'free', model: 'qwen3:30b-a3b', effort: 'on' })]
    const agent = useAgentStore()
    await agent.init()

    agent.startNew()

    expect(agent.detail).toBeNull()
    expect(agent.items).toEqual([])
    expect(agent.mode).toBe('operate')
    expect(agent.modelName).toBe('gpt-oss:20b')
    expect(agent.effort).toBeNull()
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBeNull()
    expect(server.calls.filter((call) => call.method !== 'GET')).toEqual([])
  })

  it('largar uma conversa que está respondendo não a para: ela continua no servidor', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')
    const source = sse()

    agent.startNew()

    expect(agent.busy).toBe(false)
    expect(agent.items).toEqual([])
    expect(server.to('POST /api/agent/conversations/c1/stop')).toHaveLength(0)
    source.emit({ kind: 'answer', t: 1, text: 'tarde demais' }) // o que chega depois de largar a conversa não aparece
    expect(agent.items).toEqual([])
  })

  it('abrir outra conversa troca a tela e esquece o turno da anterior', async () => {
    server.state.conversations = [detail({ transcript: SAVED_TURN })]
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')
    expect(agent.busy).toBe(true)

    await agent.open('c1')

    expect(agent.busy).toBe(false)
    expect(agent.items.map((item) => item.kind)).toEqual(['user', 'answer'])
  })
})

describe('renomear e apagar', () => {
  it('renomeia pelo servidor e atualiza a lista e a conversa aberta', async () => {
    server.state.conversations = [detail()]
    stubServer({
      'PATCH /api/agent/conversations/c1': (call: { body: unknown }) => ({ ...detail(), title: (call.body as { title: string }).title }),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    expect(await agent.rename('c1', '  Roteiro do reel  ')).toBe(true)

    expect(server.to('PATCH /api/agent/conversations/c1')[0]?.body).toEqual({ title: 'Roteiro do reel' })
    expect(agent.conversations[0]?.title).toBe('Roteiro do reel')
    expect(agent.detail?.title).toBe('Roteiro do reel')
  })

  it('um nome vazio não vai ao servidor', async () => {
    const agent = useAgentStore()
    await agent.init()

    expect(await agent.rename('c1', '   ')).toBe(false)
    expect(server.to('PATCH /api/agent/conversations/c1')).toHaveLength(0)
  })

  it('o erro ao renomear vira um aviso na tela', async () => {
    server.state.conversations = [detail()]
    stubServer({ 'PATCH /api/agent/conversations/c1': reply(422, { detail: 'O título não pode passar de 120 caracteres.' }) })
    const agent = useAgentStore()
    await agent.init()

    expect(await agent.rename('c1', 'x')).toBe(false)
    expect(useToastsStore().items[0]).toMatchObject({ tone: 'error', description: 'O título não pode passar de 120 caracteres.' })
  })

  it('apagar a conversa aberta tira da lista, esquece a lembrada e volta à conversa nova', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    server.state.conversations = [detail({ transcript: SAVED_TURN })]
    stubServer({ 'DELETE /api/agent/conversations/c1': { deleted: 'c1' } })
    const agent = useAgentStore()
    await agent.init()

    expect(await agent.remove('c1')).toBe(true)

    expect(server.to('DELETE /api/agent/conversations/c1')).toHaveLength(1)
    expect(agent.conversations).toEqual([])
    expect(agent.detail).toBeNull()
    expect(agent.items).toEqual([])
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBeNull()
  })

  it('apagar outra conversa não mexe na aberta', async () => {
    server.state.conversations = [detail(), detail({ id: 'c2', title: 'Outra' })]
    stubServer({ 'DELETE /api/agent/conversations/c2': { deleted: 'c2' } })
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.remove('c2')

    expect(agent.conversations.map((item) => item.id)).toEqual(['c1'])
    expect(agent.conversationId).toBe('c1')
  })

  it('a conversa que ainda responde não é apagada, e o servidor explica por quê', async () => {
    server.state.conversations = [detail()]
    stubServer({
      'DELETE /api/agent/conversations/c1': reply(409, { detail: 'Pare a resposta do agente antes de apagar a conversa.' }),
    })
    const agent = useAgentStore()
    await agent.init()

    expect(await agent.remove('c1')).toBe(false)
    expect(agent.conversations).toHaveLength(1)
    expect(useToastsStore().items[0]?.description).toBe('Pare a resposta do agente antes de apagar a conversa.')
  })
})

describe('modo, modelo e esforço', () => {
  it('na conversa nova, a escolha fica no rascunho e só vai ao servidor com a primeira mensagem', async () => {
    const agent = useAgentStore()
    await agent.init()

    await agent.setMode('free')
    await agent.setModel('qwen3:30b-a3b')
    await agent.setEffort('off')

    expect(agent.mode).toBe('free')
    expect(agent.modelName).toBe('qwen3:30b-a3b')
    expect(agent.effort).toBe('off')
    expect(server.calls.filter((call) => call.method === 'PATCH')).toEqual([])
  })

  it('trocar o modelo do rascunho limpa o esforço que o modelo novo não tem', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.setEffort('high')

    await agent.setModel('qwen3:30b-a3b')

    expect(agent.effort).toBeNull()
  })

  it('na conversa salva, grava o modelo no servidor e mostra o esforço que ele ajustou', async () => {
    server.state.conversations = [detail({ effort: 'high' })]
    stubServer({
      'PATCH /api/agent/conversations/c1': () => detail({ model: 'qwen3:30b-a3b', effort: null }), // o servidor limpou o esforço
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.setModel('qwen3:30b-a3b')

    expect(server.to('PATCH /api/agent/conversations/c1')[0]?.body).toEqual({ model: 'qwen3:30b-a3b' })
    expect(agent.modelName).toBe('qwen3:30b-a3b')
    expect(agent.effort).toBeNull()
    expect(agent.conversations[0]).toMatchObject({ model: 'qwen3:30b-a3b', effort: null })
  })

  it('o esforço escolhido vai ao servidor, e voltar ao padrão manda null', async () => {
    server.state.conversations = [detail()]
    stubServer({
      'PATCH /api/agent/conversations/c1': (call: { body: unknown }) => detail({ effort: (call.body as { effort: string | null }).effort }),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.setEffort('low')
    expect(server.to('PATCH /api/agent/conversations/c1')[0]?.body).toEqual({ effort: 'low' })
    expect(agent.effort).toBe('low')

    await agent.setEffort(null)
    expect(server.to('PATCH /api/agent/conversations/c1')[1]?.body).toEqual({ effort: null })
    expect(agent.effort).toBeNull()
  })

  it('se o servidor recusa a troca, a tela volta ao que estava e diz por quê', async () => {
    server.state.conversations = [detail({ effort: 'low' })]
    stubServer({ 'PATCH /api/agent/conversations/c1': reply(422, { detail: "O modelo qwen3:30b-a3b não tem o esforço 'low'." }) })
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.setModel('qwen3:30b-a3b')

    expect(agent.modelName).toBe('gpt-oss:20b')
    expect(agent.effort).toBe('low')
    expect(agent.error).toContain('não tem o esforço')
  })

  it('o modo trava depois da primeira mensagem e a troca é ignorada', async () => {
    server.state.conversations = [detail({ mode_locked: true })]
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.setMode('free')

    expect(agent.modeLocked).toBe(true)
    expect(agent.mode).toBe('operate')
    expect(server.to('PATCH /api/agent/conversations/c1')).toHaveLength(0)
  })

  it('numa conversa salva ainda vazia, o modo ainda pode mudar', async () => {
    server.state.conversations = [detail({ messages: 0, mode_locked: false })]
    stubServer({ 'PATCH /api/agent/conversations/c1': () => detail({ messages: 0, mode_locked: false, mode: 'free' }) })
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.setMode('free')

    expect(server.to('PATCH /api/agent/conversations/c1')[0]?.body).toEqual({ mode: 'free' })
    expect(agent.mode).toBe('free')
  })

  it('o modelo não muda no meio da resposta', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')

    await agent.setModel('qwen3:30b-a3b')

    expect(agent.modelName).toBe('gpt-oss:20b')
    expect(server.to('PATCH /api/agent/conversations/c1')).toHaveLength(0)
  })
})

describe('prontidão e memória', () => {
  it('o modelo que não está na lista de instalados não deixa enviar e diz o que fazer', async () => {
    stubServer({ 'GET /api/agent/models': { ...MODELS, models: [QWEN] } })
    const agent = useAgentStore()
    await agent.init()

    expect(agent.ready).toBe(false)
    expect(agent.problem).toContain("O modelo 'gpt-oss:20b' não está instalado")
    expect(agent.problem).toContain('dmaker doctor --offline')
  })

  it('com o servidor do modelo parado, não está pronto e o aviso diz onde abrir', async () => {
    stubServer({ 'GET /api/agent/status': { ...STATUS, reachable: false, model_installed: false }, 'GET /api/agent/models': reply(503, { detail: 'fora do ar' }) })
    const agent = useAgentStore()
    await agent.init()

    expect(agent.ready).toBe(false)
    expect(agent.problem).toBe('O modelo local não está respondendo em http://127.0.0.1:11434. Abra o Ollama.')
  })

  it('sem a lista de modelos, vale o que o status disse do modelo padrão', async () => {
    stubServer({ 'GET /api/agent/models': reply(503, { detail: 'fora do ar' }) })
    const agent = useAgentStore()
    await agent.init()

    expect(agent.models).toBeNull()
    expect(agent.ready).toBe(true)
  })

  it('antes de o servidor responder, a tela não reclama de nada', async () => {
    const agent = useAgentStore()

    expect(agent.status).toBeNull()
    expect(agent.problem).toBe('')

    await agent.loadStatus()
    expect(agent.problem).toBe('')
  })

  it('um erro ao ler o status vira mensagem e deixa o status vazio', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('fora do ar')))
    const agent = useAgentStore()
    await agent.loadStatus()

    expect(agent.status).toBeNull()
    expect(agent.error).toContain('Não foi possível falar com o servidor')
    expect(agent.problem).toContain('Não foi possível falar com o servidor')
  })

  it('o modelo que não cabe na memória pede confirmação; o apertado só avisa', async () => {
    stubServer({ 'GET /api/agent/models': { ...MODELS, models: [{ ...GPT_OSS, fit: 'tight' }, QWEN] } })
    const agent = useAgentStore()
    await agent.init()

    expect(agent.memoryWarning?.tone).toBe('warning')
    expect(agent.confirmsMemory).toBe(false)

    await agent.setModel('qwen3:30b-a3b')
    expect(agent.memoryWarning?.tone).toBe('error')
    expect(agent.confirmsMemory).toBe(true)
  })

  it('se a lista de modelos falha depois de já ter vindo, a anterior continua na tela', async () => {
    const agent = useAgentStore()
    await agent.init()
    server.set('GET /api/agent/models', reply(503, { detail: 'ocupado' }))

    await agent.loadModels()

    expect(agent.models?.models).toHaveLength(2)
  })
})

describe('modelo sem ferramentas', () => {
  it('na conversa nova, escolher Operar com um modelo sem ferramentas avisa e não deixa enviar', async () => {
    server = stubAgentServer({ 'GET /api/agent/models': MODELS_WITH_GEMMA })
    const agent = useAgentStore()
    await agent.init()
    await agent.setMode('free')
    await agent.setModel('gemma3:4b')

    expect(agent.toolsProblem).toBe('')
    expect(agent.canSend).toBe(true)

    await agent.setMode('operate')

    expect(agent.toolsProblem).toContain('O modelo gemma3:4b não usa ferramentas')
    expect(agent.canSend).toBe(false)
    expect(agent.ready).toBe(true)
  })

  it('voltar a um modelo com ferramentas libera o envio', async () => {
    server = stubAgentServer({ 'GET /api/agent/models': MODELS_WITH_GEMMA })
    const agent = useAgentStore()
    await agent.init()
    await agent.setMode('free')
    await agent.setModel('gemma3:4b')
    await agent.setMode('operate')
    expect(agent.canSend).toBe(false)

    await agent.setModel('gpt-oss:20b')

    expect(agent.canSend).toBe(true)
  })

  it('se o servidor recusar mesmo assim (422), o detalhe vira o erro da mensagem e nada fica ocupado', async () => {
    const detailText =
      'O modelo gemma3:4b não usa ferramentas. Para operar o DMaker, escolha um modelo com ferramentas; para conversar com ele, use a Conversa livre.'
    server = stubAgentServer({ 'POST /api/agent/messages': reply(422, { detail: detailText }) })
    const agent = useAgentStore()
    await agent.init()

    expect(await agent.send('Corta as pausas deste vídeo')).toBe(false)

    expect(agent.error).toBe(detailText)
    expect(agent.busy).toBe(false)
    expect(agent.items).toEqual([])
    expect(agent.detail).toBeNull()
  })
})
