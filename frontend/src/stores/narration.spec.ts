import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { contextWithDurations, type FakeAudioContext } from '@/test/audioContext'
import { FakeEventSource } from '@/test/fetch'
import { callsTo } from '@/test/speechServer'
import { NARRATION_RESULT, PROJECT, stubVoiceServer, TIMELINE_WITH_NARRATION, utterance, type VoiceServer } from '@/test/voiceServer'
import { useNarrationStore } from './narration'
import { useToastsStore } from './toasts'
import { useWorkspaceStore } from './workspace'

let server: VoiceServer
let context: FakeAudioContext

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  // só o intervalo é falso: as promessas e os timeouts do teste seguem reais
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  server = stubVoiceServer()
  context = contextWithDurations(0)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const audio = () => context

async function ready() {
  const narration = useNarrationStore()
  await narration.loadVoices()
  narration.text = 'Olá, mundo. Esta é a narração.'
  return narration
}

const source = () => FakeEventSource.latest()
const emit = async (event: unknown) => {
  source().emit(event)
  await flushPromises()
}
const end = (status: string, result: unknown, error: string | null = null) => emit({ kind: 'end', t: 9, status, error, result })

describe('gerar a narração', () => {
  it('manda o roteiro com as escolhas e só leva voz, idioma e semente quando existem', async () => {
    const narration = await ready()
    narration.chooseVoice('dora')
    narration.speed = 1.25
    narration.seed = 7
    narration.language = 'en'
    narration.brand = 'medlycare'
    void narration.generate(audio)
    await flushPromises()

    expect(callsTo(server.calls, 'POST', '/api/voices/speak')[0]!.body).toEqual({
      text: 'Olá, mundo. Esta é a narração.',
      voice: 'dora',
      language: 'en',
      speed: 1.25,
      seed: 7,
      brand: 'medlycare',
    })
  })

  it('sem escolher nada, manda voz, idioma, semente e marca como null', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/voices/speak')[0]!.body).toMatchObject({
      voice: null,
      language: null,
      speed: 1,
      seed: null,
      brand: null,
    })
  })

  it('mostra o andamento, e a última linha de log vale mais que a etapa velha', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    expect(narration.job).toMatchObject({ running: true, label: 'Na fila...', percent: null })

    await emit({ kind: 'log', t: 1, message: 'Aguardando outro trabalho de voz terminar' })
    expect(narration.job.label).toBe('Aguardando outro trabalho de voz terminar')
    await emit({ kind: 'progress', t: 2, label: 'fala 2 de 5', done: 2, total: 5, percent: 20 })
    expect(narration.job).toMatchObject({ label: 'fala 2 de 5', percent: 20 })
  })

  it('ao terminar, guarda o resultado no histórico com o nome da voz', async () => {
    const narration = await ready()
    narration.chooseVoice('entrevistado')
    narration.speed = 1.1
    void narration.generate(audio)
    await flushPromises()
    await end('done', NARRATION_RESULT)

    expect(narration.job.running).toBe(false)
    expect(narration.current).toMatchObject({
      text: 'Olá, mundo. Esta é a narração.',
      voiceId: 'entrevistado',
      voiceName: 'Entrevistado',
      speed: 1.1,
      duration: 12.4,
      audioUrl: NARRATION_RESULT.audio_url,
      output: NARRATION_RESULT.output,
    })
    expect(narration.history).toHaveLength(1)
  })

  it('sem voz escolhida, o histórico diz "Voz automática"', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    await end('done', NARRATION_RESULT)
    expect(narration.current?.voiceName).toBe('Voz automática')
  })

  it('o histórico guarda só as 30 últimas, a mais nova primeiro', async () => {
    const narration = await ready()
    for (let round = 1; round <= 32; round += 1) {
      narration.text = `roteiro ${round}`
      void narration.generate(audio)
      await flushPromises()
      await end('done', NARRATION_RESULT)
    }
    expect(narration.history).toHaveLength(30)
    expect(narration.history[0]!.text).toBe('roteiro 32')
    expect(narration.history.at(-1)!.text).toBe('roteiro 3')
  })

  it('um segundo pedido durante o primeiro é ignorado', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    void narration.generate(audio)
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/voices/speak')).toHaveLength(1)
  })

  it('não gera sem roteiro, com semente inválida ou com roteiro grande demais', async () => {
    const narration = await ready()
    narration.text = '   '
    expect(narration.canGenerate).toBe(false)
    narration.text = 'ok'
    narration.seed = 1.5
    expect(narration.canGenerate).toBe(false)
    narration.seed = null
    narration.text = 'a'.repeat(20_001)
    expect(narration.canGenerate).toBe(false)
    narration.text = 'a'.repeat(20_000)
    expect(narration.canGenerate).toBe(true)
  })

  it('a falha ao pedir a narração vira o erro da tela e solta o botão', async () => {
    server = stubVoiceServer({ speakReply: { status: 400, body: { detail: 'Voz "x" não encontrada.' } } })
    const narration = await ready()
    await narration.generate(audio)
    expect(narration.job.error).toContain('Voz "x" não encontrada.')
    expect(narration.job.running).toBe(false)
    expect(narration.live.visible).toBe(false)
  })

  it('um job que falha mostra o motivo sem o nome da exceção e esconde a prévia', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    expect(narration.live.visible).toBe(true)
    await end('error', null, 'RuntimeError: modelo de voz não carregou\nTraceback (most recent call last)')
    expect(narration.job.error).toBe('modelo de voz não carregou')
    expect(narration.live.visible).toBe(false)
    expect(narration.history).toHaveLength(0)
  })
})

