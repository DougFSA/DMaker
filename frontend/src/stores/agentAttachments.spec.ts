/* Os anexos, as opções avançadas e o modelo carregado da store do agente (o resto da store fica em agent.spec.ts). */
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentConversationDetail } from '@/api'
import type { StreamEvent } from '@/lib/agent'
import {
  deferred,
  detail,
  GEMMA,
  GPT_OSS,
  imageAttachment,
  LOADED,
  mediaAttachment,
  MODELS,
  MODELS_WITH_GEMMA,
  QWEN,
  removes,
  STATUS,
  stubConversationServer,
  textAttachment,
  uploads,
  type AgentServer,
  type Upload,
} from '@/test/agentServer'
import { FakeEventSource } from '@/test/fetch'
import { reply } from '@/test/routedFetch'
import { OPEN_CONVERSATION_KEY, useAgentStore } from './agent'

let server: AgentServer

const file = (name: string, size = 10) => new File(['x'.repeat(size)], name)
const END_DONE: StreamEvent = { kind: 'end', t: 9, status: 'done', error: null, result: {} }

/** O servidor de mentira que guarda a conversa (ver `stubConversationServer`); a tela fala com o último que se montou. */
function stubWithAttachments(extra: Record<string, unknown> = {}, conversations: AgentConversationDetail[] = []): AgentServer {
  server = stubConversationServer(extra, conversations)
  return server
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  stubWithAttachments()
})
afterEach(() => vi.unstubAllGlobals())

describe('anexar no rascunho', () => {
  it('o rascunho vira conversa com o modo, o modelo, o esforço e as opções escolhidos, e só depois sobe o arquivo', async () => {
    stubWithAttachments({ 'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()) })
    const agent = useAgentStore()
    await agent.init()
    await agent.setMode('free')
    await agent.setEffort('high')
    await agent.setOptions({ num_ctx: 8192, seed: 3 })

    await agent.attach([file('roteiro.docx')])

    const posts = server.calls.filter((call) => call.method === 'POST').map((call) => call.path)
    expect(posts).toEqual(['/api/agent/conversations', '/api/agent/conversations/c1/attachments'])
    expect(server.to('POST /api/agent/conversations')[0]?.body).toEqual({
      mode: 'free',
      model: 'gpt-oss:20b',
      effort: 'high',
      options: { num_ctx: 8192, seed: 3 },
    })
    expect(agent.conversationId).toBe('c1')
    expect(agent.modeLocked).toBe(false)
    expect(localStorage.getItem(OPEN_CONVERSATION_KEY)).toBe('c1')
    expect(agent.conversations[0]).toMatchObject({ id: 'c1', messages: 0 })
    expect(agent.attachmentCards.map((card) => [card.name, card.state])).toEqual([['roteiro.docx', 'ready']])
  })

  it('vários arquivos de uma vez criam uma conversa só e sobem na ordem', async () => {
    let next = 0
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment({ id: `a${(next += 1)}`, name: `arquivo${next}.txt` })),
    })
    const agent = useAgentStore()
    await agent.init()

    await agent.attach([file('um.txt'), file('dois.txt'), file('tres.txt')])

    expect(server.to('POST /api/agent/conversations')).toHaveLength(1)
    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(3)
    expect(agent.attachmentCards.map((card) => card.id)).toEqual(['a1', 'a2', 'a3'])
  })

  it('o arquivo sobe como multipart no campo file, com o nome dele', async () => {
    stubWithAttachments({ 'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()) })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('roteiro.docx')])

    const sent = server.to('POST /api/agent/conversations/c1/attachments')[0]!
    expect((sent.form?.get('file') as File).name).toBe('roteiro.docx')
  })

  it('numa conversa que já existe, o anexo vai direto, sem criar outra', async () => {
    stubWithAttachments({ 'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()) }, [
      detail({ messages: 0, mode_locked: false }),
    ])
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.attach([file('roteiro.docx')])

    expect(server.to('POST /api/agent/conversations')).toHaveLength(0)
    expect(agent.pendingCount).toBe(1)
  })

  it('enquanto o arquivo sobe, a ficha mostra o envio e o botão Enviar fica parado', async () => {
    const upload = deferred<Upload>()
    stubWithAttachments({ 'POST /api/agent/conversations/c1/attachments': uploads(() => upload.promise) })
    const agent = useAgentStore()
    await agent.init()

    const attaching = agent.attach([file('aula.mp4')])
    await vi.waitFor(() => expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(1))

    expect(agent.uploading).toBe(true)
    expect(agent.attachmentCards).toMatchObject([{ name: 'aula.mp4', state: 'uploading', kind: 'media' }])
    expect(agent.sendable).toBe(false)
    expect(await agent.send('corta as pausas')).toBe(false)
    expect(server.to('POST /api/agent/messages')).toHaveLength(0)

    upload.resolve(mediaAttachment())
    await attaching
    expect(agent.uploading).toBe(false)
    expect(agent.attachmentCards).toMatchObject([{ name: 'aula.mp4', state: 'ready' }])
    expect(agent.sendable).toBe(true)
  })

  it('o erro do servidor (413, 422) fica na ficha com o detalhe, e a pessoa tira a ficha sem chamar o servidor', async () => {
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() => reply(413, { detail: 'O arquivo passa do limite de 20 MB para imagens.' })),
    })
    const agent = useAgentStore()
    await agent.init()

    await agent.attach([file('grande.png')])

    expect(agent.attachmentCards).toMatchObject([{ name: 'grande.png', state: 'error', error: 'O arquivo passa do limite de 20 MB para imagens.' }])
    expect(agent.sendable).toBe(true) // a ficha com erro não segura o envio

    await agent.removeAttachment(agent.attachmentCards[0]!)
    expect(agent.attachmentCards).toEqual([])
    expect(server.calls.filter((call) => call.method === 'DELETE')).toEqual([])
  })

  it('um arquivo que falha não impede os outros', async () => {
    let calls = 0
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() =>
        (calls += 1) === 1 ? reply(422, { detail: 'Formato desconhecido.' }) : textAttachment({ id: 'a7', name: 'bom.txt' }),
      ),
    })
    const agent = useAgentStore()
    await agent.init()

    await agent.attach([file('ruim.exe'), file('bom.txt')])

    expect(agent.attachmentCards.map((card) => [card.name, card.state])).toEqual([
      ['bom.txt', 'ready'],
      ['ruim.exe', 'error'],
    ])
  })

  it('se a conversa não pode nascer, nenhuma ficha fica e o erro aparece', async () => {
    stubWithAttachments({ 'POST /api/agent/conversations': reply(422, { detail: 'O modelo x não está instalado.' }) })
    const agent = useAgentStore()
    await agent.init()

    await agent.attach([file('a.txt')])

    expect(agent.error).toBe('O modelo x não está instalado.')
    expect(agent.attachmentCards).toEqual([])
    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(0)
  })
})

