import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { QueueAction } from '@/lib/queue'
import { FakeEventSource } from '@/test/fetch'
import {
  finishedItem,
  queueCallsTo,
  queueItem,
  queueView,
  stubQueueServer,
  type QueueServerOptions,
} from '@/test/queueServer'
import { useNarrationStore } from './narration'
import { useQueueStore } from './queue'
import { useToastsStore } from './toasts'
import { useVoiceStore } from './voice'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** Instala o servidor falso, cria o store e abre o acompanhamento até a primeira leitura chegar. */
async function startQueue(options: QueueServerOptions = {}) {
  const server = stubQueueServer(options)
  const queue = useQueueStore()
  await queue.start()
  return { server, queue, toasts: useToastsStore() }
}

describe('acompanhar a fila', () => {
  it('abre o fluxo ao vivo da fila e lê a lista uma vez', async () => {
    const { server, queue } = await startQueue({ view: queueView([queueItem()]) })
    expect(FakeEventSource.latest().url).toBe('/api/voices/queue/events')
    expect(queueCallsTo(server, 'GET', '/api/voices/queue')).toHaveLength(1)
    expect(queue.items.map((item) => item.id)).toEqual(['q1'])
  })

  it('cada foto do fluxo troca a lista inteira', async () => {
    const { queue } = await startQueue({ view: queueView([queueItem()]) })
    FakeEventSource.latest().emit(queueView([queueItem({ id: 'q2', title: 'Outro' }), finishedItem()]))
    expect(queue.items.map((item) => item.id)).toEqual(['q2', 'q9'])
    expect(queue.summary?.text).toContain('2 itens')
  })

  it('a leitura inicial não sobrescreve uma foto do fluxo que chegou antes dela', async () => {
    stubQueueServer({ view: queueView([queueItem({ title: 'Velho' })]) })
    const queue = useQueueStore()
    const starting = queue.start()
    FakeEventSource.latest().emit(queueView([queueItem({ title: 'Novo' })]))
    await starting
    expect(queue.items[0]?.title).toBe('Novo')
  })

  it('abrir de novo enquanto já acompanha não abre outra conexão', async () => {
    const { queue } = await startQueue()
    await queue.start()
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('parar fecha o fluxo', async () => {
    const { queue } = await startQueue()
    const source = FakeEventSource.latest()
    queue.stop()
    expect(source.closed).toBe(true)
    expect(queue.status).toBe('closed')
  })

  it('a queda da conexão vira o aviso de "sem conexão", e a volta o tira', async () => {
    const { queue } = await startQueue()
    const source = FakeEventSource.latest()
    source.open()
    expect(queue.offline).toBe(false)
    source.drop()
    expect(queue.offline).toBe(true)
    source.open()
    expect(queue.offline).toBe(false)
  })

  it('se a fila não carrega, guarda o motivo; uma foto do fluxo depois o apaga', async () => {
    const { queue } = await startQueue({ listFailure: 'O arquivo da fila está corrompido.' })
    expect(queue.view).toBeNull()
    expect(queue.failure).toBe('O arquivo da fila está corrompido.')
    FakeEventSource.latest().emit(queueView())
    expect(queue.failure).toBe('')
    expect(queue.view?.items).toEqual([])
  })

  it('uma leitura que falha com a lista já na tela não troca a lista por um erro', async () => {
    const { queue } = await startQueue({ view: queueView([queueItem()]) })
    stubQueueServer({ listFailure: 'fora do ar' })
    await queue.reload()
    expect(queue.failure).toBe('')
    expect(queue.items).toHaveLength(1)
  })

  it('diz quais itens ainda podem subir ou descer, e se há o que limpar', async () => {
    const { queue } = await startQueue({
      view: queueView([queueItem({ id: 'a' }), queueItem({ id: 'b' }), finishedItem()]),
    })
    expect(queue.limits).toEqual({ a: { up: false, down: true }, b: { up: true, down: false } })
    expect(queue.canClear).toBe(true)
  })
})

describe('comandos sobre um item', () => {
  const ROUTES: Array<[QueueAction, string, string, unknown]> = [
    ['pause', 'POST', '/api/voices/queue/q1/pause', {}],
    ['resume', 'POST', '/api/voices/queue/q1/resume', {}],
    ['cancel', 'POST', '/api/voices/queue/q1/cancel', {}],
    ['retry', 'POST', '/api/voices/queue/q1/retry', {}],
    ['up', 'POST', '/api/voices/queue/q1/move', { direction: -1 }],
    ['down', 'POST', '/api/voices/queue/q1/move', { direction: 1 }],
    ['remove', 'DELETE', '/api/voices/queue/q1', undefined],
  ]

  it.each(ROUTES)('%s chama a rota certa', async (action, method, url, body) => {
    const { server, queue } = await startQueue({ view: queueView([queueItem()]) })
    await queue.act('q1', action)
    const calls = queueCallsTo(server, method, url)
    expect(calls).toHaveLength(1)
    expect(calls[0]?.body).toEqual(body)
  })

  it('a resposta do comando já traz a fila nova e entra na tela na hora', async () => {
    const paused = queueView([queueItem({ state: 'paused', state_label: 'Pausado' })])
    const { queue } = await startQueue({
      view: queueView([queueItem({ state: 'running' })]),
      replies: { 'POST /api/voices/queue/q1/pause': { body: paused } },
    })
    await queue.act('q1', 'pause')
    expect(queue.items[0]?.state).toBe('paused')
  })

  it('enquanto o comando espera a resposta, o item fica marcado e outro comando nele é ignorado', async () => {
    const { server, queue } = await startQueue({ view: queueView([queueItem()]) })
    const first = queue.act('q1', 'pause')
    expect(queue.working).toEqual({ q1: true })
    await queue.act('q1', 'cancel')
    await first
    expect(queue.working).toEqual({})
    expect(queueCallsTo(server, 'POST', '/api/voices/queue/q1/cancel')).toHaveLength(0)
  })

  it('o servidor recusa: avisa com a frase dele e a lista não muda', async () => {
    const { queue, toasts } = await startQueue({
      view: queueView([queueItem({ state: 'running' })]),
      replies: {
        'DELETE /api/voices/queue/q1': { body: { detail: 'O item está rodando; cancele antes de remover.' }, status: 400 },
      },
    })
    await queue.act('q1', 'remove')
    expect(toasts.items.at(-1)).toMatchObject({
      tone: 'error',
      title: 'Não consegui remover o item',
      description: 'O item está rodando; cancele antes de remover.',
    })
    expect(queue.items).toHaveLength(1)
    expect(queue.working).toEqual({})
  })
})

describe('limpar concluídos', () => {
  it('tira os prontos da lista e diz quantos saíram', async () => {
    const { queue, toasts } = await startQueue({
      view: queueView([finishedItem(), queueItem()]),
      replies: { 'POST /api/voices/queue/clear-finished': { body: { ...queueView([queueItem()]), removed: 2 } } },
    })
    await queue.clearFinished()
    expect(queue.items.map((item) => item.id)).toEqual(['q1'])
    expect(toasts.items.at(-1)).toMatchObject({ title: '2 itens saíram da lista', description: 'Os áudios continuam na pasta de saída.' })
  })

  it('no singular, fala "1 item"', async () => {
    const { queue, toasts } = await startQueue({
      replies: { 'POST /api/voices/queue/clear-finished': { body: { ...queueView(), removed: 1 } } },
    })
    await queue.clearFinished()
    expect(toasts.items.at(-1)?.title).toBe('1 item saiu da lista')
  })

  it('o erro vira aviso', async () => {
    const { queue, toasts } = await startQueue({
      replies: { 'POST /api/voices/queue/clear-finished': { body: { detail: 'disco cheio' }, status: 500 } },
    })
    await queue.clearFinished()
    expect(toasts.items.at(-1)).toMatchObject({ tone: 'error', title: 'Não consegui limpar a lista', description: 'disco cheio' })
    expect(queue.clearing).toBe(false)
  })
})

describe('importar um roteiro', () => {
  const roteiro = () => new File(['# Capítulo 1\nUm texto.'], 'curso.md', { type: 'text/markdown' })

  it('manda o arquivo com o título, o formato, o rascunho e as escolhas da Narração', async () => {
    const { server, queue } = await startQueue()
    const narration = useNarrationStore()
    await narration.loadVoices()
    useVoiceStore().chooseVoice('dora')
    narration.speed = 1.25
    narration.language = 'en'
    narration.brand = 'medlycare'

    const added = await queue.importScript(roteiro(), { title: '  Curso de pintura ', format: 'mp3', draft: true })

    expect(added?.id).toBe('novo')
    const [call] = queueCallsTo(server, 'POST', '/api/voices/queue/upload')
    expect(call?.form).toMatchObject({
      title: 'Curso de pintura',
      voice: 'dora',
      language: 'en',
      speed: '1.25',
      brand: 'medlycare',
      draft: 'true',
      format: 'mp3',
    })
    expect((call?.form?.file as File).name).toBe('curso.md')
  })

  it('sem escolha na Narração, não manda voz, idioma nem marca (o servidor usa o padrão)', async () => {
    const { server, queue } = await startQueue()
    await queue.importScript(roteiro(), { title: '', format: 'wav', draft: false })
    const [call] = queueCallsTo(server, 'POST', '/api/voices/queue/upload')
    expect(call?.form).not.toHaveProperty('title')
    expect(call?.form).not.toHaveProperty('voice')
    expect(call?.form).not.toHaveProperty('language')
    expect(call?.form).not.toHaveProperty('brand')
    expect(call?.form).toMatchObject({ speed: '1', draft: 'false', format: 'wav' })
  })

  it('a fila nova entra na tela e a pessoa é avisada', async () => {
    const { queue, toasts } = await startQueue({
      replies: {
        'POST /api/voices/queue/upload': {
          body: { id: 'q3', ...queueView([queueItem({ id: 'q3', title: 'Curso', source: { kind: 'file', name: 'curso.md' } })]) },
        },
      },
    })
    await queue.importScript(roteiro(), { title: '', format: 'wav', draft: false })
    expect(queue.items.map((item) => item.id)).toEqual(['q3'])
    expect(toasts.items.at(-1)).toMatchObject({ tone: 'success', title: 'Roteiro na fila' })
    expect(queue.importing).toBe(false)
  })

  it('o servidor recusa o arquivo: avisa com a frase dele e devolve nulo', async () => {
    const { queue, toasts } = await startQueue({
      replies: {
        'POST /api/voices/queue/upload': { body: { detail: 'O arquivo de roteiro é grande demais (limite de 20 MB).' }, status: 400 },
      },
    })
    const added = await queue.importScript(roteiro(), { title: '', format: 'wav', draft: false })
    expect(added).toBeNull()
    expect(toasts.items.at(-1)).toMatchObject({
      tone: 'error',
      title: 'Não consegui importar o roteiro',
      description: 'O arquivo de roteiro é grande demais (limite de 20 MB).',
    })
    expect(queue.importing).toBe(false)
  })

  it('marca o envio em andamento até a resposta', async () => {
    const { queue } = await startQueue()
    const sending = queue.importScript(roteiro(), { title: '', format: 'wav', draft: false })
    expect(queue.importing).toBe(true)
    await sending
    await flushPromises()
    expect(queue.importing).toBe(false)
  })
})
