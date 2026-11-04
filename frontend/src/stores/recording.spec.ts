import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCaptureEngine } from '@/lib/recordingCapture'
import { makeClick, readCalibration, webAudioLatency } from '@/lib/recordingLatency'
import { voiceSpec, voiceView } from '@/test/audioPanelFixtures'
import { fakeEngine, FAKE_RATE, type FakeEngine, type FakeSession } from '@/test/fakeCapture'
import { openEditor, type OpenedEditor } from '@/test/editorMount'
import { useAudioPanelStore } from './audioPanel'
import { usePlayerStore } from './player'
import { useRecordingStore } from './recording'
import { useToastsStore } from './toasts'

const ID = 'rec-1'
const BASE = '/api/projects/demo/recordings'
let opened: OpenedEditor
let engine: FakeEngine

function finishBody(extra: Record<string, unknown> = {}) {
  return {
    id: ID,
    state: 'finished',
    rate: FAKE_RATE,
    channels: 1,
    start: 5,
    label: '',
    created_at: '',
    chunks: 4,
    frames: 4 * FAKE_RATE,
    duration: 4,
    gaps: [],
    src: `recordings/${ID}/gravacao.wav`,
    punch: null,
    device: '',
    op: { type: 'audio_record_add', src: `recordings/${ID}/gravacao.wav`, start: 5, duration: 4 },
    recover_op: { type: 'audio_record_add', src: `recordings/${ID}/gravacao.wav`, start: 5, duration: 4 },
    ...extra,
  }
}

async function open(extra: Record<string, unknown> = {}) {
  const view = voiceView()
  const routes: Record<string, unknown> = {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/edit': () => ({ spec: voiceSpec(), timeline: view }),
    [`POST ${BASE}`]: () => ({ ...finishBody(), state: 'open', src: null }),
    [`POST ${BASE}/${ID}/finish`]: () => finishBody(),
    [`GET ${BASE}`]: { recordings: [] },
  }
  for (let seq = 0; seq < 40; seq += 1) routes[`PUT ${BASE}/${ID}/chunks/${seq}`] = { seq, bytes: 0, duplicate: false }
  Object.assign(routes, extra)
  opened = await openEditor(voiceSpec(), routes)
  return useRecordingStore()
}

const calls = (route: string) => opened.fetch.to(route)
const session = (): FakeSession => engine.sessions[0] as FakeSession

