import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { audioWave, voiceSpec, voiceView } from '@/test/audioPanelFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { useAudioPanelStore } from '@/stores/audioPanel'
import SpectrogramView from './SpectrogramView.vue'

const SPECTROGRAM = 'POST /api/projects/demo/audio-panel/spectrogram'

let wrapper: VueWrapper | null = null
let opened: OpenedEditor

const canvasContext = new Proxy({}, { get: () => () => undefined, set: () => true })

beforeEach(() => {
  window.localStorage.clear()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => canvasContext as never)
  // a área tem 1000 px de largura e 300 de altura: 12 s ocupam 1000 px (83,33 px por segundo)
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

function png(headers: Record<string, string> = {}): Response {
  return new Response(new Uint8Array([137, 80, 78, 71]), {
    headers: {
      'Content-Type': 'image/png',
      'X-Spectrogram-Start': '0',
      'X-Spectrogram-End': '12',
      'X-Spectrogram-Columns': '1024',
      'X-Spectrogram-Rows': '256',
      'X-Spectrogram-Min-Hz': '0',
      'X-Spectrogram-Max-Hz': '24000',
      'X-Spectrogram-Cached': '0',
      ...headers,
    },
  })
}

async function mountSpectrogram(routes: Record<string, unknown> = {}) {
  const view = voiceView()
  opened = await openEditor(voiceSpec(), {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/edit': () => ({ spec: voiceSpec(), timeline: view }),
    [SPECTROGRAM]: () => png(),
    ...routes,
  })
  const panel = useAudioPanelStore()
  panel.openFor(opened.store.findItem('VO-0'))
  panel.setOverview(audioWave())
  wrapper = await mountEditorPart(SpectrogramView, opened, { data: audioWave() }, true)
  return { panel, area: wrapper.get('[data-spectrogram-area]').element as HTMLElement }
}

const mouse = (target: EventTarget, type: string, x: number, y: number, extra: MouseEventInit = {}) =>
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, ...extra }))

describe('a imagem do espectrograma', () => {
  it('pede o trecho que está na tela com os ajustes do store', async () => {
    vi.useFakeTimers()
    const { panel } = await mountSpectrogram()
    panel.setSpectrogram({ scale: 'mel', gainDb: 10, maxHz: 8000 })
    await vi.advanceTimersByTimeAsync(400)
    const calls = opened.fetch.to(SPECTROGRAM)
    expect(calls.length).toBeGreaterThan(0)
    const body = calls[calls.length - 1]?.body as Record<string, unknown>
    expect(body).toMatchObject({ target: 'audio.voiceover.0', start: 0, end: 12, scale: 'mel', gain_db: 10, max_hz: 8000, window: 'hann', window_size: 2048 })
    expect(body.columns).toBeGreaterThanOrEqual(64)
    expect(body.rows).toBe(300) // uma linha por pixel de altura, dentro de 64 a 512
  })

  it('trocar só as cores não pede a imagem de novo', async () => {
    vi.useFakeTimers()
    const { panel } = await mountSpectrogram()
    await vi.advanceTimersByTimeAsync(400)
    const before = opened.fetch.to(SPECTROGRAM).length
    panel.setSpectrogram({ scheme: 'flame' })
    await vi.advanceTimersByTimeAsync(400)
    expect(opened.fetch.to(SPECTROGRAM)).toHaveLength(before)
    panel.setSpectrogram({ windowSize: 4096 })
    await vi.advanceTimersByTimeAsync(400)
    expect(opened.fetch.to(SPECTROGRAM).length).toBe(before + 1)
  })

  it('decodifica o PNG com o tamanho do bitmap lido antes do close e pinta com o esquema de cores', async () => {
    vi.useFakeTimers()
    const painted: Array<{ width: number; height: number; first: number[] }> = []
    const methods: Record<string | symbol, unknown> = {
      getImageData: (_x: number, _y: number, width: number, height: number) => ({ data: new Uint8ClampedArray(width * height * 4).fill(255) }),
      putImageData: (image: { width: number; height: number; data: Uint8ClampedArray }) => painted.push({ width: image.width, height: image.height, first: [...image.data.slice(0, 4)] }),
    }
    const context = new Proxy(methods, { get: (target, key) => (key in target ? target[key] : () => undefined), set: () => true })
    vi.mocked(HTMLCanvasElement.prototype.getContext).mockImplementation(() => context as never)
    vi.stubGlobal('ImageData', class { constructor(public data: Uint8ClampedArray, public width: number, public height: number) {} })
    vi.stubGlobal('createImageBitmap', async () => {
      const bitmap = { width: 6, height: 3, close() { this.width = 0; this.height = 0 } }
      return bitmap
    })
    await mountSpectrogram()
    await vi.advanceTimersByTimeAsync(600)
    expect(painted.length).toBeGreaterThan(0)
    expect(painted[0]).toMatchObject({ width: 6, height: 3 })
    expect(painted[0]?.first.slice(3)).toEqual([255]) // opaco, e o cinza 255 vira o claro do esquema de cores
  })

  it('pergunta de novo enquanto os efeitos do item estão sendo aplicados (202)', async () => {
    vi.useFakeTimers()
    let calls = 0
    await mountSpectrogram({
      [SPECTROGRAM]: () => {
        calls += 1
        return calls === 1 ? new Response(null, { status: 202 }) : png()
      },
    })
    await vi.advanceTimersByTimeAsync(2000)
    expect(calls).toBeGreaterThanOrEqual(2)
  })
})

