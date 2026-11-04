import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { audioWave, voiceSpec, voiceView } from '@/test/audioPanelFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { useAudioPanelStore } from '@/stores/audioPanel'
import AudioWaveView from './AudioWaveView.vue'

let wrapper: VueWrapper | null = null
let opened: OpenedEditor

const canvasContext = new Proxy({}, { get: () => () => undefined, set: () => true })
const edits = () => opened.fetch.to('POST /api/projects/demo/edit').map((call) => (call.body as { op: Record<string, unknown> }).op)

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
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

async function mountWave(spec: Record<string, unknown> = voiceSpec(), tool: 'select' | 'envelope' | 'zoom' | 'multi' = 'select') {
  const view = voiceView()
  opened = await openEditor(spec, {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/edit': () => ({ spec, timeline: view }),
  })
  const panel = useAudioPanelStore()
  panel.openFor(opened.store.findItem('VO-0'))
  panel.setOverview(audioWave())
  panel.setTool(tool)
  wrapper = await mountEditorPart(AudioWaveView, opened, { data: audioWave() }, true)
  return { panel, area: wrapper.get('[data-wave-area]').element as HTMLElement, wave: wrapper }
}

const mouse = (target: EventTarget, type: string, x: number, extra: MouseEventInit = {}) =>
  target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: 100, button: 0, ...extra }))

describe('selecionar com o mouse', () => {
  it('arrastar seleciona o trecho entre os dois pontos e põe o cursor no começo', async () => {
    const { panel, area } = await mountWave()
    mouse(area, 'mousedown', 250) // 3 s
    mouse(document, 'mousemove', 400)
    mouse(document, 'mousemove', 500) // 6 s
    mouse(document, 'mouseup', 500)
    expect(panel.selection?.start).toBeCloseTo(3, 2)
    expect(panel.selection?.end).toBeCloseTo(6, 2)
    expect(panel.cursor).toBeCloseTo(3, 2)
    expect(opened.store.dirty).toBe(false) // selecionar não muda a spec
  })

  it('arrastar para a esquerda também funciona, e a seleção cai em amostras inteiras', async () => {
    const { panel, area } = await mountWave()
    mouse(area, 'mousedown', 600)
    mouse(document, 'mousemove', 400)
    mouse(document, 'mouseup', 400)
    expect(panel.selection?.start).toBeCloseTo(4.8, 2)
    expect(panel.selection?.end).toBeCloseTo(7.2, 2)
    const samples = (panel.selection?.start ?? 0) * 48000
    expect(samples).toBeCloseTo(Math.round(samples), 6)
  })

  it('um clique sem arrastar só põe o cursor e tira a seleção', async () => {
    const { panel, area } = await mountWave()
    panel.select(2, 4)
    mouse(area, 'mousedown', 500)
    mouse(document, 'mouseup', 500)
    expect(panel.selection).toBeNull()
    expect(panel.cursor).toBeCloseTo(6, 2)
  })

  it('Shift estende a seleção movendo a ponta mais perto', async () => {
    const { panel, area } = await mountWave()
    panel.select(2, 4)
    mouse(area, 'mousedown', 500, { shiftKey: true }) // 6 s
    mouse(document, 'mouseup', 500)
    expect(panel.selection?.start).toBeCloseTo(2, 2)
    expect(panel.selection?.end).toBeCloseTo(6, 2)
  })

  it('puxar a borda da seleção a muda; o duplo clique seleciona tudo', async () => {
    const { panel, area } = await mountWave()
    panel.select(2, 4) // de 167 a 333 px
    mouse(area, 'mousedown', 333)
    mouse(document, 'mousemove', 416) // 5 s
    mouse(document, 'mouseup', 416)
    expect(panel.selection?.start).toBeCloseTo(2, 2)
    expect(panel.selection?.end).toBeCloseTo(5, 1)
    area.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, clientX: 500, clientY: 100 }))
    expect(panel.selection).toEqual({ start: 0, end: 12 })
  })
})

describe('zoom e rolagem', () => {
  it('Ctrl com a roda aproxima em volta do instante sob o ponteiro', async () => {
    const { panel, wave } = await mountWave()
    const root = wave.get('[data-audio-wave]').element
    root.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: 500, deltaY: -100, ctrlKey: true }))
    expect(panel.view.end - panel.view.start).toBeCloseTo(9.6, 5)
    // o instante de 6 s continua a meio da tela
    expect((6 - panel.view.start) / (panel.view.end - panel.view.start)).toBeCloseTo(0.5, 5)
  })

  it('a roda sozinha anda a janela sem mudar a largura', async () => {
    const { panel, wave } = await mountWave()
    panel.setView({ start: 0, end: 4 })
    wave.get('[data-audio-wave]').element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: 500, deltaY: 100 }))
    expect(panel.view.end - panel.view.start).toBeCloseTo(4, 5)
    expect(panel.view.start).toBeGreaterThan(0)
  })

  it('a ferramenta de zoom aproxima no clique, afasta com Shift e aproxima na região arrastada', async () => {
    const { panel, area } = await mountWave(voiceSpec(), 'zoom')
    mouse(area, 'mousedown', 500)
    mouse(document, 'mouseup', 500)
    expect(panel.view.end - panel.view.start).toBeCloseTo(6, 5)
    mouse(area, 'mousedown', 500, { shiftKey: true })
    expect(panel.view.end - panel.view.start).toBeCloseTo(12, 5)
    mouse(area, 'mousedown', 250) // 3 s
    mouse(document, 'mousemove', 500) // 6 s
    mouse(document, 'mouseup', 500)
    expect(panel.view.start).toBeCloseTo(3, 2)
    expect(panel.view.end).toBeCloseTo(6, 2)
  })
})

