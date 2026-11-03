import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PickedMedia } from '@/components/media/MediaPicker.vue'
import { useConfirmStore } from '@/stores/confirm'
import { DUB_PATH, dubProject, renderResult, stubDubServer, type DubServer } from '@/test/dubServer'
import { FakeEventSource } from '@/test/fetch'
import { callsTo, CLIP } from '@/test/speechServer'
import { useDubbingStore, type DubOutcome } from './dubbing'

let server: DubServer

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  server = stubDubServer()
})
afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

const PICKED: PickedMedia = { path: CLIP, name: 'entrevista.mp4', origin: 'upload', entry: null }

const finish = async (result: unknown, status = 'done', error: string | null = null) => {
  FakeEventSource.latest().emit({ kind: 'end', t: 1, status, error, result })
  await flushPromises()
}

/** A store com o projeto de dublagem do servidor aberto. */
async function openedStore() {
  const dub = useDubbingStore()
  await dub.loadSaved()
  dub.savedChoice = DUB_PATH
  await dub.openSaved()
  return dub
}

describe('useDubbingStore: preparar', () => {
  it('só prepara com arquivo e idiomas diferentes', () => {
    const dub = useDubbingStore()
    expect(dub.canPrepare).toBe(false)
    dub.media = PICKED
    expect(dub.canPrepare).toBe(true)
    dub.targetLanguage = 'pt-BR'
    expect(dub.sameLanguages).toBe(true)
    expect(dub.canPrepare).toBe(false)
  })

  it('prepara com os campos do formulário e abre o projeto no fim', async () => {
    const dub = useDubbingStore()
    dub.media = PICKED
    dub.speakerMode = 'per_segment'
    dub.keepDb = -10
    const preparing = dub.prepare()
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/dub/prepare')[0]!.body).toMatchObject({ path: CLIP, speaker_mode: 'per_segment', keep_original_db: -10, num_speakers: null })
    expect(dub.preparation.running).toBe(true)
    expect(dub.busy).toBe(true)
    await finish(dubProject({ fit_mode: 'misto', voice: 'dora' }))
    await preparing
    expect(dub.project?.project).toBe(DUB_PATH)
    expect(dub.rows).toHaveLength(3)
    expect(dub.fitMode).toBe('misto')
    expect(dub.voice).toBe('dora')
    expect(dub.busy).toBe(false)
    expect(dub.dirty).toBe(false)
  })

  it('guarda de onde veio o arquivo (o projeto aberto) só quando ele é da mídia do projeto', async () => {
    localStorage.setItem('dmaker.currentProject', 'demo')
    setActivePinia(createPinia())
    const dub = useDubbingStore()
    const entry = { id: 'file:' + CLIP, kind: 'clip' as const, label: 'entrevista.mp4', path: CLIP, src: CLIP }
    dub.media = { path: CLIP, name: 'entrevista.mp4', origin: 'project', entry }
    const preparing = dub.prepare()
    await flushPromises()
    await finish(dubProject())
    await preparing
    expect(dub.entry).toEqual(entry)
    expect(dub.entryProject).toBe('demo')

    dub.media = PICKED
    const again = dub.prepare()
    await flushPromises()
    await finish(dubProject())
    await again
    expect(dub.entry).toBeNull()
    expect(dub.entryProject).toBeNull()
  })

  describe('quando a dublagem já existe', () => {
    const preparing = async () => {
      server = stubDubServer({ existingDubbing: DUB_PATH, project: null })
      const dub = useDubbingStore()
      dub.media = PICKED
      const pending = dub.prepare()
      await flushPromises()
      return { dub, pending }
    }

    it('o servidor recusa (409), a pessoa vê o que se perde e o sim repete o pedido com `overwrite`', async () => {
      const { dub, pending } = await preparing()
      const prepares = () => callsTo(server.calls, 'POST', '/api/dub/prepare')
      expect(prepares()).toHaveLength(1)
      expect(prepares()[0]!.body).not.toHaveProperty('overwrite')

      const asked = useConfirmStore().current
      expect(asked?.options.title).toBe('Preparar a dublagem de novo?')
      expect(asked?.options.description).toContain('entrevista.en.dub.json')
      expect(asked?.options.warning).toContain('apaga as traduções que você revisou')
      expect(dub.preparation.running).toBe(false) // não há job: a pergunta vem antes do andamento
      expect(dub.busy).toBe(true) // e, com ela na tela, nada mais se mexe

      useConfirmStore().answer(true)
      await flushPromises()
      expect(prepares()).toHaveLength(2)
      expect(prepares()[1]!.body).toMatchObject({ path: CLIP, overwrite: true })

      await finish(dubProject())
      await pending
      expect(dub.project?.project).toBe(DUB_PATH)
      expect(dub.preparation.error).toBe('')
    })

    it('o não deixa tudo como está: um pedido só, sem job, sem erro, sem "parado a pedido" e com o resultado antigo à vista', async () => {
      server = stubDubServer({ existingDubbing: DUB_PATH, project: null })
      const dub = useDubbingStore()
      dub.media = PICKED
      dub.outcome = { ...(renderResult() as unknown as DubOutcome), stamp: 1 }
      const pending = dub.prepare()
      await flushPromises()

      useConfirmStore().answer(false)
      await pending
      expect(dub.outcome?.stamp).toBe(1)

      expect(callsTo(server.calls, 'POST', '/api/dub/prepare')).toHaveLength(1)
      expect(FakeEventSource.instances).toHaveLength(0)
      expect(dub.project).toBeNull()
      expect(dub.preparation.running).toBe(false)
      expect(dub.preparation.error).toBe('')
      expect(dub.preparation.cancelled).toBe(false)
      expect(dub.busy).toBe(false)
      expect(dub.canPrepare).toBe(true)
    })

    it('outro erro do servidor não vira pergunta: aparece como erro', async () => {
      server = stubDubServer({ startReply: { status: 404, body: { detail: 'Arquivo não encontrado.' } } })
      const dub = useDubbingStore()
      dub.media = PICKED
      await dub.prepare()
      expect(useConfirmStore().current).toBeNull()
      expect(dub.preparation.error).toBe('Arquivo não encontrado.')
    })

    it('uma dublagem nova não pergunta nada', async () => {
      const dub = useDubbingStore()
      dub.media = PICKED
      const pending = dub.prepare()
      await flushPromises()
      expect(useConfirmStore().current).toBeNull()
      await finish(dubProject())
      await pending
      expect(dub.project?.project).toBe(DUB_PATH)
    })
  })

  it('a preparação cancelada não abre projeto nenhum', async () => {
    const dub = useDubbingStore()
    dub.media = PICKED
    const preparing = dub.prepare()
    await flushPromises()
    await finish(null, 'cancelled')
    await preparing
    expect(dub.project).toBeNull()
    expect(dub.preparation.cancelled).toBe(true)
  })
})

