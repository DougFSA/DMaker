import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  boxLayout,
  DISK_REVISION,
  editorSchema,
  outputFile,
  overlayBox,
  projectDetail,
  projectSpec,
  timelineItem,
  timelineView,
} from '@/test/editorFixtures'
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
    'POST /api/projects/demo/boxes': () => boxLayout(),
    'GET /api/projects/demo/revision': { revision: DISK_REVISION },
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

  describe('um comando de várias operações', () => {
    /** Cada chamada acrescenta um cartão à spec que recebeu, como as duplicações de um "duplicar tudo". */
    function growing(failAt = Infinity) {
      let calls = 0
      return (call: { body: unknown }) => {
        calls += 1
        if (calls === failAt) return reply(400, { detail: 'índice fora do intervalo' })
        const received = (call.body as { spec: { timeline: unknown[] } }).spec.timeline.length
        return {
          spec: { ...projectSpec(), timeline: Array.from({ length: received + 1 }, () => ({ type: 'card', title: 'x' })) },
          timeline: timelineView(Array.from({ length: received + 1 }, (_, i) => timelineItem(i))),
        }
      }
    }

    it('vale um passo só do desfazer, não um por operação', async () => {
      serve({ 'POST /api/projects/demo/edit': growing() })
      const store = await opened()
      const ok = await store.applyOps([
        { type: 'duplicate', index: 1 },
        { type: 'duplicate', index: 0 },
        { type: 'duplicate', index: 0 },
      ])
      expect(ok).toBe(true)
      expect((store.get('timeline') as unknown[]).length).toBe(5)
      store.undo()
      expect((store.get('timeline') as unknown[]).length).toBe(2)
      expect(store.canUndo).toBe(false)
      expect(store.dirty).toBe(false)
    })

    it('se uma falha, as seguintes não rodam e o que já foi feito fica registrado em um passo', async () => {
      serve({ 'POST /api/projects/demo/edit': growing(2) })
      const store = await opened()
      const ok = await store.applyOps([
        { type: 'duplicate', index: 0 },
        { type: 'duplicate', index: 0 },
        { type: 'duplicate', index: 0 },
      ])
      expect(ok).toBe(false)
      expect(fetch.to('POST /api/projects/demo/edit')).toHaveLength(2)
      expect((store.get('timeline') as unknown[]).length).toBe(3)
      expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'error', description: 'índice fora do intervalo' })
      store.undo()
      expect((store.get('timeline') as unknown[]).length).toBe(2)
    })

    it('se a primeira falha, nada entra no desfazer', async () => {
      serve({ 'POST /api/projects/demo/edit': growing(1) })
      const store = await opened()
      expect(await store.applyOps([{ type: 'remove', index: 0 }, { type: 'remove', index: 0 }])).toBe(false)
      expect(store.canUndo).toBe(false)
    })

    it('sem operações, devolve verdadeiro sem chamar o servidor', async () => {
      serve({ 'POST /api/projects/demo/edit': growing() })
      const store = await opened()
      expect(await store.applyOps([])).toBe(true)
      expect(fetch.to('POST /api/projects/demo/edit')).toHaveLength(0)
    })

    it('entra na mesma fila das operações avulsas', async () => {
      serve({ 'POST /api/projects/demo/edit': growing() })
      const store = await opened()
      const results = await Promise.all([
        store.applyOp({ type: 'duplicate', index: 0 }),
        store.applyOps([{ type: 'duplicate', index: 0 }, { type: 'duplicate', index: 0 }]),
      ])
      expect(results).toEqual([true, true])
      expect((store.get('timeline') as unknown[]).length).toBe(5)
    })
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

