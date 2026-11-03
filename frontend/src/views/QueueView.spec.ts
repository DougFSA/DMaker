import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource } from '@/test/fetch'
import { finishedItem, queueCallsTo, queueItem, queueView, stubQueueServer, type QueueServer, type QueueServerOptions } from '@/test/queueServer'
import { mountRoute } from '@/test/routes'
import { buttonLabelled } from '@/test/speechServer'

let wrapper: VueWrapper | null = null
let server: QueueServer

beforeEach(() => {
  localStorage.clear()
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function openQueue(options: QueueServerOptions = {}): Promise<VueWrapper> {
  server = stubQueueServer(options)
  const mounted = await mountRoute('/fila')
  wrapper = mounted.wrapper
  await flushPromises()
  return wrapper
}

/** O servidor manda uma foto nova da fila. */
async function emit(view: ReturnType<typeof queueView>): Promise<void> {
  FakeEventSource.latest().emit(view)
  await flushPromises()
}

const card = (id: string) => wrapper!.find(`[data-queue-id="${id}"]`)
const act = async (id: string, action: string) => {
  await card(id).find(`[data-action="${action}"]`).trigger('click')
  await flushPromises()
}

describe('QueueView (/fila)', () => {
  it('mostra o título, os botões do topo e já não é uma tela em construção', async () => {
    await openQueue()
    expect(wrapper!.find('h1').text()).toBe('Fila')
    expect(wrapper!.text()).not.toContain('em construção')
    expect(buttonLabelled(wrapper!, 'Importar roteiro')).toBeTruthy()
    expect(buttonLabelled(wrapper!, 'Limpar concluídos').attributes('disabled')).toBeDefined()
  })

  it('fila vazia: diz que não há nada e aponta para a Narração e para o Importar', async () => {
    await openQueue()
    expect(wrapper!.text()).toContain('A fila está vazia.')
    expect(wrapper!.text()).toContain('Nada na fila')
    expect(wrapper!.find('a[href="/voz/narracao"]').text()).toBe('Ir para a Narração')
  })

  it('enquanto a primeira leitura não chega, diz que está carregando', async () => {
    server = stubQueueServer()
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => undefined)))
    const mounted = await mountRoute('/fila')
    wrapper = mounted.wrapper
    expect(wrapper.text()).toContain('Carregando a fila...')
  })

  it('abre o fluxo ao vivo ao montar e fecha ao sair da tela', async () => {
    await openQueue()
    const source = FakeEventSource.latest()
    expect(source.url).toBe('/api/voices/queue/events')
    expect(source.closed).toBe(false)
    wrapper!.unmount()
    wrapper = null
    expect(source.closed).toBe(true)
  })

  it('lista os itens com o estado e o andamento, e acompanha as fotos do servidor', async () => {
    await openQueue({ view: queueView([queueItem({ title: 'Audiobook' })]) })
    expect(card('q1').text()).toContain('Audiobook')
    expect(card('q1').text()).toContain('Pendente')
    expect(wrapper!.text()).toContain('1 item · tempo estimado para esvaziar: 40 s')

    await emit(
      queueView([
        queueItem({
          title: 'Audiobook',
          state: 'running',
          state_label: 'Rodando',
          chapter: 1,
          chapters_total: 3,
          utterance: 4,
          utterances: 10,
          percent: 40,
        }),
      ]),
    )
    expect(card('q1').text()).toContain('Rodando')
    expect(card('q1').text()).toContain('capítulo 1 de 3, fala 4 de 10')
    expect(card('q1').find('[role="progressbar"]').attributes('aria-valuenow')).toBe('40')
  })

  it('avisa quando a fila tem o que narrar e nenhum executor', async () => {
    await openQueue({ view: queueView([queueItem()], { worker: false }) })
    expect(wrapper!.find('[role="alert"]').text()).toContain('Nenhum executor ativo')
    await emit(queueView([queueItem()], { worker: true }))
    expect(wrapper!.find('[role="alert"]').exists()).toBe(false)
  })

  it('avisa quando a conexão cai e tira o aviso quando volta', async () => {
    await openQueue({ view: queueView([queueItem()]) })
    FakeEventSource.latest().drop()
    await flushPromises()
    expect(wrapper!.find('.notice').text()).toContain('Sem conexão com o servidor')
    FakeEventSource.latest().open()
    await flushPromises()
    expect(wrapper!.find('.notice').exists()).toBe(false)
  })

  it('a fila que não carrega mostra o motivo e deixa tentar de novo', async () => {
    await openQueue({ listFailure: 'O arquivo da fila está corrompido.' })
    expect(wrapper!.find('[role="alert"]').text()).toContain('O arquivo da fila está corrompido.')
    await buttonLabelled(wrapper!, 'Tentar de novo').trigger('click')
    await flushPromises()
    expect(queueCallsTo(server, 'GET', '/api/voices/queue')).toHaveLength(2)
  })

  it('cada botão do item comanda o servidor e a lista mostra a resposta', async () => {
    const running = queueItem({ state: 'running', state_label: 'Rodando' })
    const paused = queueItem({ state: 'paused', state_label: 'Pausado', percent: 30 })
    await openQueue({
      view: queueView([running]),
      replies: { 'POST /api/voices/queue/q1/pause': { body: queueView([paused]) } },
    })
    await act('q1', 'pause')
    expect(queueCallsTo(server, 'POST', '/api/voices/queue/q1/pause')).toHaveLength(1)
    expect(card('q1').text()).toContain('Pausado')
    expect(card('q1').text()).toContain('Pausado em 30%')
    // pausado, o item oferece Retomar
    expect(card('q1').find('[data-action="resume"]').exists()).toBe(true)
  })

  it('Subir e Descer mandam a direção; o primeiro não sobe e o último não desce', async () => {
    await openQueue({ view: queueView([queueItem({ id: 'a', title: 'A' }), queueItem({ id: 'b', title: 'B' })]) })
    expect(card('a').find('[data-action="up"]').attributes('disabled')).toBeDefined()
    expect(card('b').find('[data-action="down"]').attributes('disabled')).toBeDefined()

    await act('b', 'up')
    await act('a', 'down')
    const moves = queueCallsTo(server, 'POST', '/api/voices/queue/b/move').concat(queueCallsTo(server, 'POST', '/api/voices/queue/a/move'))
    expect(moves.map((call) => call.body)).toEqual([{ direction: -1 }, { direction: 1 }])
  })

  it('Remover tira o item pelo DELETE', async () => {
    await openQueue({ view: queueView([finishedItem()]) })
    await act('q9', 'remove')
    expect(queueCallsTo(server, 'DELETE', '/api/voices/queue/q9')).toHaveLength(1)
  })

  it('item pronto mostra a duração, a pasta e os arquivos para ouvir e baixar', async () => {
    await openQueue({ view: queueView([finishedItem()]) })
    expect(card('q9').text()).toContain('Pronto · 1 capítulo · 2 min de áudio')
    expect(card('q9').text()).toContain('Pasta: output/voz/primeiro-roteiro')
    expect(card('q9').text()).toContain('Arquivos prontos (2)')
    await card('q9').find('summary').trigger('click')
    expect(card('q9').find('button[aria-label="Ouvir roteiro-pronto.wav"]').exists()).toBe(true)
  })

  it('a foto nova não fecha os arquivos que a pessoa abriu nem derruba o player', async () => {
    await openQueue({ view: queueView([finishedItem()]) })
    const details = card('q9').find('details').element as HTMLDetailsElement
    details.open = true
    await card('q9').find('button[aria-label="Ouvir roteiro-pronto.wav"]').trigger('click')
    const player = card('q9').find('audio').element

    // outro item avança: a lista inteira chega de novo
    await emit(queueView([finishedItem(), queueItem({ id: 'q2', state: 'running', percent: 10 })]))

    expect((card('q9').find('details').element as HTMLDetailsElement).open).toBe(true)
    expect(card('q9').find('audio').element).toBe(player)
  })

  it('Limpar concluídos só liga com item pronto ou cancelado e tira os itens', async () => {
    await openQueue({
      view: queueView([finishedItem(), queueItem()]),
      replies: { 'POST /api/voices/queue/clear-finished': { body: { ...queueView([queueItem()]), removed: 1 } } },
    })
    const clear = buttonLabelled(wrapper!, 'Limpar concluídos')
    expect(clear.attributes('disabled')).toBeUndefined()
    await clear.trigger('click')
    await flushPromises()
    expect(queueCallsTo(server, 'POST', '/api/voices/queue/clear-finished')).toHaveLength(1)
    expect(wrapper!.find('[data-queue-id="q9"]').exists()).toBe(false)
    expect(buttonLabelled(wrapper!, 'Limpar concluídos').attributes('disabled')).toBeDefined()
  })

  it('Importar roteiro abre o diálogo com a voz da Narração e manda o arquivo para a fila', async () => {
    await openQueue()
    await buttonLabelled(wrapper!, 'Importar roteiro').trigger('click')
    await flushPromises()

    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog.textContent).toContain('Narra com: Voz automática do motor · idioma da voz · velocidade 1,00x.')

    const input = dialog.querySelector('input[type="file"]') as HTMLInputElement
    const roteiro = new File(['# Um\nTexto.'], 'curso.md')
    Object.defineProperty(input, 'files', { value: [roteiro], configurable: true })
    input.dispatchEvent(new Event('change'))
    await flushPromises()
    ;(dialog.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()

    const [call] = queueCallsTo(server, 'POST', '/api/voices/queue/upload')
    expect((call?.form?.file as File).name).toBe('curso.md')
    expect(call?.form).toMatchObject({ format: 'wav', draft: 'false' })
    // o envio deu certo: o diálogo fecha
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()
  })

  it('se o servidor recusa o arquivo, o diálogo continua aberto para tentar outro', async () => {
    await openQueue({
      replies: { 'POST /api/voices/queue/upload': { body: { detail: 'Formato não aceito.' }, status: 400 } },
    })
    await buttonLabelled(wrapper!, 'Importar roteiro').trigger('click')
    await flushPromises()
    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement
    const input = dialog.querySelector('input[type="file"]') as HTMLInputElement
    Object.defineProperty(input, 'files', { value: [new File(['x'], 'curso.txt')], configurable: true })
    input.dispatchEvent(new Event('change'))
    await flushPromises()
    ;(dialog.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    expect(document.body.querySelector('[role="dialog"]')).not.toBeNull()
  })
})
