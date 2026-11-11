import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AudioEffectCatalog, TimelineView } from '@/api'
import { audioEffectCatalog } from '@/test/audioEffectsFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import { reply } from '@/test/routedFetch'
import AudioEffectsSection from './AudioEffectsSection.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
beforeEach(() => window.localStorage.clear())

/** O catálogo com a Redução de ruído, como o servidor a entrega (o `profile` é um parâmetro do tipo `profile`). */
function catalogWithNoise(): AudioEffectCatalog {
  const catalog = audioEffectCatalog()
  catalog.effects.push({
    type: 'noise_reduction',
    label: 'Redução de ruído',
    audacity_name: 'Noise Reduction',
    summary: 'Tira o chiado de fundo a partir de um perfil de ruído.',
    changes_duration: false,
    sample_stage: true,
    parameters: [
      { name: 'reduction_db', label: 'Redução de ruído', kind: 'number', unit: 'dB', default: 12, minimum: 0, maximum: 48, hint: '', options: [] },
      { name: 'profile', label: 'Perfil de ruído', kind: 'profile', unit: '', default: 'auto', minimum: null, maximum: null, hint: '', options: [] },
    ],
  })
  return catalog
}

function noiseSpec(profiles: Record<string, unknown> = {}): Record<string, unknown> {
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
      voiceover: [{ src: 'voz.wav', start: 0, offset: 0, volume: 1, effects: [{ type: 'noise_reduction', reduction_db: 12, profile: 'auto' }] }],
      ...(Object.keys(profiles).length > 0 ? { noise_profiles: profiles } : {}),
    },
  }
}

function view(): TimelineView {
  const item = (id: string, index: number, kind: string) => timelineItem(index, { id, kind, label: `${kind}.${index}` })
  return {
    total: 9,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [timelineTrack('V1', [item('V1-0', 0, 'clip')]), timelineTrack('VO', [item('VO-0', 0, 'voiceover')], { kind: 'audio' })],
    sources: {},
    warnings: [],
  }
}

const savedProfile = { target: 'audio.voiceover.0', start: 0.2, end: 1.4 }
const report = {
  name: 'sala',
  target: 'audio.voiceover.0',
  start: 0.2,
  end: 1.4,
  duration: 1.2,
  level_db: -57.3,
  bands: [
    { hz: 100, db: -70 },
    { hz: 1000, db: -62 },
    { hz: 8000, db: -55 },
  ],
}

async function mountNoise(
  routes: Record<string, unknown> = {},
  profiles: Record<string, unknown> = {},
): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const opened = await openEditor(noiseSpec(profiles), {
    'GET /api/audio-effects': catalogWithNoise(),
    'POST /api/projects/demo/timeline': () => view(),
    ...routes,
  })
  const wrapper = await mountEditorPart(AudioEffectsSection, opened, {}, true)
  opened.store.select(['VO-0'])
  await flushPromises()
  return { opened, wrapper }
}

