import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { FakeEventSource } from '@/test/fetch'
import { buttonLabelled, callsTo, press, type ServerCall } from '@/test/speechServer'
import { stubVoiceServer } from '@/test/voiceServer'
import { useNarrationStore } from '@/stores/narration'
import { useToastsStore } from '@/stores/toasts'
import NarrationForm from './NarrationForm.vue'

let wrapper: VueWrapper | null = null
let calls: ServerCall[]
const LANGUAGES = [
  { value: 'pt', label: 'Português' },
  { value: 'en', label: 'Inglês' },
]
const BRANDS = [{ value: 'medlycare', label: 'MedlyCare' }]

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  // sem Web Audio: o formulário não depende da prévia ao vivo, e o jsdom não tem AudioContext
  calls = stubVoiceServer().calls
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

async function mountForm() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/fila', component: { template: '<p />' } }] })
  const push = vi.spyOn(router, 'push')
  wrapper = mount(NarrationForm, {
    props: { languages: LANGUAGES, brands: BRANDS },
    global: { plugins: [router] },
    attachTo: document.body,
  })
  await useNarrationStore().loadVoices()
  await flushPromises()
  return push
}

function field(label: string) {
  const owner = wrapper!.findAll('label').find((node) => node.text().startsWith(label))
  if (!owner) throw new Error(`campo "${label}" não encontrado`)
  return wrapper!.find(`#${owner.attributes('for')}`)
}

const dialog = () => document.body.querySelector('[role="dialog"]') as HTMLElement | null
const submitDialog = async () => {
  ;(dialog()!.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { cancelable: true }))
  await flushPromises()
}

describe('NarrationForm', () => {
  it('as escolhas da voz entram na store: a voz, o idioma, a velocidade, a semente e o dicionário', async () => {
    await mountForm()
    const narration = useNarrationStore()
    await field('Voz').setValue('dora')
    await field('Idioma').setValue('en')
    await field('Velocidade').setValue('1.5')
    await field('Semente (opcional)').setValue('9')
    await field('Dicionário de pronúncia').setValue('medlycare')
    await field('Roteiro').setValue('Olá.')
    expect(narration).toMatchObject({ voiceId: 'dora', language: 'en', speed: 1.5, seed: 9, brand: 'medlycare', text: 'Olá.' })
  })

  it('avisa quando as vozes não carregaram', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'servidor parado' }), { status: 500 })))
    await mountForm()
    expect(wrapper!.text()).toContain('Não consegui carregar as vozes: servidor parado')
  })

  it('enviar o formulário gera a narração', async () => {
    await mountForm()
    await field('Roteiro').setValue('Olá.')
    await press(wrapper!, 'Gerar narração')
    await flushPromises()
    expect(callsTo(calls, 'POST', '/api/voices/speak')).toHaveLength(1)
    expect(wrapper!.text()).toContain('Na fila...')
    expect(wrapper!.text()).toContain('Na CPU a síntese é lenta')
  })

  it('o aviso de que a prévia foi silenciada desliga o botão de silenciar', async () => {
    await mountForm()
    const narration = useNarrationStore()
    narration.live.visible = true
    narration.live.muted = true
    await flushPromises()
    expect(buttonLabelled(wrapper!, 'Silenciar prévia').attributes('disabled')).toBeDefined()
  })

  describe('mandar para a fila', () => {
    it('manda o roteiro, fecha o diálogo e oferece ir à fila', async () => {
      const push = await mountForm()
      await field('Roteiro').setValue('Um roteiro longo.')
      await buttonLabelled(wrapper!, 'Mandar para a fila').trigger('click')
      await flushPromises()
      expect(dialog()).not.toBeNull()

      await submitDialog()
      expect(callsTo(calls, 'POST', '/api/voices/queue')).toHaveLength(1)
      expect(dialog()).toBeNull()
      const toast = useToastsStore().items.at(-1)!
      expect(toast).toMatchObject({ tone: 'success', title: 'Roteiro na fila' })
      toast.action!.run()
      expect(push).toHaveBeenCalledWith('/fila')
    })

    it('se a fila recusa, avisa e deixa o diálogo aberto para tentar de novo', async () => {
      calls = stubVoiceServer({ queueReply: { status: 400, body: { detail: 'Roteiro vazio.' } } }).calls
      await mountForm()
      await field('Roteiro').setValue('Um roteiro.')
      await buttonLabelled(wrapper!, 'Mandar para a fila').trigger('click')
      await flushPromises()
      await submitDialog()

      expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'error', description: 'Roteiro vazio.' })
      expect(dialog()).not.toBeNull()
    })
  })
})
