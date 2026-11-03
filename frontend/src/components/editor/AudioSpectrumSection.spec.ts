import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineView } from '@/api'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import { reply, type RoutedCall } from '@/test/routedFetch'
import { spectrumAnalysis } from '@/test/spectrumFixtures'
import AudioSpectrumSection from './AudioSpectrumSection.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
beforeEach(() => window.localStorage.clear())

function spectrumSpec(): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    sources: {},
    timeline: [{ type: 'clip', src: 'a.mp4', start: 0, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 }],
    overlays: [],
    audio: {
      voice_gain: 1,
      normalize: 'two-pass',
      mute_clips: false,
      music: { src: 'musica.mp3', volume: 0.18, loop: true },
      voiceover: [{ src: 'voz.wav', start: 0, offset: 0, volume: 1 }],
    },
  }
}

function spectrumView(): TimelineView {
  const item = (id: string, index: number, kind: string) => timelineItem(index, { id, kind, label: `${kind}.${index}` })
  return {
    total: 9,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [
      timelineTrack('V1', [item('V1-0', 0, 'clip')]),
      timelineTrack('VO', [item('VO-0', 0, 'voiceover')], { kind: 'audio' }),
      timelineTrack('MUS', [item('MUS-0', 0, 'music')], { kind: 'audio' }),
    ],
    sources: {},
    warnings: [],
  }
}

const ANALYSIS_ROUTE = 'POST /api/projects/demo/audio-analysis'

async function mountSpectrum(
  analysis: unknown = () => spectrumAnalysis(),
): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const opened = await openEditor(spectrumSpec(), {
    'POST /api/projects/demo/timeline': () => spectrumView(),
    [ANALYSIS_ROUTE]: analysis,
  })
  const wrapper = await mountEditorPart(AudioSpectrumSection, opened, {}, true)
  return { opened, wrapper }
}

const dialog = () => document.body.querySelector('[role="dialog"]')
const inDialog = (selector: string) => document.body.querySelector(selector)

async function openChart(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('[data-spectrum-open]').trigger('click')
  await flushPromises()
}

describe('AudioSpectrumSection', () => {
  it('sem seleção fala da saída final e analisa `output`', async () => {
    const { opened, wrapper } = await mountSpectrum()
    expect(wrapper.find('[data-spectrum-target]').text()).toBe('Master (mistura inteira)')
    expect(wrapper.text()).toContain('saída final já renderizada')
    await openChart(wrapper)
    const call = opened.fetch.to(ANALYSIS_ROUTE)[0]!
    expect(call.body).toMatchObject({
      analyzer: 'spectrum',
      target: 'output',
      params: { algorithm: 'spectrum', window: 'hann', size: 4096, axis: 'log' },
    })
  })

  it('cada item selecionado analisa o seu próprio alvo, como o bloco de efeitos o entende', async () => {
    const { opened, wrapper } = await mountSpectrum()
    const targets: Array<[string, string]> = [
      ['VO-0', 'audio.voiceover.0'],
      ['MUS-0', 'audio.music'],
      ['V1-0', 'timeline.0'],
    ]
    for (const [id, target] of targets) {
      opened.store.select([id])
      await flushPromises()
      await openChart(wrapper)
      expect((opened.fetch.calls.filter((call) => call.path.endsWith('/audio-analysis')).at(-1) as RoutedCall).body).toMatchObject({
        target,
      })
      document.body.querySelector<HTMLElement>('.dialog__close')?.click()
      await flushPromises()
    }
  })

  it('mostra o gráfico com o cursor no pico, o resumo e os maiores picos', async () => {
    const { wrapper } = await mountSpectrum()
    await openChart(wrapper)
    expect(dialog()).not.toBeNull()
    expect(inDialog('[data-spectrum-plot]')).not.toBeNull()
    expect(inDialog('[data-spectrum-readout]')?.textContent).toBe('1 kHz · Si5 +21 cents · -6,0 dB')
    expect(inDialog('[data-spectrum-summary]')?.textContent).toContain('Pico do espectro')
    expect(inDialog('[data-spectrum-peaks]')?.textContent).toContain('2 kHz')
  })

  it('mudar um valor refaz a análise com ele, e só a resposta do último pedido vale', async () => {
    let calls = 0
    const { opened, wrapper } = await mountSpectrum(() => {
      calls += 1
      return spectrumAnalysis({ summary: `Análise ${calls}` })
    })
    await openChart(wrapper)
    const size = inDialog('select[id]') as HTMLSelectElement
    const selects = [...document.body.querySelectorAll<HTMLSelectElement>('.dialog select')]
    expect(selects).toHaveLength(4)
    const fft = selects.find((select) => [...select.options].some((option) => option.value === '65536'))!
    fft.value = '8192'
    fft.dispatchEvent(new Event('change'))
    await flushPromises()
    expect(size).not.toBeNull()
    const sent = opened.fetch.to(ANALYSIS_ROUTE).map((call) => (call.body as { params: { size: number } }).params.size)
    expect(sent).toEqual([4096, 8192])
    expect(inDialog('[data-spectrum-summary]')?.textContent).toBe('Análise 2')
  })

  it('a recusa do servidor aparece no lugar do gráfico, com o motivo', async () => {
    const { wrapper } = await mountSpectrum(() =>
      reply(400, { detail: 'o projeto "demo" não tem saída final renderizada: renderize antes, ou informe um arquivo' }),
    )
    await openChart(wrapper)
    expect(inDialog('[data-spectrum-error]')?.textContent).toContain('não tem saída final renderizada')
    expect(inDialog('[data-spectrum-plot]')).toBeNull()
  })
})