describe('o que a tela recusa antes do servidor', () => {
  it('mais de 8 anexos: os que passam ficam de fora, com o aviso, e o servidor nem é chamado por eles', async () => {
    let next = 0
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment({ id: `a${(next += 1)}` })),
    })
    const agent = useAgentStore()
    await agent.init()

    await agent.attach(Array.from({ length: 10 }, (_, index) => file(`f${index}.txt`)))

    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(8)
    expect(agent.pendingCount).toBe(8)
    expect(agent.attachNotice).toBe('Uma mensagem leva no máximo 8 anexos. Não anexei: f8.txt, f9.txt.')

    await agent.attach([file('f10.txt')])
    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(8)
    expect(agent.attachNotice).toContain('f10.txt')
  })

  it('vídeo numa Conversa livre é recusado, a conversa nem nasce e o aviso diz que o modo Operar é que trabalha com ele', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.setMode('free')

    await agent.attach([file('aula.mp4')])

    expect(server.to('POST /api/agent/conversations')).toHaveLength(0)
    expect(agent.detail).toBeNull()
    expect(agent.attachNotice).toContain('não é usado')
    expect(agent.attachNotice).toContain('modo Operar o DMaker')
  })

  it('com a resposta em andamento não anexa, e diz por quê', async () => {
    stubWithAttachments({}, [detail({ messages: 0, mode_locked: false })])
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')
    await agent.send('oi')

    await agent.attach([file('a.txt')])

    expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(0)
    expect(agent.attachNotice).toBe('Espere a resposta terminar para anexar arquivos.')
  })

  it('com o servidor do modelo fora do ar não anexa', async () => {
    stubWithAttachments({ 'GET /api/agent/status': { ...STATUS, reachable: false } })
    const agent = useAgentStore()
    await agent.init()

    await agent.attach([file('a.txt')])

    expect(server.to('POST /api/agent/conversations')).toHaveLength(0)
    expect(agent.attachNotice).toContain('não está respondendo')
  })

  it('o modelo escolhido não usa ferramentas no modo Operar: não cria conversa que o servidor recusaria', async () => {
    stubWithAttachments({ 'GET /api/agent/models': MODELS_WITH_GEMMA })
    const agent = useAgentStore()
    await agent.init()
    await agent.setMode('free')
    await agent.setModel('gemma3:4b')
    await agent.setMode('operate')

    await agent.attach([file('a.txt')])

    expect(server.to('POST /api/agent/conversations')).toHaveLength(0)
    expect(agent.attachNotice).toContain('não usa ferramentas')
  })
})

