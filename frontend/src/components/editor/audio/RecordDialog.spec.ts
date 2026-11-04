import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCaptureEngine } from '@/lib/recordingCapture'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useRecordCloneStore } from '@/stores/recordClone'
import { useRecordingStore } from '@/stores/recording'
import { voiceSpec, voiceView } from '@/test/audioPanelFixtures'
import { openEditor, mountEditorPart, type OpenedEditor } from '@/test/editorMount'
import { fakeEngine, FAKE_RATE, type FakeEngine, type FakeSession } from '@/test/fakeCapture'
import RecordDialog from './RecordDialog.vue'
import RecordingRecovery from './RecordingRecovery.vue'
import VoiceTakes from './VoiceTakes.vue'

let opened: OpenedEditor
let wrapper: VueWrapper | null = null
let engine: FakeEngine

const BASE = '/api/projects/demo/recordings'
const body = () => document.body

async function mountWith(component: typeof RecordDialog | typeof RecordingRecovery | typeof VoiceTakes, extra: Record<string, unknown> = {}) {
  const view = voiceView()
  opened = await openEditor(voiceSpec(), {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/edit': () => ({ spec: voiceSpec(), timeline: view }),
    [`GET ${BASE}`]: { recordings: [] },
    'GET /api/voices': [],
    ...extra,
  })
  wrapper = await mountEditorPart(component, opened, {}, true)
}

const button = (selector: string) => body().querySelector(selector) as HTMLButtonElement | null
const session = (): FakeSession => engine.sessions[0] as FakeSession

beforeEach(() => {
  window.localStorage.clear()
  engine = fakeEngine()
  useCaptureEngine(() => engine)
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  useCaptureEngine()
  vi.unstubAllGlobals()
})

describe('a janela Gravar', () => {
  it('lista os microfones, monitora o nível sem gravar e avisa da microfonia na escuta pelo fone', async () => {
    await mountWith(RecordDialog)
    const recording = useRecordingStore()
    recording.openDialog()
    await flushPromises()
    expect(body().textContent).toContain('Microfone A')
    expect(body().textContent).toContain('Padrão do sistema')
    expect(body().textContent).toContain('Use fone de ouvido')
    expect(body().textContent).toContain('ficam desligados')
    button('[data-record-monitor]')?.click()
    await flushPromises()
    expect(recording.phase).toBe('monitoring')
    session().pushLevel(1)
    await flushPromises()
    expect(body().querySelector('[data-audio-meter]')).not.toBeNull()
    expect(body().querySelector('.meter__clip--on')).not.toBeNull() // o clipping acende no medidor
    expect(opened.fetch.to(`POST ${BASE}`)).toHaveLength(0)
    button('[data-record-monitor-stop]')?.click()
    await flushPromises()
    expect(recording.phase).toBe('idle')
  })

  it('a hora marcada e a gravação por som avisam que a aba precisa ficar aberta', async () => {
    await mountWith(RecordDialog)
    const recording = useRecordingStore()
    recording.openDialog()
    await flushPromises()
    expect(body().querySelector('[data-record-tab-warning]')).toBeNull()
    recording.settings.soundActivated = true
    await flushPromises()
    expect(body().querySelector('[data-record-tab-warning]')?.textContent).toContain('aba precisa ficar aberta')
    recording.settings.soundActivated = false
    recording.settings.scheduled = true
    await flushPromises()
    expect(body().querySelector('[data-record-start-at]')).not.toBeNull()
    expect(body().querySelector('[data-record-tab-warning]')).not.toBeNull()
  })

  it('grava e para pelos botões da janela', async () => {
    await mountWith(RecordDialog, {
      [`POST ${BASE}`]: () => ({ id: 'r1', state: 'open' }),
      [`PUT ${BASE}/r1/chunks/0`]: { seq: 0 },
      [`PUT ${BASE}/r1/chunks/1`]: { seq: 1 },
      [`POST ${BASE}/r1/finish`]: () => ({
        id: 'r1',
        duration: 1.5,
        gaps: [],
        op: { type: 'audio_record_add', src: 'recordings/r1/gravacao.wav', start: 0, duration: 1.5 },
        recover_op: { type: 'audio_record_add', src: 'recordings/r1/gravacao.wav', start: 0, duration: 1.5 },
      }),
    })
    const recording = useRecordingStore()
    recording.openDialog()
    recording.settings.overVideo = false
    await flushPromises()
    button('[data-record-start]')?.click()
    await flushPromises()
    expect(recording.phase).toBe('recording')
    session().pushSeconds(1.5, 0.2)
    await flushPromises()
    expect(body().querySelector('[data-record-status]')?.textContent).toContain('Gravando')
    button('[data-record-stop]')?.click()
    await flushPromises()
    await vi.waitFor(() => expect(recording.phase).toBe('idle'))
    expect(opened.fetch.to('POST /api/projects/demo/edit').at(-1)?.body).toMatchObject({ op: { type: 'audio_record_add' } })
  })

  it('o navegador sem captura mostra o motivo e desabilita o Gravar', async () => {
    engine.isSupported = () => false
    await mountWith(RecordDialog)
    useRecordingStore().openDialog()
    await flushPromises()
    expect(body().querySelector('[role="alert"]')?.textContent).toContain('não captura o som cru')
    expect(button('[data-record-start]')?.disabled).toBe(true)
  })

  it('o atalho de clonagem mostra a folha, exige a permissão e manda o WAV direto para a clonagem', async () => {
    await mountWith(RecordDialog, {
      'POST /api/voices/clone': () => ({ id: 'minha-voz', name: 'Minha voz', kind: 'clone', language: 'pt' }),
    })
    const recording = useRecordingStore()
    recording.openDialog('clone')
    await flushPromises()
    const clone = useRecordCloneStore()
    expect(body().querySelector('[data-clone-script]')?.textContent).toContain('Olá, estou gravando a minha voz')
    expect(button('[data-clone-record]')?.disabled).toBe(true) // sem nome nem permissão
    clone.name = 'Minha voz'
    clone.consent = true
    await flushPromises()
    expect(button('[data-clone-record]')?.disabled).toBe(false)
    button('[data-clone-record]')?.click()
    await flushPromises()
    expect(clone.phase).toBe('recording')
    session().pushSeconds(15.2, 0.1) // 15 s lidos: para sozinho e clona
    await flushPromises()
    await vi.waitFor(() => expect(opened.fetch.to('POST /api/voices/clone')).toHaveLength(1))
    const form = opened.fetch.to('POST /api/voices/clone')[0]?.form as FormData
    expect(form.get('name')).toBe('Minha voz')
    expect(String(form.get('reference_text'))).toContain('Olá, estou gravando a minha voz')
    const audio = form.get('audio') as File
    expect(audio.type).toBe('audio/wav')
    expect(audio.size).toBeGreaterThan(44 + FAKE_RATE * 2 * 14) // 15 s de 16 bits mono
    await vi.waitFor(() => expect(clone.phase).toBe('idle'))
    expect(session().closed).toBe(true)
  })

  it('parar o clone antes de 3 s não clona', async () => {
    await mountWith(RecordDialog, { 'POST /api/voices/clone': () => ({}) })
    useRecordingStore().openDialog('clone')
    const clone = useRecordCloneStore()
    clone.name = 'Curta'
    clone.consent = true
    await clone.record()
    session().pushSeconds(1, 0.1)
    await clone.stop()
    expect(clone.error).toContain('pelo menos 3 segundos')
    expect(opened.fetch.to('POST /api/voices/clone')).toHaveLength(0)
    await clone.cancel()
  })
})

