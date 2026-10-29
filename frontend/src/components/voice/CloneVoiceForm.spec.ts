import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { microphoneKey } from '@/composables/useMicrophoneRecorder'
import { createMicrophone } from '@/lib/microphone'
import { useToastsStore } from '@/stores/toasts'
import { useVoiceStore } from '@/stores/voice'
import { FakeRecorder, fakeEnvironment } from '@/test/recorder'
import CloneVoiceForm from './CloneVoiceForm.vue'

const LANGUAGES = [
  { value: 'pt', label: 'Português' },
  { value: 'en', label: 'Inglês' },
]
const BRANDS = [{ value: 'medlycare', label: 'MedlyCare' }]

interface Call {
  method: string
  url: string
  form: FormData | null
}

let calls: Call[]
let cloneReply: () => Response
let wrapper: VueWrapper | null = null

function stubApi(): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      calls.push({
        method: init.method ?? 'GET',
        url,
        form: init.body instanceof FormData ? init.body : null,
      })
      if (url === '/api/voices/clone') return Promise.resolve(cloneReply())
      return Promise.resolve(new Response('[]'))
    }),
  )
}

const profile = (name: string) => ({ id: name.toLowerCase(), name, kind: 'clone', language: 'pt' })

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  FakeRecorder.reset()
  cloneReply = () => new Response(JSON.stringify(profile('Ana')))
  stubApi()
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
})

function mountForm(microphone = createMicrophone(() => fakeEnvironment())): VueWrapper {
  URL.createObjectURL = vi.fn(() => 'blob:gravacao')
  URL.revokeObjectURL = vi.fn()
  wrapper = mount(CloneVoiceForm, {
    props: { languages: LANGUAGES, brands: BRANDS },
    global: { provide: { [microphoneKey as symbol]: microphone } },
  })
  return wrapper
}

const submit = () => wrapper!.find('button[type="submit"]')
const consent = () => wrapper!.find('input[type="checkbox"]')

async function chooseFile(name = 'referencia.wav', type = 'audio/wav'): Promise<void> {
  const input = wrapper!.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    value: [new File(['som'], name, { type, lastModified: 1 })],
    configurable: true,
  })
  await input.trigger('change')
}

async function fillName(name = 'Ana'): Promise<void> {
  await wrapper!.find('input[type="text"]').setValue(name)
}

describe('CloneVoiceForm', () => {
  it('começa com o botão desligado e diz o que falta', () => {
    mountForm()
    expect(submit().attributes('disabled')).toBeDefined()
    expect(submit().text()).toBe('Clonar voz')
    expect(wrapper!.text()).toContain(
      'Para clonar falta: dar um nome à voz, enviar um arquivo ou gravar pelo microfone, marcar a permissão do dono da voz.',
    )
  })

  it('traz o aviso de permissão e a caixa de autorização sem marcar', () => {
    mountForm()
    expect(wrapper!.text()).toContain('Clone apenas vozes que você tem permissão do dono para usar.')
    expect(wrapper!.text()).toContain('Tenho permissão do dono desta voz para cloná-la')
    expect((consent().element as HTMLInputElement).checked).toBe(false)
  })

  it('com nome e arquivo, mas sem a autorização, o botão continua desligado', async () => {
    mountForm()
    await fillName()
    await chooseFile()
    expect(submit().attributes('disabled')).toBeDefined()
    expect(wrapper!.text()).toContain('Para clonar falta: marcar a permissão do dono da voz.')
  })

  it('marcar a autorização liga o botão, e desmarcar desliga de novo', async () => {
    mountForm()
    await fillName()
    await chooseFile()
    await consent().setValue(true)
    expect(submit().attributes('disabled')).toBeUndefined()
    expect(wrapper!.text()).not.toContain('Para clonar falta')
    await consent().setValue(false)
    expect(submit().attributes('disabled')).toBeDefined()
  })

  it('clona pelo arquivo: manda o multipart, avisa, escolhe a voz e limpa o formulário', async () => {
    mountForm()
    await fillName('  Ana  ')
    await chooseFile('minha-voz.wav')
    await wrapper!.find('textarea').setValue('Olá, tudo bem?')
    await wrapper!.findAll('select')[0]!.setValue('en')
    await wrapper!.findAll('select')[1]!.setValue('medlycare')
    await consent().setValue(true)
    await submit().trigger('submit')
    await flushPromises()

    const post = calls.find((call) => call.url === '/api/voices/clone')!
    expect(post.method).toBe('POST')
    expect(post.form?.get('name')).toBe('Ana')
    expect((post.form?.get('audio') as File).name).toBe('minha-voz.wav')
    expect(post.form?.get('reference_text')).toBe('Olá, tudo bem?')
    expect(post.form?.get('language')).toBe('en')
    expect(post.form?.get('brand')).toBe('medlycare')

    expect(useVoiceStore().selectedVoiceId).toBe('ana')
    expect(useToastsStore().items[0]).toMatchObject({ tone: 'success', title: 'Voz "Ana" clonada' })
    expect((wrapper!.find('input[type="text"]').element as HTMLInputElement).value).toBe('')
    expect((consent().element as HTMLInputElement).checked).toBe(false)
    expect(wrapper!.find('.upload__file').exists()).toBe(false)
    expect(submit().attributes('disabled')).toBeDefined()
  })

  it('sem o texto da gravação, o botão avisa que vai transcrever', async () => {
    let finish: (response: Response) => void = () => undefined
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) =>
        url === '/api/voices/clone'
          ? new Promise<Response>((resolve) => (finish = resolve))
          : Promise.resolve(new Response('[]')),
      ),
    )
    mountForm()
    await fillName()
    await chooseFile()
    await consent().setValue(true)
    await submit().trigger('submit')
    await flushPromises()
    expect(submit().text()).toBe('Clonando e transcrevendo...')
    expect(submit().attributes('disabled')).toBeDefined()

    finish(new Response(JSON.stringify(profile('Ana'))))
    await flushPromises()
    expect(submit().text()).toBe('Clonar voz')
  })

  it('com o texto da gravação, o botão só diz que está clonando', async () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => undefined)))
    mountForm()
    await fillName()
    await chooseFile()
    await wrapper!.find('textarea').setValue('Olá')
    await consent().setValue(true)
    await submit().trigger('submit')
    await flushPromises()
    expect(submit().text()).toBe('Clonando...')
  })

  it('se o servidor recusar, mostra o motivo e mantém o que foi preenchido', async () => {
    cloneReply = () => new Response('{"detail":"O arquivo de áudio enviado está vazio."}', { status: 400 })
    mountForm()
    await fillName()
    await chooseFile()
    await consent().setValue(true)
    await submit().trigger('submit')
    await flushPromises()

    expect(useToastsStore().items[0]).toMatchObject({
      tone: 'error',
      title: 'Não consegui clonar a voz',
      description: 'O arquivo de áudio enviado está vazio.',
    })
    expect((wrapper!.find('input[type="text"]').element as HTMLInputElement).value).toBe('Ana')
    expect((consent().element as HTMLInputElement).checked).toBe(true)
    expect(submit().attributes('disabled')).toBeUndefined()
  })

  it('um arquivo que não é áudio nem vídeo é recusado antes do envio', async () => {
    mountForm()
    await chooseFile('roteiro.txt', 'text/plain')
    expect(wrapper!.find('.upload__problem').text()).toContain('Não aceitei roteiro.txt')
    expect(wrapper!.find('.upload__file').exists()).toBe(false)
  })
})

