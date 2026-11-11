/* A portadora do Vocoder vinda de outra trilha, no cartão do efeito: o seletor aparece na música, na voz e no som do clipe com o som
   gerado e só as trilhas que o par aceita, some no PiP, esconde os controles da portadora gerada enquanto uma trilha está escolhida,
   e cada escolha é um passo do desfazer. */
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import type { AudioEffectCatalog, AudioEffectParam, TimelineView } from '@/api'
import { audioEffectCatalog } from '@/test/audioEffectsFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import AudioEffectsSection from './AudioEffectsSection.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.innerHTML = ''
})

function param(extra: Partial<AudioEffectParam> & Pick<AudioEffectParam, 'name' | 'label' | 'kind'>): AudioEffectParam {
  return { unit: '', default: null, minimum: null, maximum: null, hint: '', options: [], ...extra }
}

/** O catálogo básico com o Vocoder: a portadora gerada (que some com uma trilha escolhida), a trilha e as bandas. */
function catalog(): AudioEffectCatalog {
  const base = audioEffectCatalog()
  const carrier = { generator: 'tone', params: { waveform: 'sawtooth', frequency_hz: 110 } }
  return {
    ...base,
    effects: [
      ...base.effects,
      {
        type: 'vocoder',
        label: 'Vocoder',
        audacity_name: 'Vocoder',
        summary: 'A voz modula uma portadora.',
        changes_duration: false,
        sample_stage: true,
        parameters: [
          param({ name: 'carrier', label: 'Portadora', kind: 'carrier', default: carrier as never, shown_when: { carrier_track: null } }),
          param({ name: 'carrier_track', label: 'Trilha da portadora', kind: 'carrier_track', hint: 'De que trilha vem a portadora.' }),
          param({
            name: 'carrier_ignores_mute',
            label: 'Ouvir a trilha mesmo muda',
            kind: 'boolean',
            default: false,
            hint: 'O mudo e o solo só tiram a trilha da mistura.',
            shown_when: { carrier_track: '*' },
          }),
          param({ name: 'bands', label: 'Bandas', kind: 'integer', default: 40, minimum: 1, maximum: 50 }),
        ],
      },
    ],
  }
}

function spec(effect: Record<string, unknown> = { type: 'vocoder' }): Record<string, unknown> {
  const effects = [effect]
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    sources: {},
    timeline: [{ type: 'clip', src: 'a.mp4', start: 0, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 }],
    overlays: [{ type: 'video', src: 'pip.mp4', start: 0, effects }],
    audio: {
      voice_gain: 1,
      normalize: 'two-pass',
      mute_clips: false,
      music: { src: 'musica.mp3', volume: 0.3, effects },
      voiceover: [{ src: 'voz.wav', start: 0, offset: 0, volume: 1, effects }],
    },
  }
}

function view(): TimelineView {
  return {
    total: 5,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [
      timelineTrack('V1', [timelineItem(0, { id: 'V1-0', kind: 'clip', label: 'clip.0' })]),
      timelineTrack('V2', [timelineItem(0, { id: 'V2-0', kind: 'video', label: 'pip.0' })]),
      timelineTrack('A1', [timelineItem(0, { id: 'A1-0', kind: 'clip', label: 'clip.0' })], { kind: 'audio' }),
      timelineTrack('A2', [timelineItem(0, { id: 'A2-0', kind: 'audio', label: 'gravador' })], { kind: 'audio' }),
      timelineTrack('MUS', [timelineItem(0, { id: 'MUS-0', kind: 'music', label: 'musica' })], { kind: 'audio' }),
      timelineTrack('VO', [timelineItem(0, { id: 'VO-0', kind: 'voiceover', label: 'voiceover.0' })], { kind: 'audio' }),
    ],
    sources: {},
    warnings: [],
  }
}

async function mountOn(itemId: string, effect?: Record<string, unknown>): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const opened = await openEditor(spec(effect), {
    'GET /api/audio-effects': catalog(),
    'POST /api/projects/demo/timeline': () => view(),
  })
  const wrapper = await mountEditorPart(AudioEffectsSection, opened, {}, true)
  mounted.push(wrapper)
  opened.store.select([itemId])
  await flushPromises()
  return { opened, wrapper }
}

const values = (wrapper: VueWrapper) =>
  wrapper.findAll('[data-effect-param="carrier_track"] option').map((option) => (option.element as HTMLOptionElement).value)

