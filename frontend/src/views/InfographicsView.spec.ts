import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import type { InfographicInfo } from '@/api'
import { createAppRouter } from '@/router'
import { useToastsStore } from '@/stores/toasts'
import InfographicsView from './InfographicsView.vue'

const COUNTER: InfographicInfo = {
  name: 'contador',
  title: 'Contador',
  description: 'Um número que conta de um valor até outro.',
  size: [900, 300],
  area: {},
  duration: 4,
  example: { ate: 10000, prefixo: '+ de R$' },
  anchors_to_caption: false,
  params: [
    { name: 'de', type: 'number', label: 'Começa em', required: false, default: 0, min: -1000, max: 1000 },
    { name: 'ate', type: 'number', label: 'Termina em', required: true, min: -1000000, max: 1000000 },
    { name: 'prefixo', type: 'text', label: 'Antes do número', required: false, default: '', max_length: 30 },
    { name: 'easing', type: 'choice', label: 'Ritmo', required: false, default: 'suave', options: ['suave', 'linear'] },
    { name: 'sombra', type: 'bool', label: 'Sombra suave', required: false, default: true },
  ],
}
const BAR: InfographicInfo = {
  ...COUNTER,
  name: 'barra',
  title: 'Barra',
  description: 'Uma barra que enche até um valor.',
  example: { valor: 95 },
  params: [{ name: 'valor', type: 'number', label: 'Valor', required: true, min: 0, max: 1000 }],
}

const STATE = {
  presets: [],
  brands: [
    { key: 'default', name: 'Padrão', colors: {} },
    { key: 'minha', name: 'Minha', colors: {} },
  ],
  projects: [],
}

interface Call {
  url: string
  method: string
  body: unknown
}

let calls: Call[]

function stubApi(overrides: Partial<Record<string, () => Response>> = {}): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({
        url,
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      const path = url.split('?')[0] ?? url
      const custom = overrides[path]
      if (custom) return Promise.resolve(custom())
      if (path === '/api/infographics') return Promise.resolve(new Response(JSON.stringify({ infographics: [COUNTER, BAR] })))
      if (path === '/api/state') return Promise.resolve(new Response(JSON.stringify(STATE)))
      if (path === '/api/templates') return Promise.resolve(new Response('[]'))
      if (path.endsWith('/frame')) return Promise.resolve(new Response(new Blob(['png']), { status: 200 }))
      return Promise.resolve(new Response('{"detail":"nada"}', { status: 404 }))
    }),
  )
}

async function mountView() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/infograficos')
  await router.isReady()
  return mount(InfographicsView, { global: { plugins: [router] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:quadro', revokeObjectURL: () => undefined }))
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('InfographicsView', () => {
  it('lista cada modelo com a descrição e o quadro de exemplo da marca escolhida', async () => {
    stubApi()
    const wrapper = await mountView()
    await flushPromises()
    const cards = wrapper.findAll('.infographic')
    expect(cards.map((card) => card.find('.infographic__name').text())).toEqual(['contador', 'barra'])
    expect(cards[0]!.text()).toContain('conta de um valor')
    expect(cards[0]!.find('img').attributes('src')).toBe('/api/infographics/contador/preview')
    await wrapper.find('#infographic-brand').setValue('minha')
    await flushPromises()
    expect(wrapper.find('.infographic img').attributes('src')).toBe('/api/infographics/contador/preview?brand=minha')
  })

  it('filtra pela busca e avisa quando nada combina', async () => {
    stubApi()
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.find('input[type="search"]').setValue('enche')
    expect(wrapper.findAll('.infographic__name').map((node) => node.text())).toEqual(['barra'])
    await wrapper.find('input[type="search"]').setValue('zzz')
    expect(wrapper.text()).toContain('Nada encontrado')
  })

  it('monta o formulário do esquema e pede o quadro com os valores digitados', async () => {
    stubApi()
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.findAll('.infographic')[0]!.find('footer button').trigger('click')
    // um campo por parâmetro, com o rótulo em português
    const labels = wrapper.findAll('.editor__form label').map((node) => node.text().replace('*', '').trim())
    expect(labels).toEqual(['Começa em', 'Termina em', 'Antes do número', 'Ritmo', 'Sombra suave'])
    expect((wrapper.find('#contador-ate').element as HTMLInputElement).value).toBe('10000')

    await wrapper.find('#contador-ate').setValue('95')
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()
    const frame = calls.filter((call) => call.url === '/api/infographics/contador/frame').at(-1)!
    expect(frame.method).toBe('POST')
    expect(frame.body).toMatchObject({ params: { de: 0, ate: 95, prefixo: '+ de R$', easing: 'suave', sombra: true }, at: 2.4 })
    expect(wrapper.find('.frame img').attributes('src')).toBe('blob:quadro')
  })

  it('aponta o valor fora do esquema e não pede o quadro enquanto estiver errado', async () => {
    stubApi()
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.findAll('.infographic')[0]!.find('footer button').trigger('click')
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()
    const before = calls.filter((call) => call.url.endsWith('/frame')).length

    await wrapper.find('#contador-ate').setValue('dez mil')
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Termina em: precisa ser um número.')
    expect(calls.filter((call) => call.url.endsWith('/frame')).length).toBe(before)
    expect(wrapper.find('button.btn--primary[disabled]').exists()).toBe(true)
  })

  it('mostra o erro do servidor quando o quadro não sai', async () => {
    stubApi({
      '/api/infographics/contador/frame': () =>
        new Response(JSON.stringify({ detail: 'O Chromium não está instalado: rode dmaker setup --html' }), {
          status: 503,
        }),
    })
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.findAll('.infographic')[0]!.find('footer button').trigger('click')
    await vi.advanceTimersByTimeAsync(600)
    await flushPromises()
    expect(wrapper.find('.frame__error').text()).toContain('dmaker setup --html')
  })

  it('copia o trecho de spec com o modelo e os valores que diferem do padrão', async () => {
    stubApi()
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = await mountView()
    await flushPromises()
    await wrapper.findAll('.infographic')[0]!.find('footer button').trigger('click')
    await wrapper.find('button.btn--primary').trigger('click')
    await flushPromises()
    const copied = JSON.parse(writeText.mock.calls[0]![0] as string)
    expect(copied).toMatchObject({ type: 'html', infographic: 'contador', data: { ate: 10000, prefixo: '+ de R$' } })
    expect(useToastsStore().items.at(-1)?.title).toBe('Trecho copiado')
  })

  it('explica quando a API falha', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    const wrapper = await mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('Não foi possível carregar os infográficos')
  })
})
