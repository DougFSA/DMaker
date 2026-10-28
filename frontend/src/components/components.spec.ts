import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import type { OutputFile, ProjectListItem, TemplateParam, TransitionCatalog } from '@/api'
import { createAppRouter } from '@/router'
import { useJobsStore } from '@/stores/jobs'
import { useThemeStore } from '@/stores/theme'
import { useToastsStore } from '@/stores/toasts'
import JobsMenu from './layout/JobsMenu.vue'
import SidebarNav from './layout/SidebarNav.vue'
import ThemeToggle from './layout/ThemeToggle.vue'
import TemplateParamField from './projects/TemplateParamField.vue'
import AppButton from './ui/AppButton.vue'
import ProgressBar from './ui/ProgressBar.vue'
import ToastHost from './ui/ToastHost.vue'
import OutputsView from '@/views/OutputsView.vue'
import ProjectsView from '@/views/ProjectsView.vue'
import TransitionsView from '@/views/TransitionsView.vue'

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
  it('lista as áreas na ordem e marca as futuras como em breve', async () => {
    const wrapper = await mountWithRouter(SidebarNav, { collapsed: false })
    const labels = wrapper.findAll('.nav__label').map((node) => node.text())
    expect(labels).toEqual(['Projetos', 'Editor', 'Voz', 'Dublagem', 'Fila', 'Modelos', 'Saídas', 'Transições'])
    expect(wrapper.findAll('.nav__soon')).toHaveLength(5)
    expect(wrapper.find('a[href="/classica"]').exists()).toBe(true)
  })

  it('recolhida, esconde os rótulos mas mantém o texto para leitor de tela', async () => {
    const wrapper = await mountWithRouter(SidebarNav, { collapsed: true })
    expect(wrapper.find('.nav__label').exists()).toBe(false)
    expect(wrapper.findAll('.visually-hidden').length).toBeGreaterThanOrEqual(8)
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


describe('TransitionsView', () => {
  const catalog: TransitionCatalog = {
    curves: ['linear', 'ease', 'spring'],
    transitions: [
      { name: 'whippan', kind: 'motion', summary: 'Chicote: o quadro corre com borrão.' },
      { name: 'crosszoom', kind: 'motion', summary: 'Zoom de passagem.' },
      { name: 'wipeleft', kind: 'xfade', summary: 'Uma cortina corre para a esquerda.' },
    ],
  }

  it('lista cada transição com o que ela faz e a folha de contato da curva escolhida', async () => {
    stubApi({ '/api/transitions': catalog })
    const wrapper = await mountWithRouter(TransitionsView)
    await flushPromises()
    const cards = wrapper.findAll('.transition')
    expect(cards.map((card) => card.find('.transition__name').text())).toEqual(['whippan', 'crosszoom', 'wipeleft'])
    expect(cards[0]!.text()).toContain('Chicote')
    expect(cards[0]!.text()).toContain('movimento')
    expect(cards[2]!.text()).toContain('xfade')
    expect(cards[0]!.find('img').attributes('src')).toBe('/api/transitions/whippan/sheet?curve=linear')

    const curveButtons = wrapper.findAll('[aria-label="Curva de tempo"] button')
    expect(curveButtons.map((button) => button.text())).toEqual(['Linear', 'Suave', 'Mola'])
    await curveButtons[2]!.trigger('click')
    expect(wrapper.findAll('.transition')[0]!.find('img').attributes('src')).toBe(
      '/api/transitions/whippan/sheet?curve=spring',
    )
    expect(wrapper.text()).toContain('passa um pouco do ponto final')
  })

  it('filtra por tipo e pela busca, e avisa quando nada combina', async () => {
    stubApi({ '/api/transitions': catalog })
    const wrapper = await mountWithRouter(TransitionsView)
    await flushPromises()

    const kinds = wrapper.findAll('[aria-label="Tipo de transição"] button')
    await kinds[1]!.trigger('click')
    expect(wrapper.findAll('.transition')).toHaveLength(2)
    await kinds[2]!.trigger('click')
    expect(wrapper.findAll('.transition__name').map((node) => node.text())).toEqual(['wipeleft'])
    await kinds[0]!.trigger('click')

    await wrapper.find('input[type="search"]').setValue('zoom')
    expect(wrapper.findAll('.transition__name').map((node) => node.text())).toEqual(['crosszoom'])
    await wrapper.find('input[type="search"]').setValue('zzz')
    expect(wrapper.text()).toContain('Nada encontrado')
  })

  it('mostra o aviso e tenta de novo quando a prévia não é gerada', async () => {
    stubApi({ '/api/transitions': catalog })
    const wrapper = await mountWithRouter(TransitionsView)
    await flushPromises()
    const first = wrapper.findAll('.transition')[0]!
    await first.find('img').trigger('error')
    expect(first.text()).toContain('Não foi possível gerar a prévia')
    await first.find('[role="alert"] button').trigger('click')
    expect(first.find('img').attributes('src')).toContain('&tentativa=1')
    await first.find('img').trigger('load')
    expect(first.find('[role="alert"]').exists()).toBe(false)
  })

  it('copia o trecho da spec com a curva escolhida', async () => {
    stubApi({ '/api/transitions': catalog })
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = await mountWithRouter(TransitionsView)
    await flushPromises()
    await wrapper.findAll('[aria-label="Curva de tempo"] button')[1]!.trigger('click')
    await wrapper.findAll('.transition')[1]!.find('footer button').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('"transition": { "type": "crosszoom", "duration": 0.5, "curve": "ease" }')
    expect(useToastsStore().items.at(-1)?.title).toBe('Trecho copiado')
  })

  it('explica quando a API falha', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    const wrapper = await mountWithRouter(TransitionsView)
    await flushPromises()
    expect(wrapper.text()).toContain('Não foi possível carregar as transições')
  })
})