describe('a régua e o scrub', () => {
  it('apertar na régua leva o cursor e começa o scrub; arrastar o acompanha; soltar acaba', async () => {
    const { panel, wave } = await mountWave()
    const ruler = wave.get('[data-wave-ruler]').element
    mouse(ruler, 'mousedown', 250)
    mouse(document, 'mousemove', 500)
    mouse(document, 'mouseup', 500)
    const scrubs = wave.emitted('scrub') as number[][]
    expect(scrubs.map(([time]) => Math.round((time as number) * 10) / 10)).toEqual([3, 6])
    expect(wave.emitted('scrub-end')).toHaveLength(1)
    expect(panel.cursor).toBeCloseTo(6, 1)
  })
})

describe('o envelope sobre a onda', () => {
  it('um clique da ferramenta de envelope cria o efeito pela operação de envelope', async () => {
    const { area } = await mountWave(voiceSpec(), 'envelope')
    mouse(area, 'mousedown', 250) // 3 s, a 100 de 300 px de altura
    mouse(document, 'mouseup', 250)
    await flushPromises()
    const op = edits().at(-1) as { type: string; target: string; points: Array<{ at: number; db: number }> }
    expect(op.type).toBe('audio_envelope')
    expect(op.target).toBe('audio.voiceover.0')
    expect(op.points).toHaveLength(1)
    expect(op.points[0]?.at).toBeCloseTo(3.5, 2) // 3 s do eixo + 0,5 s do começo do item
    // 100 px de 300 é um terço da altura: 12 dB - 24 dB = -12 dB
    expect(op.points[0]?.db).toBeCloseTo(-12, 0)
  })

  it('arrastar um ponto existente troca os pontos do efeito e grava ao soltar', async () => {
    const spec = voiceSpec({
      audio: {
        voice_gain: 1,
        normalize: 'off',
        mute_clips: false,
        voiceover: [{ src: 'voz.wav', start: 0.5, offset: 0, volume: 1, effects: [{ type: 'envelope', points: [{ at: 2, db: 0 }, { at: 8, db: -6 }] }] }],
      },
    })
    const { wave, area } = await mountWave(spec, 'envelope')
    await flushPromises()
    expect(wave.findAll('[data-envelope-point]')).toHaveLength(2)
    // o ponto de 2 s e 0 dB: x = 167, y = (12 - 0) / 72 * 300 = 50
    mouse(area, 'mousedown', 167, { clientY: 50 })
    mouse(document, 'mousemove', 250, { clientY: 150 })
    mouse(document, 'mouseup', 250, { clientY: 150 })
    await flushPromises()
    const op = edits().at(-1) as { type: string; action: string; index: number; params: { points: Array<{ at: number; db: number }> } }
    expect(op).toMatchObject({ type: 'audio_effect', action: 'set', target: 'audio.voiceover.0', index: 0 })
    expect(op.params.points).toHaveLength(2)
    expect(op.params.points[0]?.at).toBeCloseTo(3, 1)
    expect(op.params.points[1]).toEqual({ at: 8, db: -6 })
  })

  it('Alt com o clique tira o ponto', async () => {
    const spec = voiceSpec({
      audio: {
        voice_gain: 1,
        normalize: 'off',
        mute_clips: false,
        voiceover: [{ src: 'voz.wav', start: 0.5, offset: 0, volume: 1, effects: [{ type: 'envelope', points: [{ at: 2, db: 0 }, { at: 8, db: -6 }] }] }],
      },
    })
    const { area } = await mountWave(spec, 'envelope')
    mouse(area, 'mousedown', 167, { clientY: 50, altKey: true })
    await flushPromises()
    const op = edits().at(-1) as { params: { points: unknown[] } }
    expect(op.params.points).toEqual([{ at: 8, db: -6 }])
  })
})

describe('a multiferramenta', () => {
  it('seleciona onde não há envelope nem zoom de amostra', async () => {
    const { panel, area } = await mountWave(voiceSpec(), 'multi')
    mouse(area, 'mousedown', 250)
    mouse(document, 'mousemove', 500)
    mouse(document, 'mouseup', 500)
    expect(panel.selection?.start).toBeCloseTo(3, 2)
  })
})