describe('useDubbingStore: revisar', () => {
  it('abre uma dublagem salva e mostra o projeto como o servidor o tem', async () => {
    const dub = await openedStore()
    expect(dub.project?.segments).toHaveLength(3)
    expect(dub.rows[1]).toMatchObject({ id: 's2', locked: true })
    expect(dub.entry).toBeNull()
  })

  it('"dirty" acompanha a tradução, a trava, o falante e as opções do projeto', async () => {
    const dub = await openedStore()
    expect(dub.dirty).toBe(false)
    dub.rows = dub.rows.map((row, index) => (index === 0 ? { ...row, text: 'Hi.' } : row))
    expect(dub.dirty).toBe(true)
    dub.rows = dub.rows.map((row, index) => (index === 0 ? { ...row, text: 'Hello everyone.' } : row))
    expect(dub.dirty).toBe(false)
    dub.keepDb = 15
    expect(dub.dirty).toBe(true)
    dub.keepDb = null
    dub.fitMode = 'video'
    expect(dub.dirty).toBe(true)
    dub.fitMode = 'voz'
    dub.voice = 'dora'
    expect(dub.dirty).toBe(true)
  })

  it('salvar manda o que a tela tem e a tela passa a mostrar o que o servidor guardou', async () => {
    const dub = await openedStore()
    dub.rows = dub.rows.map((row, index) => (index === 2 ? { ...row, text: '  See you!  ', locked: true } : row))
    await dub.saveTranslations()
    expect(server.lastSave()).toMatchObject({ project: DUB_PATH, segments: [{ id: 's1' }, { id: 's2' }, { id: 's3', text: 'See you!', locked: true }] })
    expect(dub.rows[2]!.text).toBe('See you!')
    expect(dub.dirty).toBe(false)
    expect(dub.saving).toBe(false)
  })

  it('se salvar falha, o texto digitado fica e o erro aparece', async () => {
    server = stubDubServer({ saveError: 'Falha ao gravar.' })
    const dub = await openedStore()
    dub.rows = dub.rows.map((row, index) => (index === 0 ? { ...row, text: 'Hi.' } : row))
    await dub.saveTranslations()
    expect(dub.actionError).toBe('Falha ao gravar.')
    expect(dub.rows[0]!.text).toBe('Hi.')
    expect(dub.dirty).toBe(true)
  })

  it('sem projeto aberto, nenhuma ação de projeto faz nada', async () => {
    const dub = useDubbingStore()
    await dub.saveTranslations()
    await dub.retranslate()
    await dub.render()
    expect(await dub.makeStems()).toBe('')
    expect(server.calls.filter((call) => call.method !== 'GET')).toEqual([])
  })

  it('só um trabalho por vez: enquanto traduz, não gera nem salva', async () => {
    const dub = await openedStore()
    const translating = dub.retranslate()
    await flushPromises()
    expect(dub.retranslation.running).toBe(true)
    expect(dub.canChangeProject).toBe(false)
    await dub.render()
    expect(callsTo(server.calls, 'POST', '/api/dub/render')).toHaveLength(0)
    await finish(dubProject())
    await translating
    expect(dub.canChangeProject).toBe(true)
  })
})

