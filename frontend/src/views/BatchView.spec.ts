import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import type { BatchListItem, BatchReport, BatchRow, BatchValidation } from '@/api'
import { createAppRouter } from '@/router'
import BatchView from './BatchView.vue'

/** EventSource de mentira: o teste não precisa do SSE, só de a tela conseguir pedir o acompanhamento do job. */
class FakeEventSource {
  static readonly CLOSED = 2
  readyState = 1
  onmessage: ((message: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null
  close(): void {
    this.readyState = FakeEventSource.CLOSED
  }
}

interface Call {
  method: string
  url: string
  body: unknown
}

const TEMPLATES = [
  {
    name: 'stories-medlycare',
    description: 'Story de uma dica.',
    summary: '',
    params: {
      titulo: { description: '', type: 'text', default: null, required: false },
      print: { description: '', type: 'path', default: null, required: true },
    },
  },
]

const STATE = { version: '1', presets: [], brands: [], projects: [] }

function validation(overrides: Partial<BatchValidation> = {}): BatchValidation {
  return {
    template: 'stories-medlycare',
    name_column: 'titulo',
    headers: ['titulo', 'print'],
    columns: { matched: { titulo: 'titulo', print: 'print' }, unused: [], missing: [] },
    issues: [],
    rows: [
      { index: 1, line: 2, title: 'Dica um', valid: true, issues: [] },
      {
        index: 2,
        line: 3,
        title: 'Dica dois',
        valid: false,
        issues: [{ line: 3, field: 'print', message: 'arquivo não encontrado: D:/x/sumiu.png', level: 'erro' }],
      },
      {
        index: 3,
        line: 4,
        title: 'Dica três',
        valid: false,
        issues: [{ line: 4, field: 'titulo', message: 'contém travessão ou meia-risca', level: 'erro' }],
      },
    ],
    total: 3,
    valid: 1,
    invalid: 2,
    ok: false,
    text: '',
    ...overrides,
  }
}

function row(overrides: Partial<BatchRow>): BatchRow {
  return {
    index: 1,
    line: 2,
    title: 'Dica um',
    state: 'pending',
    state_label: 'Pendente',
    project: 'serie-dica-um',
    output: null,
    duration_s: null,
    render_s: null,
    error: null,
    warnings: [],
    issues: [],
    ...overrides,
  }
}

function report(overrides: Partial<BatchReport> = {}): BatchReport {
  return {
    name: 'serie',
    template: 'stories-medlycare',
    status: 'paused',
    status_label: 'Pausado',
    preview: false,
    output_dir: 'D:/output/serie',
    total: 3,
    done: 1,
    failed: 1,
    skipped: 0,
    waiting: 1,
    summary: '1 de 3 vídeo(s) pronto(s), 1 falhou(aram), 1 esperando',
    rows: [
      row({ index: 1, title: 'Dica um', state: 'done', state_label: 'Pronto', output: 'D:/output/serie/dica-um.mp4', duration_s: 8, render_s: 11 }),
      row({ index: 2, line: 3, title: 'Dica dois', state: 'failed', state_label: 'Falhou', error: 'RuntimeError: sem espaço em disco' }),
      row({ index: 3, line: 4, title: 'Dica três', state: 'pending', state_label: 'Pendente' }),
    ],
    text: '',
    job_id: null,
    ...overrides,
  }
}

let calls: Call[]
let validationResult: BatchValidation
let saved: BatchListItem[]
let viewResult: BatchReport

function stubServer(): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      const path = url.split('?')[0] ?? url
      const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body)))
      if (path === '/api/state') return json(STATE)
      if (path === '/api/templates') return json(TEMPLATES)
      if (path === '/api/batches' && method === 'GET') return json({ batches: saved })
      if (path === '/api/batches/validate') return json(validationResult)
      if (path === '/api/batches' && method === 'POST') return json({ name: 'serie', job_id: 'j1' })
      if (path === '/api/batches/serie/pause') return json({ name: 'serie', pause_requested: true })
      if (path === '/api/batches/serie/resume') return json({ name: 'serie', job_id: 'j2' })
      if (path === '/api/batches/serie') return json(viewResult)
      return Promise.resolve(new Response('{"detail":"nada"}', { status: 404 }))
    }),
  )
}

