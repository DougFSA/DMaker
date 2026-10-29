import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { editorSchema, outputFile, projectDetail, projectSpec, timelineItem, timelineView } from '@/test/editorFixtures'
import { reply, routedFetch, type RoutedFetch } from '@/test/routedFetch'
import { useToastsStore } from './toasts'
import { useEditorStore, VIEW_REFRESH_DELAY_MS } from './editor'

let fetch: RoutedFetch

function serve(extra: Record<string, unknown> = {}): RoutedFetch {
  fetch = routedFetch({
    'GET /api/projects/demo': () => projectDetail(),
    'GET /api/schema': editorSchema,
    'GET /api/transitions': { curves: ['linear'], transitions: [{ name: 'fade', kind: 'xfade', summary: '' }] },
    'POST /api/projects/demo/timeline': () => timelineView(),
    'PUT /api/projects/demo': { ok: true, spec_path: 'x' },
    ...extra,
  })
  return fetch
}

async function opened() {
  const store = useEditorStore()
  await store.open('demo')
  return store
}

beforeEach(() => {
  setActivePinia(createPinia())
  // só os temporizadores: a leitura da resposta do fetch falso não pode ficar presa ao relógio de mentira
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('abrir o projeto', () => {
  it('carrega a spec, as saídas e a vista, e começa sem "não salvo"', async () => {
    serve()
    const store = await opened()
    expect(store.status).toBe('ready')
    expect(store.name).toBe('demo')
    expect((store.spec?.timeline as unknown[]).length).toBe(2)
    expect(store.dirty).toBe(false)
    expect(store.view?.tracks[0]?.items).toHaveLength(2)
    expect(store.total).toBe(6)
    // a vista é calculada sobre a spec do projeto, sem os campos vazios
    expect(fetch.to('POST /api/projects/demo/timeline')).toHaveLength(1)
  })

  it('carrega o schema e as transições para os formulários', async () => {
    serve()
    const store = await opened()
    await flushPromises()
    expect(store.schema).toMatchObject({ $defs: expect.any(Object) })
    expect(store.transitions).toEqual(['fade'])
  })

  it('o schema que não carrega não derruba a abertura', async () => {
    serve({ 'GET /api/schema': reply(500, { detail: 'quebrou' }) })
    const store = await opened()
    await flushPromises()
    expect(store.status).toBe('ready')
    expect(store.schema).toBeNull()
    expect(store.referenceError).toContain('quebrou')
  })

  it('projeto que não existe fica como "missing"', async () => {
    serve({ 'GET /api/projects/demo': reply(404, { detail: 'não achei' }) })
    const store = await opened()
    expect(store.status).toBe('missing')
    expect(store.loadError).toContain('demo')
    expect(store.spec).toBeNull()
  })

  it('outro erro de rede fica como "failed" com a mensagem', async () => {
    serve({ 'GET /api/projects/demo': reply(500, { detail: 'disco cheio' }) })
    const store = await opened()
    expect(store.status).toBe('failed')
    expect(store.loadError).toBe('disco cheio')
  })

  it('spec inválida (422 com raw_spec) abre para consertar, com os erros, sem pedir a vista', async () => {
    const raw = { name: 'demo', timeline: [{ type: 'clip' }] }
    serve({
      'GET /api/projects/demo': reply(422, {
        detail: [{ loc: ['timeline', 0], msg: 'clipe precisa de src' }],
        raw_spec: raw,
      }),
    })
    const store = await opened()
    expect(store.status).toBe('ready')
    expect(store.specErrors).toEqual(['timeline,0: clipe precisa de src'])
    expect(store.dirty).toBe(false)
    expect(store.spec?.name).toBe('demo')
    expect(fetch.to('POST /api/projects/demo/timeline')).toHaveLength(0)
  })

  it('abrir o mesmo projeto de novo mantém a edição em andamento', async () => {
    serve()
    const store = await opened()
    store.setField('output.quality', 'draft')
    await store.open('demo')
    expect(store.dirty).toBe(true)
    expect((store.get('output.quality') as string)).toBe('draft')
  })

  it('abrir outro projeto recomeça do zero', async () => {
    serve({ 'GET /api/projects/outro': () => projectDetail({ name: 'outro' }) })
    const store = await opened()
    store.setField('output.quality', 'draft')
    store.select(['V1:0'])
    await store.open('outro')
    expect(store.name).toBe('outro')
    expect(store.dirty).toBe(false)
    expect(store.canUndo).toBe(false)
    expect(store.selection).toEqual([])
  })
})

describe('editar campos', () => {
  it('muda o campo e passa a valer "não salvo"; a mesma coisa de novo não muda nada', async () => {
    serve()
    const store = await opened()
    store.setField('timeline.0.speed', 1)
    expect(store.dirty).toBe(false)
    store.setField('timeline.0.speed', 2)
    expect(store.get('timeline.0.speed')).toBe(2)
    expect(store.dirty).toBe(true)
  })

  it('apagar um campo (undefined) tira a chave da spec', async () => {
    serve()
    const store = await opened()
    store.setField('timeline.0.end', undefined)
    expect(store.get('timeline.0')).not.toHaveProperty('end')
    expect(store.dirty).toBe(true)
  })

  it('completa o par do foco do enquadramento', async () => {
    serve()
    const store = await opened()
    store.setField('timeline.0.reframe.focus.0', 0.2)
    expect(store.get('timeline.0.reframe.focus')).toEqual([0.2, 0.5])
  })

  it('pede a vista nova só depois de 250 ms sem mudança, uma vez, com a spec podada', async () => {
    serve()
    const store = await opened()
    fetch.calls.length = 0
    store.setField('timeline.0.speed', 2)
    store.setField('timeline.0.speed', 3)
    store.setField('timeline.0.label', '')
    await vi.advanceTimersByTimeAsync(VIEW_REFRESH_DELAY_MS - 10)
    expect(fetch.to('POST /api/projects/demo/timeline')).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(20)
    await flushPromises()
    const calls = fetch.to('POST /api/projects/demo/timeline')
    expect(calls).toHaveLength(1)
    const sent = (calls[0]?.body as { spec: { timeline: Array<Record<string, unknown>> } }).spec
    expect(sent.timeline[0]?.speed).toBe(3)
    expect(sent.timeline[0]).not.toHaveProperty('label') // vazio não vai
  })

  it('erro ao recalcular a vista (spec incompleta) vira aviso e a vista anterior fica', async () => {
    serve()
    const store = await opened()
    fetch.set('POST /api/projects/demo/timeline', reply(422, { detail: 'clipe precisa de src' }))
    store.setField('timeline.0.src', '')
    await vi.advanceTimersByTimeAsync(VIEW_REFRESH_DELAY_MS + 5)
    await flushPromises()
    expect(store.viewError).toBe('clipe precisa de src')
    expect(store.view?.tracks[0]?.items).toHaveLength(2)
  })

  it('uma resposta atrasada da vista não sobrescreve a mais nova', async () => {
    serve()
    const store = await opened()
    const late: Array<(value: unknown) => void> = []
    let calls = 0
    fetch.set('POST /api/projects/demo/timeline', () => {
      calls += 1
      // o primeiro pedido fica esperando; o segundo responde na hora
      return calls === 1 ? new Promise((resolve) => late.push(resolve)) : timelineView([timelineItem(0)])
    })
    const first = store.refreshView()
    await flushPromises()
    await store.refreshView()
    expect(store.view?.tracks[0]?.items).toHaveLength(1)
    late[0]?.(timelineView([timelineItem(0), timelineItem(1), timelineItem(2)]))
    await first
    expect(store.view?.tracks[0]?.items).toHaveLength(1)
  })

  it('mutate registra um passo, e se nada mudou não registra nada', async () => {
    serve()
    const store = await opened()
    store.mutate(() => undefined)
    expect(store.canUndo).toBe(false)
    const result = store.mutate((draft) => {
      ;(draft.timeline as unknown[]).pop()
      return 'tirou'
    })
    expect(result).toBe('tirou')
    expect(store.canUndo).toBe(true)
    expect((store.get('timeline') as unknown[]).length).toBe(1)
  })

  it('replaceSpec troca a spec inteira, normalizada, e vale um passo', async () => {
    serve()
    const store = await opened()
    store.replaceSpec({ name: 'demo', timeline: [{ type: 'card', title: 'só um' }] })
    expect((store.get('timeline') as unknown[]).length).toBe(1)
    expect(store.get('overlays')).toEqual([])
    expect(store.dirty).toBe(true)
    store.undo()
    expect((store.get('timeline') as unknown[]).length).toBe(2)
  })
})

describe('desfazer e refazer', () => {
  it('voltar ao ponto salvo tira o "não salvo"', async () => {
    serve()
    const store = await opened()
    store.setField('output.quality', 'draft')
    expect(store.dirty).toBe(true)
    expect(store.undo()).toBe(true)
    expect(store.get('output.quality')).toBe('high')
    expect(store.dirty).toBe(false)
    expect(store.canRedo).toBe(true)
    expect(store.redo()).toBe(true)
    expect(store.get('output.quality')).toBe('draft')
    expect(store.dirty).toBe(true)
  })

  it('digitar várias vezes no mesmo campo é um passo só; outro campo é outro passo', async () => {
    serve()
    const store = await opened()
    store.setField('timeline.0.speed', 2)
    store.setField('timeline.0.speed', 2.5)
    store.setField('timeline.0.speed', 3)
    store.setField('timeline.0.volume', 2)
    store.undo() // volume
    expect(store.get('timeline.0.volume')).toBe(1)
    expect(store.get('timeline.0.speed')).toBe(3)
    store.undo() // speed inteiro
    expect(store.get('timeline.0.speed')).toBe(1)
    expect(store.canUndo).toBe(false)
  })

  it('depois de desfazer, o campo mexido de novo vira passo novo e apaga o refazer', async () => {
    serve()
    const store = await opened()
    store.setField('timeline.0.speed', 2)
    store.undo()
    store.setField('timeline.0.speed', 4)
    expect(store.canRedo).toBe(false)
    store.undo()
    expect(store.get('timeline.0.speed')).toBe(1)
  })

  it('guarda no máximo 100 passos', async () => {
    serve()
    const store = await opened()
    for (let i = 0; i < 130; i += 1) store.setField('timeline.0.fade_in', i + 1) // mesmo campo: um passo só
    let undone = 0
    while (store.undo()) undone += 1
    expect(undone).toBe(1)

    for (let i = 0; i < 130; i += 1) {
      store.mutate((draft) => {
        ;(draft.timeline as Array<Record<string, unknown>>)[0]!.label = `r${i}`
      })
    }
    undone = 0
    while (store.undo()) undone += 1
    expect(undone).toBe(100)
  })

  it('desfazer refaz a vista na hora, sem esperar os 250 ms', async () => {
    serve()
    const store = await opened()
    store.setField('output.quality', 'draft')
    fetch.calls.length = 0
    store.undo()
    await flushPromises()
    expect(fetch.to('POST /api/projects/demo/timeline')).toHaveLength(1)
  })
})

describe('salvar', () => {
  it('grava a spec sem os campos vazios e zera o "não salvo"', async () => {
    serve()
    const store = await opened()
    store.setField('timeline.0.label', 'abertura')
    store.setField('timeline.1.subtitle', '')
    expect(await store.save()).toBe(true)
    const put = fetch.to('PUT /api/projects/demo')[0]
    const sent = put?.body as { timeline: Array<Record<string, unknown>> }
    expect(sent.timeline[0]?.label).toBe('abertura')
    expect(sent.timeline[1]).not.toHaveProperty('subtitle')
    expect(store.dirty).toBe(false)
    expect(useToastsStore().items.at(-1)?.title).toBe('Projeto salvo')
  })

  it('o que muda enquanto salva continua "não salvo"', async () => {
    serve()
    const store = await opened()
    store.setField('output.quality', 'draft')
    const saving = store.save()
    store.setField('output.quality', 'medium')
    await saving
    expect(store.dirty).toBe(true)
  })

  it('erro do servidor fica em saveError e a spec continua "não salva"', async () => {
    serve({ 'PUT /api/projects/demo': reply(422, { detail: [{ loc: ['timeline', 0, 'src'], msg: 'obrigatório' }] }) })
    const store = await opened()
    store.setField('timeline.0.src', '')
    expect(await store.save()).toBe(false)
    expect(store.saveError).toContain('obrigatório')
    expect(store.dirty).toBe(true)
    expect(useToastsStore().items.at(-1)?.tone).toBe('error')
  })

  it('consertar o JSON de uma spec inválida e salvar libera os erros, a vista e as saídas', async () => {
    let valid = false
    serve({
      'GET /api/projects/demo': () =>
        valid
          ? projectDetail({ outputs: [outputFile()], captions_exists: true })
          : reply(422, { detail: [{ loc: ['timeline'], msg: 'vazia' }], raw_spec: { name: 'demo', timeline: [] } }),
    })
    const store = await opened()
    expect(store.specErrors).toHaveLength(1)
    expect(store.outputs).toEqual([])
    valid = true
    store.replaceSpec(projectSpec())
    await vi.advanceTimersByTimeAsync(VIEW_REFRESH_DELAY_MS + 5)
    await flushPromises()
    expect(store.specErrors).toEqual([]) // a vista foi montada, então a spec vale
    expect(await store.save()).toBe(true)
    expect(store.outputs).toHaveLength(1) // as saídas e as legendas, que o 422 não deu, vieram depois de salvar
    expect(store.captionsExists).toBe(true)
  })
})

describe('operações da linha do tempo', () => {
  const afterSplit = {
    spec: { ...projectSpec(), timeline: [{ type: 'card', title: 'a' }, { type: 'card', title: 'b' }, { type: 'card', title: 'c' }] },
    timeline: timelineView([timelineItem(0), timelineItem(1), timelineItem(2)]),
  }

  it('manda a spec podada e a operação, e adota a spec e a vista que voltam', async () => {
    serve({ 'POST /api/projects/demo/edit': afterSplit })
    const store = await opened()
    store.setField('timeline.0.label', '')
    expect(await store.applyOp({ type: 'split', index: 0, at: 1 })).toBe(true)
    const sent = fetch.to('POST /api/projects/demo/edit')[0]?.body as { spec: { timeline: unknown[] }; op: unknown }
    expect(sent.op).toEqual({ type: 'split', index: 0, at: 1 })
    expect(sent.spec.timeline[0]).not.toHaveProperty('label')
    expect((store.get('timeline') as unknown[]).length).toBe(3)
    expect(store.view?.tracks[0]?.items).toHaveLength(3)
    expect(store.dirty).toBe(true)
  })

  it('a operação entra no desfazer', async () => {
    serve({ 'POST /api/projects/demo/edit': afterSplit })
    const store = await opened()
    await store.applyOp({ type: 'split', index: 0, at: 1 })
    expect(store.canUndo).toBe(true)
    store.undo()
    expect((store.get('timeline') as unknown[]).length).toBe(2)
    expect(store.dirty).toBe(false)
  })

  it('erro do servidor avisa, devolve false e não mexe na spec', async () => {
    serve({ 'POST /api/projects/demo/edit': reply(400, { detail: 'corte fora do trecho' }) })
    const store = await opened()
    const before = JSON.stringify(store.spec)
    expect(await store.applyOp({ type: 'split', index: 0, at: 99 })).toBe(false)
    expect(JSON.stringify(store.spec)).toBe(before)
    expect(store.canUndo).toBe(false)
    expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'error', description: 'corte fora do trecho' })
  })

  it('várias operações seguidas entram em fila: cada uma parte da spec que a anterior deixou', async () => {
    let step = 0
    serve({
      'POST /api/projects/demo/edit': (call: { body: unknown }) => {
        step += 1
        const received = (call.body as { spec: { timeline: unknown[] } }).spec.timeline.length
        return {
          spec: { ...projectSpec(), timeline: Array.from({ length: received + 1 }, () => ({ type: 'card', title: 'x' })) },
          timeline: timelineView(Array.from({ length: received + 1 }, (_, i) => timelineItem(i))),
        }
      },
    })
    const store = await opened()
    const results = await Promise.all([
      store.applyOp({ type: 'duplicate', index: 0 }),
      store.applyOp({ type: 'duplicate', index: 0 }),
      store.applyOp({ type: 'duplicate', index: 0 }),
    ])
    expect(results).toEqual([true, true, true])
    expect(step).toBe(3)
    expect((store.get('timeline') as unknown[]).length).toBe(5) // 2 + 3
  })
})