describe('CloneVoiceForm pelo microfone', () => {
  async function recordSomething(): Promise<void> {
    await wrapper!.findAll('button').find((button) => button.text() === 'Gravar pelo microfone')!.trigger('click')
    await wrapper!.findAll('button').find((button) => button.text() === 'Gravar')!.trigger('click')
    await flushPromises()
    await wrapper!.findAll('button').find((button) => button.text() === 'Parar gravação')!.trigger('click')
    await flushPromises()
  }

  it('trocar para o microfone mostra o gravador e o botão espera a gravação', async () => {
    mountForm()
    await fillName()
    await consent().setValue(true)
    await wrapper!.findAll('button').find((button) => button.text() === 'Gravar pelo microfone')!.trigger('click')
    expect(wrapper!.text()).toContain('Recomendado: 5 a 8 segundos de fala limpa.')
    expect(submit().attributes('disabled')).toBeDefined()
    expect(wrapper!.text()).toContain('enviar um arquivo ou gravar pelo microfone')
  })

  it('depois de gravar, clona com a gravação e o nome do arquivo pelo tipo gravado', async () => {
    mountForm(createMicrophone(() => fakeEnvironment({ mimeType: 'audio/ogg;codecs=opus' })))
    await fillName()
    await consent().setValue(true)
    await recordSomething()
    expect(submit().attributes('disabled')).toBeUndefined()

    await submit().trigger('submit')
    await flushPromises()
    const post = calls.find((call) => call.url === '/api/voices/clone')!
    expect((post.form?.get('audio') as File).name).toBe('gravacao.ogg')
  })

  it('voltar para o arquivo para a gravação em andamento e mantém o que gravou', async () => {
    const environment = fakeEnvironment()
    mountForm(createMicrophone(() => environment))
    await wrapper!.findAll('button').find((button) => button.text() === 'Gravar pelo microfone')!.trigger('click')
    await wrapper!.findAll('button').find((button) => button.text() === 'Gravar')!.trigger('click')
    await flushPromises()
    expect(environment.stream.released).toBe(false)

    await wrapper!.findAll('button').find((button) => button.text() === 'Enviar arquivo')!.trigger('click')
    await flushPromises()
    expect(environment.stream.released).toBe(true)
    // a gravação continua guardada: ao voltar para o microfone ela está lá
    await wrapper!.findAll('button').find((button) => button.text() === 'Gravar pelo microfone')!.trigger('click')
    expect(wrapper!.text()).toContain('Gravar de novo')
  })
})