describe('a prévia ao vivo', () => {
  async function started() {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    return narration
  }

  it('libera o áudio dentro do clique e mostra a prévia antes de a primeira fala chegar', async () => {
    const narration = await started()
    expect(context.resumed).toBe(1)
    expect(narration.live.visible).toBe(true)
    expect(narration.liveText).toBe('Esperando a primeira fala ficar pronta...')
  })

  it('agenda cada fala no relógio do áudio e diz qual está tocando', async () => {
    const narration = await started()
    await emit(utterance(1, 3))
    await emit(utterance(2, 3))
    vi.advanceTimersByTime(150)

    expect(context.sources.map((item) => Number((item.startedAt ?? 0).toFixed(6)))).toEqual([0.06, 1.41])
    expect(narration.liveText).toBe('Tocando fala 1 de 3 · 2 prontas')
    context.currentTime = 1.6
    vi.advanceTimersByTime(150)
    expect(narration.liveText).toBe('Tocando fala 2 de 3 · 2 prontas')
    context.currentTime = 2.9
    vi.advanceTimersByTime(150)
    expect(narration.liveText).toBe('Esperando a fala 3 de 3 ficar pronta...')
  })

  it('termina dizendo que a prévia acabou quando a última fala para de tocar', async () => {
    const narration = await started()
    await emit(utterance(1, 1, 0))
    await end('done', NARRATION_RESULT)
    vi.advanceTimersByTime(150)
    expect(narration.liveText).toBe('Tocando fala 1 de 1')
    context.currentTime = 5
    vi.advanceTimersByTime(150)
    expect(narration.liveText).toBe('Prévia ao vivo terminada.')
  })

  it('a fala repetida pelo servidor ao reconectar toca uma vez só', async () => {
    await started()
    await emit(utterance(1, 3))
    await emit({ kind: 'start', t: 0, description: 'x' })
    await emit(utterance(1, 3))
    expect(context.sources).toHaveLength(1)
  })

  it('silenciar cala a prévia, ignora as falas que chegam depois e deixa a geração seguir', async () => {
    const narration = await started()
    await emit(utterance(1, 3))
    narration.muteLive()
    await emit(utterance(2, 3))

    expect(narration.liveText).toBe('Prévia ao vivo silenciada. A geração continua.')
    expect(context.sources).toHaveLength(1)
    expect(context.sources[0]!.stoppedAt).not.toBeNull()
    expect(narration.job.running).toBe(true)
    await end('done', NARRATION_RESULT)
    expect(narration.history).toHaveLength(1)
  })

  it('uma fala que não carrega avisa e deixa o arquivo final de fora do problema', async () => {
    const narration = await started()
    context.decode = async () => {
      throw new Error('áudio ilegível')
    }
    await emit(utterance(1, 2))
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('Uma fala da prévia ao vivo não tocou')
    await end('done', NARRATION_RESULT)
    expect(narration.history).toHaveLength(1)
  })

  it('sem Web Audio no navegador a narração segue só com o arquivo final', async () => {
    const narration = await ready()
    void narration.generate(() => null)
    await flushPromises()
    expect(narration.live.visible).toBe(false)
    await emit(utterance(1, 1))
    await end('done', NARRATION_RESULT)
    expect(narration.history).toHaveLength(1)
  })
})