describe('o seletor da trilha da portadora', () => {
  it('na música oferece o som gerado e as outras trilhas do projeto, nunca a própria música', async () => {
    const { wrapper } = await mountOn('MUS-0')
    expect(wrapper.find('[data-effect-param="carrier_track"]').exists()).toBe(true)
    expect(values(wrapper)).toEqual(['', 'A1', 'A2', 'VO'])
    expect(wrapper.find('[data-effect-param="carrier_track"]').text()).toContain('Som gerado')
  })

  it('na voz gravada oferece a música e o som dos clipes', async () => {
    const { wrapper } = await mountOn('VO-0')
    expect(values(wrapper)).toEqual(['', 'A1', 'A2', 'MUS'])
  })

  it('no som do clipe (A1) oferece também as faixas externas', async () => {
    const opened = await openEditor(
      { ...spec(), timeline: [{ type: 'clip', src: 'a.mp4', start: 0, speed: 1, volume: 1, mute: false, effects: [{ type: 'vocoder' }] }] },
      { 'GET /api/audio-effects': catalog(), 'POST /api/projects/demo/timeline': () => view() },
    )
    const wrapper = await mountEditorPart(AudioEffectsSection, opened, {}, true)
    mounted.push(wrapper)
    opened.store.select(['A1-0'])
    await flushPromises()
    expect(values(wrapper)).toEqual(['', 'A2', 'MUS', 'VO'])
  })

  it('no PiP a escolha não existe', async () => {
    const { wrapper } = await mountOn('V2-0')
    expect(wrapper.find('[data-effect-param="bands"]').exists()).toBe(true)
    expect(wrapper.find('[data-effect-param="carrier_track"]').exists()).toBe(false)
  })
})

describe('escolher a trilha', () => {
  it('grava a trilha na spec, esconde a portadora gerada e o desfazer volta ao som gerado', async () => {
    const { opened, wrapper } = await mountOn('VO-0')
    expect(wrapper.find('[data-effect-param="carrier"]').exists()).toBe(true)
    const select = wrapper.find('[data-effect-param="carrier_track"] select')
    await select.setValue('MUS')
    await flushPromises()
    expect(opened.store.get('audio.voiceover.0.effects.0.carrier_track')).toBe('MUS')
    expect(wrapper.find('[data-effect-param="carrier"]').exists()).toBe(false)

    opened.store.undo()
    await flushPromises()
    expect(opened.store.get('audio.voiceover.0.effects.0.carrier_track')).toBeUndefined()
    expect(wrapper.find('[data-effect-param="carrier"]').exists()).toBe(true)
  })

  it('escolher o som gerado apaga a chave: a spec fica como antes de a escolha existir', async () => {
    const { opened, wrapper } = await mountOn('VO-0', { type: 'vocoder', carrier_track: 'MUS' })
    expect(wrapper.find('[data-effect-param="carrier"]').exists()).toBe(false)
    await wrapper.find('[data-effect-param="carrier_track"] select').setValue('')
    await flushPromises()
    expect(opened.store.get('audio.voiceover.0.effects.0')).toEqual({ type: 'vocoder' })
  })

  it('a trilha que a spec cita e o projeto não tem aparece marcada', async () => {
    const { wrapper } = await mountOn('VO-0', { type: 'vocoder', carrier_track: 'A5' })
    expect(values(wrapper)).toContain('A5')
    expect(wrapper.find('[data-effect-param="carrier_track"]').text()).toContain('não existe')
  })
})

describe('ouvir a trilha mesmo muda', () => {
  const choice = '[data-effect-param="carrier_ignores_mute"]'

  it('a caixa só aparece com uma trilha escolhida e some quando se volta ao som gerado', async () => {
    const { wrapper } = await mountOn('VO-0')
    expect(wrapper.find(choice).exists()).toBe(false)
    await wrapper.find('[data-effect-param="carrier_track"] select').setValue('A2')
    await flushPromises()
    expect(wrapper.find(choice).exists()).toBe(true)
    expect(wrapper.find(choice).text()).toContain('Ouvir a trilha mesmo muda')
    await wrapper.find('[data-effect-param="carrier_track"] select').setValue('')
    await flushPromises()
    expect(wrapper.find(choice).exists()).toBe(false)
  })

  it('marcar grava a escolha na spec e o desfazer a tira, num passo só', async () => {
    const { opened, wrapper } = await mountOn('VO-0', { type: 'vocoder', carrier_track: 'MUS' })
    await wrapper.find(`${choice} input`).setValue(true)
    await flushPromises()
    expect(opened.store.get('audio.voiceover.0.effects.0.carrier_ignores_mute')).toBe(true)
    opened.store.undo()
    await flushPromises()
    expect(opened.store.get('audio.voiceover.0.effects.0.carrier_ignores_mute')).toBeUndefined()
    expect(opened.store.get('audio.voiceover.0.effects.0.carrier_track')).toBe('MUS')
  })
})