async function mountView() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/lote')
  await router.isReady()
  const wrapper = mount(BatchView, { global: { plugins: [router] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

function bodyOf(method: string, url: string): unknown {
  return calls.find((call) => call.method === method && call.url === url)?.body
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.stubGlobal('EventSource', FakeEventSource)
  validationResult = validation()
  viewResult = report()
  saved = []
  stubServer()
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

async function validateSheet(wrapper: Awaited<ReturnType<typeof mountView>>): Promise<void> {
  await wrapper.find('#batch-sheet').setValue('D:/planilhas/semana.csv')
  await wrapper.find('#batch-form').trigger('submit')
  await flushPromises()
}

describe('tela Lote: planilha e validação', () => {
  it('lista os modelos e pede a planilha antes de validar', async () => {
    const wrapper = await mountView()
    expect(wrapper.findAll('#batch-template option').map((option) => option.text())).toEqual(['stories-medlycare'])

    await wrapper.find('#batch-form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Escolha a planilha')
    expect(calls.some((call) => call.url === '/api/batches/validate')).toBe(false)
  })

  it('mostra linha, coluna e motivo de cada problema sem renderizar nada', async () => {
    const wrapper = await mountView()
    await validateSheet(wrapper)

    expect(bodyOf('POST', '/api/batches/validate')).toEqual({
      template: 'stories-medlycare',
      sheet: 'D:/planilhas/semana.csv',
      name_column: null,
    })
    const text = wrapper.text()
    expect(text).toContain('1 de 3 linhas válidas')
    expect(text).toContain('coluna print: arquivo não encontrado: D:/x/sumiu.png')
    expect(text).toContain('coluna titulo: contém travessão ou meia-risca')
    expect(wrapper.findAll('tbody tr.row--bad')).toHaveLength(2)
    expect(calls.some((call) => call.method === 'POST' && call.url === '/api/batches')).toBe(false)
  })

  it('só segue sem as linhas com problema depois da confirmação explícita', async () => {
    const wrapper = await mountView()
    await validateSheet(wrapper)

    expect(wrapper.text()).toContain('2 linhas têm problema e não serão renderizadas')
    expect(wrapper.text()).not.toContain('Iniciar lote (')
    const confirm = wrapper.findAll('button').find((button) => button.text().startsWith('Seguir sem as linhas com problema'))
    expect(confirm).toBeDefined()
    await confirm?.trigger('click')
    await flushPromises()

    expect(bodyOf('POST', '/api/batches')).toMatchObject({
      template: 'stories-medlycare',
      sheet: 'D:/planilhas/semana.csv',
      name: 'semana',
      skip_invalid: true,
      preview: false,
    })
    // depois de iniciar, o lote aparece com o estado de cada linha
    expect(wrapper.text()).toContain('Lote serie')
  })

  it('inicia direto quando todas as linhas passam e manda as prévias se a pessoa marcou', async () => {
    validationResult = validation({ valid: 3, invalid: 0, ok: true, rows: validation().rows.map((r) => ({ ...r, valid: true, issues: [] })) })
    const wrapper = await mountView()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await validateSheet(wrapper)

    const start = wrapper.findAll('button').find((button) => button.text().startsWith('Iniciar lote (3 vídeos)'))
    expect(start).toBeDefined()
    await start?.trigger('click')
    await flushPromises()

    expect(bodyOf('POST', '/api/batches')).toMatchObject({ skip_invalid: false, preview: true })
  })

  it('bloqueia quando nenhuma linha pode ser renderizada', async () => {
    validationResult = validation({ valid: 0, invalid: 3, ok: false })
    const wrapper = await mountView()
    await validateSheet(wrapper)

    expect(wrapper.text()).toContain('Nenhuma linha pode ser renderizada como está')
    expect(wrapper.findAll('button').some((button) => button.text().startsWith('Iniciar lote'))).toBe(false)
  })

  it('mostra o erro do servidor quando a validação não consegue ler a planilha', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) =>
        Promise.resolve(
          url.startsWith('/api/batches/validate')
            ? new Response('{"detail":"Planilha não encontrada: D:/x.csv"}', { status: 400 })
            : new Response(JSON.stringify(url === '/api/templates' ? TEMPLATES : url === '/api/state' ? STATE : { batches: [] })),
        ),
      ),
    )
    const wrapper = await mountView()
    await validateSheet(wrapper)

    expect(wrapper.find('[role="alert"]').text()).toContain('Planilha não encontrada')
    expect(wrapper.text()).not.toContain('Conferência da planilha')
  })
})