describe('parar', () => {
  it('pede o cancelamento, cala a prévia na hora e espera o job terminar entre duas falas', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    await emit(utterance(1, 5))
    await emit(utterance(2, 5))

    await narration.stop()
    expect(callsTo(server.calls, 'POST', '/api/jobs/j1/cancel')).toHaveLength(1)
    expect(narration.job).toMatchObject({ cancelling: true, label: 'Parando assim que a fala atual terminar' })
    expect(narration.job.running).toBe(true)
    expect(narration.live.stoppedAfter).toBe(2)
    expect(context.sources.every((item) => item.stoppedAt !== null)).toBe(true)

    // a etapa que chega enquanto para não apaga o aviso
    await emit({ kind: 'progress', t: 3, label: 'fala 3 de 5', done: 3, total: 5, percent: 40 })
    expect(narration.job.label).toBe('Parando assim que a fala atual terminar')

    await end('cancelled', { ready: 3, total: 5 })
    expect(narration.job).toMatchObject({ running: false, cancelled: true, error: '', cancelling: false })
    expect(narration.liveText).toBe('Parado depois da fala 3 de 5. O que já saiu ficou guardado.')
    expect(narration.history).toHaveLength(0)
  })

  it('parar antes da primeira fala não fala em "fala 0 de 0"', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    await narration.stop()
    await end('cancelled', { ready: 0, total: 0 })
    expect(narration.liveText).toBe('Parado antes de a primeira fala ficar pronta.')
  })

  it('parar duas vezes pede o cancelamento uma vez só, e sem job nada acontece', async () => {
    const narration = await ready()
    await narration.stop()
    expect(callsTo(server.calls, 'POST', '/api/jobs/j1/cancel')).toHaveLength(0)

    void narration.generate(audio)
    await flushPromises()
    await narration.stop()
    await narration.stop()
    expect(callsTo(server.calls, 'POST', '/api/jobs/j1/cancel')).toHaveLength(1)
  })

  it('o servidor recusar parar mostra o erro e solta o botão', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    const fetchStub = vi.mocked(fetch)
    const original = fetchStub.getMockImplementation()!
    fetchStub.mockImplementation((url, init) =>
      String(url).endsWith('/cancel')
        ? Promise.resolve(new Response(JSON.stringify({ detail: 'Este trabalho não pode ser parado.' }), { status: 409 }))
        : original(url, init),
    )
    await narration.stop()
    expect(narration.job.cancelling).toBe(false)
    expect(narration.job.error).toContain('Este trabalho não pode ser parado.')
  })
})

describe('o histórico', () => {
  it('Ouvir põe a narração no player e pede que ele toque; Reusar texto devolve o roteiro', async () => {
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    await end('done', NARRATION_RESULT)
    const first = narration.history[0]!

    narration.text = 'outro roteiro'
    void narration.generate(audio)
    await flushPromises()
    await end('done', { ...NARRATION_RESULT, audio_url: '/api/voices/audio?path=outra' })
    expect(narration.current).not.toBe(first)

    const stamp = narration.playStamp
    narration.show(first)
    expect(narration.current).toBe(first)
    expect(narration.playStamp).toBe(stamp + 1)

    narration.reuseText(first)
    expect(narration.text).toBe('Olá, mundo. Esta é a narração.')
  })
})

describe('as vozes', () => {
  it('lista todas as vozes e só vale a escolhida se ela ainda existe', async () => {
    const narration = useNarrationStore()
    narration.chooseVoice('dora')
    expect(narration.voiceId).toBe('')
    await narration.loadVoices()
    expect(narration.voiceOptions.map((option) => option.value)).toEqual(['dora', 'entrevistado'])
    expect(narration.voiceId).toBe('dora')
    narration.chooseVoice('removida')
    expect(narration.voiceId).toBe('')
  })

  it('lembra a escolha no navegador, como a biblioteca', async () => {
    const narration = useNarrationStore()
    narration.chooseVoice('entrevistado')
    expect(localStorage.getItem('dmaker.voice.lastVoice')).toBe('entrevistado')
  })

  it('a falha ao listar as vozes fica à vista e a lista fica vazia', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'servidor de voz parado' }), { status: 500 })))
    const narration = useNarrationStore()
    await narration.loadVoices()
    expect(narration.voiceFailure).toContain('servidor de voz parado')
    expect(narration.voiceOptions).toEqual([])
  })
})

