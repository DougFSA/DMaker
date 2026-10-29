import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource } from '@/test/fetch'
import { mountRoute } from '@/test/routes'
import { buttonLabelled, callsTo, CLIP, PROJECT, press, stubSpeechServer, type ServerCall } from '@/test/speechServer'

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

const CONVERTED = {
  output: 'X:/saida/voz/entrevista.dora.wav',
  audio_url: '/api/voices/audio?path=trocado',
  original: CLIP,
  original_url: '/api/file?path=original',
  voice: 'dora',
  seconds: 30,
  blocks: 2,
  gain_db: -3.04,
  excerpt: false,
}

async function mountView() {
  const mounted = await mountRoute('/voz/trocar')
  await flushPromises()
  return mounted
}

const emitEnd = async (result: unknown, status = 'done', error: string | null = null) => {
  FakeEventSource.latest().emit({ kind: 'end', t: 9, status, error, result })
  await flushPromises()
}

function field(wrapper: VueWrapper, label: string) {
  const owner = wrapper.findAll('label').find((node) => node.text().startsWith(label))
  if (!owner) throw new Error(`campo "${label}" não encontrado`)
  return wrapper.find(`#${owner.attributes('for')}`)
}

describe('SwapVoiceView (/voz/trocar)', () => {
  it('mostra os campos, a lista de vozes e o botão desligado até escolher a voz', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.text()).toContain('Trocar voz')
    expect(wrapper.text()).not.toContain('em construção')
    expect(field(wrapper, 'Voz que vai falar').findAll('option').map((option) => option.text())).toEqual([
      'Escolha a voz...',
      'Dora (feminina)',
      'Entrevistado (clonada)',
    ])
    expect(buttonLabelled(wrapper, 'Trocar voz').attributes('disabled')).toBeDefined()
    await field(wrapper, 'Voz que vai falar').setValue('dora')
    expect(buttonLabelled(wrapper, 'Trocar voz').attributes('disabled')).toBeUndefined()
  })

  it('troca o arquivo inteiro: manda a voz sem intervalo e mostra resumo, A/B, baixar e usar no projeto', async () => {
    const { wrapper } = await mountView()
    await field(wrapper, 'Voz que vai falar').setValue('dora')
    await press(wrapper, 'Trocar voz')
    await flushPromises()

    expect(callsTo(calls, 'POST', '/api/speech/convert')[0]!.body).toEqual({ path: CLIP, voice: 'dora', start: null, end: null })
    FakeEventSource.latest().emit({ kind: 'progress', t: 1, label: 'separando a voz', done: 10, total: 100, percent: 10 })
    await flushPromises()
    expect(wrapper.text()).toContain('separando a voz')

    await emitEnd(CONVERTED)
    expect(wrapper.text()).toContain('Arquivo convertido para a voz dora: 30,0 s em 2 bloco(s); volume desceu 3,0 dB para igualar ao original.')
    expect(buttonLabelled(wrapper, 'Ouvir original')).toBeDefined()
    expect(buttonLabelled(wrapper, 'Ouvir voz trocada')).toBeDefined()
    const players = wrapper.findAll('audio')
    expect(players[0]!.attributes('src')).toBe('/api/file?path=original')
    expect(players[1]!.attributes('src')).toContain('/api/voices/audio?path=trocado')
    expect(buttonLabelled(wrapper, 'Baixar com a voz trocada')).toBeDefined()
    expect(buttonLabelled(wrapper, 'Usar no projeto').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain('1,5 s antes e depois')
  })

  it('o A/B do arquivo inteiro parte do ponto em que o outro lado estava', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
    const { wrapper } = await mountView()
    await field(wrapper, 'Voz que vai falar').setValue('dora')
    await press(wrapper, 'Trocar voz')
    await flushPromises()
    await emitEnd(CONVERTED)

    const [original, converted] = wrapper.findAll('audio').map((node) => node.element as HTMLAudioElement)
    original!.currentTime = 12
    await buttonLabelled(wrapper, 'Ouvir voz trocada').trigger('click')
    expect(converted!.currentTime).toBe(12)
  })

  it('só um trecho: manda início e fim, avisa que o original é o arquivo todo e não deixa usar no projeto', async () => {
    const { wrapper } = await mountView()
    await field(wrapper, 'Voz que vai falar').setValue('entrevistado')
    await field(wrapper, 'Início').setValue('10')
    await field(wrapper, 'Fim').setValue('30')
    await press(wrapper, 'Trocar voz')
    await flushPromises()
    expect(callsTo(calls, 'POST', '/api/speech/convert')[0]!.body).toEqual({ path: CLIP, voice: 'entrevistado', start: 10, end: 30 })

    await emitEnd({ ...CONVERTED, excerpt: true, seconds: 20, blocks: 1, voice: 'entrevistado', gain_db: 0 })
    expect(wrapper.text()).toContain('Trecho convertido para a voz entrevistado')
    expect(wrapper.text()).toContain('trecho de 10,0 s até 30,0 s do original')
    expect(buttonLabelled(wrapper, 'Usar no projeto').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Só o arquivo inteiro pode entrar no projeto')
  })

  it('"Usar no projeto" troca o arquivo inteiro no projeto e salva', async () => {
    const { wrapper } = await mountView()
    await field(wrapper, 'Voz que vai falar').setValue('dora')
    await press(wrapper, 'Trocar voz')
    await flushPromises()
    await emitEnd(CONVERTED)

    await press(wrapper, 'Usar no projeto')
    await flushPromises()

    const edits = callsTo(calls, 'POST', `/api/projects/${PROJECT}/edit`).map((call) => (call.body as { op: unknown }).op)
    expect(edits).toEqual([
      { type: 'set_field', path: 'timeline.0.src', value: CONVERTED.output },
      { type: 'set_field', path: 'overlays.0.src', value: CONVERTED.output },
    ])
    expect(callsTo(calls, 'PUT', `/api/projects/${PROJECT}`)).toHaveLength(1)
    expect(wrapper.text()).toContain(`Projeto ${PROJECT} atualizado: voz trocada em 2 ponto(s).`)
  })

  it('fim antes do início trava o botão e diz o motivo', async () => {
    const { wrapper } = await mountView()
    await field(wrapper, 'Voz que vai falar').setValue('dora')
    await field(wrapper, 'Início').setValue('9')
    await field(wrapper, 'Fim').setValue('3')
    expect(wrapper.find('[role="alert"]').text()).toBe('O fim precisa ser maior que o início.')
    expect(buttonLabelled(wrapper, 'Trocar voz').attributes('disabled')).toBeDefined()
  })

  it('erro do trabalho aparece na tela e o botão volta a funcionar', async () => {
    const { wrapper } = await mountView()
    await field(wrapper, 'Voz que vai falar').setValue('dora')
    await press(wrapper, 'Trocar voz')
    await flushPromises()
    await emitEnd(null, 'error', 'RuntimeError: o modelo de conversão não está instalado\ntraceback')

    expect(wrapper.find('[role="alert"]').text()).toContain('o modelo de conversão não está instalado')
    expect(buttonLabelled(wrapper, 'Trocar voz').attributes('disabled')).toBeUndefined()
  })

  it('o resultado sobrevive a mudar de aba da Voz e voltar', async () => {
    const { wrapper, router } = await mountView()
    await field(wrapper, 'Voz que vai falar').setValue('dora')
    await press(wrapper, 'Trocar voz')
    await flushPromises()
    await emitEnd(CONVERTED)

    await router.push('/voz/isolar')
    await flushPromises()
    await router.push('/voz/trocar')
    await flushPromises()
    expect(wrapper.text()).toContain('Arquivo convertido para a voz dora')
    expect((field(wrapper, 'Voz que vai falar').element as HTMLSelectElement).value).toBe('dora')
  })
})
