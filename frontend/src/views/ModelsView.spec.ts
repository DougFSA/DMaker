import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, RouterView } from 'vue-router'
import ConfirmHost from '@/components/ui/ConfirmHost.vue'
import { createAppRouter } from '@/router'
import { LEFTOVER_DIR, LEFTOVER_FILE, stubModelsServer, type ModelsServer } from '@/test/modelsServer'
import { FakeEventSource } from '@/test/fetch'
import { buttonLabelled, callsTo } from '@/test/speechServer'
import { useConfirmStore } from '@/stores/confirm'
import { useToastsStore } from '@/stores/toasts'

let server: ModelsServer
let wrapper: VueWrapper | null = null

beforeEach(() => {
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

/** A tela na rota de verdade, com o diálogo de confirmação que a casca do app monta (apagar pergunta antes). */
async function openModels(): Promise<VueWrapper> {
  setActivePinia(createPinia())
  const router = createAppRouter(createMemoryHistory())
  await router.push('/modelos')
  await router.isReady()
  const Host = defineComponent({ render: () => [h(RouterView), h(ConfirmHost)] })
  wrapper = mount(Host, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

const row = (id: string) => wrapper!.find(`[data-model="${id}"]`)
const rowButton = (id: string, label: string) => row(id).findAll('button').find((node) => node.text().startsWith(label))
const dialog = () => document.body.querySelector('[role="alertdialog"]')
const toastTitles = () => useToastsStore().items.map((toast) => toast.title)

/** Responde ao diálogo de confirmação como a pessoa faria. */
async function answer(accepted: boolean): Promise<void> {
  useConfirmStore().answer(accepted)
  await flushPromises()
}

describe('ModelsView (/modelos)', () => {
  it('lista cada modelo com estado, tamanho no disco, licença e as funções que dependem dele', async () => {
    server = stubModelsServer()
    await openModels()
    expect(wrapper!.find('h1').text()).toBe('Modelos')
    expect(wrapper!.text()).not.toContain('em construção')

    expect(row('omnivoice').text()).toContain('OmniVoice')
    expect(row('omnivoice').text()).toContain('baixado')
    expect(row('omnivoice').text()).toContain('3,04 GB')
    expect(row('omnivoice').text()).toContain('Apache-2.0')
    expect(row('omnivoice').text()).toContain('Usado por: Narração; Dublagem')

    expect(row('demucs-htdemucs').text()).toContain('incompleto')
    expect(row('demucs-htdemucs').text()).toContain('40,0 MB')
    expect(row('demucs-htdemucs').text()).toContain('de ~80,1 MB')

    expect(row('audioseal').text()).toContain('não baixado')
    expect(row('audioseal').text()).toContain('ocupa ~89,1 MB ao baixar')
    expect(row('audioseal').text()).not.toContain('Usado por')
  })

  it('mostra a pasta e o resumo do disco, e "Medir de novo" mede outra vez', async () => {
    server = stubModelsServer()
    await openModels()
    expect(wrapper!.find('[data-testid="models-dir"]').text()).toBe('X:/dados-de-teste/cache/models')
    expect(wrapper!.find('[data-testid="models-summary"]').text()).toBe('Ocupado em cache/models: 3,73 GB · Livre no disco: 46,57 GB')

    const before = callsTo(server.calls, 'GET', '/api/models').length
    await buttonLabelled(wrapper!, 'Medir de novo').trigger('click')
    await flushPromises()
    expect(callsTo(server.calls, 'GET', '/api/models')).toHaveLength(before + 1)
  })

  it('só oferece baixar o que não está inteiro e apagar o que tem algo em disco', async () => {
    server = stubModelsServer()
    await openModels()
    expect(rowButton('omnivoice', 'Baixar')).toBeUndefined()
    expect(rowButton('omnivoice', 'Apagar')).toBeDefined()
    expect(rowButton('demucs-htdemucs', 'Continuar download')).toBeDefined()
    expect(rowButton('demucs-htdemucs', 'Apagar')).toBeDefined()
    expect(rowButton('audioseal', 'Baixar (89,1 MB)')).toBeDefined()
    expect(rowButton('audioseal', 'Apagar')).toBeUndefined()
  })

  it('baixa como job: mostra o andamento, trava os botões do modelo e mede o disco no fim', async () => {
    server = stubModelsServer()
    await openModels()
    await rowButton('audioseal', 'Baixar')!.trigger('click')
    await flushPromises()

    expect(callsTo(server.calls, 'POST', '/api/models/audioseal/download')).toHaveLength(1)
    expect(row('audioseal').text()).toContain('Na fila...')
    expect(rowButton('audioseal', 'Baixar')!.attributes('disabled')).toBeDefined()
    // os outros modelos seguem livres
    expect(rowButton('omnivoice', 'Apagar')!.attributes('disabled')).toBeUndefined()

    FakeEventSource.latest().emit({ kind: 'progress', t: 1, label: "AudioSeal: 44,5 MB de 89,1 MB", done: 46_000_000, total: 93_473_621, percent: 50 })
    await flushPromises()
    expect(row('audioseal').text()).toContain('AudioSeal: 44,5 MB de 89,1 MB')
    expect(row('audioseal').text()).toContain('50%')
    expect(row('audioseal').find('[role="progressbar"]').attributes('aria-valuenow')).toBe('50')

    server.setState('audioseal', 'installed')
    FakeEventSource.latest().emit({ kind: 'end', t: 2, status: 'done', error: null, result: server.models[2] })
    await flushPromises()
    expect(row('audioseal').text()).toContain('baixado')
    expect(row('audioseal').text()).not.toContain('Na fila')
    expect(rowButton('audioseal', 'Baixar')).toBeUndefined()
    expect(toastTitles()).toContain('Modelo baixado')
  })

  it('clicar em Continuar download de um modelo pela metade pede o mesmo download', async () => {
    server = stubModelsServer()
    await openModels()
    await rowButton('demucs-htdemucs', 'Continuar download')!.trigger('click')
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/models/demucs-htdemucs/download')).toHaveLength(1)
  })

  it('um download que falha mostra o motivo na linha e deixa tentar de novo', async () => {
    server = stubModelsServer()
    await openModels()
    await rowButton('audioseal', 'Baixar')!.trigger('click')
    await flushPromises()
    FakeEventSource.latest().emit({ kind: 'end', t: 2, status: 'error', error: 'OSError: Falta espaço no disco.\nTraceback...', result: null })
    await flushPromises()

    expect(row('audioseal').find('[role="alert"]').text()).toBe('Falta espaço no disco.')
    expect(row('audioseal').text()).toContain('não baixado')
    expect(rowButton('audioseal', 'Baixar')!.attributes('disabled')).toBeUndefined()
    expect(toastTitles()).not.toContain('Modelo baixado')
  })

  it('Apagar mostra o aviso do servidor e só apaga depois de confirmar', async () => {
    server = stubModelsServer()
    await openModels()
    await rowButton('omnivoice', 'Apagar')!.trigger('click')
    await flushPromises()

    expect(callsTo(server.calls, 'GET', '/api/models/omnivoice/removal')).toHaveLength(1)
    expect(dialog()!.textContent).toContain('Apagar OmniVoice?')
    expect(dialog()!.textContent).toContain('Vai apagar OmniVoice e liberar 3,04 GB.')
    expect(dialog()!.textContent).toContain('Narração; Dublagem')
    expect(callsTo(server.calls, 'POST', '/api/models/omnivoice/remove')).toHaveLength(0)

    await answer(true)
    expect(callsTo(server.calls, 'POST', '/api/models/omnivoice/remove')[0]!.body).toEqual({ confirm: true })
    expect(row('omnivoice').text()).toContain('não baixado')
    expect(rowButton('omnivoice', 'Apagar')).toBeUndefined()
    expect(toastTitles()).toContain('Modelo apagado')
  })

  it('Cancelar no diálogo não apaga nada nem mede o disco de novo', async () => {
    server = stubModelsServer()
    await openModels()
    await rowButton('omnivoice', 'Apagar')!.trigger('click')
    await flushPromises()
    const measured = callsTo(server.calls, 'GET', '/api/models').length

    await answer(false)
    expect(callsTo(server.calls, 'POST', '/api/models/omnivoice/remove')).toHaveLength(0)
    expect(callsTo(server.calls, 'GET', '/api/models')).toHaveLength(measured)
    expect(row('omnivoice').text()).toContain('baixado')
    expect(rowButton('omnivoice', 'Apagar')!.attributes('disabled')).toBeUndefined()
  })

  it('o servidor recusar apagar (download em andamento) vira um aviso de erro', async () => {
    server = stubModelsServer({ removeError: 'OmniVoice está sendo baixado agora; espere terminar.' })
    await openModels()
    await rowButton('omnivoice', 'Apagar')!.trigger('click')
    await flushPromises()
    await answer(true)

    const toasts = useToastsStore().items
    expect(toasts.map((toast) => toast.title)).toContain('Não consegui apagar o modelo')
    expect(toasts.find((toast) => toast.tone === 'error')!.description).toBe('OmniVoice está sendo baixado agora; espere terminar.')
    expect(row('omnivoice').text()).toContain('baixado')
  })

  it('sem sobras, o cartão de sobras não aparece', async () => {
    server = stubModelsServer()
    await openModels()
    expect(wrapper!.text()).not.toContain('Sobras')
    expect(wrapper!.text()).not.toContain('Apagar sobras')
  })

  it('lista as sobras com o tamanho, soma o total e entra no resumo do disco', async () => {
    server = stubModelsServer({ leftovers: [LEFTOVER_FILE, LEFTOVER_DIR] })
    await openModels()
    const items = wrapper!.findAll('[aria-label="Sobras encontradas"] li').map((item) => item.text())
    expect(items).toEqual(['velho/modelo.bin: 2,0 MB', 'restos/: 1,0 MB'])
    expect(wrapper!.find('[data-testid="leftovers-total"]').text()).toBe('2 item(ns), 3,0 MB')
    expect(wrapper!.find('[data-testid="models-summary"]').text()).toContain('Sobras: 3,0 MB')
  })

  it('Apagar sobras confirma com a lista que a pessoa viu e manda só esses caminhos', async () => {
    server = stubModelsServer({ leftovers: [LEFTOVER_FILE, LEFTOVER_DIR] })
    await openModels()
    await buttonLabelled(wrapper!, 'Apagar sobras').trigger('click')
    await flushPromises()

    expect(dialog()!.textContent).toContain('Apagar sobras?')
    expect(dialog()!.textContent).toContain('Vai apagar 2 item(ns) que nenhum modelo do DMaker usa e liberar 3,0 MB.')
    expect(dialog()!.textContent).toContain('velho/modelo.bin: 2,0 MB')
    expect(callsTo(server.calls, 'POST', '/api/models/prune')).toHaveLength(0)

    await answer(true)
    expect(callsTo(server.calls, 'POST', '/api/models/prune')[0]!.body).toEqual({
      confirm: true,
      paths: ['velho/modelo.bin', 'restos'],
    })
    expect(wrapper!.text()).not.toContain('Apagar sobras')
    expect(toastTitles()).toContain('Sobras apagadas')
  })

  it('Cancelar o diálogo das sobras não apaga nada', async () => {
    server = stubModelsServer({ leftovers: [LEFTOVER_FILE] })
    await openModels()
    await buttonLabelled(wrapper!, 'Apagar sobras').trigger('click')
    await flushPromises()
    await answer(false)
    expect(callsTo(server.calls, 'POST', '/api/models/prune')).toHaveLength(0)
    expect(wrapper!.findAll('[aria-label="Sobras encontradas"] li')).toHaveLength(1)
  })

  it('enquanto um modelo baixa, apagar sobras fica travado e diz por quê', async () => {
    server = stubModelsServer({ leftovers: [LEFTOVER_FILE] })
    await openModels()
    expect(buttonLabelled(wrapper!, 'Apagar sobras').attributes('disabled')).toBeUndefined()

    await rowButton('audioseal', 'Baixar')!.trigger('click')
    await flushPromises()
    expect(buttonLabelled(wrapper!, 'Apagar sobras').attributes('disabled')).toBeDefined()
    expect(wrapper!.text()).toContain('Espere o download terminar para apagar as sobras.')
  })

  it('se medir o disco falha, mostra o motivo e deixa tentar de novo', async () => {
    server = stubModelsServer({ inventoryError: 'Não consegui ler a pasta dos modelos.' })
    await openModels()
    expect(wrapper!.find('[role="alert"]').text()).toContain('Não consegui ler a pasta dos modelos.')
    expect(wrapper!.find('table').exists()).toBe(false)

    const before = callsTo(server.calls, 'GET', '/api/models').length
    await buttonLabelled(wrapper!, 'Tentar de novo').trigger('click')
    await flushPromises()
    expect(callsTo(server.calls, 'GET', '/api/models')).toHaveLength(before + 1)
  })

  it('não usa travessão em nenhum texto da tela', async () => {
    server = stubModelsServer({ leftovers: [LEFTOVER_FILE] })
    await openModels()
    expect(wrapper!.text()).not.toMatch(/[—–]/)
  })
})