describe('inserir no projeto aberto', () => {
  async function withResult(options: Parameters<typeof stubVoiceServer>[0] = {}) {
    server = stubVoiceServer(options)
    useWorkspaceStore().openProject(PROJECT)
    const narration = await ready()
    narration.chooseVoice('dora')
    narration.seed = 3
    void narration.generate(audio)
    await flushPromises()
    await end('done', NARRATION_RESULT)
    return narration
  }

  it('lê a spec na hora, acrescenta em audio.narration e salva', async () => {
    const narration = await withResult()
    narration.insertStart = 4.256
    const inserted = await narration.insertIntoProject(narration.current!)

    expect(inserted).toBe(true)
    const saved = callsTo(server.calls, 'PUT', `/api/projects/${PROJECT}`)[0]!.body as Record<string, unknown>
    expect(saved.audio).toEqual({
      normalize: 'two-pass',
      narration: [{ text: 'Olá, mundo. Esta é a narração.', start: 4.26, speed: 1, voice: 'dora', seed: 3 }],
    })
    expect(saved.timeline).toEqual([{ type: 'clip', src: 'D:/m/a.mp4' }])
    expect(narration.insertNote).toBe(`Narração inserida em 4,26 s do projeto ${PROJECT}.`)
    expect(narration.insertStart).toBeNull()
  })

  it('acrescenta depois das narrações que o projeto já tem', async () => {
    const narration = await withResult({
      spec: { name: PROJECT, timeline: [], audio: { narration: [{ text: 'Antes', start: 0 }] } },
    })
    await narration.insertIntoProject(narration.current!)
    const saved = callsTo(server.calls, 'PUT', `/api/projects/${PROJECT}`)[0]!.body as { audio: { narration: unknown[] } }
    expect(saved.audio.narration).toHaveLength(2)
    expect(saved.audio.narration[0]).toEqual({ text: 'Antes', start: 0 })
  })

  it('começa por padrão no fim da última narração do projeto', async () => {
    const narration = await withResult({ timeline: TIMELINE_WITH_NARRATION })
    await narration.refreshDefaultStart()
    expect(narration.defaultStart).toBe(9.5)
    expect(narration.startAt).toBe(9.5)
    await narration.insertIntoProject(narration.current!)
    const saved = callsTo(server.calls, 'PUT', `/api/projects/${PROJECT}`)[0]!.body as { audio: { narration: { start: number }[] } }
    expect(saved.audio.narration[0]!.start).toBe(9.5)
  })

  it('uma posição escrita à mão vale mais que a padrão', async () => {
    const narration = await withResult({ timeline: TIMELINE_WITH_NARRATION })
    await narration.refreshDefaultStart()
    narration.insertStart = 0
    expect(narration.startAt).toBe(0)
  })

  it('projeto sem vista (fonte ausente) começa no 0 sem reclamar', async () => {
    const narration = await withResult({ timeline: null })
    await narration.refreshDefaultStart()
    expect(narration.defaultStart).toBe(0)
  })

  it('sem projeto aberto, diz para abrir um e não chama o servidor', async () => {
    server = stubVoiceServer()
    const narration = await ready()
    void narration.generate(audio)
    await flushPromises()
    await end('done', NARRATION_RESULT)
    const calls = server.calls.length
    expect(await narration.insertIntoProject(narration.current!)).toBe(false)
    expect(narration.insertNote).toBe('Abra um projeto para inserir a narração nele.')
    expect(server.calls).toHaveLength(calls)
  })

  it('se o servidor recusa salvar, mostra a mensagem dele e mantém a posição escrita', async () => {
    const narration = await withResult({ saveReply: { status: 422, body: { detail: 'audio.narration.0.speed: acima do limite' } } })
    narration.insertStart = 2
    expect(await narration.insertIntoProject(narration.current!)).toBe(false)
    expect(narration.insertNote).toContain('Não consegui inserir')
    expect(narration.insertNote).toContain('acima do limite')
    expect(narration.insertStart).toBe(2)
    expect(narration.inserting).toBe(false)
  })
})

describe('mandar para a fila', () => {
  it('manda o roteiro com as escolhas da narração e as da fila', async () => {
    const narration = await ready()
    narration.chooseVoice('dora')
    narration.language = 'pt'
    narration.speed = 0.9
    narration.brand = 'medlycare'
    const added = await narration.sendToQueue({ title: '  Capítulo 1 ', format: 'mp3', draft: true })

    expect(added).toEqual({ id: 'q1', items: [] })
    expect(callsTo(server.calls, 'POST', '/api/voices/queue')[0]!.body).toEqual({
      text: 'Olá, mundo. Esta é a narração.',
      voice: 'dora',
      language: 'pt',
      speed: 0.9,
      brand: 'medlycare',
      draft: true,
      format: 'mp3',
      title: 'Capítulo 1',
    })
  })

  it('sem título, não manda o campo; sem roteiro, não manda nada', async () => {
    const narration = await ready()
    await narration.sendToQueue({ title: '   ', format: 'wav', draft: false })
    expect(callsTo(server.calls, 'POST', '/api/voices/queue')[0]!.body).not.toHaveProperty('title')

    narration.text = ' '
    expect(await narration.sendToQueue({ title: '', format: 'wav', draft: false })).toBeNull()
    expect(callsTo(server.calls, 'POST', '/api/voices/queue')).toHaveLength(1)
  })

  it('deixa a falha do servidor subir para a tela e solta o botão', async () => {
    server = stubVoiceServer({ queueReply: { status: 400, body: { detail: 'Roteiro vazio.' } } })
    const narration = await ready()
    await expect(narration.sendToQueue({ title: '', format: 'wav', draft: false })).rejects.toThrow('Roteiro vazio.')
    expect(narration.queueing).toBe(false)
  })
})
