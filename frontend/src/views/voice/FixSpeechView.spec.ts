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

const WORDS = {
  words: [
    { start: 1.0, end: 1.4, text: 'Hoje' },
    { start: 1.4, end: 1.9, text: 'é' },
    { start: 2.5, end: 3.0, text: 'o' },
    { start: 3.0, end: 3.6, text: 'casamento' },
    { start: 5.0, end: 5.4, text: 'João' },
  ],
  pause_seconds: 0.25,
}

const FIXED = {
  output: 'X:/saida/correcao/entrevista.corrigido-ab12.mp4',
  audio_url: '/api/voices/audio?path=corrigido',
  original: CLIP,
  original_url: '/api/file?path=original',
  region: [5.0, 5.4],
  old_text: 'João',
  new_text: 'Pedro',
  spoken: 'de Pedro',
  rule: 'duração mantida (0.4 s)',
  squeezed: false,
  voice: 'automática',
}

async function mountView() {
  const mounted = await mountRoute('/voz/corrigir')
  await flushPromises()
  return mounted
}

const emitEnd = async (result: unknown, status = 'done', error: string | null = null) => {
  FakeEventSource.latest().emit({ kind: 'end', t: 9, status, error, result })
  await flushPromises()
}

const word = (wrapper: VueWrapper, text: string) => wrapper.findAll('button.word').find((node) => node.text() === text)!

/** O campo ligado ao rótulo (o `for` do rótulo aponta o `id` do campo). */
function field(wrapper: VueWrapper, label: string) {
  const owner = wrapper.findAll('label').find((node) => node.text().startsWith(label))
  if (!owner) throw new Error(`campo "${label}" não encontrado`)
  return wrapper.find(`#${owner.attributes('for')}`)
}

/** Transcreve e devolve a tela com a lista de palavras já na página. */
async function transcribed() {
  const { wrapper, router } = await mountView()
  await press(wrapper, 'Transcrever')
  await flushPromises()
  await emitEnd(WORDS)
  return { wrapper, router }
}