describe('arquivos ausentes', () => {
  it('um arquivo que a vista marcou como ausente (pelo src cru ou pelo caminho resolvido) é dado como ausente', async () => {
    const view = timelineView([
      timelineItem(0, { src: 'cam1.mp4', path: 'C:/projeto/cam1.mp4' }),
      timelineItem(1, { src: 'perdido.mp4', path: 'C:/projeto/perdido.mp4', missing: true }),
    ])
    serve({ 'POST /api/projects/demo/timeline': () => view })
    const store = await opened()
    expect(store.isMissing('perdido.mp4')).toBe(true)
    expect(store.isMissing('C:/projeto/perdido.mp4')).toBe(true)
    expect(store.isMissing('cam1.mp4')).toBe(false)
    expect(store.isMissing('outro.mp4')).toBe(false)
  })

  it('uma fonte de um arquivo só marcada ausente conta; a de várias partes não diz qual parte sumiu', async () => {
    const view = {
      ...timelineView(),
      sources: {
        mesa: { src: 'mesa.wav', parts: [], offset: 0, in_point: 0, path: 'C:/projeto/mesa.wav', missing: true },
        cam: { src: 'a.mp4', parts: ['a.mp4', 'b.mp4'], offset: 0, in_point: 0, path: 'C:/projeto/a.mp4', missing: true },
      },
    }
    serve({ 'POST /api/projects/demo/timeline': () => view })
    const store = await opened()
    expect(store.isMissing('mesa.wav')).toBe(true)
    expect(store.isMissing('a.mp4')).toBe(false)
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

describe('digitação em espera (os campos com atraso do painel Filtros)', () => {
  /** Um campo de mentira: guarda o que foi "digitado" e só grava quando pedem, como o SpecField com atraso. */
  function laggingField(store: ReturnType<typeof useEditorStore>, path: string) {
    let waiting: unknown
    const flush = vi.fn(() => {
      if (waiting !== undefined) store.setField(path, waiting)
      waiting = undefined
    })
    const stop = store.onPendingEdits(flush)
    return { type: (value: unknown) => (waiting = value), flush, stop }
  }

  it('salvar grava antes o que ainda esperava, e o servidor recebe o valor digitado', async () => {
    serve()
    const store = await opened()
    const field = laggingField(store, 'timeline.0.speed')
    field.type(3)
    await store.save()
    expect(store.get('timeline.0.speed')).toBe(3)
    expect((fetch.to('PUT /api/projects/demo')[0]?.body as { timeline: Array<{ speed: number }> }).timeline[0]?.speed).toBe(3)
  })

  it('operar na linha do tempo e desfazer também gravam antes', async () => {
    serve({ 'POST /api/projects/demo/edit': { spec: projectSpec(), timeline: timelineView() } })
    const store = await opened()
    const field = laggingField(store, 'timeline.0.volume')
    field.type(2)
    await store.applyOp({ type: 'duplicate', index: 0 })
    expect((fetch.to('POST /api/projects/demo/edit')[0]?.body as { spec: { timeline: Array<{ volume: number }> } }).spec.timeline[0]?.volume).toBe(2)
    expect(field.flush).toHaveBeenCalledTimes(1)
    field.type(0.5)
    store.undo()
    expect(field.flush).toHaveBeenCalledTimes(2)
  })

  it('quem se desregistra deixa de ser chamado', async () => {
    serve()
    const store = await opened()
    const field = laggingField(store, 'timeline.0.speed')
    field.stop()
    store.flushPendingEdits()
    expect(field.flush).not.toHaveBeenCalled()
  })
})

describe('as caixas das sobreposições', () => {
  it('pede as caixas junto da vista, sobre a spec podada, e guarda a resposta', async () => {
    serve()
    const store = await opened()
    await flushPromises()
    expect(fetch.to('POST /api/projects/demo/boxes')).toHaveLength(1)
    expect(fetch.to('POST /api/projects/demo/boxes')[0]?.body).toMatchObject({ spec: { name: 'demo' } })
    expect(store.boxes?.width).toBe(1080)
    expect(store.boxes?.boxes[0]).toMatchObject({ index: 0, kind: 'text' })
    expect(store.boxesError).toBe('')
  })

  it('uma mudança na spec pede as caixas de novo, com o mesmo atraso da vista', async () => {
    serve()
    const store = await opened()
    await flushPromises()
    store.setField('overlays.0.text', 'Outro')
    store.setField('overlays.0.text', 'Outro título')
    await vi.advanceTimersByTimeAsync(VIEW_REFRESH_DELAY_MS - 1)
    expect(fetch.to('POST /api/projects/demo/boxes')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(2)
    await flushPromises()
    expect(fetch.to('POST /api/projects/demo/boxes')).toHaveLength(2)
    const sent = fetch.to('POST /api/projects/demo/boxes')[1]?.body as { spec: { overlays: Array<{ text: string }> } }
    expect(sent.spec.overlays[0]?.text).toBe('Outro título')
  })

  it('erro nas caixas (spec incompleta) fica em boxesError, mantém as anteriores e não atrapalha a vista', async () => {
    serve()
    const store = await opened()
    await flushPromises()
    fetch.set('POST /api/projects/demo/boxes', reply(422, { detail: 'texto vazio' }))
    await store.refreshView()
    await flushPromises()
    expect(store.boxesError).toBe('texto vazio')
    expect(store.boxes?.boxes).toHaveLength(1)
    expect(store.viewError).toBe('')
    expect(store.view).not.toBeNull()
  })

  it('servidor sem a rota ou resposta fora do contrato deixam o palco na posição aproximada', async () => {
    serve({ 'POST /api/projects/demo/boxes': { nada: true } })
    const store = await opened()
    await flushPromises()
    expect(store.boxes).toBeNull()
    expect(store.status).toBe('ready')
    fetch.set('POST /api/projects/demo/boxes', reply(404, { detail: 'não existe' }))
    await store.refreshBoxes()
    expect(store.boxes).toBeNull()
    expect(store.boxesError).toBe('não existe')
  })

  it('uma resposta atrasada não sobrescreve a mais nova', async () => {
    serve()
    const store = await opened()
    await flushPromises()
    const late: Array<(value: unknown) => void> = []
    let calls = 0
    fetch.set('POST /api/projects/demo/boxes', () => {
      calls += 1
      return calls === 1 ? new Promise((resolve) => late.push(resolve)) : boxLayout([overlayBox({ index: 0, left: 0.3 })])
    })
    const first = store.refreshBoxes()
    await flushPromises()
    await store.refreshBoxes()
    expect(store.boxes?.boxes[0]?.left).toBe(0.3)
    late[0]?.(boxLayout([overlayBox({ index: 0, left: 0.9 })]))
    await first
    expect(store.boxes?.boxes[0]?.left).toBe(0.3)
  })

  it('uma operação da linha do tempo também refaz as caixas', async () => {
    serve({ 'POST /api/projects/demo/edit': { spec: projectSpec(), timeline: timelineView() } })
    const store = await opened()
    await flushPromises()
    await store.applyOp({ type: 'duplicate', index: 0 })
    await flushPromises()
    expect(fetch.to('POST /api/projects/demo/boxes')).toHaveLength(2)
  })

  it('fechar o projeto apaga as caixas, e uma resposta que chega depois não as traz de volta', async () => {
    serve()
    const store = await opened()
    await flushPromises()
    let release: (value: unknown) => void = () => undefined
    fetch.set('POST /api/projects/demo/boxes', () => new Promise((resolve) => (release = resolve)))
    const pending = store.refreshBoxes()
    store.close()
    release(boxLayout())
    await pending
    expect(store.boxes).toBeNull()
  })
})

describe('a revisão do disco e o salvar', () => {
  it('guarda a revisão que veio ao abrir e a manda no If-Match do Salvar', async () => {
    serve({ 'PUT /api/projects/demo': { ok: true, spec_path: 'x', revision: 'rev-2' } })
    const store = await opened()
    expect(store.revision).toBe(DISK_REVISION)
    store.setField('output.quality', 'draft')
    expect(await store.save()).toBe(true)
    expect(fetch.to('PUT /api/projects/demo')[0]?.headers).toMatchObject({ 'If-Match': DISK_REVISION })
    // a gravação deu a revisão nova, e é ela que o próximo Salvar leva
    expect(store.revision).toBe('rev-2')
    store.setField('output.quality', 'medium')
    await store.save()
    expect(fetch.to('PUT /api/projects/demo')[1]?.headers).toMatchObject({ 'If-Match': 'rev-2' })
  })

  it('servidor sem revisão: grava como sempre, sem cabeçalho', async () => {
    serve({ 'GET /api/projects/demo': () => ({ ...projectDetail(), revision: undefined }) })
    const store = await opened()
    expect(store.revision).toBeNull()
    store.setField('output.quality', 'draft')
    expect(await store.save()).toBe(true)
    expect(fetch.to('PUT /api/projects/demo')[0]?.headers['If-Match']).toBeUndefined()
  })

  it('a spec inválida do disco também traz a revisão', async () => {
    serve({
      'GET /api/projects/demo': reply(422, { detail: [{ loc: ['timeline'], msg: 'vazia' }], raw_spec: { name: 'demo', timeline: [] }, revision: 'rev-9' }),
    })
    const store = await opened()
    expect(store.revision).toBe('rev-9')
  })

  it('salvar em silêncio não mostra o aviso "Projeto salvo"', async () => {
    serve()
    const store = await opened()
    store.setField('output.quality', 'draft')
    await store.save({ quiet: true })
    expect(store.dirty).toBe(false)
    expect(useToastsStore().items.map((toast) => toast.title)).not.toContain('Projeto salvo')
  })

  it('409: nada é gravado, o editor abre a escolha e a spec da pessoa fica como está', async () => {
    serve({ 'PUT /api/projects/demo': reply(409, { detail: 'O projeto mudou no disco desde a última leitura.', revision: 'rev-2' }) })
    const store = await opened()
    store.setField('output.quality', 'draft')
    expect(await store.save()).toBe(false)
    expect(store.conflict).toEqual({ revision: 'rev-2' })
    expect(store.saveError).toBe('')
    expect(store.dirty).toBe(true)
    expect(store.get('output.quality')).toBe('draft')
    expect(useToastsStore().items.filter((toast) => toast.tone === 'error')).toHaveLength(0)
  })

  it('"Manter o meu" grava por cima com a revisão do 409 e fecha a escolha', async () => {
    let attempt = 0
    serve({
      'PUT /api/projects/demo': () =>
        ++attempt === 1 ? reply(409, { detail: 'mudou', revision: 'rev-2' }) : { ok: true, spec_path: 'x', revision: 'rev-3' },
    })
    const store = await opened()
    store.setField('output.quality', 'draft')
    await store.save()
    expect(await store.keepMine()).toBe(true)
    const puts = fetch.to('PUT /api/projects/demo')
    expect(puts[1]?.headers).toMatchObject({ 'If-Match': 'rev-2' })
    expect(puts[1]?.body).toMatchObject({ output: { quality: 'draft' } })
    expect(store.conflict).toBeNull()
    expect(store.revision).toBe('rev-3')
    expect(store.dirty).toBe(false)
  })

  it('"Manter o meu" depois que o projeto sumiu do disco grava sem cabeçalho', async () => {
    let attempt = 0
    serve({
      'PUT /api/projects/demo': () => (++attempt === 1 ? reply(409, { detail: 'sumiu', revision: null }) : { ok: true, spec_path: 'x', revision: 'rev-1' }),
    })
    const store = await opened()
    store.setField('output.quality', 'draft')
    await store.save()
    expect(store.conflict).toEqual({ revision: null })
    await store.keepMine()
    expect(fetch.to('PUT /api/projects/demo')[1]?.headers['If-Match']).toBeUndefined()
    expect(store.conflict).toBeNull()
  })

  it('"Manter o meu" que leva outro 409 continua mostrando a escolha, com a revisão mais nova', async () => {
    let attempt = 0
    serve({ 'PUT /api/projects/demo': () => reply(409, { detail: 'mudou', revision: `rev-${++attempt + 1}` }) })
    const store = await opened()
    store.setField('output.quality', 'draft')
    await store.save()
    expect(await store.keepMine()).toBe(false)
    expect(store.conflict).toEqual({ revision: 'rev-3' })
  })

  it('"Recarregar do disco" descarta o que não foi salvo, vira um passo do desfazer e devolve a escolha', async () => {
    const onDisk = { ...projectSpec(), output: { ...(projectSpec().output as object), quality: 'max' } }
    serve({
      'PUT /api/projects/demo': reply(409, { detail: 'mudou', revision: 'rev-2' }),
    })
    const store = await opened()
    store.setField('output.quality', 'draft')
    await store.save()
    fetch.set('GET /api/projects/demo', () => projectDetail({ spec: onDisk as never, revision: 'rev-2' }))
    expect(await store.reloadFromConflict()).toBe(true)
    expect(store.get('output.quality')).toBe('max')
    expect(store.conflict).toBeNull()
    expect(store.dirty).toBe(false)
    expect(store.revision).toBe('rev-2')
    expect(useToastsStore().items.at(-1)?.title).toBe('Projeto recarregado do disco')
    // o que a pessoa tinha na tela volta pelo desfazer
    expect(store.undo()).toBe(true)
    expect(store.get('output.quality')).toBe('draft')
    expect(store.dirty).toBe(true)
  })
})

describe('a mudança de fora (consulta da revisão)', () => {
  const changedOnDisk = () => ({ ...projectSpec(), output: { ...(projectSpec().output as object), quality: 'max' } })

  async function openedWithDiskChange(revision = 'rev-2', spec: Record<string, unknown> = changedOnDisk()) {
    serve({
      'GET /api/projects/demo': () => projectDetail(),
    })
    const store = await opened()
    await flushPromises()
    fetch.set('GET /api/projects/demo/revision', { revision })
    fetch.set('GET /api/projects/demo', () => projectDetail({ spec: spec as never, revision }))
    return store
  }

  it('a mesma revisão não faz nada', async () => {
    serve()
    const store = await opened()
    fetch.calls.length = 0
    await store.checkDisk()
    expect(fetch.to('GET /api/projects/demo/revision')).toHaveLength(1)
    expect(fetch.to('GET /api/projects/demo')).toHaveLength(0)
    expect(store.conflict).toBeNull()
  })

  it('sem nada por salvar, recarrega sozinho como um passo do desfazer e avisa', async () => {
    const store = await openedWithDiskChange()
    await store.checkDisk()
    await flushPromises()
    expect(store.get('output.quality')).toBe('max')
    expect(store.revision).toBe('rev-2')
    expect(store.dirty).toBe(false)
    expect(store.conflict).toBeNull()
    expect(useToastsStore().items.at(-1)?.title).toBe('O projeto foi atualizado fora do editor')
    // Ctrl+Z devolve a versão que estava na tela (que agora difere do disco)
    expect(store.undo()).toBe(true)
    expect(store.get('output.quality')).toBe('high')
    expect(store.dirty).toBe(true)
  })

  it('a vista e as caixas acompanham a spec recarregada', async () => {
    const store = await openedWithDiskChange()
    fetch.calls.length = 0
    await store.checkDisk()
    await flushPromises()
    expect(fetch.to('POST /api/projects/demo/timeline')).toHaveLength(1)
    expect(fetch.to('POST /api/projects/demo/boxes')).toHaveLength(1)
  })

  it('a revisão mudou mas o conteúdo é o mesmo: atualiza a revisão sem passo nem aviso', async () => {
    const store = await openedWithDiskChange('rev-2', projectSpec())
    await store.checkDisk()
    await flushPromises()
    expect(store.revision).toBe('rev-2')
    expect(store.canUndo).toBe(false)
    expect(useToastsStore().items).toHaveLength(0)
  })

  it('com mudança não salva, mostra a escolha e não toca na spec nem no disco', async () => {
    const store = await openedWithDiskChange()
    store.setField('output.quality', 'draft')
    fetch.calls.length = 0
    await store.checkDisk()
    expect(store.conflict).toEqual({ revision: 'rev-2' })
    expect(store.get('output.quality')).toBe('draft')
    expect(store.dirty).toBe(true)
    expect(fetch.to('GET /api/projects/demo')).toHaveLength(0)
    expect(fetch.to('PUT /api/projects/demo')).toHaveLength(0)
  })

  it('com a escolha na tela, uma mudança nova só atualiza a revisão e nunca recarrega sozinho', async () => {
    const store = await openedWithDiskChange()
    store.setField('output.quality', 'draft')
    await store.checkDisk()
    // a pessoa desfaz tudo e o editor ficaria "limpo", mas a escolha continua para ela decidir
    store.undo()
    expect(store.dirty).toBe(false)
    fetch.set('GET /api/projects/demo/revision', { revision: 'rev-3' })
    fetch.calls.length = 0
    await store.checkDisk()
    expect(store.conflict).toEqual({ revision: 'rev-3' })
    expect(fetch.to('GET /api/projects/demo')).toHaveLength(0)
  })

  it('campo ainda em digitação conta como mudança não salva (a escolha, e não o recarregamento)', async () => {
    const store = await openedWithDiskChange()
    store.onPendingEdits(() => store.setField('output.quality', 'draft'))
    await store.checkDisk()
    expect(store.conflict).toEqual({ revision: 'rev-2' })
    expect(store.get('output.quality')).toBe('draft')
  })

  it('não consulta durante um gesto nem durante a gravação', async () => {
    const store = await openedWithDiskChange()
    fetch.calls.length = 0
    store.beginGesture()
    await store.checkDisk()
    expect(fetch.to('GET /api/projects/demo/revision')).toHaveLength(0)
    store.endGesture()
    await store.checkDisk()
    expect(fetch.to('GET /api/projects/demo/revision')).toHaveLength(1)
  })

  it('a resposta que chega durante um gesto é descartada, e a próxima consulta a trata', async () => {
    const store = await openedWithDiskChange()
    await store.checkDisk()
    await flushPromises()
    expect(store.revision).toBe('rev-2')
    let release: (value: unknown) => void = () => undefined
    fetch.set('GET /api/projects/demo/revision', () => new Promise((resolve) => (release = resolve)))
    const pending = store.checkDisk()
    store.beginGesture()
    release({ revision: 'rev-3' })
    await pending
    expect(store.revision).toBe('rev-2')
    expect(store.conflict).toBeNull()
  })

  it('descarta a resposta de uma consulta que saiu antes de uma gravação nossa', async () => {
    serve({ 'PUT /api/projects/demo': { ok: true, spec_path: 'x', revision: 'rev-2' } })
    const store = await opened()
    let release: (value: unknown) => void = () => undefined
    fetch.set('GET /api/projects/demo/revision', () => new Promise((resolve) => (release = resolve)))
    const pending = store.checkDisk()
    await flushPromises()
    store.setField('output.quality', 'draft')
    await store.save()
    // a consulta saiu antes da gravação e traz a revisão de antes dela: não pode virar "mudou por fora"
    release({ revision: DISK_REVISION })
    await pending
    expect(store.revision).toBe('rev-2')
    expect(store.conflict).toBeNull()
    expect(store.dirty).toBe(false)
  })

  it('uma consulta de cada vez', async () => {
    const store = await openedWithDiskChange()
    fetch.calls.length = 0
    let release: (value: unknown) => void = () => undefined
    fetch.set('GET /api/projects/demo/revision', () => new Promise((resolve) => (release = resolve)))
    const first = store.checkDisk()
    await store.checkDisk()
    expect(fetch.to('GET /api/projects/demo/revision')).toHaveLength(1)
    release({ revision: store.revision })
    await first
  })

  it('sem revisão conhecida na abertura, a primeira consulta só aprende a revisão', async () => {
    serve({ 'GET /api/projects/demo': () => ({ ...projectDetail(), revision: undefined }) })
    const store = await opened()
    expect(store.revision).toBeNull()
    await store.checkDisk()
    expect(store.revision).toBe(DISK_REVISION)
    expect(store.conflict).toBeNull()
    expect(useToastsStore().items).toHaveLength(0)
  })

  it('consulta que falha (servidor ocupado, projeto sumiu) é silenciosa', async () => {
    serve({ 'GET /api/projects/demo/revision': reply(404, { detail: 'sumiu' }) })
    const store = await opened()
    await store.checkDisk()
    expect(store.conflict).toBeNull()
    expect(useToastsStore().items).toHaveLength(0)
  })

  it('se não der para ler o disco, a escolha vai para a tela em vez de um erro a cada consulta', async () => {
    const store = await openedWithDiskChange()
    fetch.set('GET /api/projects/demo', reply(500, { detail: 'disco ocupado' }))
    await store.checkDisk()
    expect(store.conflict).toEqual({ revision: 'rev-2' })
    expect(useToastsStore().items.filter((toast) => toast.tone === 'error')).toHaveLength(0)
  })

  it('disco com spec inválida: abre para consertar na aba JSON, como na abertura', async () => {
    const store = await openedWithDiskChange()
    fetch.set(
      'GET /api/projects/demo',
      reply(422, { detail: [{ loc: ['timeline'], msg: 'vazia' }], raw_spec: { name: 'demo', timeline: [] }, revision: 'rev-2' }),
    )
    await store.checkDisk()
    await flushPromises()
    expect(store.specErrors).toEqual(['timeline: vazia'])
    expect(store.revision).toBe('rev-2')
    expect((store.spec?.timeline as unknown[]).length).toBe(0)
  })

  it('trocar de projeto durante a consulta não deixa a resposta velha valer no projeto novo', async () => {
    serve({ 'GET /api/projects/outro': () => projectDetail({ name: 'outro' }) })
    const store = await opened()
    let release: (value: unknown) => void = () => undefined
    fetch.set('GET /api/projects/demo/revision', () => new Promise((resolve) => (release = resolve)))
    const pending = store.checkDisk()
    await store.open('outro')
    release({ revision: 'rev-estranha' })
    await pending
    expect(store.name).toBe('outro')
    expect(store.revision).toBe(DISK_REVISION)
    expect(store.conflict).toBeNull()
  })
})

describe('a sobreposição escolhida', () => {
  it('escolher guarda o índice; "revelar" pede ao inspetor para mostrá-la', async () => {
    serve()
    const store = await opened()
    expect(store.selectedOverlay).toBeNull()
    store.selectOverlay(0)
    expect(store.selectedOverlay).toBe(0)
    expect(store.overlayReveal).toBe(0)
    store.selectOverlay(0, { reveal: true })
    store.selectOverlay(0, { reveal: true })
    expect(store.overlayReveal).toBe(2)
    store.selectOverlay(null, { reveal: true })
    expect(store.selectedOverlay).toBeNull()
    expect(store.overlayReveal).toBe(2)
  })

  it('um índice que deixou de existir (a sobreposição foi removida) não conta como escolhido', async () => {
    serve()
    const store = await opened()
    store.selectOverlay(0)
    store.mutate((spec) => {
      ;(spec.overlays as unknown[]).length = 0
    })
    expect(store.selectedOverlay).toBeNull()
  })

  it('abrir outro projeto começa sem escolha', async () => {
    serve({ 'GET /api/projects/outro': () => projectDetail({ name: 'outro' }) })
    const store = await opened()
    store.selectOverlay(0)
    await store.open('outro')
    expect(store.selectedOverlay).toBeNull()
  })
})