describe('cursor e seleção', () => {
  it('o cursor fica entre 0 e a duração do vídeo', async () => {
    serve()
    const store = await opened()
    store.setPlayhead(2.5)
    expect(store.playhead).toBe(2.5)
    store.setPlayhead(-3)
    expect(store.playhead).toBe(0)
    store.setPlayhead(99)
    expect(store.playhead).toBe(6)
  })

  it('seleciona itens sem repetir e devolve a trilha de cada um', async () => {
    serve()
    const store = await opened()
    store.select(['V1:1', 'V1:1', 'V1:0'])
    expect(store.selection).toEqual(['V1:1', 'V1:0'])
    expect(store.selectedItems.map((s) => [s.trackId, s.item.id])).toEqual([
      ['V1', 'V1:0'],
      ['V1', 'V1:1'],
    ])
    expect(store.findItem('V1:1')?.item.index).toBe(1)
    expect(store.findItem('nada')).toBeNull()
    store.clearSelection()
    expect(store.selectedItems).toEqual([])
  })

  it('o que sumiu da vista sai da seleção, e o cursor volta para dentro do vídeo', async () => {
    serve()
    const store = await opened()
    store.select(['V1:0', 'V1:1'])
    store.setPlayhead(5.5)
    fetch.set('POST /api/projects/demo/timeline', () => timelineView([timelineItem(0)]))
    await store.refreshView()
    expect(store.selection).toEqual(['V1:0'])
    expect(store.playhead).toBe(3)
  })
})

describe('fechar', () => {
  it('fechar limpa o projeto e cancela a vista que estava marcada', async () => {
    serve()
    const store = await opened()
    store.setField('output.quality', 'draft')
    fetch.calls.length = 0
    store.close()
    await vi.advanceTimersByTimeAsync(VIEW_REFRESH_DELAY_MS * 2)
    expect(store.status).toBe('idle')
    expect(store.spec).toBeNull()
    expect(fetch.to('POST /api/projects/demo/timeline')).toHaveLength(0)
  })
})
