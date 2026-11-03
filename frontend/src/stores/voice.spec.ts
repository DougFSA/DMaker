import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoiceProfile } from '@/api'
import { LAST_VOICE_KEY } from '@/lib/voice'
import { FakeEventSource } from '@/test/fetch'
import { useVoiceStore } from './voice'

function voice(id: string, overrides: Partial<VoiceProfile> = {}): VoiceProfile {
  return {
    id,
    name: id.toUpperCase(),
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
  body: unknown
  form: FormData | null
}

let calls: Call[]
/** O que o servidor falso devolve a cada chamada: a chave é "MÉTODO caminho-sem-query". */
let routes: Record<string, (call: Call) => unknown>

function stubApi(): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const isForm = init.body instanceof FormData
      const call: Call = {
        method: init.method ?? 'GET',
        url,
        body: init.body && !isForm ? JSON.parse(String(init.body)) : undefined,
        form: isForm ? (init.body as FormData) : null,
      }
      calls.push(call)
      const handler = routes[`${call.method} ${url.split('?')[0]}`]
      if (!handler) return Promise.resolve(new Response('{"detail":"nada"}', { status: 404 }))
      return Promise.resolve(new Response(JSON.stringify(handler(call))))
    }),
  )
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  routes = { 'GET /api/voices': () => [voice('ana'), voice('beto')] }
  stubApi()
})
afterEach(() => vi.unstubAllGlobals())

describe('biblioteca de vozes', () => {
  it('carrega as vozes e guarda a lista', async () => {
    const store = useVoiceStore()
    await store.loadVoices()
    expect(store.voices.map((item) => item.id)).toEqual(['ana', 'beto'])
    expect(calls[0]).toMatchObject({ method: 'GET', url: '/api/voices' })
    expect(store.loading).toBe(false)
  })

  it('o filtro de marca vai na consulta e troca a lista', async () => {
    routes['GET /api/voices'] = (call) => (call.url.includes('brand=medlycare') ? [voice('ana')] : [])
    const store = useVoiceStore()
    await store.setBrandFilter('medlycare')
    expect(calls.at(-1)?.url).toBe('/api/voices?brand=medlycare')
    expect(store.voices).toHaveLength(1)
    await store.setBrandFilter('')
    expect(calls.at(-1)?.url).toBe('/api/voices')
  })

  it('uma falha na consulta vira mensagem, sem derrubar a lista que já estava', async () => {
    const store = useVoiceStore()
    await store.loadVoices()
    delete routes['GET /api/voices']
    await store.loadVoices()
    expect(store.failure).toContain('nada')
    expect(store.voices).toHaveLength(2)
    expect(store.loading).toBe(false)
  })

  it('as opções de desenho são buscadas uma vez só', async () => {
    const options = { gender: [], age: [], pitch: [], accent: [], languages: [{ value: 'pt', label: 'Português' }] }
    routes['GET /api/voices/design-options'] = () => options
    const store = useVoiceStore()
    await store.loadOptions()
    await store.loadOptions()
    expect(calls.filter((call) => call.url === '/api/voices/design-options')).toHaveLength(1)
    expect(store.options?.languages[0]?.label).toBe('Português')
  })
})

describe('voz escolhida para o roteiro', () => {
  it('Usar guarda a escolha no navegador, na mesma chave da clássica', async () => {
    const store = useVoiceStore()
    await store.loadVoices()
    store.chooseVoice('beto')
    expect(store.selectedVoiceId).toBe('beto')
    expect(store.selectedVoice?.name).toBe('BETO')
    expect(localStorage.getItem(LAST_VOICE_KEY)).toBe('beto')
    expect(LAST_VOICE_KEY).toBe('dmaker.voice.lastVoice')
  })

  it('lembra a última voz ao abrir a interface de novo', () => {
    localStorage.setItem(LAST_VOICE_KEY, 'ana')
    setActivePinia(createPinia())
    expect(useVoiceStore().selectedVoiceId).toBe('ana')
  })

  it('a voz lembrada que não existe mais não vira voz escolhida', async () => {
    localStorage.setItem(LAST_VOICE_KEY, 'sumiu')
    setActivePinia(createPinia())
    const store = useVoiceStore()
    await store.loadVoices()
    expect(store.selectedVoiceId).toBe('sumiu')
    expect(store.selectedVoice).toBeNull()
  })
})

