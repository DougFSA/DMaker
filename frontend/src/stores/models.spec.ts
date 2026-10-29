import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource } from '@/test/fetch'
import { DEFAULT_MODELS, LEFTOVER_FILE, stubModelsServer, type ModelsServer } from '@/test/modelsServer'
import { callsTo } from '@/test/speechServer'
import { useConfirmStore } from './confirm'
import { useModelsStore } from './models'
import { useToastsStore } from './toasts'

const [OMNIVOICE, DEMUCS, AUDIOSEAL] = DEFAULT_MODELS as [(typeof DEFAULT_MODELS)[number], (typeof DEFAULT_MODELS)[number], (typeof DEFAULT_MODELS)[number]]

let server: ModelsServer

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

describe('medir', () => {
  it('guarda o inventário que o servidor mediu', async () => {
    server = stubModelsServer({ leftovers: [LEFTOVER_FILE] })
    const models = useModelsStore()
    await models.load()
    expect(models.inventory!.models.map((model) => model.id)).toEqual(['omnivoice', 'demucs-htdemucs', 'audioseal'])
    expect(models.inventory!.leftovers).toEqual([LEFTOVER_FILE])
    expect(models.failure).toBe('')
    expect(models.loading).toBe(false)
  })

  it('a falha fica à vista e o inventário anterior continua', async () => {
    server = stubModelsServer()
    const models = useModelsStore()
    await models.load()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'disco indisponível' }), { status: 500 })))
    await models.load()
    expect(models.failure).toContain('disco indisponível')
    expect(models.inventory).not.toBeNull()
  })
})

describe('baixar', () => {
  it('um segundo clique durante o download não pede outro', async () => {
    server = stubModelsServer()
    const models = useModelsStore()
    void models.download(AUDIOSEAL)
    await flushPromises()
    expect(models.isBusy('audioseal')).toBe(true)
    expect(models.anyDownloading).toBe(true)

    await models.download(AUDIOSEAL)
    expect(callsTo(server.calls, 'POST', '/api/models/audioseal/download')).toHaveLength(1)
    expect(models.isBusy('omnivoice')).toBe(false)
  })

  it('termina avisando e medindo o disco, e libera o modelo', async () => {
    server = stubModelsServer()
    const models = useModelsStore()
    const pending = models.download(AUDIOSEAL)
    await flushPromises()
    server.setState('audioseal', 'installed')
    FakeEventSource.latest().emit({ kind: 'end', t: 1, status: 'done', error: null, result: AUDIOSEAL })
    await pending

    expect(models.isBusy('audioseal')).toBe(false)
    expect(models.anyDownloading).toBe(false)
    expect(models.inventory!.models.find((model) => model.id === 'audioseal')!.state).toBe('installed')
    expect(useToastsStore().items.map((toast) => toast.title)).toEqual(['Modelo baixado'])
  })

  it('o servidor recusar o início fica no andamento do modelo, sem aviso de baixado', async () => {
    server = stubModelsServer()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Falta espaço no disco.' }), { status: 400 })))
    const models = useModelsStore()
    await models.download(AUDIOSEAL)
    expect(models.downloads['audioseal']!.error).toBe('Falta espaço no disco.')
    expect(models.isBusy('audioseal')).toBe(false)
    expect(useToastsStore().items).toEqual([])
  })
})

describe('apagar', () => {
  it('não apaga sem a confirmação, e a pergunta traz o aviso do servidor', async () => {
    server = stubModelsServer()
    const confirm = useConfirmStore()
    const models = useModelsStore()
    const pending = models.remove(OMNIVOICE)
    await flushPromises()

    expect(confirm.current!.options.title).toBe('Apagar OmniVoice?')
    expect(confirm.current!.options.tone).toBe('danger')
    expect(confirm.current!.options.warning).toContain('Vai apagar OmniVoice e liberar 3,04 GB.')
    expect(models.isBusy('omnivoice')).toBe(true)

    confirm.answer(false)
    await pending
    expect(callsTo(server.calls, 'POST', '/api/models/omnivoice/remove')).toHaveLength(0)
    expect(models.isBusy('omnivoice')).toBe(false)
  })

  it('não apaga um modelo que está baixando', async () => {
    server = stubModelsServer()
    const models = useModelsStore()
    void models.download(DEMUCS)
    await flushPromises()
    await models.remove(DEMUCS)
    expect(callsTo(server.calls, 'GET', '/api/models/demucs-htdemucs/removal')).toHaveLength(0)
  })
})

describe('sobras', () => {
  it('sem sobras não pergunta nem chama o servidor', async () => {
    server = stubModelsServer()
    const confirm = useConfirmStore()
    const models = useModelsStore()
    await models.load()
    await models.prune()
    expect(confirm.current).toBeNull()
    expect(callsTo(server.calls, 'POST', '/api/models/prune')).toHaveLength(0)
  })

  it('manda só as sobras que a pessoa viu, depois de confirmar', async () => {
    server = stubModelsServer({ leftovers: [LEFTOVER_FILE] })
    const confirm = useConfirmStore()
    const models = useModelsStore()
    await models.load()
    const pending = models.prune()
    await flushPromises()
    expect(confirm.current!.options.title).toBe('Apagar sobras?')
    confirm.answer(true)
    await pending

    expect(callsTo(server.calls, 'POST', '/api/models/prune')[0]!.body).toEqual({ confirm: true, paths: ['velho/modelo.bin'] })
    expect(models.inventory!.leftovers).toEqual([])
    expect(models.pruning).toBe(false)
  })
})