describe('enviar com anexos', () => {
  async function withTwoAttachments(): Promise<ReturnType<typeof useAgentStore>> {
    const made = [textAttachment({ id: 'a1', name: 'roteiro.docx' }), mediaAttachment({ id: 'a3' })]
    let next = 0
    stubWithAttachments({ 'POST /api/agent/conversations/c1/attachments': uploads(() => made[next++]!) })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('roteiro.docx'), file('aula.mp4')])
    return agent
  }

  it('a mensagem leva os ids dos anexos, e a conversa mostra o texto e as fichas como foram enviados', async () => {
    const agent = await withTwoAttachments()

    expect(await agent.send('Corta as pausas deste vídeo')).toBe(true)

    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({
      message: 'Corta as pausas deste vídeo',
      conversation_id: 'c1',
      attachments: ['a1', 'a3'],
    })
    const user = agent.items[0] as { text: string; attachments?: { name: string }[] }
    expect(user.text).toBe('Corta as pausas deste vídeo')
    expect(user.attachments?.map((card) => card.name)).toEqual(['roteiro.docx', 'aula.mp4'])
    expect(agent.pendingCount).toBe(0)
    expect(agent.attachmentCards).toEqual([])
  })

  it('com o campo vazio, a mensagem é "Veja os anexos." e aparece assim na conversa', async () => {
    const agent = await withTwoAttachments()

    expect(await agent.send('   ')).toBe(true)

    expect(server.to('POST /api/agent/messages')[0]?.body).toMatchObject({ message: 'Veja os anexos.' })
    expect(agent.items[0]).toMatchObject({ kind: 'user', text: 'Veja os anexos.' })
  })

  it('com um anexo só, "Veja o anexo."', async () => {
    stubWithAttachments({ 'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()) })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('roteiro.docx')])

    await agent.send('')

    expect(server.to('POST /api/agent/messages')[0]?.body).toMatchObject({ message: 'Veja o anexo.' })
  })

  it('sem texto e sem anexo, não envia', async () => {
    const agent = useAgentStore()
    await agent.init()

    expect(await agent.send('')).toBe(false)
    expect(server.to('POST /api/agent/messages')).toHaveLength(0)
  })

  it('a mensagem seguinte não repete os anexos que já foram', async () => {
    const agent = await withTwoAttachments()
    await agent.send('primeira')
    FakeEventSource.latest().emit(END_DONE)
    await flushPromises()

    await agent.send('segunda')

    expect(server.to('POST /api/agent/messages')[1]?.body).toEqual({ message: 'segunda', conversation_id: 'c1' })
  })

  it('o 422 de imagem sem visão guarda o texto e os anexos, mostra o detalhe e os modelos sugeridos do corpo cru', async () => {
    const message = 'O modelo gpt-oss:20b não aceita imagens. Escolha um destes: gemma3:4b.'
    stubWithAttachments({
      // o front não sabia que o modelo não enxerga (capacidades desconhecidas): quem recusa é o servidor
      'GET /api/agent/models': { ...MODELS, models: [{ ...GPT_OSS, capabilities: [] }, GEMMA, QWEN] },
      'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment()),
      'POST /api/agent/messages': reply(422, { detail: message, error: message, suggested_models: ['gemma3:4b'] }),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('foto.png')])
    expect(agent.warnings).toEqual([])

    expect(await agent.send('O que tem nesta foto?')).toBe(false)

    expect(agent.error).toBe(message)
    expect(agent.suggestedModels).toEqual(['gemma3:4b'])
    expect(agent.pendingCount).toBe(1)
    expect(agent.items).toEqual([])
    expect(agent.busy).toBe(false)
  })

  it('o erro de outro tipo não traz modelo sugerido', async () => {
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()),
      'POST /api/agent/messages': reply(503, { detail: 'O modelo local não está respondendo.' }),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('a.txt')])

    expect(await agent.send('oi')).toBe(false)

    expect(agent.error).toBe('O modelo local não está respondendo.')
    expect(agent.suggestedModels).toEqual([])
    expect(agent.pendingCount).toBe(1)
  })
})

