import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, type Router } from 'vue-router'
import type { VoiceProfile } from '@/api'
import ConfirmHost from '@/components/ui/ConfirmHost.vue'
import { createAppRouter } from '@/router'
import { useToastsStore } from '@/stores/toasts'
import { useVoiceStore } from '@/stores/voice'
import { FakeEventSource } from '@/test/fetch'
import VoiceLibraryCard from './VoiceLibraryCard.vue'

const LANGUAGES = [{ value: 'pt', label: 'Português' }]
const BRANDS = [
  { value: 'medlycare', label: 'MedlyCare' },
  { value: 'pascom', label: 'Pascom' },
]

function voice(id: string, overrides: Partial<VoiceProfile> = {}): VoiceProfile {
  return {
    id,
    name: id[0]!.toUpperCase() + id.slice(1),
    kind: 'clone',
    engine: 'omnivoice',
    preset: null,
    language: 'pt',
    brand: null,
    instruct: null,
    reference: null,
    reference_text: null,
    created: '2026-10-29',
    ...overrides,
  }
}

interface Call {
  method: string
  url: string
}

let calls: Call[]
let listing: () => VoiceProfile[]
let wrapper: VueWrapper | null = null
let router: Router

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  listing = () => [voice('ana'), voice('beto', { kind: 'design', instruct: 'female, low pitch' })]
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      calls.push({ method, url })
      const path = url.split('?')[0]
      if (path === '/api/voices' && method === 'GET') return Promise.resolve(new Response(JSON.stringify(listing())))
      if (path?.endsWith('/preview')) return Promise.resolve(new Response('{"job_id":"j1"}'))
      if (method === 'DELETE') return Promise.resolve(new Response('{"ok":true}'))
      return Promise.resolve(new Response('{"detail":"nada"}', { status: 404 }))
    }),
  )
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

async function mountCard(): Promise<VueWrapper> {
  router = createAppRouter(createMemoryHistory())
  await router.push('/voz')
  await router.isReady()
  const Host = defineComponent({
    render: () => [h(VoiceLibraryCard, { languages: LANGUAGES, brands: BRANDS }), h(ConfirmHost)],
  })
  wrapper = mount(Host, { global: { plugins: [router] }, attachTo: document.body })
  await useVoiceStore().loadVoices()
  await flushPromises()
  return wrapper
}

const item = (id: string) => wrapper!.find(`[data-voice="${id}"]`)
const buttonOf = (id: string, label: string) =>
  item(id)
    .findAll('button')
    .find((node) => node.text() === label)!
/** O botão do diálogo de confirmação (a lista também tem um "Remover" por voz, fora do diálogo). */
const dialogButton = (label: string) =>
  Array.from(document.body.querySelectorAll('[role="alertdialog"] button')).find(
    (node) => node.textContent?.trim() === label,
  ) as HTMLButtonElement | undefined