describe('Redução de ruído: o perfil', () => {
  it('o campo do perfil lista o automático e os perfis do projeto, e o escolhido vai para o efeito', async () => {
    const { opened, wrapper } = await mountNoise({}, { sala: savedProfile, rua: { ...savedProfile, start: 3, end: 4 } })
    const select = wrapper.find('[data-effect-param="profile"] select')
    const options = select.findAll('option').map((option) => option.text())
    expect(options).toEqual(['Automático (o trecho mais quieto do item)', 'sala', 'rua'])
    await select.setValue('sala')
    await flushPromises()
    expect((opened.store.get('audio.voiceover.0.effects') as Array<{ profile: string }>)[0]?.profile).toBe('sala')
  })

  it('um perfil que a spec cita e não existe aparece marcado, para ninguém achar que está certo', async () => {
    const { opened, wrapper } = await mountNoise()
    opened.store.setField('audio.voiceover.0.effects.0.profile', 'fantasma')
    await flushPromises()
    const options = wrapper.find('[data-effect-param="profile"] select').findAll('option').map((option) => option.text())
    expect(options).toContain('fantasma (não existe)')
  })

  it('Pegar perfil manda o trecho e aponta o efeito para ele num passo só do desfazer, e mostra o nível', async () => {
    const edited = noiseSpec({ sala: savedProfile })
    const { opened, wrapper } = await mountNoise({
      'POST /api/projects/demo/edit': (call: { body: unknown }) => {
        const op = (call.body as { op: { type: string } }).op
        if (op.type === 'noise_profile_set') {
          return { spec: noiseSpec({ sala: savedProfile }), timeline: view(), edit_warnings: [] }
        }
        const withProfile = noiseSpec({ sala: savedProfile }) as { audio: { voiceover: Array<{ effects: Array<{ profile: string }> }> } }
        withProfile.audio.voiceover[0]!.effects[0]!.profile = 'sala'
        return { spec: withProfile, timeline: view(), edit_warnings: [] }
      },
      'POST /api/projects/demo/noise-profile': report,
    })
    void edited
    const name = wrapper.find('[data-noise-name] input')
    await name.setValue('sala')
    await wrapper.find('[data-noise-start] input').setValue('0.2')
    await wrapper.find('[data-noise-end] input').setValue('1.4')
    await wrapper.find('[data-noise-take]').trigger('click')
    await flushPromises()

    const sent = opened.fetch.to('POST /api/projects/demo/edit').map((call) => (call.body as { op: unknown }).op)
    expect(sent).toEqual([
      { type: 'noise_profile_set', name: 'sala', target: 'audio.voiceover.0', start: 0.2, end: 1.4 },
      { type: 'set_field', path: 'audio.voiceover.0.effects.0.profile', value: 'sala' },
    ])
    expect(wrapper.find('[data-noise-report]').text()).toContain('-57.3 dBFS')
    expect(wrapper.find('[data-noise-report] svg polyline').exists()).toBe(true)
    // um passo só: desfazer uma vez volta ao projeto sem o perfil
    opened.store.undo()
    expect(opened.store.get('audio.noise_profiles')).toBeUndefined()
  })

  it('sem início e fim o perfil é o trecho mais quieto, e a operação não leva os tempos', async () => {
    const { opened, wrapper } = await mountNoise({
      'POST /api/projects/demo/edit': () => ({ spec: noiseSpec({ 'perfil-1': savedProfile }), timeline: view() }),
      'POST /api/projects/demo/noise-profile': report,
    })
    await wrapper.find('[data-noise-take]').trigger('click')
    await flushPromises()
    const first = (opened.fetch.to('POST /api/projects/demo/edit')[0]?.body as { op: Record<string, unknown> }).op
    expect(first).toEqual({ type: 'noise_profile_set', name: 'perfil-1', target: 'audio.voiceover.0' })
  })

  it('os botões Cursor usam a posição do cursor, e um trecho pela metade não deixa pegar o perfil', async () => {
    const { opened, wrapper } = await mountNoise()
    opened.store.setPlayhead(2.5)
    await wrapper.find('[data-noise-start-cursor]').trigger('click')
    await flushPromises()
    expect((wrapper.find('[data-noise-start] input').element as HTMLInputElement).value).toBe('2.5')
    expect(wrapper.find('[data-noise-interval-problem]').text()).toContain('início e o fim')
    expect(wrapper.find('[data-noise-take]').attributes('disabled')).toBeDefined()
    await wrapper.find('[data-noise-end] input').setValue('2')
    await flushPromises()
    expect(wrapper.find('[data-noise-interval-problem]').text()).toContain('O fim precisa ser maior')
  })

  it('um perfil que o projeto já guardava mostra o botão que mede o nível dele', async () => {
    const { opened, wrapper } = await mountNoise({ 'POST /api/projects/demo/noise-profile': report }, { sala: savedProfile })
    expect(wrapper.find('[data-noise-measure]').exists()).toBe(false) // o efeito ainda usa o automático
    opened.store.setField('audio.voiceover.0.effects.0.profile', 'sala')
    await flushPromises()
    await wrapper.find('[data-noise-measure]').trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/noise-profile')[0]?.body).toMatchObject({ profile: 'sala' })
    expect(wrapper.find('[data-noise-report]').text()).toContain('-57.3 dBFS')
    expect(wrapper.find('[data-noise-measure]').exists()).toBe(false)
  })

  it('o servidor recusando o perfil (trecho curto) fica no aviso do editor e o efeito não muda', async () => {
    const { opened, wrapper } = await mountNoise({
      'POST /api/projects/demo/edit': reply(400, { detail: 'o trecho de ruído tem 0.020 s; use pelo menos 0.1 s' }),
    })
    await wrapper.find('[data-noise-take]').trigger('click')
    await flushPromises()
    expect((opened.store.get('audio.voiceover.0.effects') as Array<{ profile: string }>)[0]?.profile).toBe('auto')
    expect(wrapper.find('[data-noise-report]').exists()).toBe(false)
  })
})