describe('avisos de antes de enviar', () => {
  it('imagem com um modelo que não lê imagem avisa, sugere os modelos que leem e segura o envio', async () => {
    stubWithAttachments({
      'GET /api/agent/models': MODELS_WITH_GEMMA,
      'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment()),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.setMode('free')

    await agent.attach([file('foto.png')])

    expect(agent.warnings).toHaveLength(1)
    expect(agent.warnings[0]).toMatchObject({ code: 'image_without_vision', models: ['gemma3:4b'] })
    expect(agent.sendable).toBe(false)
    expect(await agent.send('descreve')).toBe(false)
    expect(server.to('POST /api/agent/messages')).toHaveLength(0)

    await agent.setModel('gemma3:4b')
    expect(agent.warnings).toEqual([])
    expect(agent.sendable).toBe(true)
  })

  it('no modo Operar a imagem não segura o envio: o modelo sem visão só recebe a informação e a mensagem segue', async () => {
    stubWithAttachments({
      'GET /api/agent/models': MODELS_WITH_GEMMA,
      'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment()),
    })
    const agent = useAgentStore()
    await agent.init()

    await agent.attach([file('foto.png')])

    expect(agent.warnings).toEqual([])
    expect(agent.infos).toEqual([{ code: 'image_as_file', text: 'O modelo não vê a imagem, mas pode usá-la no vídeo.' }])
    expect(agent.sendable).toBe(true)
    expect(await agent.send('cria um projeto com esta foto')).toBe(true)
    expect(server.to('POST /api/agent/messages')[0]!.body).toMatchObject({ conversation_id: 'c1', attachments: ['a2'] })
  })

  it('trocar o modo do rascunho com a imagem anexada muda o aviso junto: Conversa livre segura, Operar só informa', async () => {
    stubWithAttachments({
      'GET /api/agent/models': MODELS_WITH_GEMMA,
      'POST /api/agent/conversations/c1/attachments': uploads(() => imageAttachment()),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('foto.png')])

    await agent.setMode('free')
    expect(agent.warnings.map((warning) => warning.code)).toEqual(['image_without_vision'])
    expect(agent.infos).toEqual([])
    expect(agent.sendable).toBe(false)

    await agent.setMode('operate')
    expect(agent.warnings).toEqual([])
    expect(agent.infos).toHaveLength(1)
    expect(agent.sendable).toBe(true)
  })

  it('o vídeo anexado no modo Operar e depois trocado para a Conversa livre segura o envio', async () => {
    stubWithAttachments({ 'POST /api/agent/conversations/c1/attachments': uploads(() => mediaAttachment()) })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('aula.mp4')])
    expect(agent.warnings).toEqual([])

    await agent.setMode('free')

    expect(agent.warnings[0]?.code).toBe('media_in_free_chat')
    expect(agent.sendable).toBe(false)
  })
})