describe('o painel Áudio', () => {
  it('avisa da gravação que a aba deixou aberta e recupera com a duração que chegou', async () => {
    const stale = { id: 'r9', state: 'open', duration: 600, chunks: 600, gaps: [], rate: 48000, channels: 1, start: 3 }
    await mountWith(RecordingRecovery, {
      [`GET ${BASE}`]: { recordings: [stale] },
      [`POST ${BASE}/r9/finish`]: () => ({
        ...stale,
        state: 'finished',
        op: {},
        recover_op: { type: 'audio_record_add', src: 'recordings/r9/gravacao.wav', start: 3, duration: 600 },
      }),
    })
    await flushPromises()
    expect(wrapper?.get('[data-recording-recovery]').text()).toContain('600,0 s salvos')
    await wrapper?.get('[data-recovery-recover]').trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/edit').at(-1)?.body).toMatchObject({
      op: { type: 'audio_record_add', duration: 600 },
    })
  })

  it('lista os takes da voz e troca o que toca num passo do desfazer', async () => {
    await mountWith(VoiceTakes)
    const panel = useAudioPanelStore()
    const view = voiceView()
    const voice = view.tracks.find((track) => track.id === 'VO')?.items[0]
    if (voice) {
      voice.extra = { takes: [{ index: 0, label: 'Original', src: 'voz.wav' }], take_label: 'Take 2' }
    }
    opened.fetch.set('POST /api/projects/demo/timeline', () => view)
    opened.fetch.set('POST /api/projects/demo/edit', () => ({ spec: voiceSpec(), timeline: view }))
    await opened.store.refreshView()
    panel.openFor(opened.store.findItem('VO-0'))
    await flushPromises()
    expect(wrapper?.get('[data-take-current]').text()).toContain('Take 2')
    await wrapper?.get('[data-take-swap]').trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/edit').at(-1)?.body).toMatchObject({
      op: { type: 'voiceover_take_set', target: 'audio.voiceover.0', take: 0 },
    })
  })

  it('sem takes a lista não aparece', async () => {
    await mountWith(VoiceTakes)
    useAudioPanelStore().openFor(opened.store.findItem('VO-0'))
    await flushPromises()
    expect(wrapper?.find('[data-voice-takes]').exists()).toBe(false)
  })
})