beforeEach(() => {
  window.localStorage.clear()
  engine = fakeEngine()
  useCaptureEngine(() => engine)
})
afterEach(() => {
  useCaptureEngine()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('gravar sobre o vídeo', () => {
  it('manda um pedaço por segundo, numerados, e põe o instante já compensado pela latência', async () => {
    const recording = await open()
    const player = usePlayerStore()
    recording.settings.overVideo = true
    await recording.start()
    expect(recording.phase).toBe('recording')
    expect(player.playing).toBe(true)
    const mic = session()
    mic.pageOrigin = 1000 // o contexto de áudio marcava zero quando o relógio da página marcava 1000 ms
    // 3,5 s de som: o cursor da prévia anda junto com o relógio da página (1x), a partir de 0
    const blocks = Math.round((3.5 * FAKE_RATE) / 2048)
    for (let index = 0; index < blocks; index += 1) {
      const atMs = (index * 2048 * 1000) / FAKE_RATE + 1000
      opened.store.setPlayhead(index === 0 ? 0 : (atMs - 1000) / 1000)
      mic.pushLevel(0.25, atMs)
    }
    await recording.stop()
    await flushPromises()
    const opening = calls(`POST ${BASE}`)[0]?.body as { start: number; rate: number; channels: number }
    const estimate = webAudioLatency(mic.latencyReading)
    expect(estimate).toBeCloseTo(0.07, 6)
    expect(opening.rate).toBe(FAKE_RATE)
    expect(opening.channels).toBe(1)
    // o primeiro bloco chegou com a prévia em 0 s: o item começa 70 ms antes, em -0,07 s
    expect(opening.start).toBeCloseTo(-0.07, 2)
    const sent = [0, 1, 2, 3].map((seq) => calls(`PUT ${BASE}/${ID}/chunks/${seq}`).length)
    expect(sent).toEqual([1, 1, 1, 1]) // 3 pedaços inteiros de 1 s e o resto no fim
    expect(calls(`POST ${BASE}/${ID}/finish`)).toHaveLength(1)
    const edit = calls('POST /api/projects/demo/edit').at(-1)?.body as { op: Record<string, unknown> }
    expect(edit.op).toMatchObject({ type: 'audio_record_add', duration: 4 })
    expect(player.playing).toBe(false)
    expect(recording.phase).toBe('idle')
    expect(mic.closed).toBe(true)
  })

  it('sem gravar sobre o vídeo o item entra no cursor, sem tocar a prévia', async () => {
    const recording = await open()
    const player = usePlayerStore()
    recording.settings.overVideo = false
    opened.store.setPlayhead(7.25)
    await recording.start()
    expect(player.playing).toBe(false)
    session().pushSeconds(1.2, 0.2)
    await recording.stop()
    await flushPromises()
    const opening = calls(`POST ${BASE}`)[0]?.body as { start: number }
    expect(opening.start).toBe(7.25)
  })

  it('o medidor mostra o nível e acusa o clipping', async () => {
    const recording = await open()
    await recording.monitor()
    expect(recording.phase).toBe('monitoring')
    session().pushLevel(0.5)
    expect(recording.levels[0]?.peakDb).toBeCloseTo(-6.02, 1)
    expect(recording.levels[0]?.clipped).toBe(false)
    session().pushLevel(1)
    expect(recording.levels[0]?.clipped).toBe(true)
    expect(calls(`POST ${BASE}`)).toHaveLength(0) // monitorar não grava nada no servidor
    await recording.stopMonitor()
    expect(session().closed).toBe(true)
  })

  it('a escuta pelo fone liga e desliga no microfone aberto', async () => {
    const recording = await open()
    await recording.monitor()
    recording.setListen(true)
    expect(session().monitoring).toBe(true)
    recording.setListen(false)
    expect(session().monitoring).toBe(false)
  })

  it('desistir apaga a gravação do servidor e não põe nada na linha do tempo', async () => {
    const recording = await open({ [`DELETE ${BASE}/${ID}`]: { discarded: ID } })
    recording.settings.overVideo = false
    await recording.start()
    session().pushSeconds(1.5, 0.2)
    await flushPromises()
    await recording.cancel()
    expect(calls(`DELETE ${BASE}/${ID}`)).toHaveLength(1)
    expect(calls(`POST ${BASE}/${ID}/finish`)).toHaveLength(0)
    expect(recording.phase).toBe('idle')
  })

  it('o servidor fora do ar não derruba a gravação: o pedaço é reenviado', async () => {
    let up = false
    const recording = await open({
      [`PUT ${BASE}/${ID}/chunks/0`]: () => (up ? { seq: 0, bytes: 0, duplicate: false } : { status: 503, body: { detail: 'fora' } }),
    })
    recording.settings.overVideo = false
    await recording.start()
    session().pushSeconds(1.2, 0.2)
    await vi.waitFor(() => expect(recording.notice).toContain('reenviados'))
    up = true
    await vi.waitFor(() => expect(calls(`PUT ${BASE}/${ID}/chunks/0`).length).toBeGreaterThan(1), { timeout: 3000 })
    await recording.stop()
    expect(calls(`POST ${BASE}/${ID}/finish`)).toHaveLength(1)
  })
})

describe('ativada por som', () => {
  it('não manda o silêncio entre as falas', async () => {
    const recording = await open()
    recording.settings.overVideo = false
    recording.settings.soundActivated = true
    recording.settings.thresholdDb = -40
    recording.settings.waitSeconds = 1
    await recording.start()
    const mic = session()
    mic.pushSeconds(2, 0.0001) // silêncio (-80 dB)
    mic.pushSeconds(2, 0.3) // fala
    mic.pushSeconds(6, 0.0001) // silêncio longo
    mic.pushSeconds(2, 0.3) // fala
    mic.pushSeconds(3, 0.0001)
    await recording.stop()
    await flushPromises()
    const finished = calls(`POST ${BASE}/${ID}/finish`)
    expect(finished).toHaveLength(1)
    // dos 15 s captados só entram as duas falas (4 s) e os 300 ms de pré-rolo e de cauda de cada uma
    const chunks = opened.fetch.calls.filter((call) => call.method === 'PUT' && call.path.includes('/chunks/'))
    const seconds = chunks.length
    expect(seconds).toBeGreaterThanOrEqual(5) // 4,6 s de som, em pedaços de 1 s (o último, parcial)
    expect(seconds).toBeLessThanOrEqual(6)
  })

  it('sem nenhum som acima do limiar nada é gravado nem finalizado', async () => {
    const recording = await open()
    recording.settings.overVideo = false
    recording.settings.soundActivated = true
    await recording.start()
    session().pushSeconds(3, 0.0001)
    await recording.stop()
    expect(calls(`POST ${BASE}`)).toHaveLength(0)
    expect(recording.notice).toContain('Nada foi gravado')
  })
})

describe('punch-in', () => {
  async function selectVoice() {
    const panel = useAudioPanelStore()
    const entry = opened.store.findItem('VO-0')
    panel.openFor(entry)
    panel.setOverview({
      target: 'audio.voiceover.0',
      label: 'voz.wav',
      state: 'ready',
      key: 'k',
      gain: 1,
      percent: 100,
      stage: '',
      error: null,
      duration: 12,
      origin: 0,
      rate: 48000,
      channels: 2,
      frames: 576000,
      clock: { start: 0.5, speed: 1 },
      notes: [],
      start: 0,
      end: 12,
      columns: 1,
      ready_until: 12,
      mode: 'peaks',
      mins: [[0]],
      maxs: [[0]],
    } as never)
    panel.selection = { start: 4, end: 7 }
    return panel
  }

  it('a seleção da onda vira o trecho do punch-in, em tempo da linha do tempo', async () => {
    const recording = await open()
    await selectVoice()
    expect(recording.punchCandidate).toEqual({ target: 'audio.voiceover.0', start: 4.5, end: 7.5 })
    recording.openDialog()
    expect(recording.settings.punchIn).toBe(true)
  })

  it('começa a prévia na pré-rolagem, abre a gravação com o trecho e para sozinho depois dele', async () => {
    const recording = await open({
      [`POST ${BASE}/${ID}/finish`]: () =>
        finishBody({
          op: { type: 'audio_punch', target: 'audio.voiceover.0', start: 4.5, end: 7.5, src: 'recordings/rec-1/gravacao.wav', recorded_at: 1.4, duration: 4 },
        }),
    })
    await selectVoice()
    recording.openDialog()
    recording.settings.prerollSeconds = 3
    await recording.start()
    expect(opened.store.playhead).toBeCloseTo(1.5, 5) // 4,5 - 3
    const mic = session()
    mic.pageOrigin = 1000
    let index = 0
    // a prévia anda a 1x; o trecho termina em 7,5 s, então a gravação passa de 1,5 s a 7,75 s e para
    while (recording.phase === 'recording' && index < 400) {
      const t = (index * 2048) / FAKE_RATE
      opened.store.setPlayhead(1.5 + t)
      mic.pushLevel(0.2, 1000 + t * 1000)
      index += 1
    }
    await flushPromises()
    expect((index * 2048) / FAKE_RATE).toBeGreaterThan(6)
    expect((index * 2048) / FAKE_RATE).toBeLessThan(6.6)
    const opening = calls(`POST ${BASE}`)[0]?.body as { punch: unknown; start: number }
    expect(opening.punch).toEqual({ target: 'audio.voiceover.0', start: 4.5, end: 7.5 })
    expect(opening.start).toBeCloseTo(1.5 - 0.07, 2)
    const edit = calls('POST /api/projects/demo/edit').at(-1)?.body as { op: { type: string } }
    expect(edit.op.type).toBe('audio_punch')
  })

  it('sem trecho selecionado, regravar avisa o que falta', async () => {
    const recording = await open()
    recording.settings.punchIn = true
    await recording.start()
    expect(recording.error).toContain('Selecione na onda')
    expect(recording.phase).toBe('idle')
  })
})

describe('hora marcada', () => {
  it('espera até a hora marcada com o microfone aberto e então grava pela duração pedida', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    vi.setSystemTime(new Date(2026, 10, 4, 19, 0, 0))
    const recording = await open()
    recording.settings.overVideo = false
    recording.settings.scheduled = true
    recording.settings.startAt = '2026-11-04T19:30'
    recording.settings.durationMinutes = null
    recording.settings.endAt = '2026-11-04T19:30'
    await recording.start()
    expect(recording.error).toContain('fim precisa ser depois')
    recording.settings.endAt = ''
    recording.settings.durationMinutes = 0.05 // 3 s
    await recording.start()
    expect(recording.phase).toBe('waiting')
    expect(recording.countdown).toBe(1800)
    expect(session().onBlock).not.toBeNull() // o medidor anda enquanto espera
    vi.advanceTimersByTime(30 * 60_000 + 10)
    expect(recording.phase).toBe('recording')
    session().pushSeconds(3.2, 0.2) // passou dos 3 s pedidos: para sozinho
    await vi.advanceTimersByTimeAsync(10)
    await flushPromises()
    expect(recording.phase).toBe('idle')
    expect(calls(`POST ${BASE}/${ID}/finish`)).toHaveLength(1)
  })
})

describe('recuperar a gravação da aba que fechou', () => {
  it('lista as abertas, finaliza com o que chegou e põe como voz nova', async () => {
    const open_ = { ...finishBody(), state: 'open', src: null, chunks: 30, duration: 30, frames: 30 * FAKE_RATE }
    const recording = await open({ [`GET ${BASE}`]: { recordings: [open_] } })
    await recording.loadUnfinished()
    expect(recording.unfinished.map((item) => item.id)).toEqual([ID])
    expect(calls(`GET ${BASE}`)[0]?.url).toContain('unfinished=true')
    const ok = await recording.recover(ID)
    expect(ok).toBe(true)
    const edit = calls('POST /api/projects/demo/edit').at(-1)?.body as { op: Record<string, unknown> }
    expect(edit.op).toMatchObject({ type: 'audio_record_add', src: 'recordings/rec-1/gravacao.wav' })
    expect(useToastsStore().items.at(-1)?.title).toContain('recuperada')
  })

  it('descartar apaga no servidor e atualiza a lista', async () => {
    const recording = await open({ [`DELETE ${BASE}/${ID}`]: { discarded: ID } })
    await recording.discardUnfinished(ID)
    expect(calls(`DELETE ${BASE}/${ID}`)).toHaveLength(1)
  })
})

describe('calibrar a latência', () => {
  it('toca um clique, grava, acha o atraso e guarda a correção do dispositivo', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const recording = await open()
    recording.settings.deviceId = 'mic-a'
    const pending = recording.calibrate()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    const mic = session()
    // o caminho de verdade levaria 113 ms (saída 82 + entrada 31): o clique volta ao microfone por esse tempo
    const trueDelay = 0.113
    const rate = FAKE_RATE
    const total = Math.round(1.6 * rate)
    const wave = new Float32Array(total)
    const click = makeClick(rate)
    // o primeiro bloco chega em 0; o clique é tocado em 0,4 s + o bloco do primeiro empurrão
    const playedAt = 2048 / rate + 0.4
    const index = Math.round((playedAt + trueDelay) * rate)
    click.forEach((value, offset) => (wave[index + offset] = value * 0.4))
    for (let start = 0; start + 2048 <= total; start += 2048) mic.push([wave.slice(start, start + 2048)])
    expect(mic.clicks).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1700)
    await pending
    expect(recording.error).toBe('')
    expect(recording.calibrationText).toContain('113 ms')
    const estimate = webAudioLatency(mic.latencyReading)
    expect(readCalibration('mic-a')).toBeCloseTo(trueDelay - estimate, 3)
  })

  it('sem ouvir o clique, avisa como melhorar e não guarda nada', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const recording = await open()
    recording.settings.deviceId = 'mic-b'
    const pending = recording.calibrate()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    const mic = session()
    for (let block = 0; block < 30; block += 1) mic.push([new Float32Array(2048)])
    await vi.advanceTimersByTimeAsync(1700)
    await pending
    expect(recording.error).toContain('Não ouvi o clique')
    expect(readCalibration('mic-b')).toBe(0)
  })
})

describe('falhas do microfone', () => {
  it('mostra a frase da falha quando o navegador nega o microfone', async () => {
    const recording = await open()
    const { CaptureError } = await import('@/lib/recordingCapture')
    engine.failWith = new CaptureError('denied')
    recording.settings.overVideo = false
    await recording.start()
    expect(recording.error).toContain('Sem acesso ao microfone')
    expect(recording.phase).toBe('idle')
  })

  it('um projeto fechado não grava', async () => {
    const recording = await open()
    opened.store.close()
    await recording.start()
    expect(recording.error).toContain('Abra um projeto')
  })
})
