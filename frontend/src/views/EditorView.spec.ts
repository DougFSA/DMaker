import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { editorRoutes } from '@/test/editorMount'
import { DISK_REVISION, outputFile, projectDetail, projectSpec } from '@/test/editorFixtures'
import { FakeEventSource } from '@/test/fetch'
import { mountRoute } from '@/test/routes'
import { reply, routedFetch } from '@/test/routedFetch'
import { useConfirmStore } from '@/stores/confirm'
import { DISK_CHECK_INTERVAL_MS, useEditorStore } from '@/stores/editor'
import { useJobsStore } from '@/stores/jobs'
import { useKeymapStore } from '@/stores/keymap'
import { usePlayerStore, useScheduler } from '@/stores/player'
import { useToastsStore } from '@/stores/toasts'
// os painéis carregam sob demanda; já importados, o teste não espera a compilação deles
import '@/components/editor/CaptionsPanel.vue'
import '@/components/editor/JsonPanel.vue'
import '@/components/editor/PlayerPanel.vue'
import '@/components/editor/PreviewPanel.vue'
import '@/components/editor/PropertiesPanel.vue'
import '@/components/editor/TimelinePanel.vue'

let mountedView: VueWrapper | null = null

beforeEach(() => {
  window.localStorage.clear()
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  // o relógio do player não anda sozinho: os testes só conferem a velocidade pedida
  useScheduler({ now: () => 0, request: () => 1, cancel: () => undefined })
})
afterEach(() => {
  // a tela escuta o teclado e o fechamento da aba na janela: sem desmontar, o teste seguinte a ouviria também
  mountedView?.unmount()
  mountedView = null
  useScheduler()
  vi.unstubAllGlobals()
})

/** Espera o editor terminar de abrir o projeto e os painéis carregarem. */
async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) await flushPromises()
}

async function openRoute(path: string, extra: Record<string, unknown> = {}) {
  const fetch = routedFetch({
    'GET /api/projects': [{ name: 'demo', spec_path: 'x', preset: 'instagram/reels', brand: 'medlycare', segments: 2 }],
    ...editorRoutes(projectSpec(), extra),
  })
  const mounted = await mountRoute(path)
  mountedView = mounted.wrapper
  await settle()
  return { ...mounted, fetch }
}

const buttonOf = (wrapper: VueWrapper, label: string) =>
  wrapper.findAll('button').find((candidate) => candidate.text() === label || candidate.attributes('aria-label') === label)