describe('tirar e reabrir anexos', () => {
  it('tirar a ficha pronta apaga o anexo no servidor', async () => {
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()),
      'DELETE /api/agent/conversations/c1/attachments/a1': removes('a1'),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('roteiro.docx')])

    await agent.removeAttachment(agent.attachmentCards[0]!)

    expect(server.to('DELETE /api/agent/conversations/c1/attachments/a1')).toHaveLength(1)
    expect(agent.pendingCount).toBe(0)
  })

  it('se o anexo já não existe no servidor (404), a ficha sai mesmo assim', async () => {
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()),
      'DELETE /api/agent/conversations/c1/attachments/a1': reply(404, { detail: 'Anexo desconhecido nesta conversa.' }),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('roteiro.docx')])

    await agent.removeAttachment(agent.attachmentCards[0]!)

    expect(agent.pendingCount).toBe(0)
    expect(agent.error).toBe('')
  })

  it('se o anexo já foi enviado (409), a ficha fica e o motivo aparece', async () => {
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()),
      'DELETE /api/agent/conversations/c1/attachments/a1': reply(409, { detail: 'Este anexo já foi enviado numa mensagem.' }),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('roteiro.docx')])

    await agent.removeAttachment(agent.attachmentCards[0]!)

    expect(agent.pendingCount).toBe(1)
    expect(agent.error).toBe('Este anexo já foi enviado numa mensagem.')
  })

  it('os anexos pendentes voltam como fichas ao reabrir a conversa', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    stubWithAttachments({}, [
      detail({
        messages: 0,
        mode_locked: false,
        pending_attachments: [textAttachment({ chars: 800, total_chars: 5000, truncated: true }), imageAttachment()],
      }),
    ])
    const agent = useAgentStore()
    await agent.init()

    expect(agent.attachmentCards.map((card) => [card.name, card.state, card.truncated])).toEqual([
      ['roteiro.docx', 'ready', true],
      ['foto.png', 'ready', false],
    ])
    expect(agent.pendingCount).toBe(2)
  })

  it('a mensagem enviada reaparece com as fichas ao reabrir a conversa', async () => {
    localStorage.setItem(OPEN_CONVERSATION_KEY, 'c1')
    stubWithAttachments({}, [
      detail({
        transcript: [
          {
            kind: 'user',
            id: 'e1',
            text: 'Veja o anexo.',
            at: '2026-10-30T12:00:00.000+00:00',
            attachments: [{ id: 'a1', kind: 'text', name: 'roteiro.docx', size: 2048, chars: 100, total_chars: 100, truncated: false }],
          },
        ],
      }),
    ])
    const agent = useAgentStore()
    await agent.init()

    const user = agent.items[0] as { attachments?: { name: string }[] }
    expect(user.attachments?.map((card) => card.name)).toEqual(['roteiro.docx'])
  })

  it('"Nova conversa" reaproveita a conversa vazia que nasceu para um anexo e solta os arquivos dela', async () => {
    stubWithAttachments({
      'POST /api/agent/conversations/c1/attachments': uploads(() => textAttachment()),
      'DELETE /api/agent/conversations/c1/attachments/a1': removes('a1'),
    })
    const agent = useAgentStore()
    await agent.init()
    await agent.attach([file('roteiro.docx')])
    await flushPromises() // a releitura da conversa que o envio pede termina antes

    agent.startNew()
    await flushPromises()

    expect(agent.pendingCount).toBe(0)
    expect(server.to('DELETE /api/agent/conversations/c1/attachments/a1')).toHaveLength(1)
    expect(agent.conversationId).toBe('c1')
  })

  it('abrir outra conversa no meio do envio não gruda a ficha na conversa nova', async () => {
    const upload = deferred<Upload>()
    stubWithAttachments(
      {
        'POST /api/agent/conversations/c1/attachments': uploads(() => upload.promise),
        'GET /api/agent/conversations/c2': () => server.state.conversations.find((item) => item.id === 'c2'),
      },
      [detail({ id: 'c1', messages: 0, mode_locked: false }), detail({ id: 'c2', title: 'Outra' })],
    )
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')
    const attaching = agent.attach([file('a.txt')])
    await vi.waitFor(() => expect(server.to('POST /api/agent/conversations/c1/attachments')).toHaveLength(1))

    await agent.open('c2')
    upload.resolve(textAttachment())
    await attaching

    expect(agent.conversationId).toBe('c2')
    expect(agent.attachmentCards).toEqual([])
  })
})

describe('opções avançadas', () => {
  it('na conversa nova ficam no rascunho e vão com a primeira mensagem; vazias não vão', async () => {
    const agent = useAgentStore()
    await agent.init()
    await agent.setOptions({ num_ctx: 8192, temperature: 0.2 })

    expect(agent.options).toEqual({ num_ctx: 8192, temperature: 0.2 })
    expect(server.calls.filter((call) => call.method === 'PATCH')).toEqual([])
    await agent.send('oi')

    expect(server.to('POST /api/agent/messages')[0]?.body).toEqual({
      message: 'oi',
      mode: 'operate',
      model: 'gpt-oss:20b',
      options: { num_ctx: 8192, temperature: 0.2 },
    })
  })

  it('na conversa salva, grava no servidor, e esvaziar tudo manda null', async () => {
    stubWithAttachments({}, [detail()])
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.setOptions({ num_ctx: 4096, seed: 0 })
    expect(server.to('PATCH /api/agent/conversations/c1')[0]?.body).toEqual({ options: { num_ctx: 4096, seed: 0 } })
    expect(agent.options).toEqual({ num_ctx: 4096, seed: 0 })

    await agent.setOptions({})
    expect(server.to('PATCH /api/agent/conversations/c1')[1]?.body).toEqual({ options: null })
    expect(agent.options).toEqual({})
  })

  it('as mesmas opções não vão ao servidor de novo', async () => {
    stubWithAttachments({}, [detail({ options: { num_ctx: 4096 } })])
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.setOptions({ num_ctx: 4096, seed: null })

    expect(server.to('PATCH /api/agent/conversations/c1')).toHaveLength(0)
  })

  it('se o servidor recusa, volta ao que estava e diz por quê', async () => {
    stubWithAttachments({ 'PATCH /api/agent/conversations/c1': reply(422, { detail: 'Este modelo vai até 131072 tokens.' }) }, [
      detail({ options: { num_ctx: 4096 } }),
    ])
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')

    await agent.setOptions({ num_ctx: 999999 })

    expect(agent.options).toEqual({ num_ctx: 4096 })
    expect(agent.error).toBe('Este modelo vai até 131072 tokens.')
  })

  it('mudar o contexto traz as fichas de texto com o corte refeito para o contexto novo', async () => {
    stubWithAttachments(
      {
        'PATCH /api/agent/conversations/c1': () =>
          detail({ options: { num_ctx: 2048 }, pending_attachments: [textAttachment({ chars: 3000, total_chars: 20000, truncated: true })] }),
      },
      [detail({ pending_attachments: [textAttachment()] })],
    )
    const agent = useAgentStore()
    await agent.init()
    await agent.open('c1')
    expect(agent.attachmentCards[0]?.truncated).toBe(false)

    await agent.setOptions({ num_ctx: 2048 })

    expect(agent.attachmentCards[0]).toMatchObject({ truncated: true, chars: 3000, totalChars: 20000 })
  })
})