describe('criar e remover vozes', () => {
  it('clonar envia o arquivo, recarrega a lista e já escolhe a voz nova', async () => {
    routes['POST /api/voices/clone'] = () => voice('nova', { name: 'Nova' })
    routes['GET /api/voices'] = () => [voice('ana'), voice('nova', { name: 'Nova' })]
    const store = useVoiceStore()
    const profile = await store.clone({
      name: 'Nova',
      audio: new Blob(['x'], { type: 'audio/webm' }),
      filename: 'gravacao.webm',
      language: 'pt',
    })
    expect(profile.id).toBe('nova')
    const post = calls.find((call) => call.method === 'POST')
    expect(post?.form?.get('name')).toBe('Nova')
    expect(store.voices.map((item) => item.id)).toContain('nova')
    expect(store.selectedVoiceId).toBe('nova')
    expect(localStorage.getItem(LAST_VOICE_KEY)).toBe('nova')
  })

  it('uma clonagem recusada não escolhe nada nem mexe na lista', async () => {
    routes['POST /api/voices/clone'] = () => {
      throw new Error('x')
    }
    const store = useVoiceStore()
    await expect(store.clone({ name: 'Nova', audio: new Blob(['x']) })).rejects.toThrow()
    expect(store.selectedVoiceId).toBe('')
  })

  it('desenhar manda os campos e escolhe a voz criada', async () => {
    routes['POST /api/voices/design'] = () => voice('narradora', { kind: 'design' })
    const store = useVoiceStore()
    await store.design({ name: 'Narradora', gender: 'female', whisper: true, language: 'pt' })
    const post = calls.find((call) => call.method === 'POST')
    expect(post?.body).toMatchObject({ name: 'Narradora', gender: 'female', whisper: true })
    expect(store.selectedVoiceId).toBe('narradora')
  })

  it('remover apaga no servidor, recarrega, e esquece a voz se era a escolhida', async () => {
    routes['DELETE /api/voices/ana'] = () => ({ ok: true })
    const store = useVoiceStore()
    await store.loadVoices()
    store.chooseVoice('ana')
    routes['GET /api/voices'] = () => [voice('beto')]
    await store.remove('ana')
    expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/voices/ana')).toBe(true)
    expect(store.voices.map((item) => item.id)).toEqual(['beto'])
    expect(store.selectedVoiceId).toBe('')
    expect(localStorage.getItem(LAST_VOICE_KEY)).toBe('')
  })

  it('remover outra voz não troca a escolhida', async () => {
    routes['DELETE /api/voices/beto'] = () => ({ ok: true })
    const store = useVoiceStore()
    store.chooseVoice('ana')
    await store.remove('beto')
    expect(store.selectedVoiceId).toBe('ana')
  })
})

describe('amostra da voz', () => {
  beforeEach(() => {
    routes['POST /api/voices/ana/preview'] = () => ({ job_id: 'j1' })
  })

  it('gera a amostra como job e deixa a voz tocar quando termina', async () => {
    const store = useVoiceStore()
    await store.loadVoices()
    const done = store.preview('ana')
    await flushPromises()

    expect(store.previews['ana']).toMatchObject({ error: '', label: '' })
    const source = FakeEventSource.latest()
    expect(source.url).toBe('/api/jobs/j1/events')
    source.emit({ kind: 'progress', t: 1, label: 'fala 1 de 1', done: 1, total: 1, percent: 0 })
    expect(store.previews['ana']?.label).toBe('fala 1 de 1')

    source.emit({
      kind: 'end',
      t: 9,
      status: 'done',
      error: null,
      result: { output: 'a.wav', audio_url: '/api/voices/audio?path=a.wav', duration_s: 3, cues: [] },
    })
    await done

    expect(store.previews['ana']).toBeUndefined()
    expect(store.sample).toMatchObject({ voiceId: 'ana', voiceName: 'ANA', url: '/api/voices/audio?path=a.wav' })
  })

  it('pedir a amostra de novo enquanto ela é gerada não abre outro job', async () => {
    const store = useVoiceStore()
    void store.preview('ana')
    await flushPromises()
    void store.preview('ana')
    await flushPromises()
    expect(calls.filter((call) => call.url === '/api/voices/ana/preview')).toHaveLength(1)
  })

  it('o job que falha deixa a mensagem na voz e libera pedir de novo', async () => {
    const store = useVoiceStore()
    const done = store.preview('ana')
    await flushPromises()
    FakeEventSource.latest().emit({
      kind: 'end',
      t: 2,
      status: 'error',
      error: 'RuntimeError: modelo de voz ausente\nTraceback...',
      result: null,
    })
    await done
    expect(store.previews['ana']?.error).toBe('modelo de voz ausente')
    expect(store.sample).toBeNull()

    void store.preview('ana')
    await flushPromises()
    expect(calls.filter((call) => call.url === '/api/voices/ana/preview')).toHaveLength(2)
    expect(store.previews['ana']?.error).toBe('')
  })

  it('uma amostra nova da mesma voz troca o carimbo, para a tela tocar de novo', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    try {
      const store = useVoiceStore()
      const finish = async () => {
        const done = store.preview('ana')
        await flushPromises()
        FakeEventSource.latest().emit({
          kind: 'end',
          t: 1,
          status: 'done',
          error: null,
          result: { output: 'a.wav', audio_url: '/a.wav', duration_s: 1, cues: [] },
        })
        await done
        return store.sample?.stamp
      }
      const first = await finish()
      vi.setSystemTime(Date.now() + 5000)
      const second = await finish()
      expect(second).toBeGreaterThan(first ?? 0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('remover a voz da amostra tira a amostra da tela', async () => {
    routes['DELETE /api/voices/ana'] = () => ({ ok: true })
    const store = useVoiceStore()
    const done = store.preview('ana')
    await flushPromises()
    FakeEventSource.latest().emit({
      kind: 'end',
      t: 1,
      status: 'done',
      error: null,
      result: { output: 'a.wav', audio_url: '/a.wav', duration_s: 1, cues: [] },
    })
    await done
    await store.remove('ana')
    expect(store.sample).toBeNull()
  })
})