describe('useDubbingStore: gerar e exportar', () => {
  it('gerar guarda o resultado e a situação de cada fala', async () => {
    const dub = await openedStore()
    dub.draft = true
    const rendering = dub.render()
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/dub/render')[0]!.body).toEqual({ project: DUB_PATH, draft: true })
    await finish(renderResult())
    await rendering
    expect(dub.outcome?.output).toBe('X:/saida/dublagem/entrevista.en.mp4')
    expect(dub.reports.s3?.status).toBe('stretched')
    expect(Object.keys(dub.reports)).toEqual(['s1', 's2', 's3'])
  })

  it('um resultado antigo some quando a pessoa gera de novo ou prepara outra dublagem', async () => {
    const dub = await openedStore()
    const first = dub.render()
    await flushPromises()
    await finish(renderResult())
    await first
    expect(dub.outcome).not.toBeNull()
    const second = dub.render()
    await flushPromises()
    expect(dub.outcome).toBeNull()
    await finish(null, 'cancelled')
    await second
    expect(dub.reports).toEqual({})
  })

  it('exportar as trilhas devolve o endereço do .zip e deixa o resumo', async () => {
    const dub = await openedStore()
    const exporting = dub.makeStems()
    await flushPromises()
    await finish({ folder: 'f', files: ['a.wav'], zip: 'z', zip_url: '/api/dub/file?path=z&download=true', duration: 12.5, original_voice_db: null })
    expect(await exporting).toBe('/api/dub/file?path=z&download=true')
    expect(dub.stemsNote).toBe('Trilhas prontas (a.wav), cada uma com 12,50 s.')
  })

  it('trilhas que falham ou param não devolvem endereço', async () => {
    const dub = await openedStore()
    const exporting = dub.makeStems()
    await flushPromises()
    await finish(null, 'error', 'RuntimeError: sem espaço em disco')
    expect(await exporting).toBe('')
    expect(dub.stems.error).toBe('sem espaço em disco')
    expect(dub.stemsNote).toBe('')
  })
})