describe('tela Lote: andamento, pausa e relatório', () => {
  beforeEach(() => {
    saved = [
      {
        name: 'serie',
        template: 'stories-medlycare',
        status: 'paused',
        status_label: 'Pausado',
        preview: false,
        output_dir: 'D:/output/serie',
        total: 3,
        done: 1,
        failed: 1,
        skipped: 0,
        waiting: 1,
        summary: '1 de 3 vídeo(s) pronto(s), 1 falhou(aram), 1 esperando',
        rows: 3,
      },
    ]
  })

  async function openSaved(wrapper: Awaited<ReturnType<typeof mountView>>): Promise<void> {
    const open = wrapper.findAll('button').find((button) => button.text() === 'Abrir')
    await open?.trigger('click')
    await flushPromises()
  }

  it('abre um lote salvo com o estado de cada vídeo, o motivo da falha e o relatório', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('Lotes salvos')
    await openSaved(wrapper)

    const rows = wrapper.findAll('[role="region"][aria-label="Vídeos do lote"] tbody tr')
    expect(rows).toHaveLength(3)
    expect(rows.map((tr) => tr.findAll('td')[2]?.text())).toEqual(['Pronto', 'Falhou', 'Pendente'])
    const text = wrapper.text()
    expect(text).toContain('RuntimeError: sem espaço em disco')
    expect(text).toContain('1 de 3 vídeo(s) pronto(s), 1 falhou(aram), 1 esperando')
    expect(wrapper.find('.report').text()).toContain('D:/output/serie')
    expect(wrapper.find('.report__problems').text()).toContain('Dica dois')
  })

  it('retoma o lote e refaz só um vídeo pelo botão da linha', async () => {
    const wrapper = await mountView()
    await openSaved(wrapper)

    const resume = wrapper.findAll('button').find((button) => button.text() === 'Retomar')
    expect(resume).toBeDefined()
    await resume?.trigger('click')
    await flushPromises()
    expect(bodyOf('POST', '/api/batches/serie/resume')).toEqual({ force: false })

    viewResult = report({ status: 'finished', status_label: 'Concluído', waiting: 0 })
    await openSaved(wrapper)
    const retry = wrapper.findAll('button').find((button) => button.text() === 'Tentar de novo')
    await retry?.trigger('click')
    await flushPromises()
    expect(calls.filter((call) => call.url === '/api/batches/serie/resume').at(-1)?.body).toEqual({ rows: [2], force: true })
  })

  it('pausa um lote em andamento e mostra que a pausa vale depois do vídeo atual', async () => {
    viewResult = report({ status: 'running', status_label: 'Rodando', job_id: 'j1' })
    saved = [{ ...(saved[0] as BatchListItem), status: 'running', status_label: 'Rodando' }]
    const wrapper = await mountView() // um lote que já estava rodando volta a ser acompanhado sozinho

    const pause = wrapper.findAll('button').find((button) => button.text() === 'Pausar')
    expect(pause).toBeDefined()
    await pause?.trigger('click')
    await flushPromises()

    expect(calls.some((call) => call.method === 'POST' && call.url === '/api/batches/serie/pause')).toBe(true)
    expect(wrapper.text()).toContain('Pausando depois deste vídeo')
    wrapper.unmount()
  })

  it('não oferece refazer enquanto o lote roda', async () => {
    viewResult = report({ status: 'running', status_label: 'Rodando', job_id: 'j1' })
    saved = [{ ...(saved[0] as BatchListItem), status: 'running', status_label: 'Rodando' }]
    const wrapper = await mountView()

    const redo = wrapper.findAll('button').filter((button) => ['Refazer', 'Tentar de novo'].includes(button.text()))
    expect(redo.length).toBeGreaterThan(0)
    expect(redo.every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    wrapper.unmount()
  })
})