describe('VoiceLibraryCard', () => {
  it('lista as vozes da biblioteca', async () => {
    await mountCard()
    expect(wrapper!.findAll('li[data-voice]').map((node) => node.find('strong').text())).toEqual(['Ana', 'Beto'])
    expect(item('beto').text()).toContain('desenhada')
  })

  it('sem vozes mostra a dica de como criar uma', async () => {
    listing = () => []
    await mountCard()
    expect(wrapper!.text()).toContain('Nenhuma voz ainda')
    expect(wrapper!.findAll('li[data-voice]')).toHaveLength(0)
  })

  it('falha ao listar mostra o motivo e deixa tentar de novo', async () => {
    await mountCard()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"biblioteca ilegível"}', { status: 500 })))
    await useVoiceStore().loadVoices()
    await flushPromises()
    expect(wrapper!.find('[role="alert"]').text()).toContain('biblioteca ilegível')
    expect(wrapper!.text()).toContain('Tentar de novo')
  })

  describe('filtro por marca', () => {
    it('oferece "Todas as vozes" e as marcas', async () => {
      await mountCard()
      const options = wrapper!.find('select').findAll('option')
      expect(options.map((node) => node.text())).toEqual(['Todas as vozes', 'MedlyCare', 'Pascom'])
    })

    it('escolher a marca consulta o servidor com ela e atualiza a lista', async () => {
      await mountCard()
      listing = () => [voice('ana', { brand: 'medlycare' })]
      await wrapper!.find('select').setValue('medlycare')
      await flushPromises()
      expect(calls.at(-1)).toEqual({ method: 'GET', url: '/api/voices?brand=medlycare' })
      expect(wrapper!.findAll('li[data-voice]')).toHaveLength(1)
    })
  })

  describe('Ouvir', () => {
    it('gera a amostra como job, mostra o andamento e toca o resultado', async () => {
      const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
      await mountCard()
      await buttonOf('ana', 'Ouvir').trigger('click')
      await flushPromises()

      expect(calls).toContainEqual({ method: 'POST', url: '/api/voices/ana/preview' })
      expect(item('ana').text()).toContain('Gerando amostra... 0:00')
      expect(buttonOf('ana', 'Ouvir').attributes('disabled')).toBeDefined()
      expect(buttonOf('beto', 'Ouvir').attributes('disabled')).toBeUndefined()

      const source = FakeEventSource.latest()
      source.emit({ kind: 'progress', t: 1, label: 'fala 1 de 1', done: 1, total: 1, percent: 0 })
      await flushPromises()
      expect(item('ana').text()).toContain('fala 1 de 1')

      source.emit({
        kind: 'end',
        t: 8,
        status: 'done',
        error: null,
        result: { output: 'a.wav', audio_url: '/api/voices/audio?path=a.wav', duration_s: 3, cues: [] },
      })
      await flushPromises()

      expect(wrapper!.text()).toContain('Amostra de Ana')
      expect(wrapper!.find('audio').attributes('src')).toContain('/api/voices/audio?path=a.wav')
      expect(play).toHaveBeenCalledTimes(1)
      expect(item('ana').find('.voice__status').exists()).toBe(false)
      expect(buttonOf('ana', 'Ouvir').attributes('disabled')).toBeUndefined()
    })

    it('se o navegador não deixar tocar sozinho, avisa para usar o player', async () => {
      vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(new DOMException('bloqueado', 'NotAllowedError'))
      await mountCard()
      await buttonOf('ana', 'Ouvir').trigger('click')
      await flushPromises()
      FakeEventSource.latest().emit({
        kind: 'end',
        t: 8,
        status: 'done',
        error: null,
        result: { output: 'a.wav', audio_url: '/a.wav', duration_s: 3, cues: [] },
      })
      await flushPromises()
      expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'info', title: 'Amostra pronta' })
      expect(wrapper!.find('audio').exists()).toBe(true)
    })

    it('quando o job falha, o erro fica sob a voz', async () => {
      await mountCard()
      await buttonOf('ana', 'Ouvir').trigger('click')
      await flushPromises()
      FakeEventSource.latest().emit({
        kind: 'end',
        t: 2,
        status: 'error',
        error: 'RuntimeError: modelo de voz ausente',
        result: null,
      })
      await flushPromises()
      expect(item('ana').find('[role="alert"]').text()).toBe('Não consegui gerar a amostra: modelo de voz ausente')
    })
  })

  describe('Usar', () => {
    it('leva a voz para o roteiro: marca no store, no card e avisa com atalho para a Narração', async () => {
      await mountCard()
      await buttonOf('beto', 'Usar').trigger('click')

      expect(useVoiceStore().selectedVoiceId).toBe('beto')
      expect(localStorage.getItem('dmaker.voice.lastVoice')).toBe('beto')
      expect(item('beto').text()).toContain('Voz do roteiro')
      expect(item('ana').text()).not.toContain('Voz do roteiro')

      const toast = useToastsStore().items.at(-1)!
      expect(toast.title).toBe('Voz "Beto" escolhida')
      expect(toast.action?.label).toBe('Abrir a Narração')
      toast.action?.run()
      // a tela da Narração é carregada sob demanda: a rota muda quando o módulo chega
      await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/voz/narracao'))
    })

    it('a voz lembrada da última vez já aparece marcada', async () => {
      localStorage.setItem('dmaker.voice.lastVoice', 'ana')
      setActivePinia(createPinia())
      await mountCard()
      expect(item('ana').text()).toContain('Voz do roteiro')
    })
  })

  describe('Remover', () => {
    it('pergunta antes e só apaga se a pessoa confirmar', async () => {
      await mountCard()
      await buttonOf('ana', 'Remover').trigger('click')
      await flushPromises()
      expect(document.body.textContent).toContain('Remover a voz "Ana"?')
      expect(document.body.textContent).toContain('apaga a gravação de referência')
      expect(calls.some((call) => call.method === 'DELETE')).toBe(false)

      listing = () => [voice('beto', { kind: 'design' })]
      dialogButton('Remover')?.click()
      await flushPromises()

      expect(calls).toContainEqual({ method: 'DELETE', url: '/api/voices/ana' })
      expect(wrapper!.findAll('li[data-voice]')).toHaveLength(1)
      expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'success', title: 'Voz removida' })
    })

    it('cancelar na confirmação não apaga nada', async () => {
      await mountCard()
      await buttonOf('ana', 'Remover').trigger('click')
      await flushPromises()
      dialogButton('Cancelar')?.click()
      await flushPromises()
      expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
      expect(wrapper!.findAll('li[data-voice]')).toHaveLength(2)
    })

    it('a voz pronta do motor não oferece Remover', async () => {
      listing = () => [voice('pf-dora', { kind: 'preset', engine: 'kokoro' })]
      await mountCard()
      expect(item('pf-dora').findAll('button').map((node) => node.text())).toEqual(['Ouvir', 'Usar'])
    })

    it('se o servidor recusar apagar, avisa o motivo', async () => {
      await mountCard()
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(new Response('{"detail":"voz em uso"}', { status: 400 })),
      )
      await buttonOf('ana', 'Remover').trigger('click')
      await flushPromises()
      dialogButton('Remover')?.click()
      await flushPromises()
      expect(useToastsStore().items.at(-1)).toMatchObject({
        tone: 'error',
        title: 'Não consegui remover a voz',
        description: 'voz em uso',
      })
    })
  })
})
