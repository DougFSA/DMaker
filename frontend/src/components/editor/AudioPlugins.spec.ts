import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineView } from '@/api'
import { audioEffectCatalog } from '@/test/audioEffectsFixtures'
import { audioPluginCatalog, DRAGONFLY_LV2, ECHO_LV2, PLUGIN_EFFECT_INFO, STEPS_LADSPA } from '@/test/audioPluginsFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import AudioEffectsSection from './AudioEffectsSection.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
beforeEach(() => window.localStorage.clear())

const ECHO_EFFECT = { type: 'plugin', format: 'lv2', plugin: ECHO_LV2.ref, params: { delay_ms: 300 } }

function pluginSpec(effects: unknown[] = []): Record<string, unknown> {
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
      voiceover: [{ src: 'voz.wav', start: 0, offset: 0, volume: 1, effects }],
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
    tracks: [
      timelineTrack('V1', [item('V1-0', 0, 'clip')]),
      timelineTrack('VO', [item('VO-0', 0, 'voiceover')], { kind: 'audio' }),
    ],
    sources: {},
    warnings: [],
  }
}

async function mountPlugins(
  effects: unknown[] = [],
  routes: Record<string, unknown> = {},
): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const catalog = audioEffectCatalog()
  const opened = await openEditor(pluginSpec(effects), {
    'GET /api/audio-effects': { ...catalog, effects: [...catalog.effects, PLUGIN_EFFECT_INFO] },
    'GET /api/audio-plugins': audioPluginCatalog(),
    'POST /api/projects/demo/timeline': () => view(),
    ...routes,
  })
  const wrapper = await mountEditorPart(AudioEffectsSection, opened, {}, true)
  opened.store.select(['VO-0'])
  await flushPromises()
  return { opened, wrapper }
}

const chain = (opened: OpenedEditor) => opened.store.get('audio.voiceover.0.effects') as Array<Record<string, unknown>> | undefined

async function openMenu(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('[data-effects-add]').trigger('click')
  await flushPromises()
}

const menuButton = (selector: string) => document.body.querySelector(selector) as HTMLElement | null
const field = (wrapper: VueWrapper, name: string) => wrapper.find(`[data-plugin-control="${name}"] input`)

describe('o grupo Plugins do menu + Efeito', () => {
  it('lista os plugins achados e deixa pôr só os que o ffmpeg hospeda', async () => {
    const { wrapper } = await mountPlugins()
    await openMenu(wrapper)
    const rows = [...document.body.querySelectorAll('[data-plugin-id]')].map((row) => row.getAttribute('data-plugin-id'))
    expect(rows).toEqual([ECHO_LV2.id, STEPS_LADSPA.id, DRAGONFLY_LV2.id])
    expect((menuButton(`[data-add-plugin="${ECHO_LV2.id}"]`) as HTMLButtonElement).disabled).toBe(false)
    const blocked = menuButton(`[data-add-plugin="${DRAGONFLY_LV2.id}"]`) as HTMLButtonElement
    expect(blocked.disabled).toBe(true)
    expect(blocked.textContent).toContain('não usável: Options feature missing')
  })

  it('o efeito Plugin não aparece na lista genérica: ele nasce da escolha de um plugin', async () => {
    const { wrapper } = await mountPlugins()
    await openMenu(wrapper)
    const generic = [...document.body.querySelectorAll('[data-add-effect]')].map((button) => button.getAttribute('data-add-effect'))
    expect(generic).toContain('amplify')
    expect(generic).not.toContain('plugin')
  })

  it('escolher um plugin acrescenta o efeito só com o formato e a referência, num passo do desfazer', async () => {
    const { opened, wrapper } = await mountPlugins()
    await openMenu(wrapper)
    menuButton(`[data-add-plugin="${ECHO_LV2.id}"]`)!.click()
    await flushPromises()
    expect(chain(opened)).toEqual([{ type: 'plugin', format: 'lv2', plugin: ECHO_LV2.ref }])
    expect(wrapper.find('[data-plugin-name]').text()).toContain('DMaker Eco')
    expect(opened.store.undo()).toBe(true)
    expect(chain(opened) ?? []).toEqual([])
  })

  it('no master não há plugin: o grupo some', async () => {
    const { opened, wrapper } = await mountPlugins()
    opened.store.select([])
    await flushPromises()
    await openMenu(wrapper)
    expect(document.body.querySelector('[data-effects-plugins]')).toBeNull()
  })

  it('Desligar e Ligar pedem ao servidor e a linha acompanha', async () => {
    const { opened, wrapper } = await mountPlugins([], {
      'POST /api/audio-plugins/lv2-f6c94886b1/disable': audioPluginCatalog([{ ...ECHO_LV2, enabled: false }]),
      'POST /api/audio-plugins/lv2-f6c94886b1/enable': audioPluginCatalog([ECHO_LV2]),
    })
    await openMenu(wrapper)
    menuButton(`[data-toggle-plugin="${ECHO_LV2.id}"]`)!.click()
    await flushPromises()
    expect(opened.fetch.to('POST /api/audio-plugins/lv2-f6c94886b1/disable')).toHaveLength(1)
    expect(menuButton(`[data-toggle-plugin="${ECHO_LV2.id}"]`)!.textContent?.trim()).toBe('Ligar')
    expect((menuButton(`[data-add-plugin="${ECHO_LV2.id}"]`) as HTMLButtonElement).disabled).toBe(true)
    menuButton(`[data-toggle-plugin="${ECHO_LV2.id}"]`)!.click()
    await flushPromises()
    expect(menuButton(`[data-toggle-plugin="${ECHO_LV2.id}"]`)!.textContent?.trim()).toBe('Desligar')
  })

  it('Varrer plugins pede a varredura e troca a lista', async () => {
    const { opened, wrapper } = await mountPlugins([], {
      'POST /api/audio-plugins/scan': audioPluginCatalog([STEPS_LADSPA]),
    })
    await openMenu(wrapper)
    menuButton('[data-scan-plugins]')!.click()
    await flushPromises()
    expect(opened.fetch.to('POST /api/audio-plugins/scan')).toHaveLength(1)
    expect([...document.body.querySelectorAll('[data-plugin-id]')].map((row) => row.getAttribute('data-plugin-id'))).toEqual([STEPS_LADSPA.id])
  })

  it('sem plugin nenhum, diz onde pôr e que depois é só varrer', async () => {
    const { wrapper } = await mountPlugins([], { 'GET /api/audio-plugins': audioPluginCatalog([]) })
    await openMenu(wrapper)
    expect(menuButton('[data-plugins-empty]')!.textContent).toContain('C:/dados/plugins')
  })
})