describe('FixSpeechView (/voz/corrigir)', () => {
  it('começa só com o passo de transcrever; o resto aparece depois', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.text()).toContain('Corrigir fala')
    expect(wrapper.text()).toContain('Transcrever de (s, opcional)')
    expect(wrapper.text()).toContain('até (s, opcional)')
    expect(wrapper.text()).not.toContain('Escolha o trecho a trocar')
    expect(wrapper.text()).not.toContain('Texto novo')
    expect(wrapper.text()).not.toContain('em construção')
    expect(buttonLabelled(wrapper, 'Transcrever').attributes('disabled')).toBeUndefined()
  })

  it('transcrever manda o arquivo e o intervalo e acompanha o job', async () => {
    const { wrapper } = await mountView()
    const [from, to] = wrapper.findAll('input[type="number"]')
    await from!.setValue('10')
    await to!.setValue('40')
    await press(wrapper, 'Transcrever')
    await flushPromises()

    expect(callsTo(calls, 'POST', '/api/speech/words')[0]!.body).toEqual({ path: CLIP, start: 10, end: 40 })
    expect(wrapper.text()).toContain('Na fila...')
    expect(buttonLabelled(wrapper, 'Transcrever').attributes('disabled')).toBeDefined()
    await emitEnd(WORDS)
    expect(wrapper.text()).toContain('Transcrição de entrevista.mp4')
  })

  it('mostra as palavras agrupadas por fôlego e a seleção por dois cliques', async () => {
    const { wrapper } = await transcribed()
    expect(wrapper.findAll('.picker__line')).toHaveLength(3)

    await word(wrapper, 'o').trigger('click')
    await word(wrapper, 'casamento').trigger('click')
    expect(wrapper.text()).toContain('Trecho escolhido: "o casamento" (2,50 a 3,60 s)')
    expect(word(wrapper, 'casamento').classes()).toContain('is-selected')
  })

  it('o botão de corrigir só liga com trecho escolhido e texto novo', async () => {
    const { wrapper } = await transcribed()
    const run = () => buttonLabelled(wrapper, 'Corrigir fala').attributes('disabled')
    expect(run()).toBeDefined()

    await word(wrapper, 'João').trigger('click')
    await word(wrapper, 'João').trigger('click')
    expect(run()).toBeDefined()

    await field(wrapper, 'O que deve ser dito no lugar').setValue('   ')
    expect(run()).toBeDefined()
    await field(wrapper, 'O que deve ser dito no lugar').setValue('Pedro')
    expect(run()).toBeUndefined()
  })

  it('corrige: manda o trecho escolhido, o texto, a voz e as opções, e mostra resumo, A/B e baixar', async () => {
    const { wrapper } = await transcribed()
    await word(wrapper, 'João').trigger('click')
    await word(wrapper, 'João').trigger('click')
    await field(wrapper, 'O que deve ser dito no lugar').setValue('  Pedro ')
    await field(wrapper, 'Voz').setValue('entrevistado')
    await field(wrapper, 'Guardar a voz do falante como').setValue('Convidado')
    await press(wrapper, 'Corrigir fala')
    await flushPromises()

    expect(callsTo(calls, 'POST', '/api/speech/fix')[0]!.body).toEqual({
      path: CLIP,
      text: 'Pedro',
      start: 5,
      end: 5.4,
      voice: 'entrevistado',
      save_voice: 'Convidado',
      expand: true,
    })
    FakeEventSource.latest().emit({ kind: 'progress', t: 1, label: 'sintetizando', done: 1, total: 3, percent: 33 })
    await flushPromises()
    expect(wrapper.text()).toContain('sintetizando')

    await emitEnd(FIXED)
    expect(wrapper.text()).toContain('Fala corrigida')
    expect(wrapper.text()).toContain('Trocado "João" por "Pedro" (região 5,0 a 5,4 s). Duração: duração mantida (0.4 s).')
    expect(buttonLabelled(wrapper, 'Ouvir trecho original')).toBeDefined()
    expect(buttonLabelled(wrapper, 'Ouvir trecho corrigido')).toBeDefined()
    expect(wrapper.text()).toContain('1,5 s antes e depois')
    const players = wrapper.findAll('audio')
    expect(players[0]!.attributes('src')).toBe('/api/file?path=original')
    expect(players[1]!.attributes('src')).toContain('/api/voices/audio?path=corrigido')
    expect(buttonLabelled(wrapper, 'Baixar corrigido')).toBeDefined()
  })

  it('sem escolher voz manda a voz do próprio falante (nada) e as vizinhas ligadas por padrão', async () => {
    const { wrapper } = await transcribed()
    expect((field(wrapper, 'Falar também as palavras vizinhas').element as HTMLInputElement).checked).toBe(true)
    await word(wrapper, 'João').trigger('click')
    await word(wrapper, 'João').trigger('click')
    await field(wrapper, 'O que deve ser dito no lugar').setValue('Pedro')
    await field(wrapper, 'Falar também as palavras vizinhas').setValue(false)
    await press(wrapper, 'Corrigir fala')
    await flushPromises()
    expect(callsTo(calls, 'POST', '/api/speech/fix')[0]!.body).toMatchObject({ voice: null, save_voice: null, expand: false })
    await emitEnd(FIXED)
  })

  it('a lista de vozes distingue a clonada das prontas', async () => {
    const { wrapper } = await transcribed()
    const options = field(wrapper, 'Voz').findAll('option').map((option) => option.text())
    expect(options).toEqual(['Voz do próprio falante (automática)', 'Dora (feminina)', 'Entrevistado (clonada)'])
  })

  it('"Usar no projeto" troca o arquivo nas fontes, trechos e vídeos sobrepostos e salva', async () => {
    const { wrapper } = await transcribed()
    await word(wrapper, 'João').trigger('click')
    await word(wrapper, 'João').trigger('click')
    await field(wrapper, 'O que deve ser dito no lugar').setValue('Pedro')
    await press(wrapper, 'Corrigir fala')
    await flushPromises()
    await emitEnd(FIXED)

    await press(wrapper, 'Usar no projeto')
    await flushPromises()

    const edits = callsTo(calls, 'POST', `/api/projects/${PROJECT}/edit`).map((call) => (call.body as { op: unknown }).op)
    expect(edits).toEqual([
      { type: 'set_field', path: 'timeline.0.src', value: FIXED.output },
      { type: 'set_field', path: 'overlays.0.src', value: FIXED.output },
    ])
    const saved = callsTo(calls, 'PUT', `/api/projects/${PROJECT}`)
    expect(saved).toHaveLength(1)
    expect(saved[0]!.body).toMatchObject({ timeline: [{ src: FIXED.output }], overlays: [{ src: FIXED.output }] })
    expect(wrapper.text()).toContain(`Projeto ${PROJECT} atualizado: arquivo corrigido em 2 ponto(s).`)
  })

  it('arquivo enviado do computador não entra no projeto: o botão explica', async () => {
    localStorage.clear()
    const { wrapper } = await mountView()
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['abc'], 'voz.wav', { type: 'audio/wav' })], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(callsTo(calls, 'POST', '/api/speech/upload')).toHaveLength(1)

    await press(wrapper, 'Transcrever')
    await flushPromises()
    expect(callsTo(calls, 'POST', '/api/speech/words')[0]!.body).toMatchObject({ path: 'cache/uploads/abc-voz.wav' })
    await emitEnd(WORDS)
    await word(wrapper, 'João').trigger('click')
    await word(wrapper, 'João').trigger('click')
    await field(wrapper, 'O que deve ser dito no lugar').setValue('Pedro')
    await press(wrapper, 'Corrigir fala')
    await flushPromises()
    await emitEnd({ ...FIXED, original: 'cache/uploads/abc-voz.wav' })

    expect(buttonLabelled(wrapper, 'Usar no projeto').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('escolha um arquivo do projeto aberto')
  })

  it('transcrição sem nenhuma fala avisa e não mostra o resto do formulário', async () => {
    const { wrapper } = await mountView()
    await press(wrapper, 'Transcrever')
    await flushPromises()
    await emitEnd({ words: [], pause_seconds: 0.25 })
    expect(wrapper.text()).toContain('Nenhuma fala encontrada nesse trecho.')
    expect(wrapper.text()).not.toContain('Texto novo')
  })

  it('erro ao corrigir aparece na tela e deixa tentar de novo com o mesmo trecho', async () => {
    const { wrapper } = await transcribed()
    await word(wrapper, 'João').trigger('click')
    await word(wrapper, 'João').trigger('click')
    await field(wrapper, 'O que deve ser dito no lugar').setValue('Pedro')
    await press(wrapper, 'Corrigir fala')
    await flushPromises()
    await emitEnd(null, 'error', 'ValueError: o texto não cabe no trecho\ntraceback')

    expect(wrapper.find('[role="alert"]').text()).toContain('o texto não cabe no trecho')
    expect(wrapper.text()).not.toContain('Fala corrigida')
    expect(buttonLabelled(wrapper, 'Corrigir fala').attributes('disabled')).toBeUndefined()
  })

  it('transcrição e seleção sobrevivem a mudar de aba da Voz e voltar', async () => {
    const { wrapper, router } = await transcribed()
    await word(wrapper, 'o').trigger('click')
    await word(wrapper, 'casamento').trigger('click')
    await field(wrapper, 'O que deve ser dito no lugar').setValue('Pedro')

    await router.push('/voz/isolar')
    await flushPromises()
    await router.push('/voz/corrigir')
    await flushPromises()

    expect(wrapper.text()).toContain('Trecho escolhido: "o casamento"')
    expect((field(wrapper, 'O que deve ser dito no lugar').element as HTMLInputElement).value).toBe('Pedro')
    expect(wrapper.findAll('.picker__line')).toHaveLength(3)
  })
})