describe('Redução de ruído: comparar antes e depois', () => {
  it('pede o trecho a partir do cursor e mostra os dois lados para ouvir', async () => {
    const { opened, wrapper } = await mountNoise({
      'POST /api/projects/demo/effect-compare': { before_url: '/api/file?path=a.wav', after_url: '/api/file?path=b.wav', duration_s: 6 },
    })
    opened.store.setPlayhead(1.5)
    await wrapper.find('[data-compare-run]').trigger('click')
    await flushPromises()
    const body = opened.fetch.to('POST /api/projects/demo/effect-compare')[0]?.body as Record<string, unknown>
    expect(body).toMatchObject({ target: 'audio.voiceover.0', index: 0, at: 1.5, duration: 6 })
    const result = wrapper.find('[data-compare-result]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('Ouvir sem o efeito')
    expect(result.text()).toContain('Ouvir com o efeito')
  })

  it('o cursor fora do item mostra o motivo do servidor, sem mostrar um par de áudios velho', async () => {
    const { opened, wrapper } = await mountNoise({
      'POST /api/projects/demo/effect-compare': reply(422, { detail: 'o instante 99 s está fora de a voz gravada' }),
    })
    opened.store.setPlayhead(8)
    await wrapper.find('[data-compare-run]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-compare-problem]').text()).toContain('fora de a voz gravada')
    expect(wrapper.find('[data-compare-result]').exists()).toBe(false)
  })

  it('mudar o efeito apaga a comparação de antes, que já não vale', async () => {
    const { opened, wrapper } = await mountNoise({
      'POST /api/projects/demo/effect-compare': { before_url: '/a.wav', after_url: '/b.wav', duration_s: 6 },
    })
    await wrapper.find('[data-compare-run]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-compare-result]').exists()).toBe(true)
    opened.store.setField('audio.voiceover.0.effects.0.reduction_db', 20)
    await flushPromises()
    expect(wrapper.find('[data-compare-result]').exists()).toBe(false)
  })
})

describe('Redução de ruído: onde ela vale', () => {
  it('no master o menu não oferece o que trabalha sobre as amostras do item', async () => {
    const { opened, wrapper } = await mountNoise()
    opened.store.select([])
    await flushPromises()
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
    const offered = [...document.body.querySelectorAll('[data-add-effect]')].map((button) => button.getAttribute('data-add-effect'))
    expect(offered).toContain('amplify')
    expect(offered).not.toContain('noise_reduction')
  })

  it('no item de voz o menu oferece a Redução de ruído', async () => {
    const { wrapper } = await mountNoise()
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
    const offered = [...document.body.querySelectorAll('[data-add-effect]')].map((button) => button.getAttribute('data-add-effect'))
    expect(offered).toContain('noise_reduction')
  })
})