describe('a seleção espectral com o mouse', () => {
  it('arrastar com a ferramenta Espectral marca tempo e frequência sem mudar a spec', async () => {
    const { panel, area } = await mountSpectrogram()
    panel.setTool('spectral')
    // x 250 = 3 s, 500 = 6 s; y 75 = 3/4 da altura = 18 kHz, y 150 = 12 kHz (escala linear de 0 a 24 kHz)
    mouse(area, 'mousedown', 250, 75)
    mouse(document, 'mousemove', 400, 110)
    mouse(document, 'mousemove', 500, 150)
    mouse(document, 'mouseup', 500, 150)
    expect(panel.selection?.start).toBeCloseTo(3, 2)
    expect(panel.selection?.end).toBeCloseTo(6, 2)
    expect(panel.selection?.high_hz).toBeCloseTo(18000, -1)
    expect(panel.selection?.low_hz).toBeCloseTo(12000, -1)
    expect(opened.store.dirty).toBe(false)
  })

  it('as bordas do retângulo se arrastam depois', async () => {
    const { panel, area } = await mountSpectrogram()
    panel.setTool('spectral')
    panel.selectSpectral(3, 6, 12000, 18000)
    await flushPromises()
    mouse(area, 'mousedown', 500, 100) // dentro da altura do retângulo (75 a 150): pega a borda direita (6 s)
    mouse(document, 'mousemove', 583, 100) // 7 s
    mouse(document, 'mouseup', 583, 100)
    expect(panel.selection?.end).toBeCloseTo(7, 1)
    expect(panel.selection?.start).toBeCloseTo(3, 2)
    expect(panel.selection?.low_hz).toBeCloseTo(12000, -1)
  })

  it('com a ferramenta de seleção comum, arrastar marca só o tempo e tira a faixa de frequência', async () => {
    const { panel, area } = await mountSpectrogram()
    panel.setTool('select')
    panel.selectSpectral(3, 6, 12000, 18000)
    mouse(area, 'mousedown', 100, 100)
    mouse(document, 'mousemove', 300, 100)
    mouse(document, 'mouseup', 300, 100)
    expect(panel.selection?.start).toBeCloseTo(1.2, 1)
    expect(panel.selection?.low_hz).toBeUndefined()
    expect(panel.selection?.high_hz).toBeUndefined()
  })

  it('um clique sem arrastar só põe o cursor', async () => {
    const { panel, area } = await mountSpectrogram()
    panel.setTool('spectral')
    panel.selectSpectral(3, 6, 12000, 18000)
    mouse(area, 'mousedown', 800, 20)
    mouse(document, 'mouseup', 800, 20)
    expect(panel.selection).toBeNull()
    expect(panel.cursor).toBeCloseTo(9.6, 1)
  })
})

describe('o popover de ajustes', () => {
  it('abre com os controles e restaura o padrão', async () => {
    await mountSpectrogram()
    expect(wrapper?.find('[data-spectrogram-settings]').exists()).toBe(false)
    await wrapper?.get('[data-spectrogram-settings-toggle]').trigger('click')
    for (const field of ['scale', 'scheme', 'min', 'max', 'window', 'size', 'gain', 'range']) {
      expect(wrapper?.find(`[data-spectrogram-${field}]`).exists(), field).toBe(true)
    }
    const panel = useAudioPanelStore()
    panel.setSpectrogram({ scale: 'bark', rangeDb: 60 })
    await wrapper?.get('[data-spectrogram-reset]').trigger('click')
    expect(panel.spectrogram.scale).toBe('linear')
    expect(panel.spectrogram.rangeDb).toBe(80)
  })
})
