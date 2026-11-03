import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoiceDesignOptions } from '@/api'
import { mountRoute } from '@/test/routes'

const OPTIONS: VoiceDesignOptions = {
  gender: [{ value: 'female', label: 'feminino' }],
  age: [{ value: 'middle-aged', label: 'meia-idade' }],
  pitch: [{ value: 'low pitch', label: 'grave' }],
  accent: [{ value: 'british accent', label: 'britânico' }],
  languages: [
    { value: 'pt', label: 'Português' },
    { value: 'en', label: 'Inglês' },
  ],
}
const STATE = {
  presets: [],
  brands: [
    { key: 'default', name: 'Padrão', colors: {} },
    { key: 'medlycare', name: 'MedlyCare', colors: {} },
  ],
  projects: [],
}
const VOICE = {
  id: 'ana',
  name: 'Ana',
  kind: 'clone',
  engine: 'omnivoice',
  preset: null,
  language: 'en',
  brand: 'medlycare',
  instruct: null,
  reference: null,
  reference_text: null,
  created: '2026-10-29',
}

let failOptions: boolean
let urls: string[]
let wrapper: VueWrapper | null = null

beforeEach(() => {
  localStorage.clear()
  failOptions = false
  urls = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      urls.push(url)
      const path = url.split('?')[0]
      const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }))
      if (path === '/api/voices') return reply([VOICE])
      if (path === '/api/voices/design-options') {
        return failOptions ? reply({ detail: 'servidor de voz parado' }, 500) : reply(OPTIONS)
      }
      if (path === '/api/state') return reply(STATE)
      if (path === '/api/templates') return reply([])
      return reply({ detail: 'nada' }, 404)
    }),
  )
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
})

/** O formulário está à mostra? O `isVisible` do test-utils lê um estilo calculado velho no jsdom, então confere o `display` direto. */
const shown = (selector: string) => !(wrapper!.find(selector).attributes('style') ?? '').includes('display: none')

async function openVoices(): Promise<VueWrapper> {
  const mounted = await mountRoute('/voz')
  wrapper = mounted.wrapper
  await flushPromises()
  return wrapper
}

describe('VoicesView (/voz)', () => {
  it('mostra a biblioteca e a criação de voz lado a lado, sob o título e as abas da Voz', async () => {
    await openVoices()
    expect(wrapper!.find('h1').text()).toBe('Voz')
    expect(wrapper!.find('nav[aria-label="Seções da Voz"] a.is-active').text()).toBe('Vozes')
    const titles = wrapper!.findAll('h3').map((node) => node.text())
    expect(titles).toEqual(['Biblioteca', 'Nova voz'])
    expect(wrapper!.text()).not.toContain('em construção')
  })

  it('carrega as vozes, as opções de desenho e as marcas ao abrir', async () => {
    await openVoices()
    expect(urls).toContain('/api/voices')
    expect(urls).toContain('/api/voices/design-options')
    expect(urls).toContain('/api/state')
    expect(wrapper!.find('[data-voice="ana"]').text()).toContain('Ana')
    // o idioma da voz aparece por extenso e a marca vem do catálogo
    expect(wrapper!.find('[data-voice="ana"]').text()).toContain('Inglês · medlycare')
  })

  it('a criação abre em Clonar, com a caixa de permissão, e Desenhar troca o formulário', async () => {
    await openVoices()
    const pressed = () =>
      wrapper!
        .findAll('[aria-label="Como criar a voz"] button[aria-pressed="true"]')
        .map((node) => node.text())
        .join()
    expect(pressed()).toBe('Clonar')
    expect(shown('form.clone')).toBe(true)
    expect(shown('form.design')).toBe(false)
    expect(wrapper!.text()).toContain('Tenho permissão do dono desta voz para cloná-la')

    await wrapper!
      .findAll('button')
      .find((node) => node.text() === 'Desenhar')!
      .trigger('click')
    expect(pressed()).toBe('Desenhar')
    expect(shown('form.design')).toBe(true)
    expect(shown('form.clone')).toBe(false)
  })

  it('trocar de aba não perde o que foi preenchido no outro formulário', async () => {
    await openVoices()
    const cloneName = () => wrapper!.find('form.clone input[type="text"]')
    await cloneName().setValue('Voz da clínica')
    await wrapper!.findAll('button').find((node) => node.text() === 'Desenhar')!.trigger('click')
    await wrapper!.findAll('button').find((node) => node.text() === 'Clonar')!.trigger('click')
    expect((cloneName().element as HTMLInputElement).value).toBe('Voz da clínica')
  })

  it('o botão Clonar voz só liga com nome, arquivo e a permissão do dono', async () => {
    await openVoices()
    const submit = () => wrapper!.find('form.clone button[type="submit"]')
    expect(submit().attributes('disabled')).toBeDefined()

    await wrapper!.find('form.clone input[type="text"]').setValue('Ana 2')
    const fileInput = wrapper!.find('form.clone input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', {
      value: [new File(['som'], 'ref.wav', { type: 'audio/wav' })],
      configurable: true,
    })
    await fileInput.trigger('change')
    expect(submit().attributes('disabled')).toBeDefined()

    await wrapper!.find('form.clone input[type="checkbox"]').setValue(true)
    expect(submit().attributes('disabled')).toBeUndefined()
  })

  it('se as opções de voz não carregam, mostra o motivo e tenta de novo', async () => {
    failOptions = true
    await openVoices()
    expect(wrapper!.text()).toContain('Não consegui carregar as opções de voz: servidor de voz parado')
    expect(wrapper!.find('form.clone').exists()).toBe(false)
    // a biblioteca funciona mesmo assim
    expect(wrapper!.find('[data-voice="ana"]').exists()).toBe(true)

    failOptions = false
    await wrapper!.findAll('button').find((node) => node.text() === 'Tentar de novo')!.trigger('click')
    await flushPromises()
    expect(wrapper!.find('form.clone').exists()).toBe(true)
  })
})
