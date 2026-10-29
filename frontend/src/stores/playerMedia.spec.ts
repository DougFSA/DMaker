import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PreviewAudioStatus, ProxyEntry } from '@/api'
import { openEditor, type OpenedEditor } from '@/test/editorMount'
import { projectSpec } from '@/test/editorFixtures'
import { reply } from '@/test/routedFetch'
import { MIX_POLL_MS, MIX_REQUEST_DELAY_MS, PROXY_POLL_MS, usePlayerMediaStore } from './playerMedia'

function status(extra: Partial<PreviewAudioStatus> = {}): PreviewAudioStatus {
  return {
    state: 'ready',
    key: 'chave-1',
    url: '/api/file?path=mix-1.m4a',
    duration_s: 6,
    warnings: [],
    error: null,
    label: '',
    percent: 0,
    ...extra,
  }
}

function proxy(extra: Partial<ProxyEntry> = {}): ProxyEntry {
  return { src: 'C:/clip0.mp4', proxy: 'C:/cache/p0.mp4', ready: true, missing: false, url: '/api/file?path=p0', ...extra }
}

const THEME = { colors: { text: '#fff' }, font: 'Poppins', logos: {}, no_dash: true }

let opened: OpenedEditor

async function setup(extra: Record<string, unknown> = {}, spec = projectSpec()) {
  opened = await openEditor(spec, {
    'GET /api/projects/demo/theme': THEME,
    'GET /api/projects/demo/proxies': [],
    'POST /api/projects/demo/preview-audio': status(),
    ...extra,
  })
  const media = usePlayerMediaStore()
  media.start()
  await flushPromises()
  return media
}

beforeEach(() => {
  // só os temporizadores: a leitura da resposta do fetch falso não pode ficar presa ao relógio de mentira
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
})