describe('o cartão do efeito Plugin', () => {
  it('mostra um campo por controle que o plugin declara, com o valor da spec ou o padrão dele', async () => {
    const { wrapper } = await mountPlugins([ECHO_EFFECT])
    const names = wrapper.findAll('[data-plugin-control]').map((control) => control.attributes('data-plugin-control'))
    expect(names).toEqual(['delay_ms', 'feedback', 'mix'])
    expect((field(wrapper, 'delay_ms').element as HTMLInputElement).value).toBe('300')
    expect((field(wrapper, 'feedback').element as HTMLInputElement).value).toBe('0.4')
    expect(field(wrapper, 'mix').attributes('max')).toBe('1')
    expect(wrapper.find('[data-effect-param="format"]').exists()).toBe(false) // o formato vem do plugin: não é campo
  })

  it('mexer num controle grava params.<nome> depois da espera e vale um passo do desfazer', async () => {
    const { opened, wrapper } = await mountPlugins([ECHO_EFFECT])
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await field(wrapper, 'mix').setValue('0.8')
    await vi.advanceTimersByTimeAsync(299)
    expect((chain(opened)![0] as { params: Record<string, number> }).params.mix).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(chain(opened)![0]!.params).toEqual({ delay_ms: 300, mix: 0.8 })
    expect(opened.store.undo()).toBe(true)
    expect(chain(opened)![0]!.params).toEqual({ delay_ms: 300 })
  })

  it('um número fora da faixa do plugin avisa e vai limitado para a spec', async () => {
    const { opened, wrapper } = await mountPlugins([ECHO_EFFECT])
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await field(wrapper, 'delay_ms').setValue('5000')
    expect(wrapper.find('[data-plugin-control="delay_ms"]').text()).toContain('Use de 1 a 1000')
    await vi.advanceTimersByTimeAsync(300)
    expect((chain(opened)![0]!.params as Record<string, number>).delay_ms).toBe(1000)
  })

  it('esvaziar o campo devolve o controle ao padrão do plugin (a chave sai da spec)', async () => {
    const { opened, wrapper } = await mountPlugins([ECHO_EFFECT])
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await field(wrapper, 'delay_ms').setValue('')
    await vi.advanceTimersByTimeAsync(300)
    expect((chain(opened)![0]!.params as Record<string, number>).delay_ms).toBeUndefined()
  })

  it('o plugin LADSPA tem um inteiro e uma caixa de marcar que grava 1 e 0', async () => {
    const effect = { type: 'plugin', format: 'ladspa', plugin: STEPS_LADSPA.ref }
    const { opened, wrapper } = await mountPlugins([effect])
    expect(field(wrapper, 'c0').attributes('step')).toBe('1')
    const toggle = wrapper.find('[data-plugin-control="c1"] input[type="checkbox"]')
    await toggle.setValue(false)
    await flushPromises()
    expect((chain(opened)![0]!.params as Record<string, number>).c1).toBe(0)
  })

  it('um plugin que não está instalado mostra o aviso com o nome, sem campos', async () => {
    const missing = { type: 'plugin', format: 'lv2', plugin: 'urn:acme:ausente' }
    const { wrapper } = await mountPlugins([missing])
    expect(wrapper.find('[data-plugin-name]').text()).toContain('urn:acme:ausente')
    expect(wrapper.find('[data-plugin-problem]').text()).toContain('não está instalado')
    expect(wrapper.findAll('[data-plugin-control]')).toHaveLength(0)
  })

  it('um plugin que o ffmpeg não hospeda mostra o motivo que a varredura deu', async () => {
    const effect = { type: 'plugin', format: 'lv2', plugin: DRAGONFLY_LV2.ref }
    const { wrapper } = await mountPlugins([effect])
    expect(wrapper.find('[data-plugin-problem]').text()).toContain('Options feature missing')
    expect(wrapper.findAll('[data-plugin-control]')).toHaveLength(0)
  })
})