describe('modelo carregado', () => {
  it('lê o que está na memória e quanto ocupa', async () => {
    stubWithAttachments({ 'GET /api/agent/loaded': LOADED })
    const agent = useAgentStore()
    await agent.init()
    await agent.loadLoaded()

    expect(agent.loaded?.models[0]).toMatchObject({ name: 'gpt-oss:20b', context_length: 16384 })
    expect(agent.engine).toBe('ollama')
  })

  it('o motor compatível com a OpenAI não tem o que ler', async () => {
    stubWithAttachments({ 'GET /api/agent/models': { ...MODELS, engine: 'openai' } })
    const agent = useAgentStore()
    await agent.init()
    server.calls.length = 0

    await agent.loadLoaded()

    expect(server.to('GET /api/agent/loaded')).toHaveLength(0)
    expect(agent.engine).toBe('openai')
  })

  it('descarregar chama o servidor e relê o que está carregado e os modelos', async () => {
    stubWithAttachments({
      'GET /api/agent/loaded': LOADED,
      'POST /api/agent/unload': { model: 'gpt-oss:20b', unloaded: true },
    })
    const agent = useAgentStore()
    await agent.init()
    server.calls.length = 0

    expect(await agent.unload('gpt-oss:20b')).toBe(true)

    expect(server.to('POST /api/agent/unload')[0]?.body).toEqual({ model: 'gpt-oss:20b' })
    expect(server.to('GET /api/agent/loaded')).toHaveLength(1)
    expect(server.to('GET /api/agent/models')).toHaveLength(1)
    expect(agent.unloading).toBeNull()
    expect(agent.unloadError).toBe('')
  })

  it('o 409 (uma resposta usa o modelo) fica como motivo e nada é relido', async () => {
    stubWithAttachments({ 'POST /api/agent/unload': reply(409, { detail: 'Pare a resposta do agente antes de descarregar o modelo.' }) })
    const agent = useAgentStore()
    await agent.init()
    server.calls.length = 0

    expect(await agent.unload('gpt-oss:20b')).toBe(false)

    expect(agent.unloadError).toBe('Pare a resposta do agente antes de descarregar o modelo.')
    expect(agent.unloading).toBeNull()
    expect(server.to('GET /api/agent/loaded')).toHaveLength(0)
  })

  it('o modelo que nem estava carregado devolve falso, sem erro', async () => {
    stubWithAttachments({ 'POST /api/agent/unload': { model: 'gpt-oss:20b', unloaded: false } })
    const agent = useAgentStore()
    await agent.init()

    expect(await agent.unload('gpt-oss:20b')).toBe(false)
    expect(agent.unloadError).toBe('')
  })

  it('o fim de um turno relê o que está carregado', async () => {
    stubWithAttachments({ 'GET /api/agent/loaded': LOADED })
    const agent = useAgentStore()
    await agent.init()
    await agent.send('oi')
    server.calls.length = 0

    FakeEventSource.latest().emit(END_DONE)
    await flushPromises()

    expect(server.to('GET /api/agent/loaded')).toHaveLength(1)
    expect(agent.loaded?.models).toHaveLength(1)
  })
})