describe('EditorView (/editor/:name)', () => {
  it('abre o projeto: título, barra de ações, encaixes da bancada e as abas do inspetor', async () => {
    const { wrapper, router } = await openRoute('/editor/demo')
    expect(router.currentRoute.value.name).toBe('editor')
    expect(wrapper.find('h1').text()).toBe('Editor')
    expect(wrapper.text()).toContain('Projeto demo')
    for (const label of ['Salvar', 'Validar', 'Prévia', 'Render final', 'Exportar']) {
      expect(buttonOf(wrapper, label), label).toBeDefined()
    }
    expect(wrapper.findAll('[data-panel]').map((slot) => slot.attributes('data-panel')).slice(0, 4)).toEqual([
      'player',
      'filters',
      'timeline',
      'media',
    ])
    expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).toEqual(['Propriedades', 'JSON', 'Preview'])
    expect(wrapper.find('.properties').exists()).toBe(true)
  })

  it('o projeto aberto passa a ser o projeto atual do app', async () => {
    await openRoute('/editor/demo')
    expect(window.localStorage.getItem('dmaker.currentProject')).toBe('demo')
  })

  it('o nome do projeto vem da URL, com acentos e espaços', async () => {
    const { router } = await openRoute('/editor/meu%20video')
    expect(router.currentRoute.value.params.name).toBe('meu video')
  })

  it('o item do menu lateral (/editor, sem nome) pede para escolher um projeto', async () => {
    const { wrapper, router } = await openRoute('/editor')
    expect(router.currentRoute.value.params.name).toBeFalsy()
    expect(wrapper.text()).toContain('Escolha um projeto para editar.')
    expect(wrapper.find('a.item').attributes('href')).toBe('/editor/demo')
    expect(wrapper.find('[role="toolbar"]').exists()).toBe(false)
  })

  it('projeto que não existe mostra o aviso e o caminho de volta', async () => {
    const { wrapper } = await openRoute('/editor/demo', { 'GET /api/projects/demo': reply(404, { detail: 'não achei' }) })
    expect(wrapper.text()).toContain('Projeto não encontrado')
    expect(wrapper.find('a[href="/editor"]').exists()).toBe(true)
    expect(wrapper.find('[role="toolbar"]').exists()).toBe(false)
  })

  it('spec inválida abre direto na aba JSON, com os erros, para consertar e salvar', async () => {
    const { wrapper } = await openRoute('/editor/demo', {
      'GET /api/projects/demo': reply(422, {
        detail: [{ loc: ['timeline'], msg: 'precisa de ao menos um trecho' }],
        raw_spec: { name: 'demo', timeline: [] },
      }),
    })
    expect(wrapper.find('[role="tab"][data-state="active"]').text()).toBe('JSON')
    expect(wrapper.find('.invalid').text()).toContain('precisa de ao menos um trecho')
    expect(wrapper.find('[role="toolbar"]').text()).toContain('Spec inválida')
    expect(buttonOf(wrapper, 'Salvar')).toBeDefined()
  })

  it('Ctrl+S salva o projeto', async () => {
    const { fetch } = await openRoute('/editor/demo')
    useEditorStore().setField('output.quality', 'draft')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true, cancelable: true }))
    await settle()
    expect(fetch.to('PUT /api/projects/demo')).toHaveLength(1)
  })

  it('a aba escolhida é lembrada para a próxima vez', async () => {
    const { wrapper } = await openRoute('/editor/demo')
    await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === 'JSON')?.trigger('mousedown', { button: 0 })
    await settle()
    expect(window.localStorage.getItem('dmaker.editor.tab')).toBe('json')
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('sair com mudança não salva pede confirmação; ficar mantém a edição', async () => {
    const { router } = await openRoute('/editor/demo')
    const editor = useEditorStore()
    editor.setField('output.quality', 'draft')
    const confirm = useConfirmStore()
    const leaving = router.push('/projetos')
    await settle()
    expect(confirm.current?.options.title).toContain('Descartar')
    confirm.answer(false)
    await leaving
    expect(router.currentRoute.value.path).toBe('/editor/demo')
    expect(editor.dirty).toBe(true)
    // a navegação recusada não muda o título da aba para o da tela que a pessoa não abriu
    expect(document.title).toBe('Editor · DMaker')
  })

  it('confirmar o descarte sai e joga a edição fora', async () => {
    const { router } = await openRoute('/editor/demo')
    const editor = useEditorStore()
    editor.setField('output.quality', 'draft')
    const confirm = useConfirmStore()
    const leaving = router.push('/projetos')
    await settle()
    confirm.answer(true)
    await leaving
    expect(router.currentRoute.value.path).toBe('/projetos')
    expect(editor.spec).toBeNull()
  })

  it('sair sem mudança não pergunta nada, e voltar mantém o projeto carregado', async () => {
    const { router } = await openRoute('/editor/demo')
    await router.push('/projetos')
    await settle()
    expect(useConfirmStore().current).toBeNull()
    expect(useEditorStore().status).toBe('ready')
  })

  it('o aviso do navegador ao fechar a aba só vale com mudança não salva', async () => {
    await openRoute('/editor/demo')
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)
    useEditorStore().setField('output.quality', 'draft')
    const dirty = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirty)
    expect(dirty.defaultPrevented).toBe(true)
  })

  it('aviso de erro ao salvar e da vista aparecem na tela', async () => {
    const { wrapper } = await openRoute('/editor/demo', { 'PUT /api/projects/demo': reply(422, { detail: 'timeline vazia' }) })
    const editor = useEditorStore()
    editor.setField('output.quality', 'draft')
    await editor.save()
    await settle()
    expect(wrapper.find('.notice--error').text()).toContain('timeline vazia')
  })

  it('um render deste projeto que termina atualiza as saídas e abre a aba Preview', async () => {
    const result = {
      output: 'C:/out/demo__instagram-reels__preview.mp4',
      output_url: '/api/file?path=x',
      thumbnail: null,
      thumbnail_url: null,
      duration_s: 6,
      size_mb: 1,
      preset: 'instagram/reels',
      resolution: '1080x1920',
      captions_file: null,
      warnings: [],
    }
    const { wrapper } = await openRoute('/editor/demo')
    routedFetch(editorRoutes(projectSpec(), { 'GET /api/projects/demo': () => projectDetail({ outputs: [outputFile({ kind: 'preview' })] }) }))
    const jobs = useJobsStore()
    jobs.track('job-9', { project: 'demo', description: 'demo: preview' })
    FakeEventSource.latest().emit({ kind: 'end', t: 1, status: 'done', error: null, result })
    await settle()
    expect(useEditorStore().outputs).toHaveLength(1)
    expect(wrapper.find('[role="tab"][data-state="active"]').text()).toBe('Preview')
    expect(wrapper.find('video[src="/api/file?path=C%3A%2Fout%2Fdemo__instagram-reels.mp4"]').exists()).toBe(true)
  })

  it('a linha do tempo ocupa o encaixe dela, com a barra de ferramentas e as trilhas', async () => {
    const { wrapper } = await openRoute('/editor/demo')
    const slot = wrapper.find('[data-panel="timeline"]')
    expect(slot.find('.timeline').exists()).toBe(true)
    expect(slot.find('[role="toolbar"][aria-label="Ferramentas da linha do tempo"]').exists()).toBe(true)
    expect(slot.findAll('.row').map((row) => row.attributes('data-track-id'))).toEqual(['V1'])
    expect(slot.text()).not.toContain('ainda não está disponível')
  })

  it('a rota do editor usa a largura toda da janela, e as outras telas continuam com o limite de leitura', async () => {
    const { router } = await openRoute('/editor/demo')
    expect(router.currentRoute.value.meta.wide).toBe(true)
    await router.push('/projetos')
    expect(router.currentRoute.value.meta.wide).toBeUndefined()
  })

  it('os botões F e M escondem e mostram os painéis Filtros e Mídia da bancada', async () => {
    const { wrapper } = await openRoute('/editor/demo')
    expect(wrapper.find('[data-panel="filters"]').exists()).toBe(true)
    await buttonOf(wrapper, 'Filtros')?.trigger('click')
    expect(wrapper.find('[data-panel="filters"]').exists()).toBe(false)
    // a coluna dos filtros recolhe junto com o painel
    expect(wrapper.find('.workbench').attributes('style')).toContain('0px 0px minmax(0, 1fr) 6px 240px')
    await buttonOf(wrapper, 'Mídia')?.trigger('click')
    expect(wrapper.find('[data-panel="media"]').exists()).toBe(false)
    await buttonOf(wrapper, 'Filtros')?.trigger('click')
    await buttonOf(wrapper, 'Mídia')?.trigger('click')
    expect(wrapper.find('[data-panel="media"]').exists()).toBe(true)
    expect(wrapper.find('[data-panel="filters"]').exists()).toBe(true)
  })

  it('J, K e L agem uma vez só: o teclado é do editor, e o painel do player não tem ouvinte próprio', async () => {
    // o jsdom não toca mídia: sem isto, tocar escreve "not implemented" no terminal
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    await openRoute('/editor/demo')
    const player = usePlayerStore()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'l', bubbles: true, cancelable: true }))
    await settle()
    expect(player.rate).toBe(1)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', bubbles: true, cancelable: true }))
    expect(player.rate).toBe(0)
    play.mockRestore()
  })

  it('a tecla ? abre a janela de atalhos', async () => {
    await openRoute('/editor/demo')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '?', shiftKey: true, bubbles: true, cancelable: true }))
    await settle()
    expect(useKeymapStore().dialogOpen).toBe(true)
    expect(document.body.querySelector('[role="dialog"]')?.textContent).toContain('Atalhos de teclado')
  })
})

