import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource } from '@/test/fetch'
import { buttonLabelled, callsTo, CLIP, PROJECT, press, stubSpeechServer, type ServerCall } from '@/test/speechServer'
import { mountRoute } from '@/test/routes'

let calls: ServerCall[]

beforeEach(() => {
  localStorage.setItem('dmaker.currentProject', PROJECT)
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  calls = stubSpeechServer()
})
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

async function mountView() {
  const mounted = await mountRoute('/voz/isolar')
  await flushPromises()
  return mounted
}

const button = buttonLabelled
const result = {
  voice: 'output/isolamento/a.voz.wav',
  background: 'output/isolamento/a.fundo.wav',
  voice_url: '/api/voices/audio?path=voz',
  background_url: '/api/voices/audio?path=fundo',
}

async function finish(wrapper: VueWrapper, payload: unknown = result) {
  FakeEventSource.latest().emit({ kind: 'end', t: 9, status: 'done', error: null, result: payload })
  await flushPromises()
  return wrapper
}

describe('IsolateView (/voz/isolar)', () => {
  it('mostra o formulário com a mídia do projeto aberto e o botão pronto', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.text()).toContain('Isolar voz')
    expect(wrapper.findAll('option').map((option) => option.text())).toContain('entrevista.mp4')
    expect(wrapper.text()).toContain('Início (s, opcional)')
    expect(wrapper.text()).toContain('Fim (s, opcional)')
    expect(wrapper.findAll('select')[1]!.findAll('option').map((option) => option.text())).toEqual(['wav (sem perdas)', 'mp3'])
    expect(button(wrapper, 'Isolar voz').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain('em construção')
  })

  it('manda o arquivo, o intervalo e o formato, acompanha o andamento e mostra voz e fundo com player e baixar', async () => {
    const { wrapper } = await mountView()
    const [startInput, endInput] = wrapper.findAll('input[type="number"]')
    await startInput!.setValue('2')
    await endInput!.setValue('8.5')
    await wrapper.findAll('select')[1]!.setValue('mp3')
    await press(wrapper, 'Isolar voz')
    await flushPromises()

    expect(callsTo(calls, 'POST', '/api/speech/isolate')[0]!.body).toEqual({ path: CLIP, start: 2, end: 8.5, format: 'mp3' })
    expect(wrapper.text()).toContain('Na fila...')
    expect(button(wrapper, 'Isolar voz').attributes('disabled')).toBeDefined()

    FakeEventSource.latest().emit({ kind: 'progress', t: 1, label: 'bloco 1 de 2', done: 1, total: 2, percent: 50 })
    await flushPromises()
    expect(wrapper.text()).toContain('bloco 1 de 2')
    expect(wrapper.text()).toContain('50%')

    await finish(wrapper)
    expect(wrapper.text()).toContain('Voz e fundo prontos')
    expect(wrapper.text()).toContain('De entrevista.mp4')
    const players = wrapper.findAll('audio')
    expect(players).toHaveLength(2)
    expect(players[0]!.attributes('src')).toContain('/api/voices/audio?path=voz')
    expect(players[1]!.attributes('src')).toContain('/api/voices/audio?path=fundo')
    expect(button(wrapper, 'Baixar voz')).toBeDefined()
    expect(button(wrapper, 'Baixar fundo')).toBeDefined()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(button(wrapper, 'Isolar voz').attributes('disabled')).toBeUndefined()
  })

  it('os botões de baixar pedem o arquivo como anexo', async () => {
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute('href') ?? '')
    })
    const { wrapper } = await mountView()
    await press(wrapper, 'Isolar voz')
    await flushPromises()
    await finish(wrapper)

    await press(wrapper, 'Baixar voz')
    await press(wrapper, 'Baixar fundo')
    await flushPromises()
    expect(clicked).toEqual(['/api/voices/audio?path=voz&download=true', '/api/voices/audio?path=fundo&download=true'])
  })

  it('sem início e fim manda o arquivo inteiro em wav', async () => {
    const { wrapper } = await mountView()
    await press(wrapper, 'Isolar voz')
    await flushPromises()
    expect(callsTo(calls, 'POST', '/api/speech/isolate')[0]!.body).toEqual({ path: CLIP, start: null, end: null, format: 'wav' })
    await finish(wrapper)
  })

  it('fim antes do início trava o botão e diz o motivo', async () => {
    const { wrapper } = await mountView()
    const [startInput, endInput] = wrapper.findAll('input[type="number"]')
    await startInput!.setValue('9')
    await endInput!.setValue('3')
    expect(wrapper.find('[role="alert"]').text()).toBe('O fim precisa ser maior que o início.')
    expect(button(wrapper, 'Isolar voz').attributes('disabled')).toBeDefined()
    expect(callsTo(calls, 'POST', '/api/speech/isolate')).toHaveLength(0)
  })

  it('erro do trabalho aparece na tela e destrava o botão', async () => {
    const { wrapper } = await mountView()
    await press(wrapper, 'Isolar voz')
    await flushPromises()
    FakeEventSource.latest().emit({ kind: 'end', t: 2, status: 'error', error: 'RuntimeError: o modelo de separação não está instalado\ntraceback', result: null })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('o modelo de separação não está instalado')
    expect(wrapper.text()).not.toContain('Voz e fundo prontos')
    expect(button(wrapper, 'Isolar voz').attributes('disabled')).toBeUndefined()
  })

  it('recusa do servidor ao iniciar (arquivo sumiu) também aparece', async () => {
    calls = stubSpeechServer({ startReply: { body: { detail: 'Arquivo não encontrado: D:/m/entrevista.mp4' }, status: 404 } })
    const { wrapper } = await mountView()
    await press(wrapper, 'Isolar voz')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Arquivo não encontrado')
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('o resultado sobrevive a mudar de aba da Voz e voltar', async () => {
    const { wrapper, router } = await mountView()
    await press(wrapper, 'Isolar voz')
    await flushPromises()
    await finish(wrapper)

    await router.push('/voz/trocar')
    await flushPromises()
    expect(wrapper.text()).not.toContain('Voz e fundo prontos')
    await router.push('/voz/isolar')
    await flushPromises()
    expect(wrapper.text()).toContain('Voz e fundo prontos')
    expect(wrapper.findAll('audio')).toHaveLength(2)
  })

  it('o arquivo escolhido não volta ao primeiro do projeto ao mudar de aba e voltar', async () => {
    const SECOND = 'D:/m/aula.mp4'
    calls = stubSpeechServer({ spec: { name: PROJECT, timeline: [{ type: 'clip', src: CLIP }, { type: 'clip', src: SECOND }] } })
    const { wrapper, router } = await mountView()
    await wrapper.findAll('select')[0]!.setValue('project:1')

    await router.push('/voz/trocar')
    await flushPromises()
    await router.push('/voz/isolar')
    await flushPromises()
    expect((wrapper.findAll('select')[0]!.element as HTMLSelectElement).value).toBe('project:1')

    await press(wrapper, 'Isolar voz')
    await flushPromises()
    expect(callsTo(calls, 'POST', '/api/speech/isolate')[0]!.body).toMatchObject({ path: SECOND })
    await finish(wrapper)
  })

  it('sem projeto aberto oferece o envio do arquivo', async () => {
    localStorage.clear()
    const { wrapper } = await mountView()
    expect(wrapper.text()).toContain('Abra um projeto')
    expect(wrapper.find('input[type="file"]').exists()).toBe(true)
    expect(button(wrapper, 'Isolar voz').attributes('disabled')).toBeDefined()
  })
})