afterEach(() => {
  usePlayerMediaStore().stop()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('a mixagem do áudio', () => {
  it('ao abrir o projeto pede a mixagem da spec e, pronta, ela passa a valer', async () => {
    const media = await setup()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    const asked = opened.fetch.to('POST /api/projects/demo/preview-audio')
    expect(asked).toHaveLength(1)
    expect(asked[0]?.body).toMatchObject({ spec: { name: 'demo' } })
    expect(media.mixState).toBe('ready')
    expect(media.mixUrl).toBe('/api/file?path=mix-1.m4a')
    expect(media.current).toBe(true)
    expect(media.approximate).toBe(false)
  })

  it('enquanto a mixagem é feita o som é aproximado, e a consulta termina quando ela fica pronta', async () => {
    let polls = 0
    const media = await setup({
      'POST /api/projects/demo/preview-audio': status({ state: 'building', url: null, label: 'áudio do trecho 1/2', percent: 40 }),
      'GET /api/projects/demo/preview-audio': () => (++polls < 3 ? status({ state: 'building', url: null, percent: 70 }) : status()),
    })
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(media.mixState).toBe('building')
    expect(media.approximate).toBe(true)
    expect(media.mixLabel).toBe('áudio do trecho 1/2')
    expect(media.mixPercent).toBe(40)

    await vi.advanceTimersByTimeAsync(MIX_POLL_MS)
    await flushPromises()
    expect(media.mixPercent).toBe(70)
    expect(media.current).toBe(false)
    await vi.advanceTimersByTimeAsync(MIX_POLL_MS * 2)
    await flushPromises()
    expect(media.mixState).toBe('ready')
    expect(media.current).toBe(true)
    expect(opened.fetch.to('GET /api/projects/demo/preview-audio')[0]?.url).toBe('/api/projects/demo/preview-audio?key=chave-1')
    // pronta, para de perguntar
    const asked = opened.fetch.to('GET /api/projects/demo/preview-audio').length
    await vi.advanceTimersByTimeAsync(MIX_POLL_MS * 5)
    expect(opened.fetch.to('GET /api/projects/demo/preview-audio')).toHaveLength(asked)
  })

  it('depois de uma edição o som volta a ser aproximado na hora e a mixagem nova entra quando fica pronta', async () => {
    let key = 1
    const media = await setup({
      'POST /api/projects/demo/preview-audio': () => status({ key: `chave-${key}`, url: `/api/file?path=mix-${key}.m4a` }),
    })
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(media.current).toBe(true)

    key = 2
    opened.store.setField('audio.voice_gain', 0.5)
    await flushPromises()
    expect(media.approximate).toBe(true) // antes mesmo de o pedido sair: a mixagem que se tem pode estar velha

    await vi.advanceTimersByTimeAsync(MIX_REQUEST_DELAY_MS)
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/preview-audio')).toHaveLength(2)
    expect(media.mixUrl).toBe('/api/file?path=mix-2.m4a')
    expect(media.current).toBe(true)
  })

  it('uma edição que não muda o som (a chave é a mesma) devolve a mixagem sem trocar de arquivo', async () => {
    const media = await setup()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    opened.store.setField('overlays.0.text', 'Outro texto')
    await flushPromises()
    expect(media.current).toBe(false)
    await vi.advanceTimersByTimeAsync(MIX_REQUEST_DELAY_MS)
    await flushPromises()
    expect(media.current).toBe(true)
    expect(media.mixUrl).toBe('/api/file?path=mix-1.m4a')
  })

  it('digitar em seguida pede uma mixagem só, depois de o silêncio de 600 ms', async () => {
    await setup()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    const before = opened.fetch.to('POST /api/projects/demo/preview-audio').length
    opened.store.setField('audio.voice_gain', 0.4)
    await vi.advanceTimersByTimeAsync(300)
    opened.store.setField('audio.voice_gain', 0.45)
    await vi.advanceTimersByTimeAsync(300)
    opened.store.setField('audio.voice_gain', 0.5)
    await vi.advanceTimersByTimeAsync(MIX_REQUEST_DELAY_MS)
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/preview-audio')).toHaveLength(before + 1)
    expect(opened.fetch.to('POST /api/projects/demo/preview-audio').at(-1)?.body).toMatchObject({
      spec: { audio: { voice_gain: 0.5 } },
    })
  })

  it('a resposta de uma edição que já foi superada não vale', async () => {
    const releases: Array<() => void> = []
    const media = await setup({
      'POST /api/projects/demo/preview-audio': () =>
        new Promise((resolve) => {
          const index = releases.length + 1
          releases.push(() => resolve(status({ key: `chave-${index}`, url: `/api/file?path=mix-${index}.m4a` })))
        }),
    })
    await vi.advanceTimersByTimeAsync(0) // o primeiro pedido sai e fica esperando
    opened.store.setField('audio.voice_gain', 0.5)
    await vi.advanceTimersByTimeAsync(MIX_REQUEST_DELAY_MS) // o segundo sai
    releases[1]?.()
    await flushPromises()
    releases[0]?.() // a resposta velha chega depois da nova
    await flushPromises()
    expect(media.latestKey).toBe('chave-2')
    expect(media.mixUrl).toBe('/api/file?path=mix-2.m4a')
  })

  it('se a mixagem falha, o som segue ao vivo e o erro fica à mão', async () => {
    const media = await setup({
      'POST /api/projects/demo/preview-audio': status({ state: 'failed', url: null, error: 'RuntimeError: disco cheio' }),
    })
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(media.mixState).toBe('failed')
    expect(media.mixError).toContain('disco cheio')
    expect(media.current).toBe(false)
    expect(media.approximate).toBe(true)
  })

  it('um erro do servidor ao pedir também deixa o som ao vivo', async () => {
    const media = await setup({ 'POST /api/projects/demo/preview-audio': reply(422, { detail: 'fonte não cobre o trecho' }) })
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(media.mixState).toBe('failed')
    expect(media.mixError).toContain('fonte não cobre o trecho')
    expect(media.approximate).toBe(true)
  })

  it('o que a mixagem deixou de fora vira aviso', async () => {
    const media = await setup({
      'POST /api/projects/demo/preview-audio': status({ warnings: ['A narração 1 ainda não foi sintetizada e fica fora da prévia.'] }),
    })
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(media.mixWarnings).toEqual(['A narração 1 ainda não foi sintetizada e fica fora da prévia.'])
  })

  it('spec inválida no disco não pede mixagem', async () => {
    const media = await setup({
      'GET /api/projects/demo': reply(422, { detail: [{ loc: 'timeline', msg: 'inválida' }], raw_spec: projectSpec() }),
    })
    await vi.advanceTimersByTimeAsync(MIX_REQUEST_DELAY_MS)
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/preview-audio')).toHaveLength(0)
    expect(media.mixState).toBe('idle')
  })

  it('parar desliga os pedidos', async () => {
    const media = await setup()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    media.stop()
    opened.store.setField('audio.voice_gain', 0.5)
    await vi.advanceTimersByTimeAsync(MIX_REQUEST_DELAY_MS * 2)
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/preview-audio')).toHaveLength(1)
  })
})

describe('tema', () => {
  it('lê as cores, a fonte e os logos do projeto', async () => {
    const media = await setup()
    expect(media.theme).toEqual(THEME)
  })

  it('sem o tema o player segue (o texto usa as cores padrão)', async () => {
    const media = await setup({ 'GET /api/projects/demo/theme': reply(500, { detail: 'quebrou' }) })
    expect(media.theme).toBeNull()
  })
})

describe('proxies', () => {
  it('os prontos viram endereços por arquivo de origem, e o de arquivo ausente não conta como pendente', async () => {
    const media = await setup({
      'GET /api/projects/demo/proxies': [
        proxy(),
        proxy({ src: 'C:/clip1.mp4', ready: false, url: null }),
        proxy({ src: 'C:/sumiu.mp4', proxy: null, ready: false, missing: true, url: null }),
      ],
    })
    expect(media.proxyUrls).toEqual({ 'C:/clip0.mp4': '/api/file?path=p0' })
    expect(media.proxiesReady).toBe(1)
    expect(media.proxiesPending).toBe(1)
    expect(media.proxiesMissing).toBe(1)
  })

  it('gerar começa o job e vai trocando os endereços até todos ficarem prontos', async () => {
    const pending = [proxy({ ready: false, url: null })]
    let lists = 0
    const media = await setup({
      'GET /api/projects/demo/proxies': () => (++lists < 3 ? pending : [proxy()]),
      'POST /api/projects/demo/proxies': { job: { job_id: 'j1' }, proxies: pending },
    })
    expect(media.proxiesPending).toBe(1)
    await media.buildProxies()
    expect(media.proxyBuilding).toBe(true)
    expect(media.proxyNotice).toContain('proxies')
    await vi.advanceTimersByTimeAsync(PROXY_POLL_MS)
    await flushPromises()
    expect(media.proxyBuilding).toBe(true)
    await vi.advanceTimersByTimeAsync(PROXY_POLL_MS)
    await flushPromises()
    expect(media.proxyBuilding).toBe(false)
    expect(media.proxyUrls).toEqual({ 'C:/clip0.mp4': '/api/file?path=p0' })
    expect(media.proxyNotice).toBe('')
  })

  it('um vídeo que não abre no navegador gera o proxy uma vez só', async () => {
    const pending = [proxy({ ready: false, url: null })]
    const media = await setup({
      'GET /api/projects/demo/proxies': pending,
      'POST /api/projects/demo/proxies': { job: { job_id: 'j1' }, proxies: pending },
    })
    media.onMediaError('C:/clip0.mp4')
    media.onMediaError('C:/clip0.mp4')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/proxies')).toHaveLength(1)
    expect(media.proxyNotice).toContain('proxies')
  })

  it('arquivo ausente que dá erro não dispara proxy nenhum', async () => {
    const media = await setup({
      'GET /api/projects/demo/proxies': [proxy({ src: 'C:/sumiu.mp4', proxy: null, ready: false, missing: true, url: null })],
    })
    media.onMediaError('C:/sumiu.mp4')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/proxies')).toHaveLength(0)
  })

  it('quando tudo já está pronto não há job a esperar', async () => {
    const media = await setup({
      'GET /api/projects/demo/proxies': [proxy()],
      'POST /api/projects/demo/proxies': { job: null, proxies: [proxy()] },
    })
    await media.buildProxies()
    expect(media.proxyBuilding).toBe(false)
  })
})