describe('EditorView: coerência com o disco', () => {
  const REVISION_ROUTE = 'GET /api/projects/demo/revision'
  const revisionCalls = (fetch: { to: (route: string) => unknown[] }) => fetch.to(REVISION_ROUTE).length
  let visibility: 'visible' | 'hidden' = 'visible'

  beforeEach(() => {
    visibility = 'visible'
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility })
    // só o relógio da consulta é de mentira: o resto da tela usa os temporizadores de verdade
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  })
  afterEach(() => {
    vi.useRealTimers()
    Reflect.deleteProperty(document, 'visibilityState')
  })

  const changedSpec = () => ({ ...projectSpec(), output: { ...(projectSpec().output as object), quality: 'max' } })

  it('consulta a revisão a cada 2 s enquanto o editor está aberto', async () => {
    const { fetch } = await openRoute('/editor/demo')
    expect(revisionCalls(fetch)).toBe(0)
    vi.advanceTimersByTime(DISK_CHECK_INTERVAL_MS)
    await settle()
    expect(revisionCalls(fetch)).toBe(1)
    vi.advanceTimersByTime(DISK_CHECK_INTERVAL_MS)
    await settle()
    expect(revisionCalls(fetch)).toBe(2)
  })

  it('com a aba escondida não consulta, e ao voltar consulta na hora', async () => {
    const { fetch } = await openRoute('/editor/demo')
    visibility = 'hidden'
    vi.advanceTimersByTime(DISK_CHECK_INTERVAL_MS * 3)
    await settle()
    expect(revisionCalls(fetch)).toBe(0)
    visibility = 'visible'
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    expect(revisionCalls(fetch)).toBe(1)
  })

  it('ao sair do editor a consulta para', async () => {
    const { fetch, router } = await openRoute('/editor/demo')
    await router.push('/projetos')
    await settle()
    vi.advanceTimersByTime(DISK_CHECK_INTERVAL_MS * 3)
    await settle()
    expect(revisionCalls(fetch)).toBe(0)
  })

  it('o Claude mudou o projeto e não há nada por salvar: o editor recarrega sozinho e avisa', async () => {
    const { fetch } = await openRoute('/editor/demo')
    const editor = useEditorStore()
    fetch.set(REVISION_ROUTE, { revision: 'rev-2' })
    fetch.set('GET /api/projects/demo', () => projectDetail({ spec: changedSpec() as never, revision: 'rev-2' }))
    vi.advanceTimersByTime(DISK_CHECK_INTERVAL_MS)
    await settle()
    expect(editor.get('output.quality')).toBe('max')
    expect(editor.dirty).toBe(false)
    expect(editor.revision).toBe('rev-2')
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('O projeto foi atualizado fora do editor')
  })

  it('com algo sem salvar, a faixa aparece e "Recarregar do disco" troca a edição pela do disco', async () => {
    const { wrapper, fetch } = await openRoute('/editor/demo')
    const editor = useEditorStore()
    expect(wrapper.text()).not.toContain('O projeto mudou fora do editor')
    editor.setField('output.quality', 'draft')
    fetch.set(REVISION_ROUTE, { revision: 'rev-2' })
    fetch.set('GET /api/projects/demo', () => projectDetail({ spec: changedSpec() as never, revision: 'rev-2' }))
    vi.advanceTimersByTime(DISK_CHECK_INTERVAL_MS)
    await settle()
    const banner = wrapper.find('[role="alert"]')
    expect(banner.text()).toContain('O projeto mudou fora do editor (pelo Claude, pelo agente ou pela CLI)')
    // nada se perde sem a pessoa escolher
    expect(editor.get('output.quality')).toBe('draft')
    expect(fetch.to('PUT /api/projects/demo')).toHaveLength(0)

    await buttonOf(wrapper, 'Recarregar do disco')?.trigger('click')
    await settle()
    expect(editor.get('output.quality')).toBe('max')
    expect(editor.dirty).toBe(false)
    expect(wrapper.text()).not.toContain('O projeto mudou fora do editor')
    expect(fetch.to('PUT /api/projects/demo')).toHaveLength(0)
  })

  it('"Manter o meu" grava a edição por cima, com a revisão nova, e a faixa some', async () => {
    const { wrapper, fetch } = await openRoute('/editor/demo')
    const editor = useEditorStore()
    editor.setField('output.quality', 'draft')
    fetch.set(REVISION_ROUTE, { revision: 'rev-2' })
    vi.advanceTimersByTime(DISK_CHECK_INTERVAL_MS)
    await settle()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)

    fetch.set('PUT /api/projects/demo', { ok: true, spec_path: 'x', revision: 'rev-3' })
    await buttonOf(wrapper, 'Manter o meu')?.trigger('click')
    await settle()
    const puts = fetch.to('PUT /api/projects/demo')
    expect(puts).toHaveLength(1)
    expect(puts[0]?.headers).toMatchObject({ 'If-Match': 'rev-2' })
    expect(editor.revision).toBe('rev-3')
    expect(editor.dirty).toBe(false)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('o Salvar recusado com 409 mostra a mesma escolha, sem mensagem de erro de gravação', async () => {
    const { wrapper } = await openRoute('/editor/demo', {
      'PUT /api/projects/demo': reply(409, { detail: 'O projeto mudou no disco desde a última leitura.', revision: 'rev-2' }),
    })
    const editor = useEditorStore()
    editor.setField('output.quality', 'draft')
    await buttonOf(wrapper, 'Salvar')?.trigger('click')
    await settle()
    expect(wrapper.find('[role="alert"]').text()).toContain('O projeto mudou fora do editor')
    expect(wrapper.find('.notice--error').exists()).toBe(false)
    expect(editor.dirty).toBe(true)
  })

  it('o Salvar leva a revisão lida no If-Match', async () => {
    const { fetch } = await openRoute('/editor/demo')
    useEditorStore().setField('output.quality', 'draft')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true, cancelable: true }))
    await settle()
    expect(fetch.to('PUT /api/projects/demo')[0]?.headers).toMatchObject({ 'If-Match': DISK_REVISION })
  })

  it('clicar numa caixa do palco leva o inspetor à aba Propriedades', async () => {
    window.localStorage.setItem('dmaker.editor.tab', 'json')
    const { wrapper } = await openRoute('/editor/demo')
    expect(wrapper.find('[role="tab"][data-state="active"]').text()).toBe('JSON')
    useEditorStore().selectOverlay(0, { reveal: true })
    await settle()
    expect(wrapper.find('[role="tab"][data-state="active"]').text()).toBe('Propriedades')
    // a troca automática não vira a aba preferida da pessoa
    expect(window.localStorage.getItem('dmaker.editor.tab')).toBe('json')
  })
})
