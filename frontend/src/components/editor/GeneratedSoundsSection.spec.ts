import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineView } from '@/api'
import { audioGeneratorCatalog } from '@/test/audioGeneratorsFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import GeneratedSoundsSection from './GeneratedSoundsSection.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
beforeEach(() => window.localStorage.clear())

function soundsSpec(generated?: unknown[]): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    sources: {},
    timeline: [{ type: 'clip', src: 'a.mp4', start: 0, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 }],
    overlays: [],
    audio: { voice_gain: 1, normalize: 'two-pass', mute_clips: false, ...(generated ? { generated } : {}) },
  }
}

const TONE = { generator: 'tone', params: { frequency_hz: 1000 }, start: 4, duration: 0.5 }

function viewWithSfx(): TimelineView {
  return {
    total: 9,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [
      timelineTrack('V1', [timelineItem(0, { id: 'V1-0', kind: 'clip' })]),
      timelineTrack('SFX', [timelineItem(1, { id: 'SFX-1', kind: 'generated', label: 'Tom 880 Hz' })], { kind: 'audio' }),
    ],
    sources: {},
    warnings: [],
  }
}

async function mountSounds(spec = soundsSpec(), routes: Record<string, unknown> = {}): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const opened = await openEditor(spec, { 'GET /api/audio-generators': audioGeneratorCatalog(), 'POST /api/projects/demo/timeline': () => viewWithSfx(), ...routes })
  const wrapper = await mountEditorPart(GeneratedSoundsSection, opened, {}, true)
  await flushPromises()
  return { opened, wrapper }
}

const cards = (wrapper: VueWrapper) => wrapper.findAll('[data-generated-sound]')
const generated = (opened: OpenedEditor) => opened.store.get('audio.generated') as Array<Record<string, unknown>> | undefined

async function openMenu(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('[data-generated-add]').trigger('click')
  await flushPromises()
}

async function addGenerator(wrapper: VueWrapper, type: string): Promise<void> {
  await openMenu(wrapper)
  ;(document.body.querySelector(`[data-add-generator="${type}"]`) as HTMLElement).click()
  await flushPromises()
}

describe('GeneratedSoundsSection', () => {
  it('sem som gerado diz que está vazio e o menu lista os geradores por família', async () => {
    const { wrapper } = await mountSounds()
    expect(wrapper.text()).toContain('Nenhum som gerado')
    await openMenu(wrapper)
    const families = [...document.body.querySelectorAll('.sounds-menu__family')].map((element) => element.textContent)
    expect(families).toEqual(['Tons', 'Telefonia', 'Ritmo'])
    expect([...document.body.querySelectorAll('[data-add-generator]')].map((button) => button.getAttribute('data-add-generator'))).toEqual(['tone', 'dtmf', 'rhythm_track'])
  })

  it('gerar um som põe o item na spec com a duração que o gerador pede, num passo só do desfazer', async () => {
    const { opened, wrapper } = await mountSounds()
    await addGenerator(wrapper, 'rhythm_track')
    expect(generated(opened)).toEqual([{ generator: 'rhythm_track', params: {}, start: 0, duration: 8 }]) // no cursor, que está em 0
    expect(cards(wrapper)).toHaveLength(1)
    expect(opened.store.undo()).toBe(true)
    expect(generated(opened)).toBeUndefined() // projeto sem som gerado volta a não ter a chave
  })

  it('o cartão mostra o valor da spec e, sem ele, o padrão do catálogo', async () => {
    const { wrapper } = await mountSounds(soundsSpec([TONE]))
    const card = cards(wrapper)[0]!
    expect(card.text()).toContain('Tom')
    const field = (name: string) => card.find(`[data-sound-field="${name}"] input`).element as HTMLInputElement
    expect(field('start').value).toBe('4')
    expect(field('duration').value).toBe('0.5')
    expect(field('frequency_hz').value).toBe('1000')
    expect(field('amplitude_db').value).toBe('-2') // o padrão do catálogo: a spec não o tem
    expect(field('volume').value).toBe('1')
  })

  it('o número digitado vai para a spec depois de uma pausa e é limitado à faixa do catálogo', async () => {
    vi.useFakeTimers()
    const { opened, wrapper } = await mountSounds(soundsSpec([TONE]))
    const input = cards(wrapper)[0]!.find('[data-sound-field="frequency_hz"] input')
    await input.setValue('99999')
    expect(generated(opened)![0]!.params).toEqual({ frequency_hz: 1000 }) // ainda esperando
    await vi.advanceTimersByTimeAsync(400)
    expect(generated(opened)![0]!.params).toEqual({ frequency_hz: 20000 })
    await cards(wrapper)[0]!.find('[data-sound-field="duration"] input').setValue('2')
    await vi.advanceTimersByTimeAsync(400)
    expect(generated(opened)![0]!.duration).toBe(2)
  })

  it('a escolha, a caixa e o texto gravam no parâmetro do gerador', async () => {
    vi.useFakeTimers()
    const { opened, wrapper } = await mountSounds(
      soundsSpec([TONE, { generator: 'dtmf', params: {}, start: 0, duration: 1 }, { generator: 'rhythm_track', params: {}, start: 0, duration: 4 }]),
    )
    const [tone, dtmf, rhythm] = cards(wrapper)
    await tone!.find('[data-sound-field="waveform"] select').setValue('square')
    expect(generated(opened)![0]!.params).toMatchObject({ waveform: 'square', frequency_hz: 1000 })
    await dtmf!.find('[data-sound-field="sequence"] input').setValue('9*#')
    await vi.advanceTimersByTimeAsync(400)
    expect(generated(opened)![1]!.params).toEqual({ sequence: '9*#' })
    await rhythm!.find('[data-sound-field="accent_first"] input').setValue(false)
    expect(generated(opened)![2]!.params).toEqual({ accent_first: false })
  })

  it('remover tira o som e, ao esvaziar a lista, a chave some da spec', async () => {
    const { opened, wrapper } = await mountSounds(soundsSpec([TONE]))
    await wrapper.find('[aria-label="Remover o som gerado 1"]').trigger('click')
    await flushPromises()
    expect(generated(opened)).toBeUndefined()
    expect(cards(wrapper)).toHaveLength(0)
  })

  it('destaca o cartão do som que a linha do tempo tem selecionado (a trilha SFX)', async () => {
    const { opened, wrapper } = await mountSounds(soundsSpec([TONE, { ...TONE, start: 6 }]))
    opened.store.select(['SFX-1'])
    await flushPromises()
    expect(cards(wrapper).map((card) => card.classes().includes('sound--selected'))).toEqual([false, true])
  })

  it('catálogo que não carregou avisa e deixa o menu desligado', async () => {
    const { wrapper } = await mountSounds(soundsSpec(), { 'GET /api/audio-generators': () => new Response('{"detail":"fora do ar"}', { status: 500 }) })
    expect(wrapper.text()).toContain('não carregou')
    expect(wrapper.find('[data-generated-add]').attributes('disabled')).toBeDefined()
  })
})
