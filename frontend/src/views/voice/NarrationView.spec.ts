import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeAudioContext } from '@/test/audioContext'
import { FakeEventSource } from '@/test/fetch'
import { mountRoute } from '@/test/routes'
import { buttonLabelled, callsTo, press, type ServerCall } from '@/test/speechServer'
import { NARRATION_RESULT, PROJECT, stubVoiceServer, TIMELINE_WITH_NARRATION, utterance } from '@/test/voiceServer'

let calls: ServerCall[]
let context: FakeAudioContext
let wrapper: VueWrapper | null = null

beforeEach(() => {
  localStorage.clear()
  FakeEventSource.reset()
  FakeAudioContext.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  // só o intervalo é falso (a prévia confere o que toca a cada 150 ms); as promessas e os timeouts seguem reais
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  // uma classe nova a cada teste: o navegador reaproveita um contexto só, e o teste precisa de um limpo
  class TestAudioContext extends FakeAudioContext {}
  vi.stubGlobal('AudioContext', TestAudioContext)
  calls = stubVoiceServer({ timeline: TIMELINE_WITH_NARRATION }).calls
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function openNarration(): Promise<VueWrapper> {
  const mounted = await mountRoute('/voz/narracao')
  wrapper = mounted.wrapper
  await flushPromises()
  return wrapper
}

/** O campo ligado ao rótulo (o `for` do rótulo aponta o `id` do campo). */
function field(label: string) {
  const owner = wrapper!.findAll('label').find((node) => node.text().startsWith(label))
  if (!owner) throw new Error(`campo "${label}" não encontrado`)
  return wrapper!.find(`#${owner.attributes('for')}`)
}

const emit = async (event: unknown) => {
  FakeEventSource.latest().emit(event)
  await flushPromises()
}
const end = (status: string, result: unknown) => emit({ kind: 'end', t: 9, status, error: null, result })

/** Escreve o roteiro e aperta Gerar; o `AudioContext` nasce dentro do clique, como no navegador. */
async function generate(text = 'Olá, mundo. Esta é a narração.') {
  await field('Roteiro').setValue(text)
  await press(wrapper!, 'Gerar narração')
  await flushPromises()
  context = FakeAudioContext.latest()
}

describe('NarrationView (/voz/narracao)', () => {
  it('mostra o roteiro e as escolhas sob o título e as abas da Voz', async () => {
    await openNarration()
    expect(wrapper!.find('h1').text()).toBe('Voz')
    expect(wrapper!.find('nav[aria-label="Seções da Voz"] a.is-active').text()).toBe('Narração')
    expect(wrapper!.text()).not.toContain('em construção')
    for (const label of ['Voz', 'Idioma', 'Velocidade', 'Semente (opcional)', 'Dicionário de pronúncia', 'Roteiro']) {
      expect(wrapper!.findAll('label').some((node) => node.text().startsWith(label)), label).toBe(true)
    }
    expect(wrapper!.text()).toContain('[pausa 1.2]')
    expect(wrapper!.text()).toContain('[[termo|pronúncia]]')
    expect(wrapper!.text()).toContain('As narrações geradas nesta sessão aparecem aqui.')
    expect(wrapper!.text()).not.toContain('Resultado')
  })

  it('lista as vozes, os idiomas e as marcas, e já escolhe a última voz usada', async () => {
    localStorage.setItem('dmaker.voice.lastVoice', 'entrevistado')
    await openNarration()
    const voice = field('Voz').element as HTMLSelectElement
    expect([...voice.options].map((option) => option.text)).toEqual(['Voz automática', 'Dora (feminina)', 'Entrevistado (clonada)'])
    expect(voice.value).toBe('entrevistado')
    expect([...(field('Idioma').element as HTMLSelectElement).options].map((option) => option.text)).toEqual([
      'Idioma da voz (padrão)',
      'Português',
      'Inglês',
    ])
    expect([...(field('Dicionário de pronúncia').element as HTMLSelectElement).options].map((option) => option.text)).toEqual([
      'O da marca da voz',
      'Padrão',
      'MedlyCare',
    ])
  })

  it('trocar a voz aqui lembra a escolha para a biblioteca', async () => {
    await openNarration()
    await field('Voz').setValue('dora')
    expect(localStorage.getItem('dmaker.voice.lastVoice')).toBe('dora')
  })

  it('o botão de gerar só liga com roteiro, e a linha sob o campo estima a duração', async () => {
    await openNarration()
    expect(buttonLabelled(wrapper!, 'Gerar narração').attributes('disabled')).toBeDefined()
    expect(buttonLabelled(wrapper!, 'Mandar para a fila').attributes('disabled')).toBeDefined()
    expect(wrapper!.text()).toContain('Escreva ou cole o roteiro da narração.')

    await field('Roteiro').setValue('a'.repeat(140))
    expect(wrapper!.text()).toContain('140 caracteres · duração estimada 10 s')
    expect(buttonLabelled(wrapper!, 'Gerar narração').attributes('disabled')).toBeUndefined()

    await field('Velocidade').setValue('2')
    expect(wrapper!.text()).toContain('duração estimada 5 s')
    expect(wrapper!.find('output').text()).toBe('2,00x')
  })

  it('semente inválida e roteiro grande demais travam o botão e dizem por quê', async () => {
    await openNarration()
    await field('Roteiro').setValue('ok')
    await field('Semente (opcional)').setValue('1.5')
    expect(wrapper!.text()).toContain('A semente é um número inteiro, a partir de 0.')
    expect(buttonLabelled(wrapper!, 'Gerar narração').attributes('disabled')).toBeDefined()

    await field('Semente (opcional)').setValue('')
    await field('Roteiro').setValue('a'.repeat(20_001))
    expect(wrapper!.text()).toContain('O roteiro passa de 20 mil caracteres')
    expect(buttonLabelled(wrapper!, 'Gerar narração').attributes('disabled')).toBeDefined()
    expect(buttonLabelled(wrapper!, 'Mandar para a fila').attributes('disabled')).toBeUndefined()
  })

  it('gerar manda as escolhas, mostra o andamento com o relógio e o botão Parar', async () => {
    await openNarration()
    await field('Voz').setValue('dora')
    await field('Idioma').setValue('en')
    await field('Semente (opcional)').setValue('7')
    await generate()

    expect(callsTo(calls, 'POST', '/api/voices/speak')[0]!.body).toEqual({
      text: 'Olá, mundo. Esta é a narração.',
      voice: 'dora',
      language: 'en',
      speed: 1,
      seed: 7,
      brand: null,
    })
    expect(wrapper!.text()).toContain('Na fila...')
    expect(wrapper!.text()).toContain('decorridos')
    expect(buttonLabelled(wrapper!, 'Parar')).toBeTruthy()
    expect(buttonLabelled(wrapper!, 'Gerar narração').attributes('disabled')).toBeDefined()

    await emit({ kind: 'progress', t: 1, label: 'fala 1 de 3', done: 1, total: 3, percent: 0 })
    expect(wrapper!.text()).toContain('fala 1 de 3')
  })

  it('toca a prévia ao vivo, fala a fala, e a silencia sem parar a geração', async () => {
    await openNarration()
    await generate()
    expect(context.resumed).toBe(1)
    expect(wrapper!.find('[aria-label="Prévia ao vivo"]').text()).toContain('Esperando a primeira fala ficar pronta...')

    await emit(utterance(1, 3))
    vi.advanceTimersByTime(150)
    await flushPromises()
    expect(context.sources).toHaveLength(1)
    expect(wrapper!.text()).toContain('Tocando fala 1 de 3 · 1 prontas')
    expect(wrapper!.text()).toContain('fala crua, sem o acabamento final')

    await buttonLabelled(wrapper!, 'Silenciar prévia').trigger('click')
    expect(wrapper!.text()).toContain('Prévia ao vivo silenciada. A geração continua.')
    expect(buttonLabelled(wrapper!, 'Silenciar prévia').attributes('disabled')).toBeDefined()
    expect(wrapper!.text()).toContain('decorridos')
  })

  it('Parar cancela entre as falas e diz até onde a narração foi', async () => {
    await openNarration()
    await generate()
    await emit(utterance(1, 5))
    await emit(utterance(2, 5))

    await buttonLabelled(wrapper!, 'Parar').trigger('click')
    await flushPromises()
    expect(callsTo(calls, 'POST', '/api/jobs/j1/cancel')).toHaveLength(1)
    expect(wrapper!.text()).toContain('Parando assim que a fala atual terminar')

    await end('cancelled', { ready: 2, total: 5 })
    expect(wrapper!.text()).toContain('Parado a pedido. O que já estava pronto ficou guardado.')
    expect(wrapper!.text()).toContain('Parado depois da fala 2 de 5.')
    expect(wrapper!.text()).toContain('não há arquivo final')
    expect(buttonLabelled(wrapper!, 'Gerar narração').attributes('disabled')).toBeUndefined()
    expect(wrapper!.text()).not.toContain('Resultado')
  })

  it('uma falha do job aparece como alerta e esconde a prévia', async () => {
    await openNarration()
    await generate()
    FakeEventSource.latest().emit({ kind: 'end', t: 9, status: 'error', error: 'RuntimeError: modelo de voz não carregou', result: null })
    await flushPromises()
    expect(wrapper!.find('[role="alert"]').text()).toContain('modelo de voz não carregou')
    expect(wrapper!.find('[aria-label="Prévia ao vivo"]').exists()).toBe(false)
  })

  describe('depois de gerar', () => {
    async function generated(text = 'Olá, mundo. Esta é a narração.') {
      await generate(text)
      await emit(utterance(1, 1, 0))
      await end('done', NARRATION_RESULT)
    }

    it('mostra o player, os dados, Baixar e o histórico com as quatro ações', async () => {
      await openNarration()
      await field('Voz').setValue('dora')
      await generated()

      expect(wrapper!.find('audio').attributes('src')).toContain(NARRATION_RESULT.audio_url)
      expect(wrapper!.text()).toContain('Dora (feminina) · 12 s · velocidade 1,00x')
      const downloads = wrapper!.findAll('button').filter((node) => node.text().includes('Baixar'))
      expect(downloads.map((node) => node.text())).toEqual(['Baixar áudio', 'Baixar'])

      const history = wrapper!.find('[aria-label="Narrações geradas nesta sessão"]')
      expect(history.findAll('li')).toHaveLength(1)
      expect(history.text()).toContain('Olá, mundo. Esta é a narração.')
      expect(history.findAll('button').map((node) => node.text())).toEqual(['Ouvir', 'Baixar', 'Reusar texto', 'Inserir no projeto'])
    })

    it('Reusar texto devolve o roteiro ao campo e Ouvir toca o resultado', async () => {
      const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
      await openNarration()
      await generated('Primeiro roteiro')
      await field('Roteiro').setValue('Outro roteiro')

      const entry = wrapper!.find('[data-history]')
      await entry.findAll('button').find((node) => node.text() === 'Reusar texto')!.trigger('click')
      expect((field('Roteiro').element as HTMLTextAreaElement).value).toBe('Primeiro roteiro')

      await entry.findAll('button').find((node) => node.text() === 'Ouvir')!.trigger('click')
      await flushPromises()
      expect(play).toHaveBeenCalled()
    })

    it('sem projeto aberto, o Inserir fica desligado e a tela diz como abrir um', async () => {
      await openNarration()
      await generated()
      expect(buttonLabelled(wrapper!, 'Inserir no projeto aberto').attributes('disabled')).toBeDefined()
      expect(wrapper!.find('[data-history] button[title^="Insere"]').attributes('disabled')).toBeDefined()
      expect(wrapper!.text()).toContain('Nenhum projeto aberto.')
      expect(wrapper!.find('a[href="/projetos"]').exists()).toBe(true)
    })

    it('com projeto aberto, insere em audio.narration depois da última narração e salva', async () => {
      localStorage.setItem('dmaker.currentProject', PROJECT)
      await openNarration()
      await generated()
      expect(wrapper!.text()).toContain(`Projeto aberto: ${PROJECT}.`)
      expect(field('Começa em (s)').attributes('placeholder')).toBe('9,5')

      await press(wrapper!, 'Inserir no projeto aberto')
      await flushPromises()

      const saved = callsTo(calls, 'PUT', `/api/projects/${PROJECT}`)[0]!.body as { audio: { narration: unknown[] } }
      expect(saved.audio.narration).toEqual([{ text: 'Olá, mundo. Esta é a narração.', start: 9.5, speed: 1 }])
      expect(wrapper!.text()).toContain(`Narração inserida em 9,50 s do projeto ${PROJECT}.`)
    })

    it('a posição escrita no campo vale mais, e o Inserir do histórico usa a mesma', async () => {
      localStorage.setItem('dmaker.currentProject', PROJECT)
      await openNarration()
      await generated()
      await field('Começa em (s)').setValue('3')

      await wrapper!.find('[data-history] button[title^="Insere"]').trigger('click')
      await flushPromises()
      const saved = callsTo(calls, 'PUT', `/api/projects/${PROJECT}`)[0]!.body as { audio: { narration: { start: number }[] } }
      expect(saved.audio.narration[0]!.start).toBe(3)
    })
  })

  describe('mandar para a fila', () => {
    const dialog = () => document.body.querySelector('[role="dialog"]') as HTMLElement | null

    it('abre o diálogo com as escolhas da fila e manda o roteiro', async () => {
      await openNarration()
      await field('Voz').setValue('dora')
      await field('Roteiro').setValue('Um roteiro bem longo.')
      await buttonLabelled(wrapper!, 'Mandar para a fila').trigger('click')
      await flushPromises()

      expect(dialog()?.textContent).toContain('Título do item (opcional)')
      expect(dialog()?.textContent).toContain('21 caracteres')
      const title = dialog()!.querySelector('input[type="text"]') as HTMLInputElement
      title.value = 'Capítulo 1'
      title.dispatchEvent(new Event('input'))
      const mp3 = [...dialog()!.querySelectorAll('button')].find((node) => node.textContent === 'MP3')!
      mp3.click()
      const draft = dialog()!.querySelector('input[type="checkbox"]') as HTMLInputElement
      draft.click()
      await flushPromises()
      ;(dialog()!.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { cancelable: true }))
      await flushPromises()

      expect(callsTo(calls, 'POST', '/api/voices/queue')[0]!.body).toEqual({
        text: 'Um roteiro bem longo.',
        voice: 'dora',
        language: null,
        speed: 1,
        brand: null,
        draft: true,
        format: 'mp3',
        title: 'Capítulo 1',
      })
      expect(dialog()).toBeNull()
    })
  })
})
