import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PronunciationEntry } from '@/api'
import { FakeEventSource } from '@/test/fetch'
import { callsTo } from '@/test/speechServer'
import { NARRATION_RESULT, stubVoiceServer, type VoiceServer } from '@/test/voiceServer'
import { useNarrationStore } from './narration'
import { usePronunciationStore } from './pronunciation'
import { useToastsStore } from './toasts'

const DMAKER: PronunciationEntry = { term: 'DMaker', spoken: 'Di-mêiker', scope: 'global', language: 'pt' }
const API: PronunciationEntry = { term: 'API', spoken: 'ei-pi-ai', scope: 'medlycare', language: 'en' }

let server: VoiceServer

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  server = stubVoiceServer({ pronunciation: [DMAKER, API] })
})
afterEach(() => vi.unstubAllGlobals())

describe('listar', () => {
  it('lê o dicionário global e, ao escolher uma marca, o dela', async () => {
    const pronunciation = usePronunciationStore()
    await pronunciation.load()
    expect(pronunciation.entries).toEqual([DMAKER, API])
    expect(server.calls.at(-1)!.url).toBe('/api/voices/pronunciation')

    await pronunciation.setBrand('medlycare')
    expect(server.calls.at(-1)!.url).toBe('/api/voices/pronunciation?brand=medlycare')
  })

  it('a falha ao ler fica à vista', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'léxico ilegível' }), { status: 500 })))
    const pronunciation = usePronunciationStore()
    await pronunciation.load()
    expect(pronunciation.failure).toContain('léxico ilegível')
    expect(pronunciation.loading).toBe(false)
  })
})

describe('adicionar', () => {
  it('só adiciona com o termo e como falá-lo', () => {
    const pronunciation = usePronunciationStore()
    expect(pronunciation.canAdd).toBe(false)
    pronunciation.term = 'Pix'
    expect(pronunciation.canAdd).toBe(false)
    pronunciation.spoken = 'piques'
    expect(pronunciation.canAdd).toBe(true)
  })

  it('manda o termo no dicionário aberto, limpa o formulário e mostra a lista nova', async () => {
    const pronunciation = usePronunciationStore()
    await pronunciation.load()
    pronunciation.brand = 'medlycare'
    pronunciation.term = ' Pix '
    pronunciation.spoken = ' piques '
    pronunciation.language = 'pt'

    expect(await pronunciation.add()).toBe(true)

    expect(callsTo(server.calls, 'POST', '/api/voices/pronunciation')[0]!.body).toEqual({
      term: 'Pix',
      spoken: 'piques',
      brand: 'medlycare',
      language: 'pt',
    })
    expect(pronunciation.entries.map((entry) => entry.term)).toEqual(['DMaker', 'API', 'Pix'])
    expect(pronunciation.term).toBe('')
    expect(pronunciation.spoken).toBe('')
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('Pronúncia salva')
  })

  it('no dicionário global manda a marca como null', async () => {
    const pronunciation = usePronunciationStore()
    pronunciation.term = 'Pix'
    pronunciation.spoken = 'piques'
    await pronunciation.add()
    expect(callsTo(server.calls, 'POST', '/api/voices/pronunciation')[0]!.body).toMatchObject({ brand: null })
  })

  it('se o servidor recusa, avisa e mantém o que foi escrito', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Termo repetido.' }), { status: 400 })))
    const pronunciation = usePronunciationStore()
    pronunciation.term = 'Pix'
    pronunciation.spoken = 'piques'
    expect(await pronunciation.add()).toBe(false)
    expect(pronunciation.term).toBe('Pix')
    expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'error', description: 'Termo repetido.' })
    expect(pronunciation.adding).toBe(false)
  })
})

describe('remover', () => {
  it('tira o termo global do dicionário global', async () => {
    const pronunciation = usePronunciationStore()
    await pronunciation.load()
    await pronunciation.remove(DMAKER)
    expect(callsTo(server.calls, 'DELETE', '/api/voices/pronunciation?term=DMaker&language=pt')).toHaveLength(1)
    expect(pronunciation.entries).toEqual([API])
  })

  it('tira o termo de marca da marca dona dele, mesmo vendo outro dicionário', async () => {
    const pronunciation = usePronunciationStore()
    await pronunciation.load()
    await pronunciation.remove(API)
    expect(callsTo(server.calls, 'DELETE', '/api/voices/pronunciation?term=API&brand=medlycare&language=en')).toHaveLength(1)
    expect(pronunciation.entries).toEqual([DMAKER])
  })
})

describe('ouvir', () => {
  it('gera a frase do termo com a voz da Narração e deixa a amostra pronta', async () => {
    const narration = useNarrationStore()
    await narration.loadVoices()
    narration.chooseVoice('dora')
    const pronunciation = usePronunciationStore()
    pronunciation.brand = 'medlycare'

    const listening = pronunciation.listen(API)
    await flushPromises()
    expect(pronunciation.listening['en:API']).toBe(true)
    expect(callsTo(server.calls, 'POST', '/api/voices/speak')[0]!.body).toEqual({
      text: 'I say API. Again: API.',
      voice: 'dora',
      language: 'en',
      brand: 'medlycare',
      seed: 1,
    })

    FakeEventSource.latest().emit({ kind: 'end', t: 5, status: 'done', error: null, result: NARRATION_RESULT })
    await listening
    expect(pronunciation.listening).toEqual({})
    expect(pronunciation.sample).toMatchObject({ term: 'API', url: NARRATION_RESULT.audio_url })
  })

  it('sem voz escolhida, fala com a voz automática', async () => {
    const pronunciation = usePronunciationStore()
    void pronunciation.listen(DMAKER)
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/voices/speak')[0]!.body).toMatchObject({ voice: null, brand: null })
  })

  it('o mesmo termo não é pedido duas vezes enquanto a frase não fica pronta', async () => {
    const pronunciation = usePronunciationStore()
    void pronunciation.listen(DMAKER)
    await flushPromises()
    void pronunciation.listen(DMAKER)
    await flushPromises()
    expect(callsTo(server.calls, 'POST', '/api/voices/speak')).toHaveLength(1)
  })

  it('se o job falha, avisa e libera o botão', async () => {
    const pronunciation = usePronunciationStore()
    const listening = pronunciation.listen(DMAKER)
    await flushPromises()
    FakeEventSource.latest().emit({ kind: 'end', t: 5, status: 'error', error: 'RuntimeError: sem modelo\ntraceback', result: null })
    await listening
    expect(pronunciation.listening).toEqual({})
    expect(pronunciation.sample).toBeNull()
    expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'error', description: 'sem modelo' })
  })
})
