import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import type { CutReport, OutputFile, ProjectListItem, TemplateParam } from '@/api'
import { createAppRouter } from '@/router'
import { useJobsStore } from '@/stores/jobs'
import { useThemeStore } from '@/stores/theme'
import { useToastsStore } from '@/stores/toasts'
import JobsMenu from './layout/JobsMenu.vue'
import SidebarNav from './layout/SidebarNav.vue'
import ThemeToggle from './layout/ThemeToggle.vue'
import AutoCutDialog from './projects/AutoCutDialog.vue'
import CutsCard from './projects/CutsCard.vue'
import TemplateParamField from './projects/TemplateParamField.vue'
import AppButton from './ui/AppButton.vue'
import ProgressBar from './ui/ProgressBar.vue'
import ToastHost from './ui/ToastHost.vue'
import OutputsView from '@/views/OutputsView.vue'
import ProjectDetailView from '@/views/ProjectDetailView.vue'
import ProjectsView from '@/views/ProjectsView.vue'

function stubApi(routes: Record<string, unknown>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      const body = routes[url.split('?')[0] ?? url]
      return Promise.resolve(
        body === undefined ? new Response('{"detail":"nada"}', { status: 404 }) : new Response(JSON.stringify(body)),
      )
    }),
  )
}

async function mountWithRouter(component: object, props: Record<string, unknown> = {}) {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/projetos')
  await router.isReady()
  return mount(component, { props, global: { plugins: [router] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe('AppButton', () => {
  it('vira link quando recebe href e some o link quando está carregando', () => {
    const link = mount(AppButton, { props: { href: '/x.mp4', download: 'x.mp4' }, slots: { default: 'Baixar' } })
    expect(link.element.tagName).toBe('A')
    expect(link.attributes('download')).toBe('x.mp4')

    const busy = mount(AppButton, { props: { href: '/x.mp4', loading: true }, slots: { default: 'Baixar' } })
    expect(busy.element.tagName).toBe('BUTTON')
    expect(busy.attributes('disabled')).toBeDefined()
    expect(busy.attributes('aria-busy')).toBe('true')
  })
})

describe('ProgressBar', () => {
  it('expõe o valor para leitores de tela e limita a 0 a 100', () => {
    const bar = mount(ProgressBar, { props: { value: 140, label: 'Render' } })
    expect(bar.attributes('role')).toBe('progressbar')
    expect(bar.attributes('aria-valuenow')).toBe('100')
  })

  it('fica indeterminada sem valor', () => {
    const bar = mount(ProgressBar, { props: { label: 'Render' } })
    expect(bar.attributes('aria-valuenow')).toBeUndefined()
    expect(bar.classes()).toContain('progress--indeterminate')
  })
})

describe('SidebarNav', () => {
  it('lista as sete áreas na ordem e marca as futuras como em breve', async () => {
    const wrapper = await mountWithRouter(SidebarNav, { collapsed: false })
    const labels = wrapper.findAll('.nav__label').map((node) => node.text())
    expect(labels).toEqual(['Projetos', 'Editor', 'Voz', 'Dublagem', 'Fila', 'Modelos', 'Saídas'])
    expect(wrapper.findAll('.nav__soon')).toHaveLength(5)
    expect(wrapper.find('a[href="/classica"]').exists()).toBe(true)
  })

  it('recolhida, esconde os rótulos mas mantém o texto para leitor de tela', async () => {
    const wrapper = await mountWithRouter(SidebarNav, { collapsed: true })
    expect(wrapper.find('.nav__label').exists()).toBe(false)
    expect(wrapper.findAll('.visually-hidden').length).toBeGreaterThanOrEqual(7)
  })
})

describe('tema', () => {
  it('começa escuro, alterna para claro e guarda a escolha', async () => {
    const theme = useThemeStore()
    expect(document.documentElement.dataset.theme).toBe('dark')
    const wrapper = mount(ThemeToggle)
    await wrapper.trigger('click')
    expect(theme.theme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('dmaker.theme')).toBe('light')
    theme.set('dark')
  })
})

describe('JobsMenu', () => {
  it('resume os jobs em andamento', async () => {
    const jobs = useJobsStore()
    const wrapper = mount(JobsMenu, { global: { plugins: [await createReadyRouter()] } })
    expect(wrapper.text()).toContain('Nenhum job ativo')

    jobs.jobs['a'] = {
      id: 'a',
      description: 'demo: preview',
      status: 'running',
      project: 'demo',
      progress: { percent: 30 },
      startedAtMs: Date.now(),
      finishedAtMs: null,
      error: null,
      log: [],
      result: null,
    }
    await flushPromises()
    expect(wrapper.text()).toContain('1 job em andamento')
  })

  it('avisa quando o servidor não responde', async () => {
    const jobs = useJobsStore()
    jobs.reachable = false
    const wrapper = mount(JobsMenu, { global: { plugins: [await createReadyRouter()] } })
    expect(wrapper.text()).toContain('Servidor sem resposta')
  })
})

async function createReadyRouter() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/projetos')
  await router.isReady()
  return router
}

describe('ToastHost', () => {
  it('mostra o aviso, com alerta para erros, e dispensa', async () => {
    const toasts = useToastsStore()
    const wrapper = mount(ToastHost)
    toasts.push({ tone: 'error', title: 'Falhou', description: 'motivo' })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Falhou')
    await wrapper.find('.toast__close').trigger('click')
    await flushPromises()
    expect(toasts.items).toHaveLength(0)
  })
})

describe('TemplateParamField', () => {
  const param = (overrides: Partial<TemplateParam>): TemplateParam => ({
    description: 'ajuda do campo',
    type: 'text',
    default: null,
    required: false,
    ...overrides,
  })

  it('campo de texto devolve o que foi digitado', async () => {
    const wrapper = mount(TemplateParamField, { props: { name: 'titulo', param: param({}) } })
    expect(wrapper.text()).toContain('ajuda do campo')
    await wrapper.find('input').setValue('Olá')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['Olá'])
  })

  it('lista separada por vírgula vira array sem apagar a vírgula digitada', async () => {
    const wrapper = mount(TemplateParamField, { props: { name: 'tags', param: param({ type: 'list' }) } })
    const input = wrapper.find('input')
    await input.setValue('a, b,')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([['a', 'b']])
    expect((input.element as HTMLInputElement).value).toBe('a, b,')
  })

  it('campo obrigatório leva asterisco e bool vira caixa de marcar', async () => {
    const required = mount(TemplateParamField, { props: { name: 'print', param: param({ type: 'path', required: true }) } })
    expect(required.find('label').text()).toBe('print *')

    const flag = mount(TemplateParamField, { props: { name: 'ligado', param: param({ type: 'bool' }) } })
    await flag.find('input').setValue(true)
    expect(flag.emitted('update:modelValue')?.at(-1)).toEqual([true])
  })
})

describe('ProjectsView', () => {
  const projects: ProjectListItem[] = [
    { name: 'reel-a', spec_path: 'a', preset: 'instagram/reels', brand: 'medlycare', segments: 4, mtime: 1_700_000_000 },
    { name: 'casamento-b', spec_path: 'b', preset: 'youtube/video', brand: null, segments: 120, mtime: 1_600_000_000 },
    { name: 'quebrado', spec_path: 'c', error: 'spec ilegível' },
  ]

  it('lista os projetos, filtra pela busca e mostra spec ilegível', async () => {
    stubApi({ '/api/projects': projects })
    const wrapper = await mountWithRouter(ProjectsView)
    await flushPromises()
    expect(wrapper.findAll('.project')).toHaveLength(3)
    expect(wrapper.text()).toContain('spec ilegível')

    await wrapper.find('input[type="search"]').setValue('casamento')
    expect(wrapper.findAll('.project').map((card) => card.find('.project__name').text())).toEqual(['casamento-b'])

    await wrapper.find('input[type="search"]').setValue('zzz')
    expect(wrapper.text()).toContain('Nada encontrado')
  })

  it('troca para tabela e lembra da escolha', async () => {
    stubApi({ '/api/projects': projects })
    const wrapper = await mountWithRouter(ProjectsView)
    await flushPromises()
    await wrapper.find('button[aria-label="Tabela"]').trigger('click')
    expect(wrapper.find('table').exists()).toBe(true)
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)
    expect(localStorage.getItem('dmaker.projectsLayout')).toBe('table')
  })

  it('explica quando não há projetos e quando a API falha', async () => {
    stubApi({ '/api/projects': [] })
    const empty = await mountWithRouter(ProjectsView)
    await flushPromises()
    expect(empty.text()).toContain('Nenhum projeto ainda')

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    const failed = await mountWithRouter(ProjectsView)
    await flushPromises()
    expect(failed.text()).toContain('Não foi possível carregar os projetos')
  })
})

describe('cortes automáticos', () => {
  const report: CutReport = {
    source: 'D:/gravacao.mp4',
    intensity: 'agressiva',
    min_pause_s: 0.5,
    breath_s: 0.15,
    duration_before_s: 120,
    duration_after_s: 84,
    removed_s: 36,
    removed_percent: 30,
    counts: { silence: 1, filler: 1 },
    cuts: [
      { id: 1, start_s: 3.2, end_s: 5.4, duration_s: 2.2, reason: 'silence', reason_label: 'pausa', text: '', undone: false },
      { id: 2, start_s: 12, end_s: 14.5, duration_s: 2.5, reason: 'filler', reason_label: 'vício de fala', text: 'é...', undone: false },
      { id: 3, start_s: 20, end_s: 25, duration_s: 5, reason: 'repetition', reason_label: 'frase repetida', text: 'Hoje eu vou', undone: true },
    ],
  }

  it('lista cada corte com tempo, motivo e palavras, e pede para desfazer pelo número', async () => {
    const wrapper = mount(CutsCard, { props: { report } })
    expect(wrapper.text()).toContain('2:00 para 1:24 (30% a menos)')
    expect(wrapper.text()).toContain('1 pausa, 1 vício')
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(3)
    expect(rows[0]?.text()).toContain('00:03.2 a 00:05.4')
    expect(rows[0]?.text()).toContain('(silêncio)')
    expect(rows[1]?.text()).toContain('vício de fala')
    expect(rows[1]?.text()).toContain('é...')

    await rows[1]?.find('button').trigger('click')
    expect(wrapper.emitted('undo')).toEqual([[2]])
  })

  it('um corte já desfeito não pode ser desfeito de novo, e nada clica enquanto um desfaz', async () => {
    const wrapper = mount(CutsCard, { props: { report } })
    const undone = wrapper.findAll('tbody tr')[2]?.find('button')
    expect(undone?.text()).toBe('Desfeito')
    expect(undone?.attributes('disabled')).toBeDefined()

    await wrapper.setProps({ busyId: 1 })
    const buttons = wrapper.findAll('tbody button')
    expect(buttons.every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    expect(buttons[0]?.attributes('aria-busy')).toBe('true')
  })

  it('avisa quando nada passou do limite', () => {
    const wrapper = mount(CutsCard, { props: { report: { ...report, cuts: [], counts: {} } } })
    expect(wrapper.text()).toContain('Nada passou do limite')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('o detalhe do projeto mostra a lista só quando o projeto nasceu do corte, e desfaz pela API', async () => {
    const detail = { name: 'corte', spec_path: 'x', spec: { name: 'corte', timeline: [{ type: 'clip' }] }, captions_exists: false, outputs: [] }
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (url === '/api/projects/corte/cuts/1/undo') return Promise.resolve(new Response(JSON.stringify(report)))
        if (url === '/api/projects/corte') return Promise.resolve(new Response(JSON.stringify({ ...detail, cuts: report })))
        if (url === '/api/projects/avulso') return Promise.resolve(new Response(JSON.stringify({ ...detail, name: 'avulso', cuts: null })))
        return Promise.resolve(new Response('{}'))
      }),
    )
    const router = createAppRouter(createMemoryHistory())
    await router.push('/projetos/corte')
    await router.isReady()
    const wrapper = mount(ProjectDetailView, { props: { name: 'corte' }, global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Cortes automáticos')

    await wrapper.findAll('tbody tr')[0]?.find('button').trigger('click')
    await flushPromises()
    expect(calls).toContain('POST /api/projects/corte/cuts/1/undo')
    expect(calls.filter((call) => call === 'GET /api/projects/corte')).toHaveLength(2) // abriu e recarregou

    const plain = mount(ProjectDetailView, { props: { name: 'avulso' }, global: { plugins: [router] } })
    await flushPromises()
    expect(plain.text()).not.toContain('Cortes automáticos')
  })

  it('o diálogo pede a gravação e o nome, e manda o corte com a intensidade escolhida', async () => {
    stubApi({ '/api/state': { presets: [{ id: 'instagram/reels', platform: 'Instagram', name: 'Reels' }], brands: [] }, '/api/templates': [] })
    const wrapper = mount(AutoCutDialog, { props: { open: true }, attachTo: document.body })
    await flushPromises()
    const form = document.body.querySelector('#autocut-form') as HTMLFormElement
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    expect(document.body.textContent).toContain('Escolha a gravação que será cortada.')
    expect(wrapper.emitted('started')).toBeUndefined()
    wrapper.unmount()
  })
})

describe('OutputsView', () => {
  const outputs: OutputFile[] = [
    {
      path: 'D:/o/demo__instagram-reels.mp4',
      url: '/api/file?path=D:/o/demo__instagram-reels.mp4',
      name: 'demo__instagram-reels.mp4',
      project: 'demo',
      preset: 'instagram/reels',
      kind: 'final',
      size_mb: 12.3,
      mtime: 1_700_000_000,
      thumbnail: '/api/file?path=D:/o/demo__instagram-reels.jpg',
    },
    {
      path: 'D:/o/x__youtube-video__preview.mp4',
      url: '/api/file?path=D:/o/x__youtube-video__preview.mp4',
      name: 'x__youtube-video__preview.mp4',
      project: 'x',
      preset: 'youtube/video',
      kind: 'preview',
      size_mb: 1,
      mtime: 1_600_000_000,
      thumbnail: null,
    },
  ]

  it('mostra miniatura, tipo e o link de download de cada saída', async () => {
    stubApi({ '/api/outputs': outputs })
    const wrapper = await mountWithRouter(OutputsView)
    await flushPromises()
    const cards = wrapper.findAll('.output')
    expect(cards).toHaveLength(2)
    expect(cards[0]!.find('img').attributes('src')).toContain('demo__instagram-reels.jpg')
    expect(cards[0]!.text()).toContain('Final')
    expect(cards[1]!.text()).toContain('Prévia')
    const download = cards[0]!.find('a[download]')
    expect(download.attributes('href')).toBe(outputs[0]!.url)
    expect(download.attributes('download')).toBe('demo__instagram-reels.mp4')
  })

  it('filtra por tipo', async () => {
    stubApi({ '/api/outputs': outputs })
    const wrapper = await mountWithRouter(OutputsView)
    await flushPromises()
    const previews = wrapper.findAll('.segmented button').find((button) => button.text() === 'Prévias')
    await previews!.trigger('click')
    expect(wrapper.findAll('.output')).toHaveLength(1)
    expect(wrapper.find('.output').text()).toContain('x__youtube-video__preview.mp4')
  })

  it('estado vazio leva para Projetos', async () => {
    stubApi({ '/api/outputs': [] })
    const wrapper = await mountWithRouter(OutputsView)
    await flushPromises()
    expect(wrapper.text()).toContain('Nenhum vídeo gerado ainda')
  })
})
