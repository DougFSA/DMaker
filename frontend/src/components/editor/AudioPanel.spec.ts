import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { audioEffectCatalog } from '@/test/audioEffectsFixtures'
import { audioWave, FakeWebAudio, voiceSpec, voiceView } from '@/test/audioPanelFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useKeymapStore } from '@/stores/keymap'
import { defineComponent, h } from 'vue'
import AudioPanel from './AudioPanel.vue'
import { AUDIO_TOOLBAR_EXTRAS, AUDIO_VIEWS } from './audio/views'

const WAVE = 'POST /api/projects/demo/audio-panel/wave'
const WINDOW = 'POST /api/projects/demo/audio-panel/window'
const PREVIEW = 'POST /api/projects/demo/audio-panel/preview'

let wrapper: VueWrapper | null = null
let opened: OpenedEditor

/** Um contexto 2D que aceita qualquer chamada: o desenho não é o que se confere aqui. */
const canvasContext = new Proxy({}, { get: () => () => undefined, set: () => true })

beforeEach(() => {
  window.localStorage.clear()
  FakeWebAudio.instances = []
  vi.stubGlobal('AudioContext', FakeWebAudio)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => canvasContext as never)
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(
    () => ({ left: 0, top: 0, right: 1000, bottom: 300, width: 1000, height: 300, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect,
  )
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

async function mountPanel(routes: Record<string, unknown> = {}) {
  const view = voiceView()
  opened = await openEditor(voiceSpec(), {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/edit': () => ({ spec: voiceSpec(), timeline: view }),
    'GET /api/audio-effects': audioEffectCatalog(),
    [WAVE]: () => audioWave(),
    [WINDOW]: () => new Response(new ArrayBuffer(400), { headers: { 'X-Window-Seconds': '4' } }),
    [PREVIEW]: () => new Response(new ArrayBuffer(400), { headers: { 'X-Window-Seconds': '4', 'X-Preview-Exact': '1', 'X-Preview-Note': '' } }),
    ...routes,
  })
  const panel = useAudioPanelStore()
  panel.openFor(opened.store.findItem('VO-0'))
  wrapper = await mountEditorPart(AudioPanel, opened, {}, true)
  await flushPromises()
  return { panel, wrapper }
}

const edits = () => opened.fetch.to('POST /api/projects/demo/edit').map((call) => (call.body as { op: Record<string, unknown> }).op)
const button = (selector: string) => wrapper?.get(selector)

describe('abrir e mostrar a onda', () => {
  it('pede a onda do alvo com a spec da tela e mostra o título e os dados do áudio', async () => {
    await mountPanel()
    const calls = opened.fetch.to(WAVE)
    expect(calls.length).toBeGreaterThan(0)
    const body = calls[0]?.body as Record<string, unknown>
    expect(body.target).toBe('audio.voiceover.0')
    expect(body.columns).toBe(1000)
    expect((body.spec as { audio: unknown }).audio).toBeDefined()
    expect(wrapper?.get('[data-audio-title]').text()).toContain('Voz gravada 1')
    expect(wrapper?.get('.audio__meta').text()).toBe('12,00 s · 48 kHz · estéreo')
    expect(wrapper?.find('[data-audio-error]').exists()).toBe(false)
  })

  it('mostra o andamento enquanto a onda é construída e consulta de novo até ficar pronta', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let state: 'building' | 'ready' = 'building'
    await mountPanel({
      [WAVE]: () => (state === 'building' ? audioWave({ state: 'building', percent: 40, stage: 'Calculando a onda', ready_until: 4 }) : audioWave()),
    })
    expect(wrapper?.get('[data-audio-building]').text()).toContain('Calculando a onda: 40%')
    const before = opened.fetch.to(WAVE).length
    state = 'ready'
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(opened.fetch.to(WAVE).length).toBeGreaterThan(before)
    expect(wrapper?.find('[data-audio-building]').exists()).toBe(false)
  })

  it('mostra o motivo quando o servidor não consegue ler o áudio', async () => {
    await mountPanel({ [WAVE]: () => ({ status: 400, body: { detail: 'audio.voiceover.0: arquivo não encontrado: voz.wav' } }) })
    expect(wrapper?.get('[data-audio-error]').text()).toContain('arquivo não encontrado')
  })

  it('o botão volta à linha do tempo', async () => {
    const { panel } = await mountPanel()
    await button('[data-audio-back]')?.trigger('click')
    expect(panel.open).toBe(false)
  })
})

describe('os pontos de extensão (espectrograma e gravação)', () => {
  it('uma vista nova entra por AUDIO_VIEWS, ganha o seletor e recebe a mesma resposta da onda', async () => {
    const received: unknown[] = []
    const Spectrogram = defineComponent({
      props: { data: { type: Object, default: null } },
      emits: ['size', 'scrub', 'scrub-end'],
      setup(props) {
        received.push(props.data)
        return () => h('div', { 'data-fake-spectrogram': '' }, 'espectrograma')
      },
    })
    AUDIO_VIEWS.push({ id: 'vista-falsa', title: 'Vista falsa', component: Spectrogram })
    try {
      const { panel } = await mountPanel()
      expect(wrapper?.find('[data-audio-views]').exists()).toBe(true)
      expect(wrapper?.find('[data-wave-area]').exists()).toBe(true)
      panel.viewId = 'vista-falsa'
      await flushPromises()
      expect(wrapper?.find('[data-fake-spectrogram]').exists()).toBe(true)
      expect(wrapper?.find('[data-wave-area]').exists()).toBe(false)
      // a vista nova recebe a resposta que a onda recebe, e o resto (janela, seleção) está no mesmo store
      await vi.waitFor(() => expect(received.some((value) => (value as { target?: string } | null)?.target === 'audio.voiceover.0')).toBe(true))
      // uma escolha que deixou de existir volta à onda
      panel.viewId = 'nao-existe'
      await flushPromises()
      expect(wrapper?.find('[data-wave-area]').exists()).toBe(true)
    } finally {
      AUDIO_VIEWS.pop()
    }
  })

  it('um comando novo entra por AUDIO_TOOLBAR_EXTRAS, no fim da barra de reprodução', async () => {
    const Record = defineComponent({ setup: () => () => h('button', { 'data-fake-record': '' }, 'Gravar') })
    AUDIO_TOOLBAR_EXTRAS.push({ id: 'fake-extra', component: Record })
    try {
      await mountPanel()
      expect(wrapper?.find('[data-fake-record]').exists()).toBe(true)
    } finally {
      AUDIO_TOOLBAR_EXTRAS.pop()
    }
  })
})

describe('a seleção e os comandos', () => {
  it('mostra a seleção em tempo e em amostras e habilita os comandos que dependem dela', async () => {
    const { panel } = await mountPanel()
    expect(wrapper?.get('[data-audio-silence]').attributes('disabled')).toBeDefined()
    panel.select(2, 4)
    await flushPromises()
    expect(wrapper?.get('[data-audio-selection]').text()).toBe('2,000 s a 4,000 s (2,000 s, 96.000 amostras)')
    expect(wrapper?.get('[data-audio-silence]').attributes('disabled')).toBeUndefined()
  })

  it('Silenciar e Cortar mandam a operação com o intervalo em tempo do projeto', async () => {
    const { panel } = await mountPanel()
    panel.select(2, 4)
    await flushPromises()
    await button('[data-audio-silence]')?.trigger('click')
    await flushPromises()
    expect(edits().at(-1)).toEqual({ type: 'audio_silence', target: 'audio.voiceover.0', start: 2.5, end: 4.5 })
    await button('[data-audio-cut]')?.trigger('click')
    await flushPromises()
    expect(edits().at(-1)).toEqual({ type: 'audio_cut', target: 'audio.voiceover.0', start: 2.5, end: 4.5 })
  })

  it('os atalhos do painel ficam registrados enquanto ele existe, e saem com ele', async () => {
    await mountPanel()
    const keymap = useKeymapStore()
    for (const id of ['audio_play', 'audio_label', 'audio_silence', 'audio_split', 'audio_undo'] as const) {
      expect(keymap.registered.has(id), id).toBe(true)
    }
    const panel = useAudioPanelStore()
    panel.select(1, 2)
    keymap.registered.get('audio_label')?.(new KeyboardEvent('keydown'))
    await flushPromises()
    expect(edits().at(-1)).toEqual({ type: 'marker_add', start: 1.5, end: 2.5, text: '' })
    keymap.registered.get('audio_undo')?.(new KeyboardEvent('keydown'))
    wrapper?.unmount()
    wrapper = null
    expect(keymap.registered.has('audio_silence')).toBe(false)
  })

  it('o Espaço do painel toca a seleção: o motor agenda exatamente o trecho', async () => {
    const { panel } = await mountPanel()
    const keymap = useKeymapStore()
    panel.select(2, 5)
    keymap.registered.get('audio_play')?.(new KeyboardEvent('keydown', { key: ' ' }))
    await flushPromises()
    await vi.waitFor(() => expect(FakeWebAudio.instances[0]?.sources.length).toBeGreaterThan(0))
    const call = FakeWebAudio.instances[0]?.sources[0]?.started[0]
    expect(call?.offset).toBe(2)
    expect(call?.duration).toBe(3)
    expect(panel.playing).toBe(true)
    // o servidor foi pedido o bloco de 8 s que contém a seleção
    expect((opened.fetch.to(WINDOW)[0]?.body as { start: number; end: number }).start).toBe(0)
    keymap.registered.get('audio_stop')?.(new KeyboardEvent('keydown'))
    expect(panel.playing).toBe(false)
  })
})

describe('a janela do efeito', () => {
  it('monta os parâmetros pelo catálogo, toca a prévia e aplica com o intervalo da seleção', async () => {
    const { panel } = await mountPanel()
    panel.select(2, 5)
    await flushPromises()
    await button('[data-audio-effect]')?.trigger('click')
    await flushPromises()
    const dialog = document.body.querySelector('[data-audio-effect-dialog]')
    expect(dialog).not.toBeNull()
    expect(dialog?.textContent).toContain('Vale para a seleção')
    expect(dialog?.querySelector('[data-effect-param="peak_db"]')).not.toBeNull() // Normalizar é o efeito inicial

    ;(document.body.querySelector('[data-effect-preview]') as HTMLElement).click()
    await flushPromises()
    await vi.waitFor(() => expect(opened.fetch.to(PREVIEW)).toHaveLength(1))
    const body = opened.fetch.to(PREVIEW)[0]?.body as { effect: Record<string, unknown>; start: number; end: number; target: string }
    expect(body.target).toBe('audio.voiceover.0')
    expect(body.effect).toMatchObject({ type: 'normalize', peak_db: -1, start: 2, end: 5 })
    expect([body.start, body.end]).toEqual([2, 5])
    // o trecho sem o efeito também foi pedido, para o antes e depois
    expect(opened.fetch.to(WINDOW).length).toBeGreaterThan(0)

    ;(document.body.querySelector('[data-effect-apply]') as HTMLElement).click()
    await flushPromises()
    expect(edits().at(-1)).toEqual({
      type: 'audio_effect',
      action: 'add',
      target: 'audio.voiceover.0',
      effect: { type: 'normalize', peak_db: -1, remove_dc: true, stereo_independent: false, start: 2, end: 5 },
    })
  })

  it('com uma seleção espectral oferece o Apagar espectral, com a faixa preenchida, e aplica com o retângulo', async () => {
    const { panel } = await mountPanel()
    panel.selectSpectral(2, 5, 2800, 3200)
    await button('[data-audio-effect]')?.trigger('click')
    await vi.waitFor(() => expect(document.body.querySelector('[data-effect-param="low_hz"]')).not.toBeNull())
    const form = document.body.querySelector('[data-audio-effect-form]')
    expect((form?.querySelector('[data-effect-param="low_hz"] input') as HTMLInputElement).value).toBe('2800')
    expect((form?.querySelector('[data-effect-param="high_hz"] input') as HTMLInputElement).value).toBe('3200')
    expect(document.body.querySelector('[data-effect-range]')?.textContent).toContain('2,8 kHz a 3,2 kHz')
    ;(document.body.querySelector('[data-effect-apply]') as HTMLElement).click()
    await flushPromises()
    expect(edits().at(-1)).toEqual({
      type: 'audio_effect',
      action: 'add',
      target: 'audio.voiceover.0',
      effect: { type: 'spectral_delete', low_hz: 2800, high_hz: 3200, start: 2, end: 5 },
    })
  })

  it('avisa quando a prévia não é igual ao render', async () => {
    const { panel } = await mountPanel({
      [PREVIEW]: () =>
        new Response(new ArrayBuffer(400), {
          headers: { 'X-Window-Seconds': '4', 'X-Preview-Exact': '0', 'X-Preview-Note': encodeURIComponent('Prévia aproximada: marque um trecho.') },
        }),
    })
    panel.select(1, 3)
    await button('[data-audio-effect]')?.trigger('click')
    await vi.waitFor(() => expect(document.body.querySelector('[data-effect-param="peak_db"]')).not.toBeNull())
    ;(document.body.querySelector('[data-effect-preview]') as HTMLElement).click()
    await vi.waitFor(() => expect(document.body.querySelector('[data-effect-note]')?.textContent).toContain('Prévia aproximada'))
  })

  it('mostra o motivo da recusa da prévia', async () => {
    const { panel } = await mountPanel({ [PREVIEW]: () => ({ status: 400, body: { detail: 'o efeito pede um intervalo' } }) })
    panel.select(1, 3)
    await button('[data-audio-effect]')?.trigger('click')
    await vi.waitFor(() => expect(document.body.querySelector('[data-effect-param="peak_db"]')).not.toBeNull())
    ;(document.body.querySelector('[data-effect-preview]') as HTMLElement).click()
    await vi.waitFor(() => expect(document.body.querySelector('[data-effect-problem]')?.textContent).toContain('o efeito pede um intervalo'))
  })
})

describe('o espectrograma no painel', () => {
  const SPECTROGRAM = 'POST /api/projects/demo/audio-panel/spectrogram'
  const png = () => new Response(new Uint8Array([137, 80, 78, 71]), { headers: { 'X-Spectrogram-Start': '0', 'X-Spectrogram-End': '12', 'X-Spectrogram-Columns': '64', 'X-Spectrogram-Rows': '64', 'X-Spectrogram-Min-Hz': '0', 'X-Spectrogram-Max-Hz': '24000' } })

  it('oferece a onda, o espectrograma e a multivista, e a ferramenta acompanha a vista', async () => {
    const { panel } = await mountPanel({ [SPECTROGRAM]: png })
    expect(AUDIO_VIEWS.map((entry) => entry.id)).toEqual(['wave', 'spectrogram', 'both'])
    expect(panel.tool).toBe('select')
    panel.viewId = 'spectrogram'
    await flushPromises()
    expect(wrapper?.find('[data-audio-spectrogram]').exists()).toBe(true)
    expect(wrapper?.find('[data-wave-area]').exists()).toBe(false)
    expect(panel.tool).toBe('spectral')
    panel.viewId = 'both'
    await flushPromises()
    expect(wrapper?.find('[data-wave-area]').exists()).toBe(true)
    expect(wrapper?.find('[data-audio-spectrogram]').exists()).toBe(true)
    panel.viewId = 'wave'
    await flushPromises()
    expect(panel.tool).toBe('select')
  })

  it('mostra a faixa de frequência e o centro da seleção espectral', async () => {
    const { panel } = await mountPanel({ [SPECTROGRAM]: png })
    panel.selectSpectral(2, 4, 2800, 3200)
    await flushPromises()
    const text = wrapper?.get('[data-audio-selection]').text() ?? ''
    expect(text).toContain('2,8 kHz a 3,2 kHz')
    expect(text).toContain('centro em 2,99 kHz')
  })

  it('o marcador de uma seleção espectral leva low_hz e high_hz, e o efeito espectral nasce da janela com a faixa preenchida', async () => {
    const { panel } = await mountPanel({ [SPECTROGRAM]: png })
    panel.selectSpectral(2, 4, 2800, 3200)
    await panel.label()
    await panel.applyEffect('spectral_delete', {})
    const ops = edits()
    expect(ops[0]).toMatchObject({ type: 'marker_add', start: 2.5, end: 4.5, low_hz: 2800, high_hz: 3200 })
    expect(ops[1]).toMatchObject({ type: 'audio_effect', action: 'add', target: 'audio.voiceover.0', effect: { type: 'spectral_delete', start: 2, end: 4, low_hz: 2800, high_hz: 3200 } })
  })
})
